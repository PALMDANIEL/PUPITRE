import { spawn } from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';
import { config, engineCommand } from './config';
import { ensureVoices } from './voix';
import { dirOf, listMetas, patchMeta, readMeta } from './store';
import { BUSY, UserError, type Job, type Manifest } from './types';

export function run(cmd: string, args: string[], opts: { label: string; timeoutMs: number; onLine?: (l: string) => void }): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(cmd, args, { stdio: ['ignore', 'pipe', 'pipe'], env: process.env, windowsHide: true });
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
      reject(Object.assign(readable ? new UserError(last) : new Error(`${opts.label} a échoué (code ${code}) :\n${tail}`), { detail: tail }));
    });
  });
}

async function processScore(id: string) {
  const meta = await readMeta(id);
  if (!meta) return;
  const dir = dirOf(id);

  if (meta.source === 'musicxml' || meta.source === 'midi') {
    await patchMeta(id, { partitionFile: meta.sourceFile });
    return renderScore(id);
  }
  if (meta.source === 'musescore') {
    if (!config.musescore) {
      throw new UserError('Ce serveur ne sait pas ouvrir les fichiers MuseScore. Dans MuseScore : Fichier › Exporter › MusicXML, puis envoyez ce fichier.');
    }
    await run(config.musescore, ['-o', path.join(dir, 'partition.musicxml'), path.join(dir, meta.sourceFile)], {
      label: 'La conversion du fichier MuseScore', timeoutMs: config.renderTimeoutMs,
    });
    await patchMeta(id, { partitionFile: 'partition.musicxml' });
    return renderScore(id);
  }

  await patchMeta(id, { status: 'preprocessing', progress: 5 });
  let partitionFile = '';
  const pagesDir = path.join(dir, 'pages');
  const update = (patch: Parameters<typeof patchMeta>[1]) => void patchMeta(id, patch).catch(() => undefined);
  const [omrCmd, omrArgs] = engineCommand('omr', [path.join(dir, meta.sourceFile), dir]);
  await run(omrCmd, omrArgs, {
    label: 'La lecture des notes',
    timeoutMs: config.omrTimeoutMs * 2,
    onLine: (line) => {
      if (line.startsWith('pages:')) {
        void fs.readdir(pagesDir).then((files) => update({ pages: files.filter((f) => f.endsWith('.png')).sort(), status: 'recognizing', progress: 20 }));
      }
      const pct = /^progress:omr:(\d+)/.exec(line);
      if (pct) update({ progress: 20 + Math.round((38 * Number(pct[1])) / 100) });
      const done = /^partition:(.+)$/.exec(line);
      if (done) partitionFile = done[1];
    },
  });
  if (!partitionFile) throw new UserError('Aucune portée n’a été reconnue. Essayez un scan plus net : page bien à plat, éclairage régulier, sans ombre.');
  const pages = (await fs.readdir(pagesDir)).filter((f) => f.endsWith('.png')).sort();
  await patchMeta(id, { pages, partitionFile, corrected: false, progress: 62 });
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

  const args = [path.join(dir, meta.partitionFile), next, '--timbre', meta.timbre];
  if (meta.tempo) args.push('--tempo', String(meta.tempo));
  if (meta.timbre === 'reel') args.push('--voyelle', meta.voyelle ?? 'ah');
  if (meta.timbre === 'chant') {
    // voix chantées : voix de synthèse téléchargées au premier usage, paroles saisies passées au moteur
    await ensureVoices((done, total) => void patchMeta(id, { progress: base + Math.round((5 * done) / total) }).catch(() => undefined));
    args.push('--langue', meta.langue ?? 'fr');
    if (meta.paroles && Object.values(meta.paroles).some((t) => t.trim())) {
      const file = path.join(dir, 'paroles.json');
      await fs.writeFile(file, JSON.stringify(meta.paroles));
      args.push('--paroles', file);
    }
  }
  if (meta.source === 'pdf' || meta.source === 'image') args.push('--omr');
  const [renderCmd, renderArgs] = engineCommand('render', args);
  await run(renderCmd, renderArgs, {
    label: 'La création de l’audio',
    // le chant prend bien plus longtemps que le synthétiseur (chaque syllabe est prononcée puis accordée)
    timeoutMs: meta.timbre === 'chant' ? config.chantTimeoutMs : config.renderTimeoutMs,
    onLine: (line) => {
      const sung = /^Chant (\d+)\/(\d+)/.exec(line);
      if (sung) { void patchMeta(id, { progress: base + Math.round(((80 - base) * (Number(sung[1]) - 1)) / Number(sung[2])) }).catch(() => undefined); return; }
      const m = /(?:progress:voice:|Voix )(\d+)\/(\d+)/.exec(line);
      const from = meta.timbre === 'chant' ? 80 : base;
      if (m) void patchMeta(id, { progress: from + Math.round(((95 - from) * Number(m[1])) / Number(m[2])) }).catch(() => undefined);
    },
  });

  const manifest = JSON.parse(await fs.readFile(path.join(next, 'manifest.json'), 'utf8')) as Manifest;
  // noms de voix choisis par l'utilisateur : gardés quand l'audio est recréé
  const names = (await readMeta(id))?.voiceNames ?? {};
  for (const v of manifest.voices) if (names[v.id]) v.name = names[v.id];
  if (Object.keys(names).length) await fs.writeFile(path.join(next, 'manifest.json'), JSON.stringify(manifest, null, 2));
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
