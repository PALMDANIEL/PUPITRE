/**
 * Registre d'administration AIT (serveur en ligne, base PostgreSQL / Neon) :
 * licences d'ordinateur et codes de chorale, dernière connexion, état (actif / désactivé), journal.
 * Inactif sans base de données : le serveur fonctionne alors comme avant.
 */
import pg from 'pg';
import { config } from './config';

export type ItemKind = 'licence' | 'acces';
export interface Item {
  id: string; kind: ItemKind; client: string; contact: string | null; machine: string | null;
  issued: string | null; expires: string | null; status: 'active' | 'revoked'; reason: string | null;
  revoked_at: string | null; registered_at: string; first_seen: string | null; last_seen: string | null;
  app_version: string | null; os: string | null; ip: string | null; uses: number; device?: string | null;
  /** Forfait (produit des tarifs) : enregistré à la vente ou par AIT, sinon déduit de la durée */
  product: string | null; plan: string; plan_label: string | null;
  /** Limite propre au client (NULL : celle du forfait) ; limite en vigueur (NULL : illimité) ; copies lues aujourd'hui */
  daily_quota: number | null; limit: number | null; used_today: number;
}

/** Quota de copies à déchiffrer par jour d'une licence ou d'un code. */
export interface Quota { plan: string; label: string | null; limit: number | null; used: number; own: boolean }

const DAY_MS = 86_400_000;

/**
 * Forfait d'une licence ou d'un code : celui de la vente (ou choisi par AIT), sinon d'après sa durée
 * (forfait le plus proche : jusqu'à 106 jours 1 mois, jusqu'à 273 jours 6 mois, au-delà ou sans date de fin 1 an).
 */
export function planOf(it: { kind: string; product?: string | null; issued?: string | null; expires?: string | null }): string {
  if (it.product) return it.product;
  const kind = it.kind === 'licence' ? 'licence' : 'acces';
  if (!it.issued || !it.expires) return `${kind}-1a`;
  const days = (Date.parse(`${it.expires}T00:00:00Z`) - Date.parse(`${it.issued}T00:00:00Z`)) / DAY_MS;
  // au plus près : 3 mois → 1 mois, 9 mois → 1 an ; 2 ans et définitive → 1 an
  return `${kind}-${days <= 106 ? '1m' : days <= 273 ? '6m' : '1a'}`;
}

/** Jour en cours (heure du Burkina = temps universel). */
export const today = (now = new Date()) => now.toISOString().slice(0, 10);

const SCHEMA = `
  CREATE TABLE IF NOT EXISTS ait_items (
    id text PRIMARY KEY,
    kind text NOT NULL,
    client text NOT NULL,
    contact text,
    machine text,
    issued date,
    expires date,
    status text NOT NULL DEFAULT 'active',
    reason text,
    revoked_at timestamptz,
    registered_at timestamptz NOT NULL DEFAULT now(),
    first_seen timestamptz,
    last_seen timestamptz,
    app_version text,
    os text,
    ip text,
    uses integer NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS ait_items_client ON ait_items (client);
  CREATE TABLE IF NOT EXISTS ait_events (
    id bigserial PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now(),
    item_id text,
    kind text NOT NULL,
    detail jsonb
  );
  CREATE INDEX IF NOT EXISTS ait_events_at ON ait_events (at DESC);
  ALTER TABLE ait_items ADD COLUMN IF NOT EXISTS text text;
  ALTER TABLE ait_items ADD COLUMN IF NOT EXISTS device text;
  CREATE TABLE IF NOT EXISTS ait_prices (
    product text PRIMARY KEY,
    kind text NOT NULL,
    duration text NOT NULL,
    label text NOT NULL,
    amount integer,
    active boolean NOT NULL DEFAULT false,
    sort integer NOT NULL DEFAULT 0
  );
  INSERT INTO ait_prices (product, kind, duration, label, sort) VALUES
    ('licence-1m', 'licence', '1m', 'Licence d’ordinateur · 1 mois', 1),
    ('licence-6m', 'licence', '6m', 'Licence d’ordinateur · 6 mois', 2),
    ('licence-1a', 'licence', '1a', 'Licence d’ordinateur · 1 an', 3),
    ('acces-1m', 'acces', '1m', 'Code de chorale · 1 mois', 4),
    ('acces-6m', 'acces', '6m', 'Code de chorale · 6 mois', 5),
    ('acces-1a', 'acces', '1a', 'Code de chorale · 1 an', 6)
  ON CONFLICT (product) DO NOTHING;
  CREATE TABLE IF NOT EXISTS ait_orders (
    id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    product text NOT NULL,
    kind text NOT NULL,
    duration text NOT NULL,
    amount integer NOT NULL,
    client text NOT NULL,
    contact text,
    machine text,
    renew_id text,
    status text NOT NULL DEFAULT 'created',
    invoice_token text,
    operator text,
    item_id text,
    expires date,
    text text,
    paid_at timestamptz,
    detail jsonb
  );
  CREATE INDEX IF NOT EXISTS ait_orders_machine ON ait_orders (machine) WHERE status = 'paid';
  CREATE INDEX IF NOT EXISTS ait_orders_token ON ait_orders (invoice_token);
  CREATE TABLE IF NOT EXISTS ait_counters (name text PRIMARY KEY, n integer NOT NULL);
  ALTER TABLE ait_orders ADD COLUMN IF NOT EXISTS gateway text;
  ALTER TABLE ait_orders ADD COLUMN IF NOT EXISTS declared_at timestamptz;
  -- Copies à déchiffrer par jour : par forfait (NULL = illimité), et limite propre à un client si AIT la fixe
  ALTER TABLE ait_prices ADD COLUMN IF NOT EXISTS daily_quota integer;
  ALTER TABLE ait_items ADD COLUMN IF NOT EXISTS product text;
  ALTER TABLE ait_items ADD COLUMN IF NOT EXISTS daily_quota integer;
  -- ordinateurs : lectures du jour signalées à chaque vérification de licence
  ALTER TABLE ait_items ADD COLUMN IF NOT EXISTS desk_day date;
  ALTER TABLE ait_items ADD COLUMN IF NOT EXISTS desk_used integer;
  CREATE INDEX IF NOT EXISTS ait_events_lecture ON ait_events (item_id, at) WHERE kind = 'lecture';
`;

let pool: pg.Pool | null = null;
let ready: Promise<void> | null = null;

/** Connexion paresseuse : la base n'est contactée qu'à la première requête qui en a besoin. */
export async function db(): Promise<pg.Pool | null> {
  if (!config.online || !config.adminDatabaseUrl) return null;
  if (!pool) {
    pool = new pg.Pool({ connectionString: config.adminDatabaseUrl, max: 3, idleTimeoutMillis: 20_000 });
    ready = pool.query(SCHEMA).then(() => undefined);
  }
  await ready;
  return pool;
}

export const adminEnabled = () => config.online && !!config.adminDatabaseUrl;

const date = (v: unknown) => (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null);

/** Enregistre une licence ou un code la première fois qu'on le voit (créé au Mac ou au téléphone, même hors ligne). */
export async function register(kind: ItemKind, p: { id: string; client: string; contact?: string; machine?: string; issued?: string; expires?: string | null }) {
  const d = await db();
  if (!d) return;
  await d.query(
    `INSERT INTO ait_items (id, kind, client, contact, machine, issued, expires) VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (id) DO NOTHING`,
    [p.id, kind, p.client, p.contact ?? null, p.machine ?? null, date(p.issued), date(p.expires)],
  );
}

/** Dernière connexion ; un événement « connexion » au plus toutes les 6 heures pour garder le journal lisible. */
export async function touch(id: string, info: { version?: string; os?: string; ip?: string }) {
  const d = await db();
  if (!d) return;
  const { rows } = await d.query(
    `UPDATE ait_items SET last_seen = now(), first_seen = COALESCE(first_seen, now()),
       app_version = COALESCE($2, app_version), os = COALESCE($3, os), ip = COALESCE($4, ip)
     WHERE id = $1 RETURNING (first_seen = last_seen) AS first`,
    [id, info.version ?? null, info.os ?? null, info.ip ?? null],
  );
  const recent = await d.query(`SELECT 1 FROM ait_events WHERE item_id = $1 AND kind IN ('connexion','premiere-connexion') AND at > now() - interval '6 hours' LIMIT 1`, [id]);
  if (!recent.rowCount) await event(id, rows[0]?.first ? 'premiere-connexion' : 'connexion', info);
}

export async function statusOf(id: string): Promise<{ status: 'active' | 'revoked'; reason: string | null } | null> {
  const d = await db();
  if (!d) return null;
  const { rows } = await d.query(`SELECT status, reason FROM ait_items WHERE id = $1`, [id]);
  return rows[0] ?? null;
}

/**
 * Un code de chorale = un téléphone. Le premier appareil qui se présente est lié au code ; un autre est refusé
 * jusqu'à ce qu'AIT libère l'appareil (tableau de bord). Rend false si le code est déjà lié à un autre appareil
 * (ou lié alors que l'appareil ne s'annonce pas : ancienne version de l'application).
 */
export async function bindDevice(id: string, device: string): Promise<boolean> {
  const d = await db();
  if (!d) return true;
  if (!device) {
    const { rows } = await d.query(`SELECT device FROM ait_items WHERE id = $1`, [id]);
    return !rows[0]?.device;
  }
  const { rowCount } = await d.query(`UPDATE ait_items SET device = $2 WHERE id = $1 AND (device IS NULL OR device = $2)`, [id, device]);
  if (rowCount) return true;
  await event(id, 'appareil-refuse', { device: device.slice(0, 8) });
  return false;
}

export async function freeDevice(id: string) {
  const d = (await db())!;
  const { rowCount } = await d.query(`UPDATE ait_items SET device = NULL WHERE id = $1`, [id]);
  if (rowCount) await event(id, 'appareil-libere');
  return rowCount ?? 0;
}

export async function countUse(id: string) {
  const d = await db();
  if (!d) return;
  await d.query(`UPDATE ait_items SET uses = uses + 1 WHERE id = $1`, [id]);
}

export async function event(itemId: string | null, kind: string, detail: object = {}) {
  const d = await db();
  if (!d) return;
  await d.query(`INSERT INTO ait_events (item_id, kind, detail) VALUES ($1, $2, $3)`, [itemId, kind, JSON.stringify(detail)]);
}

// --- Tableau de bord ---

export async function overview() {
  const d = (await db())!;
  const { rows: [r] } = await d.query(`
    SELECT
      count(*) FILTER (WHERE kind = 'licence') AS licences,
      count(*) FILTER (WHERE kind = 'licence' AND status = 'revoked') AS licences_desactivees,
      count(*) FILTER (WHERE kind = 'acces') AS codes,
      count(*) FILTER (WHERE kind = 'acces' AND status = 'revoked') AS codes_desactives,
      count(*) FILTER (WHERE kind = 'licence' AND last_seen > now() - interval '15 minutes') AS en_ligne,
      count(*) FILTER (WHERE last_seen > now() - interval '7 days') AS actifs_7j,
      count(DISTINCT client) AS clients,
      COALESCE(sum(uses) FILTER (WHERE kind = 'acces'), 0) AS lectures
    FROM ait_items`);
  const { rows: [t] } = await d.query(`SELECT count(*) AS lectures_24h FROM ait_events WHERE kind = 'lecture' AND at > now() - interval '24 hours'`);
  return Object.fromEntries(Object.entries({ ...r, ...t }).map(([k, v]) => [k, Number(v)]));
}

export async function listItems(): Promise<Item[]> {
  const d = (await db())!;
  const { rows } = await d.query(`SELECT i.*, to_char(i.issued, 'YYYY-MM-DD') AS issued, to_char(i.expires, 'YYYY-MM-DD') AS expires,
      CASE WHEN i.kind = 'licence' THEN CASE WHEN i.desk_day = (now() AT TIME ZONE 'UTC')::date THEN COALESCE(i.desk_used, 0) ELSE 0 END
           ELSE (SELECT count(*) FROM ait_events e WHERE e.item_id = i.id AND e.kind = 'lecture' AND e.at >= ${DAY_START})::int END AS used_today
    FROM ait_items i ORDER BY i.last_seen DESC NULLS LAST, i.registered_at DESC`);
  const plans = await planQuotas();
  return rows.map((r) => {
    const plan = planOf(r);
    return { ...r, plan, plan_label: plans.get(plan)?.label ?? null, limit: r.daily_quota ?? plans.get(plan)?.quota ?? null };
  });
}

/** Début du jour en cours, en temps universel (heure du Burkina). */
const DAY_START = `((now() AT TIME ZONE 'UTC')::date::timestamp AT TIME ZONE 'UTC')`;

async function planQuotas(): Promise<Map<string, { label: string; quota: number | null }>> {
  const d = (await db())!;
  const { rows } = await d.query<{ product: string; label: string; daily_quota: number | null }>(`SELECT product, label, daily_quota FROM ait_prices`);
  return new Map(rows.map((r) => [r.product, { label: r.label, quota: r.daily_quota }]));
}

/**
 * Quota du jour d'une licence ou d'un code inscrit au registre ; null sans base ou s'il est inconnu.
 * Codes de chorale : lectures comptées par le serveur (événements « lecture » du jour).
 * Licences d'ordinateur : lectures signalées par l'ordinateur à sa dernière vérification.
 */
export async function quotaOf(id: string): Promise<Quota | null> {
  const d = await db();
  if (!d) return null;
  const { rows } = await d.query(
    `SELECT i.kind, i.product, i.daily_quota, to_char(i.issued, 'YYYY-MM-DD') AS issued, to_char(i.expires, 'YYYY-MM-DD') AS expires,
       CASE WHEN i.kind = 'licence' THEN CASE WHEN i.desk_day = (now() AT TIME ZONE 'UTC')::date THEN COALESCE(i.desk_used, 0) ELSE 0 END
            ELSE (SELECT count(*) FROM ait_events e WHERE e.item_id = i.id AND e.kind = 'lecture' AND e.at >= ${DAY_START})::int END AS used
     FROM ait_items i WHERE i.id = $1`, [id]);
  if (!rows[0]) return null;
  const r = rows[0];
  const plan = planOf(r);
  const { rows: p } = await d.query<{ label: string; daily_quota: number | null }>(`SELECT label, daily_quota FROM ait_prices WHERE product = $1`, [plan]);
  const own = r.daily_quota !== null && r.daily_quota !== undefined;
  return { plan, label: p[0]?.label ?? null, limit: own ? r.daily_quota : (p[0]?.daily_quota ?? null), used: Number(r.used ?? 0), own };
}

/** Lectures du jour signalées par un ordinateur (vérification de licence). */
export async function reportDeskUse(id: string, day: string, used: number) {
  const d = await db();
  if (!d || !/^\d{4}-\d{2}-\d{2}$/.test(day) || !Number.isFinite(used)) return;
  await d.query(`UPDATE ait_items SET desk_day = $2::date, desk_used = $3 WHERE id = $1 AND (desk_day IS NULL OR desk_day <= $2::date)`,
    [id, day, Math.max(0, Math.round(used))]);
}

/** Forfait et limite propre d'un client, choisis par AIT (null : forfait déduit, limite du forfait). */
export async function setItemQuota(id: string, product: string | null, dailyQuota: number | null) {
  const d = (await db())!;
  const { rowCount } = await d.query(`UPDATE ait_items SET product = $2, daily_quota = $3 WHERE id = $1`, [id, product, dailyQuota]);
  if (rowCount) await event(id, 'quota', { product, daily_quota: dailyQuota });
  return rowCount ?? 0;
}

export async function setStatus(id: string, status: 'active' | 'revoked', reason: string | null) {
  const d = (await db())!;
  const { rowCount } = await d.query(
    `UPDATE ait_items SET status = $2, reason = $3, revoked_at = CASE WHEN $2 = 'revoked' THEN now() ELSE NULL END WHERE id = $1`,
    [id, status, reason],
  );
  if (rowCount) await event(id, status === 'revoked' ? 'desactivation' : 'reactivation', { reason });
  return rowCount ?? 0;
}

export async function setClientStatus(client: string, status: 'active' | 'revoked', reason: string | null) {
  const d = (await db())!;
  const { rows } = await d.query(`SELECT id FROM ait_items WHERE client = $1`, [client]);
  for (const r of rows) await setStatus(r.id, status, reason);
  return rows.length;
}

export async function listEvents(limit = 100) {
  const d = (await db())!;
  const { rows } = await d.query(
    `SELECT e.at, e.kind, e.item_id, e.detail, i.client FROM ait_events e LEFT JOIN ait_items i ON i.id = e.item_id ORDER BY e.at DESC LIMIT $1`,
    [Math.min(500, limit)],
  );
  return rows;
}
