import express, { type NextFunction, type Request, type Response } from 'express';
import multer from 'multer';
import { spawn } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import fsSync from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { checkSetup, config } from './config';
import { enqueue, recover } from './jobs';
import { dirOf, initDb, isId, listMetas, patchMeta, readMeta, removeScore, writeMeta } from './store';
import { BUSY, UserError, type ScoreMeta, type SourceKind, type Timbre } from './types';
import { buildPack, packFileName } from './pack';
import { readDirect } from './direct';
import { checkAccess, type AccessPayload } from '../licence/acces';

const KINDS: Record<string, SourceKind> = {
  '.pdf': 'pdf',
  '.png': 'image', '.jpg': 'image', '.jpeg': 'image', '.heic': 'image', '.heif': 'image',
  '.webp': 'image', '.tif': 'image', '.tiff': 'image', '.bmp': 'image',
  '.mxl': 'musicxml', '.musicxml': 'musicxml', '.xml': 'musicxml',
  '.mid': 'midi', '.midi': 'midi',
  '.mscz': 'musescore', '.mscx': 'musescore',
};
const UNSUPPORTED = 'Format non pris en charge. Envoyez un PDF, des photos (JPG, PNG, HEIC…), un fichier MusicXML, MIDI ou MuseScore.';
const MAX_PAGES = 40;
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: config.maxUploadMb * 1024 * 1024, files: MAX_PAGES } });
const utf8Name = (name: string) => Buffer.from(name, 'latin1').toString('utf8');
const titleFrom = (name: string) =>
  path.parse(name).name.replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim() || 'Partition sans titre';

function fail(status: number, message: string): never {
  throw Object.assign(new UserError(message), { status });
}
/** Chorale à l'origine de la requête (serveur en ligne) ; null en local. */
const ownerOf = (res: Response): string | null => (res.locals['owner'] as string | undefined) ?? null;

async function getScore(id: unknown, res: Response): Promise<ScoreMeta> {
  const meta = isId(id) ? await readMeta(id) : null;
  // En ligne, une chorale ne voit jamais les partitions d'une autre : même réponse que si elle n'existait pas
  if (!meta || (config.online && (meta.owner ?? null) !== ownerOf(res))) fail(404, 'Cette partition n’existe pas ou a été supprimée.');
  return meta;
}
const assertIdle = (m: ScoreMeta) => { if (BUSY.includes(m.status)) fail(409, 'Un traitement est déjà en cours pour cette partition.'); };

const app = express();
app.disable('x-powered-by');
app.use(express.json({ limit: '100kb' }));

if (config.online) {
  const publicKey = fsSync.readFileSync(config.accessPublicKey, 'utf8');
  // Application mobile (Capacitor) : autre origine que le serveur
  app.use((req, res, next) => {
    const origin = req.headers.origin;
    if (origin && config.corsOrigins.includes(origin)) {
      res.setHeader('Access-Control-Allow-Origin', origin);
      res.setHeader('Vary', 'Origin');
      res.setHeader('Access-Control-Allow-Headers', 'Authorization, Content-Type');
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PATCH, PUT, DELETE, OPTIONS');
      res.setHeader('Access-Control-Expose-Headers', 'Content-Disposition');
    }
    if (req.method === 'OPTIONS') { res.status(204).end(); return; }
    next();
  });
  // Code d'accès de la chorale : en-tête « Authorization: Pupitre PUPA1… »
  app.use(['/api', '/files'], (req, res, next) => {
    if (req.path === '/health') return next();
    const header = req.headers.authorization ?? '';
    const token = header.startsWith('Pupitre ') ? header.slice(8) : '';
    if (!token) { res.status(401).json({ error: 'Code d’accès manquant. Saisissez le code de votre chorale dans les réglages.' }); return; }
    try {
      const acc = checkAccess(token, publicKey);
      res.locals['owner'] = acc.id;
      res.locals['access'] = acc;
      next();
    } catch (e) {
      res.status(401).json({ error: (e as Error).message });
    }
  });
}

app.get('/api/health', (_req, res) => { res.json({ ok: true, online: config.online, direct: config.direct, problems: checkSetup() }); });
/** Réglages de l'application mobile : vérifie le code et affiche la chorale. */
app.get('/api/acces', (_req, res) => {
  const acc = res.locals['access'] as AccessPayload | undefined;
  res.json({ ...(acc ? { client: acc.client, id: acc.id, expires: acc.expires } : { client: null, id: null, expires: null }), direct: config.direct });
});
app.get('/api/scores', async (_req, res) => {
  const owner = ownerOf(res);
  res.json((await listMetas()).filter((m) => !config.online || (m.owner ?? null) === owner));
});
app.get('/api/scores/:id', async (req, res) => { res.json(await getScore(req.params.id, res)); });

app.post('/api/scores', upload.array('file', MAX_PAGES), async (req, res) => {
  const files = (req.files as Express.Multer.File[] | undefined) ?? [];
  if (!files.length) fail(400, 'Aucun fichier reçu.');
  const named = files.map((f) => ({ f, name: utf8Name(f.originalname), ext: path.extname(utf8Name(f.originalname)).toLowerCase() }));
  for (const n of named) if (!KINDS[n.ext]) fail(415, UNSUPPORTED);
  if (named.length > 1 && named.some((n) => KINDS[n.ext] !== 'image' && KINDS[n.ext] !== 'pdf')) {
    fail(415, 'Plusieurs fichiers à la fois : seulement des photos ou des PDF, qui deviennent les pages d’une même partition.');
  }
  // Les pages, dans l'ordre naturel des noms (page2 avant page10) ; la première donne le titre.
  named.sort((a, b) => a.name.localeCompare(b.name, 'fr', { numeric: true }));
  const originalName = named[0].name;
  const id = randomUUID();
  await fs.mkdir(dirOf(id), { recursive: true });
  let source = KINDS[named[0].ext];
  let sourceFile = `source${named[0].ext}`;
  if (named.length === 1) {
    await fs.writeFile(path.join(dirOf(id), sourceFile), named[0].f.buffer);
  } else {
    source = 'image';
    sourceFile = 'source';
    await fs.mkdir(path.join(dirOf(id), sourceFile));
    for (const [i, n] of named.entries()) {
      await fs.writeFile(path.join(dirOf(id), sourceFile, `${String(i + 1).padStart(2, '0')}${n.ext}`), n.f.buffer);
    }
  }
  const now = new Date().toISOString();
  const meta = await writeMeta({
    id, title: titleFrom(originalName), originalName, source, sourceFile, partitionFile: null, corrected: false, pages: [], owner: ownerOf(res),
    status: 'queued', progress: 0, error: null, tempo: null, timbre: 'choeur', manifest: null, revision: 0,
    createdAt: now, updatedAt: now,
  });
  enqueue({ id, kind: 'process' });
  res.status(201).json(meta);
});

app.patch('/api/scores/:id', async (req, res) => {
  const meta = await getScore(req.params.id, res);
  const title = typeof req.body?.title === 'string' ? req.body.title.trim().slice(0, 140) : '';
  if (!title) fail(400, 'Le titre ne peut pas être vide.');
  res.json(await patchMeta(meta.id, { title }));
});

app.post('/api/scores/:id/render', async (req, res) => {
  const meta = await getScore(req.params.id, res);
  assertIdle(meta);
  if (!meta.partitionFile) fail(409, 'La partition n’a pas encore été lue.');
  const tempo = req.body?.tempo == null ? meta.tempo : Number(req.body.tempo);
  if (tempo !== null && (!Number.isInteger(tempo) || tempo < 30 || tempo > 240)) fail(400, 'Le tempo doit être un entier entre 30 et 240.');
  const timbre: Timbre = req.body?.timbre === 'piano' || req.body?.timbre === 'choeur' ? req.body.timbre : meta.timbre;
  const next = await patchMeta(meta.id, { tempo, timbre, status: 'queued', progress: 0, error: null });
  enqueue({ id: meta.id, kind: 'render' });
  res.status(202).json(next);
});

app.post('/api/scores/:id/retry', async (req, res) => {
  const meta = await getScore(req.params.id, res);
  assertIdle(meta);
  const next = await patchMeta(meta.id, { status: 'queued', progress: 0, error: null });
  enqueue({ id: meta.id, kind: meta.partitionFile ? 'render' : 'process' });
  res.status(202).json(next);
});

app.put('/api/scores/:id/partition', upload.single('file'), async (req, res) => {
  const meta = await getScore(req.params.id, res);
  assertIdle(meta);
  const file = req.file ?? fail(400, 'Aucun fichier reçu.');
  const ext = path.extname(utf8Name(file.originalname)).toLowerCase();
  if (KINDS[ext] !== 'musicxml') fail(415, 'La version corrigée doit être un fichier MusicXML (.musicxml, .mxl ou .xml).');
  const partitionFile = `corrected${ext}`;
  await fs.writeFile(path.join(dirOf(meta.id), partitionFile), file.buffer);
  const next = await patchMeta(meta.id, { partitionFile, corrected: true, status: 'queued', progress: 0, error: null });
  enqueue({ id: meta.id, kind: 'render' });
  res.status(202).json(next);
});

app.delete('/api/scores/:id', async (req, res) => {
  const meta = await getScore(req.params.id, res);
  assertIdle(meta);
  await removeScore(meta.id);
  res.status(204).end();
});

/** Pack de répétition (.pupitre) : partition + une piste par voix, à envoyer aux choristes pour l'application mobile. */
/**
 * Lecture directe : photos (ou PDF) → pack de répétition dans la même réponse, sans rien stocker.
 * Réponse en lignes JSON : {"status","progress"} au fil de la lecture, puis {"pack": base64} ou {"error"}.
 */
app.post('/api/lire', upload.array('file', 12), async (req, res) => {
  const files = ((req.files as Express.Multer.File[] | undefined) ?? []).map((f) => {
    const name = utf8Name(f.originalname);
    return { name, ext: path.extname(name).toLowerCase(), data: f.buffer };
  });
  if (!files.length) fail(400, 'Aucune photo reçue.');
  if (files.some((f) => KINDS[f.ext] !== 'image' && KINDS[f.ext] !== 'pdf')) fail(415, 'Envoyez des photos (JPG, PNG, HEIC) ou un PDF.');
  files.sort((a, b) => a.name.localeCompare(b.name, 'fr', { numeric: true }));
  const title = (typeof req.body?.titre === 'string' && req.body.titre.trim().slice(0, 140)) || titleFrom(files[0].name);
  res.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Accel-Buffering', 'no');
  const send = (o: object) => res.write(`${JSON.stringify(o)}\n`);
  const ping = setInterval(() => send({ ping: true }), 10_000); // garde la connexion ouverte pendant les longues lectures
  try {
    const pack = await readDirect(files, title, (e) => send(e));
    send({ status: 'ready', progress: 100, title, pack: pack.toString('base64') });
  } catch (e) {
    console.error('Lecture directe :', e, (e as { detail?: string }).detail ?? '');
    send({ status: 'failed', error: e instanceof UserError ? e.message : 'La lecture a échoué. Reprenez la photo : page bien à plat, en pleine lumière.' });
  } finally {
    clearInterval(ping);
    res.end();
  }
});

app.get('/api/scores/:id/pack', async (req, res) => {
  const meta = await getScore(req.params.id, res);
  const m = meta.manifest ?? fail(409, 'L’audio de cette partition n’est pas encore prêt.');
  const data = await buildPack(meta.title, m, path.join(dirOf(meta.id), 'audio'));
  const name = packFileName(meta.title);
  res.setHeader('Content-Type', 'application/octet-stream');
  const ascii = name.normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/[^\x20-\x7e]|"/g, '_');
  res.setHeader('Content-Disposition', `attachment; filename="${ascii}"; filename*=UTF-8''${encodeURIComponent(name)}`);
  res.send(data);
});

app.get('/files/:id/:folder/:file', async (req, res) => {
  const { id, folder, file } = req.params;
  if (!isId(id) || !['audio', 'pages'].includes(folder) || !/^[\w.-]+$/.test(file)) fail(404, 'Fichier introuvable.');
  if (config.online) await getScore(id, res);
  const download = req.query['download'] !== undefined;
  res.sendFile(file, {
    root: path.join(dirOf(id), folder), dotfiles: 'deny', maxAge: '7d',
    headers: download ? { 'Content-Disposition': `attachment; filename="${file}"` } : {},
  }, (err) => { if (err && !res.headersSent) res.status(404).json({ error: 'Fichier introuvable.' }); });
});

app.use('/api', (_req: Request, res: Response) => { res.status(404).json({ error: 'Adresse inconnue.' }); });
app.use(express.static(config.webDir, { index: 'index.html', maxAge: '1h' }));
app.get('/{*splat}', (_req, res) => { res.sendFile(path.join(config.webDir, 'index.html')); });

app.use((err: unknown, _req: Request, res: Response, _next: NextFunction) => {
  if (err instanceof multer.MulterError) {
    res.status(400).json({ error: err.code === 'LIMIT_FILE_SIZE' ? `Fichier trop lourd : ${config.maxUploadMb} Mo maximum.` : 'Envoi du fichier impossible.' });
    return;
  }
  if (err instanceof UserError) {
    res.status((err as UserError & { status?: number }).status ?? 400).json({ error: err.message });
    return;
  }
  console.error(err);
  res.status(500).json({ error: 'Erreur interne du serveur.' });
});

/** Démarre Pupitre ; renvoie l'adresse réelle (port 0 = port libre choisi par le système). */
export async function start(opts: { port?: number; host?: string } = {}): Promise<{ url: string; close: () => void }> {
  await fs.mkdir(config.storageDir, { recursive: true });
  const problems = checkSetup();
  if (problems.length) {
    console.warn('\nAttention :');
    for (const p of problems) console.warn(`  - ${p}`);
    console.warn('');
  }
  await initDb();
  await recover();
  const port = opts.port ?? config.port;
  const host = opts.host ?? config.host;
  return new Promise((resolve, reject) => {
    const server = host ? app.listen(port, host) : app.listen(port);
    server.once('error', reject);
    server.once('listening', () => {
      const address = server.address();
      const real = typeof address === 'object' && address ? address.port : port;
      resolve({ url: `http://${host && host !== '0.0.0.0' ? host : 'localhost'}:${real}`, close: () => server.close() });
    });
  });
}

// Lancement en ligne de commande (npm run serve). L'application de bureau importe ce fichier et appelle start().
if (!process.env.PUPITRE_EMBEDDED) {
  start().then(({ url }) => {
    console.log(`\nPupitre est lancé : ${url}`);
    console.log('Laissez ce terminal ouvert. Ctrl+C pour arrêter.\n');
    if (process.platform === 'darwin' && !process.env.NO_OPEN) spawn('open', [url], { stdio: 'ignore', detached: true }).unref();
  }).catch((e) => {
    console.error('\nImpossible de démarrer Pupitre :', e.message);
    process.exit(1);
  });
}
