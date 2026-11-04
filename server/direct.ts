/**
 * Lecture directe (sans stockage) : pour un hébergement sans disque permanent, comme Vercel.
 * Le téléphone envoie ses photos et reste connecté ; on lit la partition dans un dossier temporaire,
 * on lui envoie la progression au fil de l'eau, puis le pack de répétition, et on efface tout.
 */
import { randomUUID } from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { config, engineCommand } from './config';
import { run } from './jobs';
import { buildPack } from './pack';
import { UserError, type Langue, type Manifest, type ScoreStatus, type Timbre, type Voyelle } from './types';
import { ensureVoices } from './voix';

export interface DirectEvent { status: ScoreStatus; progress: number }

/**
 * Copie usée lue voix par voix : sur un hébergement limité à 5 minutes par requête, la lecture des notes et la
 * création de l'audio ne tiennent pas dans la même. On renvoie alors la partition lue et les pages nettoyées ;
 * le téléphone demande l'audio dans une seconde requête (/api/recreer, avec ces mêmes fichiers).
 */
export interface DirectPartition { partition: Buffer; pages: Buffer[]; fiabilite?: string }
/** Étape 1 faite (nettoyage, portées repérées, premières lignes lues) : l'état repart avec le téléphone, qui lance l'étape 2. */
export interface DirectState { etat: Buffer; pages: Buffer[] }

async function readReliability(dir: string): Promise<string | undefined> {
  return fs.readFile(path.join(dir, 'fiabilite.json'), 'utf8').catch(() => undefined);
}

async function pagesOf(dir: string): Promise<Buffer[]> {
  const names = (await fs.readdir(path.join(dir, 'pages')).catch(() => [] as string[])).filter((f) => /^page-\d+\.png$/.test(f)).sort();
  return Promise.all(names.map((f) => fs.readFile(path.join(dir, 'pages', f))));
}

/** Étape 2 : lecture des portées par homr et assemblage, à partir de l'état de l'étape 1. */
export async function resumeDirect(state: Buffer, onEvent: (e: DirectEvent) => void): Promise<DirectPartition> {
  const dir = path.join(os.tmpdir(), `pupitre-suite-${randomUUID()}`);
  await fs.mkdir(dir, { recursive: true });
  try {
    const zipFile = path.join(dir, 'etat.zip');
    await fs.writeFile(zipFile, state);
    onEvent({ status: 'recognizing', progress: 35 });
    let partition = '';
    const [cmd, args] = engineCommand('omr', ['--reprise', zipFile, dir]);
    await run(cmd, args, {
      label: 'La lecture des notes', timeoutMs: config.omrTimeoutMs * 2,
      onLine: (line) => {
        if (line.startsWith('actif:')) onEvent({ status: 'recognizing', progress: 45 });
        const done = /^partition:(.+)$/.exec(line);
        if (done) partition = done[1];
      },
    });
    if (!partition) throw new UserError('Aucune portée n’a été reconnue. Reprenez la photo : page bien à plat, en pleine lumière.');
    return { partition: await fs.readFile(path.join(dir, partition)), pages: [], fiabilite: await readReliability(dir) };
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}

export async function readDirect(
  files: { name: string; ext: string; data: Buffer }[],
  title: string,
  onEvent: (e: DirectEvent) => void,
  disposition: 'satb' | null = null,
): Promise<Buffer | DirectPartition | DirectState> {
  const dir = path.join(os.tmpdir(), `pupitre-direct-${randomUUID()}`);
  await fs.mkdir(dir, { recursive: true });
  try {
    let source = path.join(dir, `source${files[0].ext}`);
    if (files.length === 1) {
      await fs.writeFile(source, files[0].data);
    } else {
      source = path.join(dir, 'source');
      await fs.mkdir(source);
      for (const [i, f] of files.entries()) await fs.writeFile(path.join(source, `${String(i + 1).padStart(2, '0')}${f.ext}`), f.data);
    }
    onEvent({ status: 'preprocessing', progress: 5 });
    let partition = '';
    let state = '';
    let byVoice = false;
    // hébergement limité à 5 minutes par requête : une copie lue voix par voix s'arrête après l'étape 1 (--etape1)
    const [omrCmd, omrArgs] = engineCommand('omr', [source, dir, ...(disposition ? ['--disposition', disposition] : []), ...(config.direct ? ['--etape1'] : [])]);
    await run(omrCmd, omrArgs, {
      label: 'La lecture des notes', timeoutMs: config.omrTimeoutMs * 2,
      onLine: (line) => {
        if (line.startsWith('pages:')) onEvent({ status: 'recognizing', progress: 20 });
        const pct = /^progress:omr:(\d+)/.exec(line);
        if (pct) onEvent({ status: 'recognizing', progress: 20 + Math.round((38 * Number(pct[1])) / 100) });
        if (line.startsWith('disposition:')) byVoice = true;
        const stateLine = /^etat:(.+)$/.exec(line);
        if (stateLine) state = stateLine[1];
        const done = /^partition:(.+)$/.exec(line);
        if (done) partition = done[1];
      },
    });
    if (state) return { etat: await fs.readFile(path.join(dir, state)), pages: await pagesOf(dir) };
    if (!partition) throw new UserError('Aucune portée n’a été reconnue. Reprenez la photo : page bien à plat, en pleine lumière.');
    if (byVoice && config.direct && partition.endsWith('.musicxml')) {
      return { partition: await fs.readFile(path.join(dir, partition)), pages: await pagesOf(dir), fiabilite: await readReliability(dir) };
    }
    onEvent({ status: 'rendering', progress: 62 });
    const audio = path.join(dir, 'audio');
    const [renderCmd, renderArgs] = engineCommand('render', [path.join(dir, partition), audio, '--timbre', 'choeur', '--omr', '--sans-travail']);
    await run(renderCmd, renderArgs, {
      label: 'La création de l’audio', timeoutMs: config.renderTimeoutMs,
      onLine: (line) => {
        const m = /(?:progress:voice:|Voix )(\d+)\/(\d+)/.exec(line);
        if (m) onEvent({ status: 'rendering', progress: 62 + Math.round((33 * Number(m[1])) / Number(m[2])) });
      },
    });
    const manifest = JSON.parse(await fs.readFile(path.join(audio, 'manifest.json'), 'utf8')) as Manifest;
    return await buildPack(title, manifest, audio, path.join(dir, 'pages'));
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}

/**
 * Téléphone : recrée l'audio d'un chant déjà enregistré (tempo, sonorité, voix chantées avec paroles)
 * à partir de la partition de son pack, sans relire la photo. Même principe : connexion ouverte, puis le pack.
 */
export async function recreateDirect(
  score: Buffer,
  title: string,
  opts: { tempo: number | null; timbre: Timbre; langue: Langue; paroles: Record<string, string> | null; voyelle: Voyelle },
  onEvent: (e: DirectEvent) => void,
  pages: Buffer[] = [],
  fiabilite?: string,
): Promise<Buffer> {
  const dir = path.join(os.tmpdir(), `pupitre-recreer-${randomUUID()}`);
  await fs.mkdir(dir, { recursive: true });
  try {
    const source = path.join(dir, 'score.musicxml');
    await fs.writeFile(source, score);
    if (fiabilite) await fs.writeFile(path.join(dir, 'fiabilite.json'), fiabilite); // lue par render.py, à côté de la partition
    const audio = path.join(dir, 'audio');
    // --omr : les partitions lues par photo nomment « Piano » chaque portée ; l'ordre des voix suit la page
    const args = [source, audio, '--timbre', opts.timbre, '--omr', '--sans-travail'];
    if (opts.tempo) args.push('--tempo', String(opts.tempo));
    if (opts.timbre === 'reel') args.push('--voyelle', opts.voyelle);
    const sung = opts.timbre === 'chant';
    if (sung) {
      onEvent({ status: 'rendering', progress: 3 });
      await ensureVoices();
      args.push('--langue', opts.langue);
      if (opts.paroles && Object.values(opts.paroles).some((t) => t.trim())) {
        const file = path.join(dir, 'paroles.json');
        await fs.writeFile(file, JSON.stringify(opts.paroles));
        args.push('--paroles', file);
      }
    }
    onEvent({ status: 'rendering', progress: 8 });
    const [renderCmd, renderArgs] = engineCommand('render', args);
    await run(renderCmd, renderArgs, {
      label: sung ? 'La création des voix chantées' : 'La création de l’audio',
      timeoutMs: sung ? config.chantTimeoutMs : config.renderTimeoutMs,
      onLine: (line) => {
        const c = /^Chant (\d+)\/(\d+)/.exec(line);
        if (c) { onEvent({ status: 'rendering', progress: 8 + Math.round((72 * (Number(c[1]) - 1)) / Number(c[2])) }); return; }
        const m = /(?:progress:voice:|Voix )(\d+)\/(\d+)/.exec(line);
        const from = sung ? 80 : 8;
        if (m) onEvent({ status: 'rendering', progress: from + Math.round(((97 - from) * Number(m[1])) / Number(m[2])) });
      },
    });
    const manifest = JSON.parse(await fs.readFile(path.join(audio, 'manifest.json'), 'utf8')) as Manifest;
    // pages nettoyées de la copie (lecture en deux temps) : jointes au pack comme dans la lecture d'un seul tenant
    const pagesDir = path.join(dir, 'pages');
    if (pages.length) {
      await fs.mkdir(pagesDir);
      for (const [i, p] of pages.entries()) await fs.writeFile(path.join(pagesDir, `page-${String(i + 1).padStart(2, '0')}.png`), p);
    }
    return await buildPack(title, manifest, audio, pages.length ? pagesDir : undefined);
  } finally {
    await fs.rm(dir, { recursive: true, force: true });
  }
}
