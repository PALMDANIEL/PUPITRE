/**
 * Journal des échecs (version installable) : Documents/Pupitre/journal.txt.
 * Un traitement qui échoue n'affiche à l'écran qu'un message court ; la vraie cause (message du moteur, fin de ses
 * explications) est écrite ici, pour qu'on puisse la lire et l'envoyer à AIT sans ouvrir de console.
 */
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { config } from './config';

const MAX_BYTES = 1_000_000;
export const journalFile = () => path.join(config.storageDir, 'journal.txt');

export async function journal(what: string, err: unknown): Promise<void> {
  if (config.direct) return; // hébergement en ligne : pas de disque, les journaux de la plateforme suffisent
  const e = err as { message?: string; detail?: string };
  const entry = [
    `--- ${new Date().toISOString()} · ${what}`,
    `Pupitre ${process.env.PUPITRE_VERSION ?? ''} · ${process.platform} ${os.arch()} · ${os.cpus().length} cœurs · ${Math.round(os.totalmem() / 2 ** 30)} Go`,
    e?.message ?? String(err),
    ...(e?.detail ? ['Détail du moteur :', e.detail.trim()] : []),
    '',
  ].join('\n');
  try {
    const file = journalFile();
    await fs.mkdir(path.dirname(file), { recursive: true });
    const size = await fs.stat(file).then((s) => s.size).catch(() => 0);
    if (size > MAX_BYTES) await fs.rename(file, `${file}.1`).catch(() => undefined); // un seul fichier de secours
    await fs.appendFile(file, entry);
  } catch { /* le journal ne doit jamais faire échouer un traitement */ }
}
