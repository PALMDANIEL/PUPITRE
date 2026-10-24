// Stockage par fichiers (un meta.json par partition) : version installable, sans base de données à installer.
import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from './config';
import { dirOf, isId, type Store } from './store-base';
import type { ScoreMeta } from './types';

const cache = new Map<string, ScoreMeta>();
const queues = new Map<string, Promise<unknown>>();
const fileOf = (id: string) => path.join(dirOf(id), 'meta.json');

/** Une seule écriture à la fois par partition (la progression est mise à jour très souvent). */
function serial<T>(id: string, job: () => Promise<T>): Promise<T> {
  const next = (queues.get(id) ?? Promise.resolve()).then(job, job);
  queues.set(id, next.catch(() => undefined));
  return next;
}

async function save(meta: ScoreMeta) {
  await fs.mkdir(dirOf(meta.id), { recursive: true });
  const tmp = `${fileOf(meta.id)}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(meta, null, 1));
  await fs.rename(tmp, fileOf(meta.id)); // remplacement atomique : jamais de fichier à moitié écrit
  cache.set(meta.id, meta);
  return meta;
}

async function init() {
  await fs.mkdir(config.storageDir, { recursive: true });
  for (const id of (await fs.readdir(config.storageDir)).filter(isId)) {
    try { cache.set(id, JSON.parse(await fs.readFile(fileOf(id), 'utf8'))); } catch { /* dossier sans meta.json : ignoré */ }
  }
  console.log(`Bibliothèque locale : ${cache.size} partition(s) dans ${config.storageDir}`);
}

async function read(id: string) {
  return isId(id) ? cache.get(id) ?? null : null;
}

function write(meta: ScoreMeta) {
  return serial(meta.id, () => save({ ...meta, updatedAt: new Date().toISOString() }));
}

function patch(id: string, changes: Partial<ScoreMeta>) {
  return serial(id, async () => {
    const current = cache.get(id);
    if (!current) throw new Error(`Partition introuvable : ${id}`);
    return save({ ...current, ...changes, id, createdAt: current.createdAt, updatedAt: new Date().toISOString() });
  });
}

async function list() {
  return [...cache.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}

async function remove(id: string) {
  if (!isId(id)) return;
  await serial(id, async () => {
    cache.delete(id);
    await fs.rm(dirOf(id), { recursive: true, force: true });
  });
}

export const fileStore: Store = { init, read, write, patch, list, remove };
