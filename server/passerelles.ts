/**
 * Moyens de paiement (Orange Money, Moov Money) : LigdiCash (automatique, compte marchand) et paiement direct au numéro d'AIT.
 * L'agrégateur crée une page de paiement et dit où en est un paiement ; le reste de la vente (paiement.ts) ne dépend pas de lui.
 */
import { config } from './config';
import { UserError } from './types';

export type GatewayName = 'ligdicash' | 'direct';
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

/** Agrégateur automatique (LigdiCash), s'il est configuré sur le serveur. */
export const activeGateway = (): Gateway | null => (ligdicash.configured() ? ligdicash : null);
export const gatewayOf = (_name: string | null): Gateway => ligdicash;

/**
 * Paiement direct : le client envoie l'argent par Orange Money ou Moov Money au numéro d'AIT, donne la référence
 * reçue par SMS, et AIT confirme depuis le tableau de bord (rien ne passe par un agrégateur, aucune commission).
 */
export interface DirectNumbers { orange: string | null; moov: string | null }
export const directNumbers = (): DirectNumbers | null => {
  const { orange, moov } = config.directPay;
  return config.directPay.enabled && (orange || moov) ? { orange, moov } : null;
};
