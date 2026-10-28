// Pack de répétition (.pupitre) : partition + une piste par voix, lu par l'application mobile,
// et les pages nettoyées de la copie (pour la « copie nettoyée » en PDF sur le téléphone).
import fs from 'node:fs/promises';
import path from 'node:path';
import type { Manifest } from './types';
import { zip } from './zip';

export async function buildPack(title: string, manifest: Manifest, audioDir: string, pagesDir?: string): Promise<Buffer> {
  const files = [manifest.score, ...(manifest.rebuilt ? [manifest.rebuilt] : []), manifest.tutti, ...manifest.voices.map((v) => v.stem)];
  const pack = {
    format: 'pupitre-pack', version: 1, title, exportedAt: new Date().toISOString(),
    manifest: { ...manifest, voices: manifest.voices.map(({ practice: _p, ...v }) => v) },
  };
  const entries = [{ name: 'pack.json', data: Buffer.from(JSON.stringify(pack, null, 1)) }];
  for (const f of files) entries.push({ name: `audio/${f}`, data: await fs.readFile(path.join(audioDir, f)) });
  if (pagesDir) {
    const pages = (await fs.readdir(pagesDir).catch(() => [] as string[])).filter((f) => /^page-\d+\.png$/.test(f)).sort();
    for (const f of pages) entries.push({ name: `pages/${f}`, data: await fs.readFile(path.join(pagesDir, f)) });
  }
  return zip(entries);
}

export const packFileName = (title: string) => `${title.replace(/[\\/:*?"<>|]+/g, ' ').trim() || 'chant'}.pupitre`;
