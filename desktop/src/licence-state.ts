// Licence installée sur cette machine : texte de la licence et dernier jour d'utilisation (contre le recul d'horloge).
import { app } from 'electron';
import fs from 'node:fs';
import path from 'node:path';
import { checkLicence, LicenceError, type LicencePayload } from '../../licence/core';
import { machineId } from '../../licence/machine';
import PUBLIC_KEY from '../../licence/cle-publique.pem';

interface State { licence: string | null; lastSeen: string | null }

const file = () => path.join(app.getPath('userData'), 'licence.json');

function load(): State {
  try { return { licence: null, lastSeen: null, ...JSON.parse(fs.readFileSync(file(), 'utf8')) }; } catch { return { licence: null, lastSeen: null }; }
}

function save(state: State) {
  fs.mkdirSync(path.dirname(file()), { recursive: true });
  fs.writeFileSync(file(), JSON.stringify(state, null, 1));
}

export type LicenceStatus =
  | { ok: true; licence: LicencePayload; machine: string }
  | { ok: false; problem: LicenceError['problem']; message: string; machine: string };

export function currentStatus(now = new Date()): LicenceStatus {
  const machine = machineId();
  const state = load();
  if (!state.licence) return { ok: false, problem: 'missing', message: 'Pupitre n’est pas encore activé sur cet ordinateur.', machine };
  try {
    const licence = checkLicence(state.licence, PUBLIC_KEY, machine, now, state.lastSeen);
    if (!state.lastSeen || now.toISOString() > state.lastSeen) save({ ...state, lastSeen: now.toISOString() });
    return { ok: true, licence, machine };
  } catch (e) {
    const err = e as LicenceError;
    return { ok: false, problem: err.problem ?? 'format', message: err.message, machine };
  }
}

/** Installe une nouvelle licence si elle est valide pour cette machine ; renvoie l'état obtenu. */
export function install(text: string, now = new Date()): LicenceStatus {
  const machine = machineId();
  const state = load();
  try {
    const licence = checkLicence(text, PUBLIC_KEY, machine, now, state.lastSeen);
    save({ licence: text.replace(/\s+/g, ''), lastSeen: now.toISOString() });
    return { ok: true, licence, machine };
  } catch (e) {
    const err = e as LicenceError;
    return { ok: false, problem: err.problem ?? 'format', message: err.message, machine };
  }
}
