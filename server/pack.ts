// Pack de répétition (.pupitre) : partition + une piste par voix, lu par l'application mobile.
import fs from 'node:fs/promises';
import path from 'node:path';
import type { Manifest } from './types';
import { zip } from './zip';

export async function buildPack(title: string, manifest: Manifest, audioDir: string): Promise<Buffer> {
  const files = [manifest.score, manifest.tutti, ...manifest.voices.map((v) => v.stem)];
  const pack = {
    format: 'pupitre-pack', version: 1, title, exportedAt: new Date().toISOString(),
    manifest: { ...manifest, voices: manifest.voices.map(({ practice: _p, ...v }) => v) },
  };
  const entries = [{ name: 'pack.json', data: Buffer.from(JSON.stringify(pack, null, 1)) }];
  for (const f of files) entries.push({ name: `audio/${f}`, data: await fs.readFile(path.join(audioDir, f)) });
  return zip(entries);
}

export const packFileName = (title: string) => `${title.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'chant'}.pupitre`;
