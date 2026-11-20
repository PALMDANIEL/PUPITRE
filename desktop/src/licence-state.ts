// Licence installée sur cette machine, et son suivi par AIT :
// - dernier jour d'utilisation (contre le recul d'horloge) ;
// - dernière vérification auprès du serveur AIT : au-delà de 30 jours sans Internet, Pupitre demande une connexion ;
// - désactivation décidée par AIT (mémorisée : elle reste valable hors ligne).
import { app, net } from 'electron';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checkLicence, decodeLicence, frDate, LicenceError, type LicencePayload } from '../../licence/core';
import { machineId } from '../../licence/machine';
import PUBLIC_KEY from '../../licence/cle-publique.pem';
import SALE_KEY from '../../licence/cle-vente.pem';
import { usedToday } from '../../server/quota-local';

/** Clé AIT, et clé de vente du serveur (licences achetées et renouvelées en ligne). */
const KEYS = [PUBLIC_KEY, SALE_KEY];

// serveur AIT (VPS) ; l'ancien hébergement Vercel est fermé depuis le 19/11/2026
export const SERVER = process.env.PUPITRE_SERVEUR ?? 'https://pupitre-102-204-24-173.sslip.io';
export const OFFLINE_DAYS = 30;

/** Forfait de la licence : copies à déchiffrer par jour (null : illimité), reçu d'AIT à chaque vérification. */
export interface DeskQuota { limit: number | null; label: string | null; plan: string | null }

interface State {
  licence: string | null;
  lastSeen: string | null;
  installedAt: string | null;
  lastCheck: string | null;
  revoked: string | null; // message d'AIT
  quota: DeskQuota | null;
}

const EMPTY: State = { licence: null, lastSeen: null, installedAt: null, lastCheck: null, revoked: null, quota: null };
const file = () => path.join(app.getPath('userData'), 'licence.json');

function load(): State {
  try {
    const s = { ...EMPTY, ...JSON.parse(fs.readFileSync(file(), 'utf8')) } as State;
    if (s.licence && !s.installedAt) s.installedAt = s.lastSeen ?? new Date().toISOString(); // licences installées avant ce suivi
    return s;
  } catch { return { ...EMPTY }; }
}

function save(state: State) {
  fs.mkdirSync(path.dirname(file()), { recursive: true });
  fs.writeFileSync(file(), JSON.stringify(state, null, 1));
}

export type Problem = LicenceError['problem'] | 'revoked' | 'offline';
export type LicenceStatus =
  | { ok: true; licence: LicencePayload; machine: string; lastCheck: string | null; checkDeadline: string; quota: DeskQuota | null }
  | { ok: false; problem: Problem; message: string; machine: string };

const DAY = 86_400_000;

export function currentStatus(now = new Date()): LicenceStatus {
  const machine = machineId();
  const state = load();
  if (!state.licence) return { ok: false, problem: 'missing', message: 'Pupitre n’est pas encore activé sur cet ordinateur.', machine };
  let licence: LicencePayload;
  try {
    licence = checkLicence(state.licence, KEYS, machine, now, state.lastSeen);
  } catch (e) {
    const err = e as LicenceError;
    return { ok: false, problem: err.problem ?? 'format', message: err.message, machine };
  }
  if (state.revoked) return { ok: false, problem: 'revoked', message: state.revoked, machine };
  const since = Date.parse(state.lastCheck ?? state.installedAt ?? now.toISOString());
  const deadline = new Date(since + OFFLINE_DAYS * DAY);
  if (now > deadline) {
    return {
      ok: false, problem: 'offline', machine,
      message: `Connectez cet ordinateur à Internet quelques secondes : Pupitre vérifie sa licence auprès d’AIT au moins une fois par mois${state.lastCheck ? ` (dernière vérification le ${frDate(state.lastCheck.slice(0, 10))})` : ''}.`,
    };
  }
  if (!state.lastSeen || now.toISOString() > state.lastSeen) save({ ...state, lastSeen: now.toISOString() });
  return { ok: true, licence, machine, lastCheck: state.lastCheck, checkDeadline: deadline.toISOString(), quota: state.quota };
}

/** Installe une nouvelle licence si elle est valide pour cette machine ; renvoie l'état obtenu. */
export function install(text: string, now = new Date()): LicenceStatus {
  const machine = machineId();
  const state = load();
  try {
    checkLicence(text, KEYS, machine, now, state.lastSeen);
  } catch (e) {
    const err = e as LicenceError;
    return { ok: false, problem: err.problem ?? 'format', message: err.message, machine };
  }
  save({ licence: text.replace(/\s+/g, ''), lastSeen: now.toISOString(), installedAt: now.toISOString(), lastCheck: null, revoked: null, quota: null });
  return currentStatus(now);
}

const osName = () => `${process.platform === 'darwin' ? 'macOS' : process.platform === 'win32' ? 'Windows' : 'Linux'} ${os.release()}`;

async function post<T>(route: string, body: object, timeoutMs: number): Promise<T | null> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  const res = await net.fetch(`${SERVER}${route}`, {
    method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  }).finally(() => clearTimeout(timer));
  return res.ok ? await res.json() as T : null;
}

/** Page d'achat en ligne (LigdiCash) : licence pour cet ordinateur, ou renouvellement de la licence installée. */
export function shopUrl(): string {
  const state = load();
  let id: string | null = null;
  try { id = state.licence ? decodeLicence(state.licence, KEYS).id : null; } catch { id = null; }
  const q = new URLSearchParams({ machine: machineId(), ...(id ? { renouveler: id } : { produit: 'licence' }) });
  return `${SERVER}/acheter?${q}`;
}

/** Installe une licence reçue du serveur (achat ou renouvellement payé en ligne) si elle est valable ici. */
function adopt(text: string | null | undefined) {
  if (!text) return;
  const state = load();
  try {
    const lic = checkLicence(text, KEYS, machineId(), new Date(), state.lastSeen);
    let current: string | null = null;
    try { current = state.licence ? decodeLicence(state.licence, KEYS).expires : null; } catch { current = null; }
    if (state.licence && current !== null && (lic.expires === null ? false : lic.expires <= current)) return;
    save({ ...state, licence: text.replace(/\s+/g, ''), installedAt: state.installedAt ?? new Date().toISOString(), revoked: null });
  } catch { /* licence reçue non valable sur cet ordinateur : ignorée */ }
}

/**
 * Se signale au serveur AIT (si Internet est disponible) : note la vérification, ou la désactivation décidée par AIT,
 * et récupère une licence achetée ou renouvelée en ligne. Sans réseau, ne change rien. Renvoie l'état après coup.
 */
export async function checkIn(timeoutMs = 8000): Promise<LicenceStatus> {
  const state = load();
  try {
    if (!state.licence) {
      const r = await post<{ licence: string | null }>('/api/paiement/recuperer', { machine: machineId() }, timeoutMs);
      adopt(r?.licence);
      if (!load().licence) return currentStatus();
    }
    // copies déchiffrées aujourd'hui sur cet ordinateur : signalées à AIT (tableau de bord)
    const lectures = usedToday(process.env.STORAGE_DIR ?? path.join(app.getPath('documents'), 'Pupitre'));
    const r = await post<{ status: 'active' | 'revoked' | 'invalid'; message: string | null; renewal?: string | null; quota?: DeskQuota | null }>(
      '/api/checkin', { licence: load().licence, machine: machineId(), version: app.getVersion(), os: osName(), lectures }, timeoutMs);
    if (r) {
      adopt(r.renewal);
      const fresh = load();
      // forfait : limite de copies par jour fixée par AIT (gardée hors ligne jusqu'à la vérification suivante)
      if (r.quota !== undefined) save({ ...fresh, quota: r.quota ?? null });
      if (r.status === 'active' || (r.status === 'invalid' && r.renewal)) save({ ...load(), lastCheck: new Date().toISOString(), revoked: null });
      if (r.status === 'revoked') save({ ...load(), revoked: r.message ?? 'Cette licence a été désactivée par AIT.' });
    }
  } catch { /* hors ligne ou serveur injoignable : on réessaiera */ }
  return currentStatus();
}
