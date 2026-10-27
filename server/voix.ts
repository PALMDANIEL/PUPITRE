/**
 * Voix de synthèse des voix chantées (Piper, licences libres) : téléchargées une seule fois, au premier usage,
 * dans config.voixDir (environ 220 Mo). SIWIS (CC BY 4.0), UPMC « Pierre » (CC BY-SA 4.0), et MLS (CC BY 4.0)
 * pour les autres chanteurs de chaque pupitre.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { createWriteStream } from 'node:fs';
import { config } from './config';
import { UserError } from './types';

const BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/';
const FILES = [
  'siwis/medium/fr_FR-siwis-medium.onnx', 'siwis/medium/fr_FR-siwis-medium.onnx.json',
  'upmc/medium/fr_FR-upmc-medium.onnx', 'upmc/medium/fr_FR-upmc-medium.onnx.json',
  'mls/medium/fr_FR-mls-medium.onnx', 'mls/medium/fr_FR-mls-medium.onnx.json',
];

let pending: Promise<void> | null = null;

async function exists(file: string) {
  try { return (await fs.stat(file)).size > 0; } catch { return false; }
}

/** Télécharge les voix manquantes (une seule fois, même si plusieurs rendus le demandent en même temps). */
export function ensureVoices(onProgress?: (done: number, total: number) => void): Promise<void> {
  pending ??= (async () => {
    await fs.mkdir(config.voixDir, { recursive: true });
    let done = 0;
    for (const rel of FILES) {
      const dest = path.join(config.voixDir, path.basename(rel));
      if (!(await exists(dest))) {
        let res: Response;
        try {
          res = await fetch(BASE + rel);
        } catch {
          throw new UserError('Les voix chantées doivent être téléchargées une première fois (environ 220 Mo) : connectez-vous à Internet puis réessayez.');
        }
        if (!res.ok || !res.body) throw new UserError(`Téléchargement des voix chantées impossible (${res.status}). Réessayez plus tard.`);
        const tmp = `${dest}.partiel`;
        await pipeline(Readable.fromWeb(res.body as never), createWriteStream(tmp));
        await fs.rename(tmp, dest);
      }
      onProgress?.(++done, FILES.length);
    }
  })().finally(() => { pending = null; });
  return pending;
}
