/**
 * Agrégateurs de paiement (Orange Money, Moov Money) : Moneroo ou LigdiCash, au choix du serveur (variable PAIEMENT).
 * Chacun crée une page de paiement et dit où en est un paiement ; le reste de la vente (paiement.ts) ne dépend pas d'eux.
 */
import { createHmac, timingSafeEqual } from 'node:crypto';
import { config } from './config';
import { UserError } from './types';

export type GatewayName = 'moneroo' | 'ligdicash';
export interface Checkout { ref: string; url: string }
export interface PaymentState { state: 'paid' | 'pending' | 'failed'; amount: number | null; currency: string | null; operator: string | null; detail?: unknown }
export interface CheckoutRequest {
  order: string; amount: number; label: string; description: string;
  client: string; contact: string; email: string | null; returnUrl: string; cancelUrl: string; callbackUrl: string;
}
export interface Gateway {
  name: GatewayName;
  configured(): boolean;
  create(r: CheckoutRequest): Promise<Checkout>;
  check(ref: string): Promise<PaymentState>;
}

const fail = (status: number, message: string): never => { throw Object.assign(new UserError(message), { status }); };

async function call<T>(url: string, init: RequestInit, headers: Record<string, string>): Promise<{ status: number; body: T }> {
  let res: Response;
  try {
    res = await fetch(url, { ...init, headers: { Accept: 'application/json', 'Content-Type': 'application/json', ...headers }, signal: AbortSignal.timeout(20_000) });
  } catch {
    return fail(502, 'Le service de paiement ne répond pas. Réessayez dans quelques minutes.');
  }
  return { status: res.status, body: await res.json().catch(() => null) as T };
}

/** Moneroo (moneroo.io) : Orange Burkina (orange_bf), Moov Burkina (moov_bf), carte bancaire. */
const moneroo: Gateway = {
  name: 'moneroo',
  configured: () => !!config.moneroo.secretKey,
  async create(r) {
    const digits = r.contact.replace(/\D/g, '');
    const { status, body } = await call<{ message?: string; data?: { id?: string; checkout_url?: string }; errors?: unknown }>(
      `${config.moneroo.baseUrl}payments/initialize`,
      {
        method: 'POST',
        body: JSON.stringify({
          amount: r.amount, currency: 'XOF', description: r.description, return_url: r.returnUrl,
          customer: {
            // Moneroo exige une adresse e-mail : à défaut, une adresse de commande (le reçu reste visible sur la page)
            email: r.email || `commande-${r.order.slice(0, 8)}@clients.pupitre.bf`,
            first_name: r.client.slice(0, 50), last_name: 'Pupitre', phone: digits.length === 8 ? `226${digits}` : digits, country: 'BF',
          },
          metadata: { commande: r.order },
          methods: config.moneroo.methods,
        }),
      },
      { Authorization: `Bearer ${config.moneroo.secretKey}` });
    if (status >= 300 || !body?.data?.id || !body.data.checkout_url) {
      fail(502, `Le service de paiement a refusé la commande${body?.message ? ` : ${body.message}` : ''}.`);
    }
    return { ref: body!.data!.id!, url: body!.data!.checkout_url! };
  },
  async check(ref) {
    const { status, body } = await call<{ data?: { id?: string; status?: string; amount?: number; currency?: { code?: string }; capture?: { method?: { name?: string } | string; gateway?: { name?: string } | string } } }>(
      `${config.moneroo.baseUrl}payments/${encodeURIComponent(ref)}/verify`, { method: 'GET' }, { Authorization: `Bearer ${config.moneroo.secretKey}` });
    const d = body?.data;
    if (status >= 300 || !d || d.id !== ref) return { state: 'pending', amount: null, currency: null, operator: null };
    const method = d.capture?.method;
    const operator = typeof method === 'string' ? method : method?.name ?? null;
    const state = d.status === 'success' ? 'paid' : d.status === 'failed' || d.status === 'cancelled' ? 'failed' : 'pending';
    return { state, amount: typeof d.amount === 'number' ? d.amount : null, currency: d.currency?.code ?? null, operator, detail: { status: d.status } };
  },
};

/** LigdiCash (ligdicash.com) : Orange Money et Moov Money ; compte marchand avec IFU et RCCM. */
const ligdicash: Gateway = {
  name: 'ligdicash',
  configured: () => !!(config.ligdicash.apiKey && config.ligdicash.authToken),
  async create(r) {
    const { body } = await call<{ response_code?: string; token?: string; response_text?: string; description?: string }>(
      `${config.ligdicash.baseUrl}redirect/checkout-invoice/create`,
      {
        method: 'POST',
        body: JSON.stringify({
          commande: {
            invoice: {
              items: [{ name: r.label, description: r.client, quantity: 1, unit_price: r.amount, total_price: r.amount }],
              total_amount: r.amount, devise: 'XOF', description: r.description,
              customer: '', customer_firstname: r.client, customer_lastname: '', customer_email: r.email ?? '', external_id: r.order, otp: '',
            },
            store: { name: 'Pupitre par AIT', website_url: config.publicUrl },
            actions: { cancel_url: r.cancelUrl, return_url: r.returnUrl, callback_url: r.callbackUrl },
            custom_data: { commande: r.order },
          },
        }),
      },
      { Apikey: config.ligdicash.apiKey ?? '', Authorization: `Bearer ${config.ligdicash.authToken ?? ''}` });
    if (body?.response_code !== '00' || !body.token || !body.response_text) {
      fail(502, `Le service de paiement a refusé la commande${body?.description ? ` : ${body.description}` : ''}.`);
    }
    return { ref: body!.token!, url: body!.response_text! };
  },
  async check(ref) {
    const { body } = await call<{ response_code?: string; status?: string; montant?: number | string; amount?: number | string; operator_name?: string }>(
      `${config.ligdicash.baseUrl}redirect/checkout-invoice/confirm/?invoiceToken=${encodeURIComponent(ref)}`, { method: 'GET' },
      { Apikey: config.ligdicash.apiKey ?? '', Authorization: `Bearer ${config.ligdicash.authToken ?? ''}` });
    const amount = Number(body?.montant ?? body?.amount ?? NaN);
    const state = body?.response_code === '00' && body.status === 'completed' ? 'paid' : body?.status === 'nocompleted' ? 'failed' : 'pending';
    return { state, amount: Number.isFinite(amount) ? amount : null, currency: 'XOF', operator: body?.operator_name ?? null, detail: { status: body?.status } };
  },
};

const GATEWAYS: Record<GatewayName, Gateway> = { moneroo, ligdicash };

/** Agrégateur des nouvelles commandes ; une commande en cours garde celui avec lequel elle a été créée. */
export const activeGateway = (): Gateway | null => {
  const g = GATEWAYS[config.paymentGateway];
  return g?.configured() ? g : null;
};
export const gatewayOf = (name: string | null): Gateway => GATEWAYS[(name as GatewayName) ?? 'ligdicash'] ?? ligdicash;

/** Rappel Moneroo : signature HMAC-SHA256 (hexadécimal) du corps brut avec le secret du webhook. */
export function monerooSignatureOk(raw: Buffer | undefined, signature: string | undefined): boolean {
  const secret = config.moneroo.webhookSecret;
  if (!secret) return true; // sans secret, on se fie seulement à la vérification auprès de Moneroo (toujours faite)
  if (!raw || !signature) return false;
  const expected = createHmac('sha256', secret).update(raw).digest('hex');
  const a = Buffer.from(expected), b = Buffer.from(signature.trim().toLowerCase());
  return a.length === b.length && timingSafeEqual(a, b);
}
