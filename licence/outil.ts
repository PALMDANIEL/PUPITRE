/**
 * Outil AIT de gestion des licences Pupitre (à garder chez AIT, jamais livré aux clients).
 *
 *   npm run licence -- init                      crée la paire de clés (une seule fois)
 *   npm run licence -- creer --client "Chorale Sainte Cécile" --machine ABCD-EFGH-JKLM-NPQR --duree 1a
 *        --duree : 1a, 2a, 6m, 30j… ou illimitee        options : --contact "…" --debut AAAA-MM-JJ
 *   npm run licence -- verifier <fichier .licence ou texte PUP1…> [--machine …]
 *   npm run licence -- liste                     registre des licences émises
 *   npm run licence -- machine                   identifiant de cet ordinateur
 *
 * Clé privée et registre : ~/.pupitre-ait (ou PUPITRE_AIT_DIR). Sauvegardez ce dossier :
 * sans la clé privée, impossible d'émettre des licences reconnues par les versions déjà installées.
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { checkLicence, decodeLicence, frDate, generateKeys, signLicence, type LicencePayload } from './core';
import { machineId, normalizeMachineId } from './machine';

const HOME = process.env.PUPITRE_AIT_DIR ?? path.join(os.homedir(), '.pupitre-ait');
const PRIVATE = path.join(HOME, 'licence-privee.pem');
const PUBLIC = path.join(__dirname, 'cle-publique.pem');
const ISSUED = path.join(HOME, 'licences');
const REGISTRY = path.join(HOME, 'registre.csv');

function fail(msg: string): never {
  console.error(`\n  ✗ ${msg}\n`);
  process.exit(1);
}

function args(list: string[]) {
  const named: Record<string, string> = {};
  const rest: string[] = [];
  for (let i = 0; i < list.length; i++) {
    if (list[i].startsWith('--')) named[list[i].slice(2)] = list[i + 1]?.startsWith('--') || list[i + 1] === undefined ? 'oui' : list[++i];
    else rest.push(list[i]);
  }
  return { named, rest };
}

function addDuration(start: string, duree: string): string | null {
  if (/^illimit/i.test(duree)) return null;
  const m = /^(\d+)\s*([ajm])/i.exec(duree);
  if (!m) fail('Durée invalide. Exemples : 1a (un an), 6m (six mois), 30j (trente jours), illimitee.');
  const n = Number(m[1]);
  const d = new Date(`${start}T12:00:00Z`);
  const unit = m[2].toLowerCase();
  if (unit === 'a') d.setUTCFullYear(d.getUTCFullYear() + n);
  if (unit === 'm') d.setUTCMonth(d.getUTCMonth() + n);
  if (unit === 'j') d.setUTCDate(d.getUTCDate() + n);
  d.setUTCDate(d.getUTCDate() - 1); // une licence d'un an émise le 24/10 vaut jusqu'au 23/10 inclus
  return d.toISOString().slice(0, 10);
}

const csv = (v: string) => `"${v.replace(/"/g, '""')}"`;

function nextId(year: string): string {
  const lines = fs.existsSync(REGISTRY) ? fs.readFileSync(REGISTRY, 'utf8').split('\n') : [];
  const n = lines.filter((l) => l.startsWith(`"AIT-${year}-`)).length + 1;
  return `AIT-${year}-${String(n).padStart(4, '0')}`;
}

function describe(lic: LicencePayload) {
  console.log(`    Numéro      ${lic.id}`);
  console.log(`    Client      ${lic.client}${lic.contact ? ` (${lic.contact})` : ''}`);
  console.log(`    Machine     ${lic.machine}`);
  console.log(`    Émise le    ${frDate(lic.issued)}`);
  console.log(`    Valable     ${lic.expires ? `jusqu’au ${frDate(lic.expires)} inclus` : 'sans limite de durée'}`);
}

const [command, ...rest] = process.argv.slice(2);
const { named, rest: positional } = args(rest);

switch (command) {
  case 'init': {
    if (fs.existsSync(PRIVATE)) fail(`Une clé privée existe déjà : ${PRIVATE}\n    La remplacer rendrait invalides toutes les licences déjà émises.`);
    fs.mkdirSync(HOME, { recursive: true, mode: 0o700 });
    const { privatePem, publicPem } = generateKeys();
    fs.writeFileSync(PRIVATE, privatePem, { mode: 0o600 });
    fs.writeFileSync(PUBLIC, publicPem);
    console.log(`\n  ✓ Clé privée créée : ${PRIVATE}  (secrète : sauvegardez-la, ne la partagez jamais)`);
    console.log(`  ✓ Clé publique : ${PUBLIC}  (intégrée à l’application)\n`);
    break;
  }
  case 'creer': {
    if (!fs.existsSync(PRIVATE)) fail('Aucune clé privée. Lancez d’abord : npm run licence -- init');
    const client = named['client'];
    if (!client || client === 'oui') fail('Indiquez le client : --client "Chorale Sainte Cécile"');
    const machine = normalizeMachineId(named['machine'] ?? '');
    if (!machine) fail('Identifiant de machine invalide. Il s’affiche dans Pupitre chez le client, ex. ABCD-EFGH-JKLM-NPQR.');
    const issued = named['debut'] ?? new Date().toISOString().slice(0, 10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(issued)) fail('Date de début invalide (format AAAA-MM-JJ).');
    const expires = addDuration(issued, named['duree'] ?? fail('Indiquez la durée : --duree 1a, 6m, 30j ou illimitee'));
    const payload: LicencePayload = {
      id: nextId(issued.slice(0, 4)), client, machine, issued, expires, edition: 'standard',
      ...(named['contact'] && named['contact'] !== 'oui' ? { contact: named['contact'] } : {}),
    };
    const text = signLicence(payload, fs.readFileSync(PRIVATE, 'utf8'));
    checkLicence(text, fs.readFileSync(PUBLIC, 'utf8'), machine, new Date(`${issued}T12:00:00Z`)); // contrôle immédiat
    fs.mkdirSync(ISSUED, { recursive: true });
    const file = path.join(ISSUED, `${payload.id}.licence`);
    fs.writeFileSync(file, `${text}\n`);
    if (!fs.existsSync(REGISTRY)) fs.writeFileSync(REGISTRY, 'numero,client,contact,machine,emise,expire\n');
    fs.appendFileSync(REGISTRY, [payload.id, client, payload.contact ?? '', machine, issued, expires ?? 'illimitée'].map(csv).join(',') + '\n');
    console.log('\n  ✓ Licence créée\n');
    describe(payload);
    console.log(`\n  Fichier à envoyer au client : ${file}`);
    console.log('  Ou texte à copier-coller dans Pupitre :\n');
    console.log(text);
    console.log('');
    break;
  }
  case 'verifier': {
    const input = positional[0] ?? fail('Donnez un fichier .licence ou le texte de la licence.');
    const text = fs.existsSync(input) ? fs.readFileSync(input, 'utf8') : input;
    try {
      const pub = fs.readFileSync(PUBLIC, 'utf8');
      const lic = named['machine'] ? checkLicence(text, pub, normalizeMachineId(named['machine']) ?? '', new Date()) : decodeLicence(text, pub);
      console.log('\n  ✓ Licence authentique\n');
      describe(lic);
      console.log('');
    } catch (e) {
      fail((e as Error).message);
    }
    break;
  }
  case 'liste': {
    if (!fs.existsSync(REGISTRY)) { console.log('\n  Aucune licence émise pour l’instant.\n'); break; }
    console.log(`\n${fs.readFileSync(REGISTRY, 'utf8')}`);
    break;
  }
  case 'machine': {
    console.log(`\n  Identifiant de cet ordinateur : ${machineId()}\n`);
    break;
  }
  default:
    console.log(fs.readFileSync(__filename, 'utf8').split('*/')[0].replace(/^\/\*\*?|^ \* ?/gm, ''));
}
