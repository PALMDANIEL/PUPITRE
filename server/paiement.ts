/**
 * Vente en ligne (serveur AIT) : licences d'ordinateur et codes de chorale payés par Orange Money ou Moov Money
 * via un agrégateur (Moneroo ou LigdiCash, voir passerelles.ts), puis signés par la clé de vente du serveur et remis automatiquement.
 * La clé AIT principale ne quitte jamais le Mac et le téléphone d'AIT : le serveur n'a que la clé de vente,
 * et il ne reconnaît une licence signée par elle que s'il l'a lui-même vendue (voir isKnownSale).
 */
import { randomUUID } from 'node:crypto';
import { checkAccess, signAccess, type AccessPayload } from '../licence/acces';
import { decodeLicence, signLicence, type LicencePayload } from '../licence/core';
import { normalizeMachineId } from '../licence/machine';
import { addDuration } from '../src/app/core/duree';
import { db, event } from './admin';
import { config } from './config';
import { activeGateway, gatewayOf } from './passerelles';
import { UserError } from './types';

export interface Price { product: string; kind: 'licence' | 'acces'; duration: string; label: string; amount: number | null; active: boolean; sort: number }
export interface Order {
  id: string; created_at: string; gateway: string | null; product: string; kind: 'licence' | 'acces'; duration: string; amount: number;
  client: string; contact: string | null; machine: string | null; renew_id: string | null;
  status: 'created' | 'pending' | 'paid' | 'failed'; invoice_token: string | null; operator: string | null;
  item_id: string | null; expires: string | null; text: string | null; paid_at: string | null;
}

const fail = (status: number, message: string): never => { throw Object.assign(new UserError(message), { status }); };
const today = () => new Date().toISOString().slice(0, 10);
const nextDay = (iso: string) => new Date(Date.parse(`${iso}T12:00:00Z`) + 86_400_000).toISOString().slice(0, 10);

export const salesEnabled = () => !!(config.salePrivateKey && activeGateway() && config.online && config.adminDatabaseUrl);

async function pool() {
  const d = await db();
  if (!d) fail(503, 'Le paiement en ligne n’est pas encore ouvert. Contactez AIT au 00226 77 41 91 06.');
  return d!;
}

export async function listPrices(all = false): Promise<Price[]> {
  const d = await db();
  if (!d) return [];
  const { rows } = await d.query<Price>(`SELECT * FROM ait_prices ${all ? '' : 'WHERE active AND amount > 0'} ORDER BY sort, product`);
  return rows;
}

export async function setPrices(prices: { product: string; amount: number | null; active: boolean }[]) {
  const d = await pool();
  for (const p of prices) {
    const amount = p.amount === null || p.amount === undefined || Number(p.amount) <= 0 ? null : Math.round(Number(p.amount));
    await d.query('UPDATE ait_prices SET amount = $2, active = $3 AND $2::integer IS NOT NULL WHERE product = $1', [p.product, amount, !!p.active]);
  }
  await event(null, 'tarifs', { prices });
}

/** Licence ou code à renouveler : il doit être connu du registre (pour une licence, avec le même ordinateur). */
async function renewable(id: string, machine: string | null) {
  const d = await pool();
  const { rows } = await d.query<{ id: string; kind: 'licence' | 'acces'; client: string; contact: string | null; machine: string | null; expires: string | null; status: string }>(
    `SELECT id, kind, client, contact, machine, to_char(expires, 'YYYY-MM-DD') AS expires, status FROM ait_items WHERE id = $1`, [id]);
  const item = rows[0];
  if (!item) fail(404, `Numéro « ${id} » inconnu. Vérifiez-le, ou contactez AIT.`);
  if (item.status === 'revoked') fail(403, `« ${id} » a été désactivé par AIT : contactez AIT au 00226 77 41 91 06.`);
  if (item.kind === 'licence' && machine && item.machine && item.machine !== machine) fail(403, 'Cette licence appartient à un autre ordinateur.');
  if (item.expires === null) fail(409, `« ${id} » est déjà illimité : rien à renouveler.`);
  return item;
}

/** Crée la commande et la facture chez l'agrégateur ; renvoie l'adresse de la page de paiement. */
export async function createOrder(input: { product?: string; client?: string; contact?: string; email?: string; machine?: string; renouveler?: string }) {
  if (!salesEnabled()) fail(503, 'Le paiement en ligne n’est pas encore ouvert. Contactez AIT au 00226 77 41 91 06.');
  const d = await pool();
  const { rows } = await d.query<Price>('SELECT * FROM ait_prices WHERE product = $1 AND active AND amount > 0', [String(input.product ?? '')]);
  const price = rows[0] ?? fail(400, 'Choisissez une formule.');
  const contact = String(input.contact ?? '').trim().slice(0, 60);
  if (!/\d{8}/.test(contact.replace(/\D/g, ''))) fail(400, 'Indiquez votre numéro de téléphone (celui d’Orange Money ou de Moov Money).');
  let client = String(input.client ?? '').trim().slice(0, 80);
  let machine: string | null = null;
  let renewId: string | null = null;
  if (input.renouveler) {
    const item = await renewable(String(input.renouveler).trim().toUpperCase(), input.machine ? normalizeMachineId(input.machine) : null);
    if (item.kind !== price.kind) fail(400, item.kind === 'licence' ? 'Choisissez une formule « Licence d’ordinateur ».' : 'Choisissez une formule « Code de chorale ».');
    renewId = item.id; client = item.client; machine = item.machine;
  } else {
    if (!client) fail(400, 'Indiquez le nom de la chorale ou du client.');
    if (price.kind === 'licence') {
      machine = normalizeMachineId(String(input.machine ?? ''));
      if (!machine) fail(400, 'Identifiant d’ordinateur invalide : 16 caractères, ex. ABCD-EFGH-JKMN-PQRS (affiché par Pupitre sur l’ordinateur).');
    }
  }
  const email = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(input.email ?? '').trim()) ? String(input.email).trim().slice(0, 120) : null;
  const gateway = activeGateway()!;
  const id = randomUUID();
  await d.query(
    `INSERT INTO ait_orders (id, gateway, product, kind, duration, amount, client, contact, machine, renew_id) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)`,
    [id, gateway.name, price.product, price.kind, price.duration, price.amount, client, contact, machine, renewId]);
  const back = `${config.publicUrl}/acheter/commande/${id}`;
  let checkout;
  try {
    checkout = await gateway.create({
      order: id, amount: price.amount!, label: price.label, description: `Pupitre · ${price.label}${renewId ? ` · ${renewId}` : ''}`,
      client, contact, email, returnUrl: back, cancelUrl: `${back}?annule=1`, callbackUrl: `${config.publicUrl}/api/paiement/rappel`,
    });
  } catch (e) {
    await d.query(`UPDATE ait_orders SET status = 'failed', detail = $2 WHERE id = $1`, [id, JSON.stringify({ error: (e as Error).message })]);
    throw e;
  }
  await d.query(`UPDATE ait_orders SET status = 'pending', invoice_token = $2 WHERE id = $1`, [id, checkout.ref]);
  await event(renewId, 'commande', { order: id, product: price.product, amount: price.amount, client });
  return { id, url: checkout.url };
}

async function nextNumber(kind: 'licence' | 'acces', year: string) {
  const d = await pool();
  const name = `${kind}-${year}`;
  const { rows } = await d.query<{ n: number }>(
    `INSERT INTO ait_counters (name, n) VALUES ($1, 1) ON CONFLICT (name) DO UPDATE SET n = ait_counters.n + 1 RETURNING n`, [name]);
  return `${kind === 'licence' ? 'AIT' : 'ACC'}-${year}-V${String(rows[0].n).padStart(4, '0')}`;
}

/** Paiement confirmé : signe la licence ou le code (nouveau, ou prolongé à partir de sa date de fin). */
async function fulfil(order: Order, operator: string | null): Promise<void> {
  const d = await pool();
  const conn = await d.connect();
  try {
    await conn.query('BEGIN');
    const { rows } = await conn.query<Order>('SELECT * FROM ait_orders WHERE id = $1 FOR UPDATE', [order.id]);
    if (rows[0]?.status === 'paid') { await conn.query('COMMIT'); return; }
    let id: string, issued: string, expires: string | null, contact = order.contact ?? undefined, machine = order.machine;
    if (order.renew_id) {
      const { rows: items } = await conn.query<{ issued: string | null; expires: string | null; contact: string | null; machine: string | null }>(
        `SELECT to_char(issued, 'YYYY-MM-DD') AS issued, to_char(expires, 'YYYY-MM-DD') AS expires, contact, machine FROM ait_items WHERE id = $1 FOR UPDATE`, [order.renew_id]);
      const item = items[0];
      id = order.renew_id;
      issued = item?.issued ?? today();
      // prolongation : à partir du lendemain de la fin actuelle, ou d'aujourd'hui si elle est déjà passée
      const from = item?.expires && item.expires >= today() ? nextDay(item.expires) : today();
      expires = addDuration(from, order.duration);
      contact = item?.contact ?? contact;
      machine = item?.machine ?? machine;
    } else {
      issued = today();
      id = await nextNumber(order.kind, issued.slice(0, 4));
      expires = addDuration(issued, order.duration);
    }
    const key = config.salePrivateKey!;
    const text = order.kind === 'licence'
      ? signLicence({ id, client: order.client, ...(contact ? { contact } : {}), machine: machine!, issued, expires, edition: 'standard' } as LicencePayload, key)
      : signAccess({ id, client: order.client, ...(contact ? { contact } : {}), issued, expires, kind: 'acces' } as AccessPayload, key);
    if (order.renew_id) {
      await conn.query('UPDATE ait_items SET expires = $2, text = $3 WHERE id = $1', [id, expires, text]);
    } else {
      await conn.query(
        `INSERT INTO ait_items (id, kind, client, contact, machine, issued, expires, text) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
         ON CONFLICT (id) DO UPDATE SET expires = EXCLUDED.expires, text = EXCLUDED.text`,
        [id, order.kind, order.client, contact ?? null, machine, issued, expires, text]);
    }
    await conn.query(`UPDATE ait_orders SET status = 'paid', paid_at = now(), operator = $2, item_id = $3, expires = $4, text = $5 WHERE id = $1`,
      [order.id, operator, id, expires, text]);
    await conn.query(`INSERT INTO ait_events (item_id, kind, detail) VALUES ($1, 'vente', $2)`,
      [id, JSON.stringify({ order: order.id, amount: order.amount, product: order.product, renewal: !!order.renew_id, operator })]);
    await conn.query('COMMIT');
  } catch (e) {
    await conn.query('ROLLBACK').catch(() => undefined);
    throw e;
  } finally {
    conn.release();
  }
}

/** État d'une commande ; tant qu'elle n'est pas réglée, demande à l'agrégateur où en est le paiement. */
export async function refreshOrder(id: string): Promise<Order | null> {
  const d = await pool();
  const get = async () => (await d.query<Order>(`SELECT *, to_char(expires, 'YYYY-MM-DD') AS expires FROM ait_orders WHERE id = $1`, [id])).rows[0] ?? null;
  const order = await get();
  if (!order || order.status !== 'pending' || !order.invoice_token) return order;
  const r = await gatewayOf(order.gateway).check(order.invoice_token);
  if (r.state === 'paid') {
    if ((r.amount !== null && r.amount < order.amount) || (r.currency && r.currency !== 'XOF')) {
      await d.query(`UPDATE ait_orders SET status = 'failed', detail = $2 WHERE id = $1`, [id, JSON.stringify({ reason: 'montant', amount: r.amount, currency: r.currency })]);
    } else {
      await fulfil(order, r.operator);
    }
  } else if (r.state === 'failed') {
    await d.query(`UPDATE ait_orders SET status = 'failed', detail = $2 WHERE id = $1`, [id, JSON.stringify(r.detail ?? {})]);
  }
  return get();
}

/** Rappel de l'agrégateur : on ne croit pas son contenu, on revérifie le paiement auprès de lui. */
export async function onCallback(body: Record<string, unknown>) {
  const d = await pool();
  // Moneroo : { event, data: { id, metadata } } ; LigdiCash : { token, external_id, custom_data }
  const data = (body['data'] ?? {}) as Record<string, unknown>;
  const meta = (data['metadata'] ?? {}) as Record<string, string>;
  if (data['id']) { body = { ...body, token: data['id'], external_id: meta['commande'] ?? body['external_id'] }; }
  const token = String(body['token'] ?? body['invoiceToken'] ?? '');
  const custom = body['custom_data'];
  const fromCustom = Array.isArray(custom)
    ? (custom as { keyof_customdata?: string; valueof_customdata?: string }[]).find((c) => c.keyof_customdata === 'commande')?.valueof_customdata
    : (custom as Record<string, string> | undefined)?.['commande'];
  const external = String(body['external_id'] ?? fromCustom ?? '');
  const { rows } = await d.query<{ id: string }>('SELECT id FROM ait_orders WHERE invoice_token = $1 OR id = $2 LIMIT 1', [token, external]);
  if (rows[0]) await refreshOrder(rows[0].id);
}

/** Dernière licence payée pour cet ordinateur (première activation après un achat en ligne). */
export async function licenceForMachine(machine: string): Promise<string | null> {
  const m = normalizeMachineId(machine);
  if (!m) return null;
  const d = await db();
  if (!d) return null;
  const { rows } = await d.query<{ text: string }>(
    `SELECT i.text FROM ait_items i WHERE i.kind = 'licence' AND i.machine = $1 AND i.status = 'active' AND i.text IS NOT NULL
     ORDER BY i.expires DESC NULLS FIRST LIMIT 1`, [m]);
  return rows[0]?.text ?? null;
}

/** Version plus récente (renouvelée en ligne) d'une licence ou d'un code, à installer à la place. */
export async function renewalOf(id: string, expires: string | null): Promise<string | null> {
  if (expires === null) return null;
  const d = await db();
  if (!d) return null;
  const { rows } = await d.query<{ text: string }>(
    `SELECT text FROM ait_items WHERE id = $1 AND status = 'active' AND text IS NOT NULL AND expires > $2::date`, [id, expires]);
  return rows[0]?.text ?? null;
}

/** Texte signé par la clé de vente : valable seulement s'il a été réellement vendu (protège si la clé fuitait). */
export async function isKnownSale(text: string): Promise<boolean> {
  const d = await db();
  if (!d) return false;
  const { rows } = await d.query('SELECT 1 FROM ait_orders WHERE text = $1 AND status = $2 LIMIT 1', [text.replace(/\s+/g, ''), 'paid']);
  return rows.length > 0;
}

/** Renouvellement d'un code de chorale déjà installé sur un téléphone (même s'il a expiré). */
export async function renewalForCode(text: string, keys: string[]): Promise<string | null> {
  let acc: AccessPayload;
  try { acc = checkAccess(text, keys, new Date(0)); } catch { return null; }
  return renewalOf(acc.id, acc.expires);
}

/** Licence installée (éventuellement expirée) : numéro et date de fin, pour proposer le renouvellement. */
export function peekLicence(text: string, keys: string[]): LicencePayload | null {
  try { return decodeLicence(text, keys); } catch { return null; }
}

export async function listOrders(limit = 100) {
  const d = await pool();
  const { rows } = await d.query(
    `SELECT id, created_at, product, kind, amount, client, contact, machine, renew_id, status, operator, item_id, to_char(expires, 'YYYY-MM-DD') AS expires, paid_at
     FROM ait_orders ORDER BY created_at DESC LIMIT $1`, [Math.min(Math.max(limit, 1), 500)]);
  const { rows: totals } = await d.query<{ total: string; n: string; mois: string }>(
    `SELECT COALESCE(SUM(amount), 0) AS total, COUNT(*) AS n,
            COALESCE(SUM(amount) FILTER (WHERE paid_at > date_trunc('month', now())), 0) AS mois
     FROM ait_orders WHERE status = 'paid'`);
  return { orders: rows, total: Number(totals[0].total), count: Number(totals[0].n), month: Number(totals[0].mois) };
}

