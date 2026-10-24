import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { config } from './config';
import { dirOf, listMetas, patchMeta, readMeta } from './store';
import { BUSY, UserError, type Job, type Manifest } from './types';

function run(cmd: string, args: string[], opts: { label: string; timeoutMs: number; onLine?: (l: string) => void }): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], env: process.env });
    let tail = '';
    let buffer = '';
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      reject(new UserError(`${opts.label} a pris trop de temps et a été interrompue.`));
    }, opts.timeoutMs);
    child.stdout.on('data', (chunk: Buffer) => {
      buffer += chunk.toString();
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines) opts.onLine?.(line.trim());
    });
    child.stderr.on('data', (chunk: Buffer) => { tail = (tail + chunk.toString()).slice(-4000); });
    child.on('error', (err) => { clearTimeout(timer); reject(new Error(`${opts.label} : impossible de lancer ${cmd} (${err.message})`)); });
    child.on('close', (code) => {
      clearTimeout(timer);
      if (buffer) opts.onLine?.(buffer.trim());
      if (code === 0) return resolve();
      const last = tail.trim().split('\n').pop() ?? '';
      const readable = last && !last.includes('Traceback') && !last.includes('Error') && !/^\s*File /.test(last);
      reject(readable ? new UserError(last) : new Error(`${opts.label} a échoué (code ${code}) :\n${tail}`));
    });
  });
}

const engine = (script: string) => path.join(config.engineDir, script);

async function findAll(dir: string, ext: string): Promise<string[]> {
  try {
    const entries = (await fs.readdir(dir, { recursive: true })).map(String);
    // Audiveris écrit clean.mvt1.mxl, clean.mvt2.mxl… quand il coupe la partition en mouvements.
    const order = (f: string) => Number(/\.mvt(\d+)\./.exec(f)?.[1] ?? 0);
    return entries.filter((f) => f.toLowerCase().endsWith(ext)).sort((a, b) => order(a) - order(b)).map((f) => path.join(dir, f));
  } catch {
    return [];
  }
}

async function recognize(id: string, pdf: string, omr: string): Promise<string[]> {
  await fs.rm(omr, { recursive: true, force: true });
  let ticks = 0;
  try {
    await run(config.audiveris, ['-batch', '-export', '-output', omr, '--', pdf], {
      label: 'La lecture des notes',
      timeoutMs: config.omrTimeoutMs,
      onLine: (line) => {
        if (/Sheet#\d+/.test(line) && ++ticks % 15 === 0) {
          void patchMeta(id, { progress: Math.min(58, 20 + Math.floor(ticks / 15)) }).catch(() => undefined);
        }
      },
    });
  } catch (err) {
    console.warn(`  Audiveris a échoué sur ${path.basename(pdf)} :`, err instanceof Error ? err.message.slice(0, 300) : err);
  }
  return findAll(omr, '.mxl');
}

async function processScore(id: string) {
  const meta = await readMeta(id);
  if (!meta) return;
  const dir = dirOf(id);

  if (meta.source === 'musicxml') {
    await patchMeta(id, { partitionFile: meta.sourceFile });
    return renderScore(id);
  }

  await patchMeta(id, { status: 'preprocessing', progress: 5 });
  const pre = path.join(dir, 'pre');
  await fs.rm(pre, { recursive: true, force: true });
  await run(config.python, [engine('preprocess.py'), path.join(dir, meta.sourceFile), pre], {
    label: 'Le nettoyage de l’image', timeoutMs: config.renderTimeoutMs,
  });
  const pagesDir = path.join(dir, 'pages');
  await fs.rm(pagesDir, { recursive: true, force: true });
  await fs.mkdir(pagesDir, { recursive: true });
  const pages = (await fs.readdir(pre)).filter((f) => f.endsWith('.png')).sort();
  for (const p of pages) await fs.copyFile(path.join(pre, p), path.join(pagesDir, p));
  await patchMeta(id, { pages, progress: 15 });

  await patchMeta(id, { status: 'recognizing', progress: 20 });
  const omr = path.join(dir, 'omr');
  let movements = await recognize(id, path.join(pre, 'clean.pdf'), omr);
  if (!movements.length) {
    console.log('  nouvel essai avec l’autre version de l’image');
    movements = await recognize(id, path.join(pre, 'alt.pdf'), omr);
  }
  if (!movements.length) throw new UserError('Aucune portée n’a été reconnue. Essayez un scan plus net : page bien à plat, éclairage régulier, sans ombre.');
  for (const old of ['partition.mxl', 'partition.musicxml']) await fs.rm(path.join(dir, old), { force: true });
  let partitionFile = 'partition.mxl';
  if (movements.length === 1) {
    await fs.copyFile(movements[0], path.join(dir, partitionFile));
  } else {
    partitionFile = 'partition.musicxml';
    await run(config.python, [engine('merge.py'), path.join(dir, partitionFile), ...movements], {
      label: 'L’assemblage des pages', timeoutMs: config.renderTimeoutMs,
    });
  }
  await fs.rm(pre, { recursive: true, force: true });
  await patchMeta(id, { partitionFile, corrected: false, progress: 62 });
  await renderScore(id);
}

async function renderScore(id: string) {
  const meta = await readMeta(id);
  if (!meta?.partitionFile) throw new UserError('Aucune partition lisible pour créer l’audio.');
  const dir = dirOf(id);
  const next = path.join(dir, 'audio-next');
  await fs.rm(next, { recursive: true, force: true });
  const base = meta.status === 'queued' ? 10 : Math.max(meta.progress, 62);
  await patchMeta(id, { status: 'rendering', progress: base });

  const args = [engine('render.py'), path.join(dir, meta.partitionFile), next, '--timbre', meta.timbre];
  if (meta.tempo) args.push('--tempo', String(meta.tempo));
  if (meta.source !== 'musicxml') args.push('--omr');
  await run(config.python, args, {
    label: 'La création de l’audio',
    timeoutMs: config.renderTimeoutMs,
    onLine: (line) => {
      const m = /(?:progress:voice:|Voix )(\d+)\/(\d+)/.exec(line);
      if (m) void patchMeta(id, { progress: base + Math.round(((95 - base) * Number(m[1])) / Number(m[2])) }).catch(() => undefined);
    },
  });

  const manifest = JSON.parse(await fs.readFile(path.join(next, 'manifest.json'), 'utf8')) as Manifest;
  const audio = path.join(dir, 'audio');
  await fs.rm(audio, { recursive: true, force: true });
  await fs.rename(next, audio);
  const fresh = await readMeta(id);
  await patchMeta(id, { status: 'ready', progress: 100, error: null, manifest, revision: (fresh?.revision ?? 0) + 1 });
}

const queue: Job[] = [];
let running = false;

export function enqueue(job: Job) {
  if (!queue.some((j) => j.id === job.id)) queue.push(job);
  void pump();
}

async function pump() {
  if (running) return;
  running = true;
  while (queue.length) {
    const { id, kind } = queue.shift()!;
    const title = (await readMeta(id))?.title ?? id;
    console.log(`> ${title} (${kind === 'process' ? 'lecture complète' : 'audio seulement'})`);
    try {
      if (kind === 'process') await processScore(id); else await renderScore(id);
      console.log(`  terminé : ${title}`);
    } catch (err) {
      console.error(`  échec : ${title}`, err);
      const message = err instanceof UserError
        ? err.message
        : 'Le traitement a échoué. Relancez-le ; si le problème persiste, essayez un scan plus net.';
      await patchMeta(id, { status: 'failed', error: message }).catch(() => undefined);
    }
  }
  running = false;
}

export async function recover() {
  for (const m of await listMetas()) {
    if (BUSY.includes(m.status)) {
      await patchMeta(m.id, { status: 'queued', progress: 0 });
      enqueue({ id: m.id, kind: m.partitionFile ? 'render' : 'process' });
    }
  }
}
