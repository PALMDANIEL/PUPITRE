// Essai des quotas de copies à déchiffrer par jour (forfaits), avec une base PostgreSQL d'essai et des clés d'essai.
//   QUOTA_DB=postgresql://…/base_vide npx tsx .github/scripts/test_quotas.ts
// Lance le serveur en ligne (codes de chorale), règle les limites comme le tableau de bord AIT, vérifie les refus,
// la limite propre à un client, la vérification de licence d'un ordinateur, puis le serveur intégré de l'ordinateur.
import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { signAccess } from '../../licence/acces';
import { generateKeys, signLicence, signToken } from '../../licence/core';

const ROOT = process.cwd(); // à lancer depuis la racine du dépôt
const DB = process.env.QUOTA_DB;
if (!DB) { console.error('QUOTA_DB manquant (base PostgreSQL vide réservée à cet essai).'); process.exit(2); }

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'pupitre-quotas-'));
const { privatePem, publicPem } = generateKeys();
const pub = path.join(tmp, 'cle.pem');
fs.writeFileSync(pub, publicPem);
const today = new Date().toISOString().slice(0, 10);
const plus = (days: number) => new Date(Date.now() + days * 86_400_000).toISOString().slice(0, 10);
const code = signAccess({ id: 'ACC-2026-9001', client: 'Chorale Essai', issued: today, expires: plus(30), kind: 'acces' }, privatePem);
const code2 = signAccess({ id: 'ACC-2026-9002', client: 'Chorale Deux', issued: today, expires: plus(365), kind: 'acces' }, privatePem);
const machine = 'ABCD-EFGH-JKMN-PQRS';
const licence = signLicence({ id: 'AIT-2026-9003', client: 'Ordinateur Essai', machine, issued: today, expires: plus(182), edition: 'standard' }, privatePem);
const adminToken = () => signToken('PUPADM1', { kind: 'admin', exp: new Date(Date.now() + 5 * 60_000).toISOString(), nonce: Math.random().toString(36).slice(2) }, privatePem);
const pdf = fs.readFileSync(path.join(ROOT, 'engine', 'bench', 'fixtures', 'choral-bwv269.pdf'));

let failures = 0;
function check(ok: boolean, what: string, detail?: unknown) {
  console.log(`${ok ? '  ✓' : '  ✗'} ${what}${ok || detail === undefined ? '' : ` → ${JSON.stringify(detail)}`}`);
  if (!ok) failures++;
}

function serve(port: number, extra: Record<string, string>, entry = 'server/main.ts'): ChildProcess {
  const env: Record<string, string | undefined> = {
    ...process.env, PORT: String(port), HOST: '127.0.0.1', NO_OPEN: '1', STORE: 'files', STORAGE_DIR: path.join(tmp, `donnees-${port}`),
    ACCESS_PUBLIC_KEY_FILE: pub, PYTHON_BIN: '/usr/bin/false', ...extra,
  };
  delete env['DATABASE_URL'];
  const child = spawn(process.execPath, [path.join(ROOT, 'node_modules', 'tsx', 'dist', 'cli.mjs'), entry], { cwd: ROOT, env, stdio: ['ignore', 'pipe', 'pipe'] });
  child.stderr!.on('data', (d) => { if (process.env.QUOTA_VERBOSE) process.stderr.write(d); });
  child.stdout!.on('data', (d) => { if (process.env.QUOTA_VERBOSE) process.stdout.write(d); });
  return child;
}

async function ready(base: string) {
  for (let i = 0; i < 90; i++) {
    try { if ((await fetch(`${base}/api/health`)).ok) return; } catch { /* pas encore */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`serveur muet : ${base}`);
}

async function upload(base: string, headers: Record<string, string> = {}) {
  const form = new FormData();
  form.append('file', new Blob([pdf], { type: 'application/pdf' }), 'essai.pdf');
  const res = await fetch(`${base}/api/scores`, { method: 'POST', headers, body: form });
  return { status: res.status, body: await res.json().catch(() => null) as { error?: string } | null };
}

const json = async (res: Response) => ({ status: res.status, body: await res.json().catch(() => null) });

async function online() {
  console.log('Serveur en ligne (codes de chorale) :');
  const base = 'http://127.0.0.1:3991';
  const srv = serve(3991, { ACCES_EN_LIGNE: '1', ADMIN_DATABASE_URL: DB! });
  try {
    await ready(base);
    const chorale = { Authorization: `Pupitre ${code}`, 'X-Pupitre-Appareil': 'telephone-essai' };
    const adm = () => ({ Authorization: `PupitreAdmin ${adminToken()}`, 'Content-Type': 'application/json' });
    const acc = await json(await fetch(`${base}/api/acces`, { headers: chorale }));
    check(acc.status === 200 && acc.body?.quota?.limit === null, 'sans réglage : illimité', acc);
    // forfait de 1 mois (code de 30 jours) : 2 copies par jour ; 1 an : 5
    const prices = await json(await fetch(`${base}/api/admin/tarifs`, { headers: adm() }));
    check(prices.status === 200 && prices.body.prices.some((p: { product: string }) => p.product === 'acces-1m'), 'tarifs lus par l’administration', prices.status);
    const set = await json(await fetch(`${base}/api/admin/tarifs`, {
      method: 'POST', headers: adm(),
      body: JSON.stringify({ prices: prices.body.prices.map((p: { product: string; amount: number | null; active: boolean }) => ({ ...p, daily_quota: p.product === 'acces-1m' ? 2 : p.product === 'acces-1a' ? 5 : null })) }),
    }));
    check(set.status === 200 && set.body.prices.find((p: { product: string }) => p.product === 'acces-1m')?.daily_quota === 2, 'limite du forfait enregistrée', set);
    const a1 = await upload(base, chorale);
    const a2 = await upload(base, chorale);
    const a3 = await upload(base, chorale);
    check(a1.status === 201 && a2.status === 201, '2 copies acceptées', [a1.status, a2.status]);
    check(a3.status === 429 && /2 partitions par jour/.test(a3.body?.error ?? ''), '3e copie refusée avec un message clair', a3);
    const acc2 = await json(await fetch(`${base}/api/acces`, { headers: chorale }));
    check(acc2.body?.quota?.used === 2 && acc2.body?.quota?.limit === 2, 'le téléphone voit 2 / 2', acc2.body?.quota);
    // autre forfait (1 an) : sa propre limite
    const other = await upload(base, { Authorization: `Pupitre ${code2}`, 'X-Pupitre-Appareil': 'telephone-deux' });
    check(other.status === 201, 'autre chorale (forfait 1 an) : acceptée', other.status);
    // limite propre au client : 3
    const own = await json(await fetch(`${base}/api/admin/elements/ACC-2026-9001/quota`, { method: 'POST', headers: adm(), body: JSON.stringify({ daily_quota: 3 }) }));
    check(own.status === 200 && own.body.quota.limit === 3 && own.body.quota.own, 'limite propre au client enregistrée', own.body);
    const a4 = await upload(base, chorale);
    const a5 = await upload(base, chorale);
    check(a4.status === 201 && a5.status === 429, 'limite propre appliquée (3e acceptée, 4e refusée)', [a4.status, a5.status]);
    const items = await json(await fetch(`${base}/api/admin/elements`, { headers: adm() }));
    const it = items.body.find((i: { id: string }) => i.id === 'ACC-2026-9001');
    check(it?.used_today === 3 && it?.limit === 3 && it?.plan === 'acces-1m', 'tableau de bord : forfait, 3 / 3 aujourd’hui', it && { used: it.used_today, limit: it.limit, plan: it.plan });
    // retour au forfait (limite propre effacée) : 2, déjà dépassée
    await fetch(`${base}/api/admin/elements/ACC-2026-9001/quota`, { method: 'POST', headers: adm(), body: JSON.stringify({ daily_quota: null }) });
    const a6 = await upload(base, chorale);
    check(a6.status === 429, 'limite propre effacée : retour au forfait', a6.status);
    // ordinateur : la vérification de licence signale ses lectures et reçoit sa limite (forfait 6 mois : illimité ici)
    const ci = await json(await fetch(`${base}/api/checkin`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ licence, machine, version: 'essai', os: 'essai', lectures: { day: today, count: 4 } }),
    }));
    check(ci.status === 200 && ci.body.status === 'active' && ci.body.quota?.plan === 'licence-6m' && ci.body.quota.limit === null, 'ordinateur : forfait 6 mois, illimité', ci.body);
    await fetch(`${base}/api/admin/tarifs`, {
      method: 'POST', headers: adm(),
      body: JSON.stringify({ prices: [{ product: 'licence-6m', amount: null, active: false, daily_quota: 10 }] }),
    });
    const ci2 = await json(await fetch(`${base}/api/checkin`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ licence, machine, version: 'essai', os: 'essai', lectures: { day: today, count: 6 } }),
    }));
    check(ci2.body.quota?.limit === 10, 'ordinateur : limite du forfait reçue (10)', ci2.body.quota);
    const items2 = await json(await fetch(`${base}/api/admin/elements`, { headers: adm() }));
    const lic = items2.body.find((i: { id: string }) => i.id === 'AIT-2026-9003');
    check(lic?.used_today === 6 && lic?.limit === 10, 'tableau de bord : ordinateur 6 / 10 aujourd’hui', lic && { used: lic.used_today, limit: lic.limit });
    // sans code ou avec un jeton d'administration faux : refusé
    const anon = await upload(base);
    check(anon.status === 401, 'sans code : refusé', anon.status);
    const forged = await fetch(`${base}/api/admin/elements/ACC-2026-9001/quota`, { method: 'POST', headers: { Authorization: 'PupitreAdmin faux', 'Content-Type': 'application/json' }, body: '{"daily_quota":1000}' });
    check(forged.status === 401, 'administration sans la clé AIT : refusée', forged.status);
  } finally {
    srv.kill();
  }
}

async function desktop() {
  console.log('Ordinateur (serveur intégré, limite reçue d’AIT) :');
  const base = 'http://127.0.0.1:3992';
  const runner = path.join(tmp, 'bureau.ts');
  fs.writeFileSync(runner, `import { start } from '${path.join(ROOT, 'server', 'main.ts').replace(/\\/g, '/')}';\nstart({ port: 3992, host: '127.0.0.1' });\n`);
  const srv = serve(3992, {
    PUPITRE_EMBEDDED: '1',
    PUPITRE_LICENCE: JSON.stringify({ id: 'AIT-2026-9003', client: 'Ordinateur Essai', issued: today, expires: plus(182), machine, daysLeft: 182, quota: { limit: 1, label: 'Licence d’ordinateur · 6 mois', plan: 'licence-6m' } }),
  }, runner);
  try {
    await ready(base);
    const b1 = await upload(base);
    const b2 = await upload(base);
    check(b1.status === 201 && b2.status === 429 && /1 partition par jour/.test(b2.body?.error ?? ''), '1 copie acceptée, la 2e refusée', [b1.status, b2.status, b2.body?.error]);
    const lic = await json(await fetch(`${base}/api/licence`));
    check(lic.body?.licence?.today === 1 && lic.body?.licence?.quota?.limit === 1, '« À propos » : 1 / 1 aujourd’hui', lic.body?.licence);
  } finally {
    srv.kill();
  }
}

(async () => {
  try {
    await online();
    await desktop();
  } catch (e) {
    console.error('Essai interrompu :', (e as Error).message);
    failures++;
  } finally {
    fs.rmSync(tmp, { recursive: true, force: true });
  }
  console.log(failures ? `\n${failures} vérification(s) en échec.` : '\nToutes les vérifications passent.');
  process.exit(failures ? 1 : 0);
})();
