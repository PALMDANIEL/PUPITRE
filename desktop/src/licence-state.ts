// Licence installée sur cette machine, et son suivi par AIT :
// - dernier jour d'utilisation (contre le recul d'horloge) ;
// - dernière vérification auprès du serveur AIT : au-delà de 30 jours sans Internet, Pupitre demande une connexion ;
// - désactivation décidée par AIT (mémorisée : elle reste valable hors ligne).
import { app, net } from 'electron';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checkLicence, frDate, LicenceError, type LicencePayload } from '../../licence/core';
import { machineId } from '../../licence/machine';
import PUBLIC_KEY from '../../licence/cle-publique.pem';

export const SERVER = process.env.PUPITRE_SERVEUR ?? 'https://pupitre-lecture.vercel.app';
export const OFFLINE_DAYS = 30;

interface State {
  licence: string | null;
  lastSeen: string | null;
  installedAt: string | null;
  lastCheck: string | null;
  revoked: string | null; // message d'AIT
}

const EMPTY: State = { licence: null, lastSeen: null, installedAt: null, lastCheck: null, revoked: null };
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
  | { ok: true; licence: LicencePayload; machine: string; lastCheck: string | null; checkDeadline: string }
  | { ok: false; problem: Problem; message: string; machine: string };

const DAY = 86_400_000;

export function currentStatus(now = new Date()): LicenceStatus {
  const machine = machineId();
  const state = load();
  if (!state.licence) return { ok: false, problem: 'missing', message: 'Pupitre n’est pas encore activé sur cet ordinateur.', machine };
  let licence: LicencePayload;
  try {
    licence = checkLicence(state.licence, PUBLIC_KEY, machine, now, state.lastSeen);
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
  return { ok: true, licence, machine, lastCheck: state.lastCheck, checkDeadline: deadline.toISOString() };
}

/** Installe une nouvelle licence si elle est valide pour cette machine ; renvoie l'état obtenu. */
export function install(text: string, now = new Date()): LicenceStatus {
  const machine = machineId();
  const state = load();
  try {
    checkLicence(text, PUBLIC_KEY, machine, now, state.lastSeen);
  } catch (e) {
    const err = e as LicenceError;
    return { ok: false, problem: err.problem ?? 'format', message: err.message, machine };
  }
  save({ licence: text.replace(/\s+/g, ''), lastSeen: now.toISOString(), installedAt: now.toISOString(), lastCheck: null, revoked: null });
  return currentStatus(now);
}

const osName = () => `${process.platform === 'darwin' ? 'macOS' : process.platform === 'win32' ? 'Windows' : 'Linux'} ${os.release()}`;

/**
 * Se signale au serveur AIT (si Internet est disponible) : note la vérification, ou la désactivation décidée par AIT.
 * Sans réseau, ne change rien. Renvoie l'état de la licence après coup.
 */
export async function checkIn(timeoutMs = 8000): Promise<LicenceStatus> {
  const state = load();
  if (!state.licence) return currentStatus();
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    const res = await net.fetch(`${SERVER}/api/checkin`, {
      method: 'POST', signal: ctrl.signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ licence: state.licence, machine: machineId(), version: app.getVersion(), os: osName() }),
    }).finally(() => clearTimeout(timer));
    if (res.ok) {
      const r = await res.json() as { status: 'active' | 'revoked' | 'invalid'; message: string | null };
      const fresh = load();
      if (r.status === 'active') save({ ...fresh, lastCheck: new Date().toISOString(), revoked: null });
      if (r.status === 'revoked') save({ ...fresh, revoked: r.message ?? 'Cette licence a été désactivée par AIT.' });
    }
  } catch { /* hors ligne ou serveur injoignable : on réessaiera */ }
  return currentStatus();
}
