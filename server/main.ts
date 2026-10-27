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
import { BUSY, LANGUES, TIMBRES, UserError, type Langue, type ScoreMeta, type SourceKind, type Timbre, type Voyelle } from './types';
import { buildPack, packFileName } from './pack';
import { readDirect, recreateDirect } from './direct';
import { checkAccess, type AccessPayload } from '../licence/acces';
import { checkAdmin } from '../licence/admin';
import { checkLicence, decodeLicence, signedWith, type LicencePayload } from '../licence/core';
import * as admin from './admin';
import * as pay from './paiement';
import { directNumbers as paymentNumbers } from './passerelles';

const PHONE = '00226 77 41 91 06';
const clientIp = (req: Request) => String(req.headers['x-forwarded-for'] ?? req.socket.remoteAddress ?? '').split(',')[0].trim() || undefined;

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
  // Clé AIT + clé de vente du serveur (licences et codes payés en ligne) ; l'administration n'accepte que la clé AIT.
  const keys = [publicKey, ...(fsSync.existsSync(config.salePublicKey) ? [fsSync.readFileSync(config.salePublicKey, 'utf8')] : [])];
  /** Signé par la clé de vente mais jamais vendu par ce serveur : faux (clé de vente dérobée). */
  const forgedSale = async (text: string) => !signedWith(text, publicKey) && !(await pay.isKnownSale(text));
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
  app.use(['/api', '/files'], async (req, res, next) => {
    // signalement des ordinateurs et administration : leur propre vérification (licence, jeton AIT)
    if (req.path === '/health' || req.path === '/checkin' || req.path.startsWith('/admin') || req.path.startsWith('/paiement')) return next();
    const header = req.headers.authorization ?? '';
    const token = header.startsWith('Pupitre ') ? header.slice(8) : '';
    if (!token) { res.status(401).json({ error: 'Code d’accès manquant. Saisissez le code de votre chorale dans les réglages.' }); return; }
    let acc: AccessPayload;
    try {
      acc = checkAccess(token, keys);
      if (await forgedSale(token)) throw new Error('Ce code d’accès n’a pas été délivré par AIT.');
    } catch (e) {
      res.status(401).json({ error: (e as Error).message });
      return;
    }
    try {
      await admin.register('acces', acc);
      const st = await admin.statusOf(acc.id);
      if (st?.status === 'revoked') {
        res.status(401).json({ error: `Le code de « ${acc.client} » a été désactivé par AIT${st.reason ? ` (${st.reason})` : ''}. Contactez AIT au ${PHONE}.` });
        return;
      }
      void admin.touch(acc.id, { ip: clientIp(req), version: String(req.headers['x-pupitre-version'] ?? '') || undefined }).catch(() => undefined);
    } catch (e) {
      console.error('Registre d’administration indisponible :', (e as Error).message); // la lecture continue
    }
    res.locals['owner'] = acc.id;
    res.locals['access'] = acc;
    next();
  });

  // Signalement des ordinateurs (application de bureau) : licence vérifiée, connexion notée, état renvoyé.
  app.post('/api/checkin', async (req, res) => {
    const { licence, machine, version, os } = (req.body ?? {}) as Record<string, string>;
    // licence renouvelée en ligne : renvoyée même si celle de l'ordinateur a déjà expiré
    const peek = pay.peekLicence(String(licence ?? ''), keys);
    const renewal = peek && peek.machine === String(machine ?? '') ? await pay.renewalOf(peek.id, peek.expires).catch(() => null) : null;
    let lic: LicencePayload;
    try {
      lic = checkLicence(String(licence ?? ''), keys, String(machine ?? ''), new Date());
    } catch (e) {
      res.json({ status: 'invalid', message: (e as Error).message, renewal, serverTime: new Date().toISOString() });
      return;
    }
    let status: 'active' | 'revoked' = 'active';
    let message: string | null = null;
    try {
      if (await forgedSale(String(licence))) {
        res.json({ status: 'revoked', message: `Cette licence n’a pas été délivrée par AIT. Contactez AIT au ${PHONE}.`, renewal: null, serverTime: new Date().toISOString() });
        return;
      }
      await admin.register('licence', lic);
      await admin.touch(lic.id, { version, os, ip: clientIp(req) });
      const st = await admin.statusOf(lic.id);
      if (st?.status === 'revoked') {
        status = 'revoked';
        message = `Cette licence (${lic.id}) a été désactivée par AIT${st.reason ? ` : ${st.reason}` : ''}. Contactez AIT au ${PHONE}.`;
      }
    } catch (e) {
      console.error('Registre d’administration indisponible :', (e as Error).message);
    }
    res.json({ status, message, renewal: status === 'active' ? renewal : null, serverTime: new Date().toISOString(), managed: admin.adminEnabled() });
  });

  // Vente en ligne (LigdiCash) : sans code d'accès, la page d'achat est publique.
  app.get('/api/paiement/tarifs', async (_req, res) => {
    res.json({ open: pay.salesEnabled(), methods: pay.paymentMethods(), prices: pay.salesEnabled() ? (await pay.listPrices()).map(({ product, kind, duration, label, amount }) => ({ product, kind, duration, label, amount })) : [] });
  });
  app.post('/api/paiement/commande', async (req, res) => { res.json(await pay.createOrder((req.body ?? {}) as Record<string, string>)); });
  app.get('/api/paiement/commande/:id', async (req, res) => {
    const o = /^[0-9a-f-]{36}$/.test(req.params.id) ? await pay.refreshOrder(req.params.id) : null;
    if (!o) fail(404, 'Commande introuvable.');
    // le texte d'un code de chorale renouvelé n'est pas montré ici : il arrive tout seul sur les téléphones de la chorale
    const showText = o!.status === 'paid' && !(o!.kind === 'acces' && o!.renew_id);
    const direct = o!.gateway === 'direct';
    res.json({ id: o!.id, status: o!.status, kind: o!.kind, product: o!.product, amount: o!.amount, client: o!.client, renewal: !!o!.renew_id,
      itemId: o!.item_id, expires: o!.expires, text: showText ? o!.text : null,
      direct, numbers: direct ? paymentNumbers() : null, declared: direct && !!o!.declared_at, reference: direct ? o!.invoice_token : null, operator: direct ? o!.operator : null,
      reason: o!.status === 'failed' && direct ? ((o as unknown as { detail?: { reason?: string } }).detail?.reason ?? null) : null });
  });
  app.post('/api/paiement/commande/:id/declarer', async (req, res) => {
    if (!/^[0-9a-f-]{36}$/.test(req.params.id)) fail(404, 'Commande introuvable.');
    await pay.declareDirect(req.params.id, (req.body ?? {}) as Record<string, string>);
    res.json({ ok: true });
  });
  app.post('/api/paiement/rappel', express.urlencoded({ extended: true }), async (req, res) => {
    try { await pay.onCallback((req.body ?? {}) as Record<string, unknown>); } catch (e) { console.error('Rappel LigdiCash :', (e as Error).message); }
    res.json({ ok: true });
  });
  app.post('/api/paiement/recuperer', async (req, res) => { res.json({ licence: await pay.licenceForMachine(String(req.body?.machine ?? '')).catch(() => null) }); });
  app.post('/api/paiement/renouvellement', async (req, res) => { res.json({ code: await pay.renewalForCode(String(req.body?.code ?? ''), keys).catch(() => null) }); });

  // Administration AIT : jeton signé par la clé AIT (Espace AIT du téléphone), valable 10 minutes.
  app.use('/api/admin', (req, res, next) => {
    const header = req.headers.authorization ?? '';
    try {
      checkAdmin(header.startsWith('PupitreAdmin ') ? header.slice(13) : '', publicKey);
    } catch (e) {
      res.status(401).json({ error: (e as Error).message });
      return;
    }
    if (!admin.adminEnabled()) { res.status(503).json({ error: 'Aucune base de données reliée au serveur : le tableau de bord n’est pas disponible.' }); return; }
    next();
  });
  app.get('/api/admin/apercu', async (_req, res) => { res.json(await admin.overview()); });
  app.get('/api/admin/tarifs', async (_req, res) => { res.json({ open: pay.salesEnabled(), prices: await pay.listPrices(true) }); });
  app.post('/api/admin/tarifs', async (req, res) => {
    const prices = Array.isArray(req.body?.prices) ? req.body.prices.slice(0, 50) : [];
    await pay.setPrices(prices);
    res.json({ ok: true, prices: await pay.listPrices(true) });
  });
  app.get('/api/admin/ventes', async (req, res) => { res.json(await pay.listOrders(Number(req.query['limite'] ?? 100))); });
  app.post('/api/admin/ventes/:id/confirmer', async (req, res) => { await pay.confirmDirect(req.params.id); res.json({ ok: true }); });
  app.post('/api/admin/ventes/:id/refuser', async (req, res) => {
    await pay.refuseDirect(req.params.id, typeof req.body?.reason === 'string' ? req.body.reason.slice(0, 200) : null);
    res.json({ ok: true });
  });
  app.get('/api/admin/elements', async (_req, res) => { res.json(await admin.listItems()); });
  app.get('/api/admin/evenements', async (req, res) => { res.json(await admin.listEvents(Number(req.query['limite'] ?? 100))); });
  app.post('/api/admin/elements/:id/statut', async (req, res) => {
    const status = req.body?.status === 'revoked' ? 'revoked' : 'active';
    const reason = typeof req.body?.reason === 'string' ? req.body.reason.slice(0, 200) : null;
    const n = await admin.setStatus(req.params.id, status, reason);
    if (!n) fail(404, 'Licence ou code introuvable dans le registre.');
    res.json({ ok: true });
  });
  app.post('/api/admin/clients/statut', async (req, res) => {
    const client = typeof req.body?.client === 'string' ? req.body.client : '';
    if (!client) fail(400, 'Client manquant.');
    const status = req.body?.status === 'revoked' ? 'revoked' : 'active';
    const reason = typeof req.body?.reason === 'string' ? req.body.reason.slice(0, 200) : null;
    res.json({ ok: true, count: await admin.setClientStatus(client, status, reason) });
  });
  // Licence ou code créé hors ligne (Mac, téléphone) : inscrit au registre dès que l'administrateur a Internet.
  app.post('/api/admin/enregistrer', async (req, res) => {
    const items = Array.isArray(req.body?.items) ? req.body.items.slice(0, 500) : [];
    let n = 0;
    for (const it of items) {
      try {
        if (String(it).startsWith('PUP1.')) { const l = decodeLicence(String(it), keys); await admin.register('licence', l); n++; }
        else if (String(it).startsWith('PUPA1.')) { const a = checkAccess(String(it), keys, new Date(0)); await admin.register('acces', a); n++; }
      } catch { /* texte invalide : ignoré */ }
    }
    res.json({ ok: true, count: n });
  });
}

/** Application de bureau : licence de cet ordinateur (dates de début et de fin) ; null ailleurs. */
app.get('/api/licence', (_req, res) => {
  try { res.json({ licence: process.env.PUPITRE_LICENCE ? JSON.parse(process.env.PUPITRE_LICENCE) : null }); } catch { res.json({ licence: null }); }
});
app.get('/api/health', (_req, res) => { res.json({ ok: true, online: config.online, direct: config.direct, problems: checkSetup() }); });
/** Réglages de l'application mobile : vérifie le code et affiche la chorale. */
app.get('/api/acces', (_req, res) => {
  const acc = res.locals['access'] as AccessPayload | undefined;
  res.json({ ...(acc ? { client: acc.client, id: acc.id, issued: acc.issued, expires: acc.expires } : { client: null, id: null, issued: null, expires: null }), direct: config.direct });
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
  const timbre: Timbre = TIMBRES.includes(req.body?.timbre) ? req.body.timbre : meta.timbre;
  const voyelle: Voyelle | null = req.body?.voyelle === 'oo' || req.body?.voyelle === 'ah' ? req.body.voyelle : meta.voyelle ?? null;
  if (timbre === 'chant' && config.direct) fail(400, 'Les voix chantées se créent sur l’ordinateur (version de bureau).');
  const langue: Langue | null = LANGUES.includes(req.body?.langue) ? req.body.langue : meta.langue ?? null;
  // paroles saisies : { id de voix : « Sain-te Ma-ri-e » } ; absentes = celles de la partition
  let paroles = meta.paroles ?? null;
  if (req.body?.paroles !== undefined) {
    const raw = req.body.paroles;
    if (raw !== null && (typeof raw !== 'object' || Array.isArray(raw))) fail(400, 'Paroles invalides.');
    paroles = raw === null ? null : Object.fromEntries(Object.entries(raw as Record<string, unknown>)
      .filter(([k, v]) => /^[a-z0-9]{1,20}$/.test(k) && typeof v === 'string')
      .map(([k, v]) => [k, (v as string).slice(0, 8000)]));
  }
  const next = await patchMeta(meta.id, { tempo, timbre, langue, paroles, voyelle, status: 'queued', progress: 0, error: null });
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
/** Téléphone : recréer l'audio d'un chant enregistré (tempo, sonorité, voix chantées) à partir de sa partition. */
app.post('/api/recreer', upload.single('file'), async (req, res) => {
  const file = req.file;
  if (!file || !/\.(musicxml|xml)$/i.test(utf8Name(file.originalname))) fail(400, 'Partition manquante (fichier MusicXML du chant).');
  const body = (req.body ?? {}) as Record<string, string>;
  const title = (typeof body.titre === 'string' && body.titre.trim().slice(0, 140)) || 'Chant';
  const timbre: Timbre = TIMBRES.includes(body.timbre as Timbre) ? body.timbre as Timbre : 'choeur';
  const voyelle: Voyelle = body.voyelle === 'oo' ? 'oo' : 'ah';
  const tempo = body.tempo ? Number(body.tempo) : null;
  if (tempo !== null && (!Number.isInteger(tempo) || tempo < 30 || tempo > 240)) fail(400, 'Le tempo doit être un entier entre 30 et 240.');
  const langue: Langue = LANGUES.includes(body.langue as Langue) ? body.langue as Langue : 'fr';
  let paroles: Record<string, string> | null = null;
  if (body.paroles) {
    try {
      const raw = JSON.parse(body.paroles) as Record<string, unknown>;
      paroles = Object.fromEntries(Object.entries(raw).filter(([k, v]) => /^[a-z0-9]{1,20}$/.test(k) && typeof v === 'string').map(([k, v]) => [k, (v as string).slice(0, 8000)]));
    } catch { fail(400, 'Paroles invalides.'); }
  }
  res.setHeader('Content-Type', 'application/x-ndjson; charset=utf-8');
  res.setHeader('Cache-Control', 'no-store');
  res.setHeader('X-Accel-Buffering', 'no');
  const send = (o: object) => res.write(`${JSON.stringify(o)}\n`);
  const ping = setInterval(() => send({ ping: true }), 10_000);
  try {
    const pack = await recreateDirect(file!.buffer, title, { tempo, timbre, langue, paroles, voyelle }, (e) => send(e));
    send({ status: 'ready', progress: 100, title, pack: pack.toString('base64') });
    const owner = ownerOf(res);
    if (owner) void admin.event(owner, timbre === 'chant' ? 'voix-chantees' : 'recreation', { title, timbre }).catch(() => undefined);
  } catch (e) {
    console.error('Recréation :', e, (e as { detail?: string }).detail ?? '');
    send({ status: 'failed', error: e instanceof UserError ? e.message : 'La création de l’audio a échoué. Réessayez.' });
  } finally {
    clearInterval(ping);
    res.end();
  }
});

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
    const owner = ownerOf(res);
    if (owner) { void admin.countUse(owner).catch(() => undefined); void admin.event(owner, 'lecture', { title, pages: files.length }).catch(() => undefined); }
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
// Page d'achat en ligne (serveur AIT) : hors de l'application, ouverte dans le navigateur du client.
if (config.online) {
  const shopPage = path.join(process.env.PUPITRE_ROOT ?? process.cwd(), 'server', 'boutique', 'acheter.html');
  app.get(['/acheter', '/acheter/commande/:id'], (_req, res) => { res.setHeader('Cache-Control', 'no-store'); res.sendFile(shopPage); });
}
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
