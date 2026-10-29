// Stockage PostgreSQL : installation locale actuelle et futur hébergement en ligne.
import fs from 'node:fs/promises';
import path from 'node:path';
import pg from 'pg';
import { config } from './config';
import { dirOf, isId, type Store } from './store-base';
import type { ScoreMeta } from './types';

const COLS: Record<keyof ScoreMeta, string> = {
  id: 'id', title: 'title', originalName: 'original_name', source: 'source', sourceFile: 'source_file',
  partitionFile: 'partition_file', corrected: 'corrected', pages: 'pages', status: 'status',
  progress: 'progress', error: 'error', tempo: 'tempo', timbre: 'timbre', manifest: 'manifest',
  revision: 'revision', createdAt: 'created_at', updatedAt: 'updated_at', owner: 'owner',
  langue: 'langue', paroles: 'paroles', voyelle: 'voyelle', voiceNames: 'voice_names',
  disposition: 'disposition', lecture: 'lecture',
};
const JSON_KEYS = new Set<keyof ScoreMeta>(['pages', 'manifest', 'paroles', 'voiceNames']);
const toDb = (k: keyof ScoreMeta, v: unknown) => (JSON_KEYS.has(k) ? (v == null ? null : JSON.stringify(v)) : v);

const SCHEMA = `
  CREATE TABLE IF NOT EXISTS scores (
    id uuid PRIMARY KEY,
    title text NOT NULL,
    original_name text NOT NULL,
    source text NOT NULL,
    source_file text NOT NULL,
    partition_file text,
    corrected boolean NOT NULL DEFAULT false,
    pages jsonb NOT NULL DEFAULT '[]'::jsonb,
    status text NOT NULL,
    progress integer NOT NULL DEFAULT 0,
    error text,
    tempo integer,
    timbre text NOT NULL DEFAULT 'choeur',
    manifest jsonb,
    revision integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
  );
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS owner text;
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS langue text;
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS paroles jsonb;
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS voyelle text;
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS voice_names jsonb;
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS disposition text;
  ALTER TABLE scores ADD COLUMN IF NOT EXISTS lecture text;
  CREATE INDEX IF NOT EXISTS scores_created_idx ON scores (created_at DESC);
  CREATE INDEX IF NOT EXISTS scores_owner_idx ON scores (owner);
  CREATE INDEX IF NOT EXISTS scores_status_idx ON scores (status);
`;

let pool: pg.Pool;

function fromRow(r: any): ScoreMeta {
  return {
    id: r.id, title: r.title, originalName: r.original_name, source: r.source, sourceFile: r.source_file,
    partitionFile: r.partition_file, corrected: r.corrected, pages: r.pages ?? [], status: r.status,
    progress: r.progress, error: r.error, tempo: r.tempo, timbre: r.timbre, manifest: r.manifest,
    revision: r.revision, owner: r.owner ?? null, langue: r.langue ?? null, paroles: r.paroles ?? null, voyelle: r.voyelle ?? null, voiceNames: r.voice_names ?? null, disposition: r.disposition ?? null, lecture: r.lecture ?? null,
    createdAt: new Date(r.created_at).toISOString(), updatedAt: new Date(r.updated_at).toISOString(),
  };
}

function explain(e: any): Error {
  const where = (() => { try { const u = new URL(config.databaseUrl); return `${u.hostname}:${u.port || 5432}`; } catch { return 'localhost:5432'; } })();
  if (e?.code === 'ECONNREFUSED') return new Error(`PostgreSQL ne répond pas sur ${where}. Vérifiez qu’il est démarré (le serveur doit être accessible dans pgAdmin).`);
  if (e?.code === '28P01') return new Error('Mot de passe PostgreSQL incorrect. Corrigez la ligne DATABASE_URL dans le fichier .env.');
  if (e?.code === '28000') return new Error('Utilisateur PostgreSQL inconnu. Corrigez la ligne DATABASE_URL dans le fichier .env.');
  return e instanceof Error ? e : new Error(String(e));
}

async function initDb() {
  const dbName = decodeURIComponent(new URL(config.databaseUrl).pathname.slice(1)) || 'pupitre';
  pool = new pg.Pool({ connectionString: config.databaseUrl, max: 10 });
  try {
    await pool.query('SELECT 1');
  } catch (e: any) {
    await pool.end().catch(() => undefined);
    if (e?.code !== '3D000') throw explain(e);
    const admin = new URL(config.databaseUrl);
    admin.pathname = '/postgres';
    const client = new pg.Client({ connectionString: admin.toString() });
    try {
      await client.connect();
      await client.query(`CREATE DATABASE "${dbName.replace(/"/g, '""')}"`);
      console.log(`Base de données « ${dbName} » créée.`);
    } catch (err) {
      throw explain(err);
    } finally {
      await client.end().catch(() => undefined);
    }
    pool = new pg.Pool({ connectionString: config.databaseUrl, max: 10 });
  }
  await pool.query(SCHEMA);
  await importLegacyJson();
  console.log(`PostgreSQL connecté (base « ${dbName} »).`);
}

async function importLegacyJson() {
  let entries: string[] = [];
  try { entries = await fs.readdir(config.storageDir); } catch { return; }
  let count = 0;
  for (const id of entries.filter(isId)) {
    const file = path.join(dirOf(id), 'meta.json');
    try {
      const meta = JSON.parse(await fs.readFile(file, 'utf8')) as ScoreMeta;
      if (!(await readMeta(id))) { await writeMeta(meta); count++; }
      await fs.rename(file, `${file}.importe`);
    } catch { }
  }
  if (count) console.log(`${count} partition(s) existante(s) importée(s) dans PostgreSQL.`);
}

async function readMeta(id: string): Promise<ScoreMeta | null> {
  if (!isId(id)) return null;
  const { rows } = await pool.query('SELECT * FROM scores WHERE id = $1', [id]);
  return rows[0] ? fromRow(rows[0]) : null;
}

async function writeMeta(meta: ScoreMeta): Promise<ScoreMeta> {
  const keys = Object.keys(COLS) as (keyof ScoreMeta)[];
  const cols = keys.map((k) => COLS[k]);
  const values = keys.map((k) => toDb(k, meta[k]));
  const placeholders = keys.map((_, i) => `$${i + 1}`).join(', ');
  const updates = cols.filter((c) => c !== 'id' && c !== 'created_at').map((c) => `${c} = EXCLUDED.${c}`).join(', ');
  const { rows } = await pool.query(
    `INSERT INTO scores (${cols.join(', ')}) VALUES (${placeholders}) ON CONFLICT (id) DO UPDATE SET ${updates} RETURNING *`,
    values,
  );
  return fromRow(rows[0]);
}

async function patchMeta(id: string, patch: Partial<ScoreMeta>): Promise<ScoreMeta> {
  const keys = (Object.keys(patch) as (keyof ScoreMeta)[]).filter((k) => k in COLS && k !== 'id' && k !== 'createdAt' && k !== 'updatedAt');
  const sets = keys.map((k, i) => `${COLS[k]} = $${i + 2}`);
  sets.push('updated_at = now()');
  const { rows } = await pool.query(
    `UPDATE scores SET ${sets.join(', ')} WHERE id = $1 RETURNING *`,
    [id, ...keys.map((k) => toDb(k, patch[k]))],
  );
  if (!rows[0]) throw new Error(`Partition introuvable : ${id}`);
  return fromRow(rows[0]);
}

async function listMetas(): Promise<ScoreMeta[]> {
  const { rows } = await pool.query('SELECT * FROM scores ORDER BY created_at DESC');
  return rows.map(fromRow);
}

async function removeScore(id: string) {
  if (!isId(id)) return;
  await pool.query('DELETE FROM scores WHERE id = $1', [id]);
  await fs.rm(dirOf(id), { recursive: true, force: true });
}

export const pgStore: Store = { init: initDb, read: readMeta, write: writeMeta, patch: patchMeta, list: listMetas, remove: removeScore };
