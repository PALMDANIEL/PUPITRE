/**
 * Copies déchiffrées aujourd'hui sur cet ordinateur (application de bureau) : compteur du jour dans le dossier des
 * partitions. La limite vient du forfait de la licence (renvoyée par AIT à chaque vérification de licence) ; le
 * compte est signalé à AIT à la vérification suivante (tableau de bord).
 */
import fs from 'node:fs';
import path from 'node:path';

const FILE = '.lectures-du-jour.json';
const today = (now = new Date()) => now.toISOString().slice(0, 10); // heure du Burkina = temps universel

interface Count { day: string; count: number }

function read(dir: string): Count {
  try {
    const c = JSON.parse(fs.readFileSync(path.join(dir, FILE), 'utf8')) as Count;
    return c.day === today() ? { day: c.day, count: Math.max(0, Number(c.count) || 0) } : { day: today(), count: 0 };
  } catch {
    return { day: today(), count: 0 };
  }
}

/** Copies déchiffrées aujourd'hui sur cet ordinateur. */
export function usedToday(dir: string): Count {
  return read(dir);
}

/** Une copie de plus aujourd'hui. */
export function addUse(dir: string): Count {
  const c = read(dir);
  const next = { day: c.day, count: c.count + 1 };
  try {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, FILE), JSON.stringify(next));
  } catch { /* dossier en lecture seule : la lecture continue */ }
  return next;
}

/** Limite du forfait de cette licence (null : illimité), telle que l'application de bureau l'a publiée. */
export function licenceLimit(): { limit: number | null; label: string | null } {
  try {
    const l = JSON.parse(process.env.PUPITRE_LICENCE ?? 'null') as { quota?: { limit: number | null; label: string | null } | null } | null;
    const q = l?.quota;
    return { limit: typeof q?.limit === 'number' && q.limit >= 0 ? q.limit : null, label: q?.label ?? null };
  } catch {
    return { limit: null, label: null };
  }
}
