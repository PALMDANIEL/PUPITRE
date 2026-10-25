import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

// PUPITRE_ROOT : dossier des ressources (l'application de bureau le fixe ; sinon le dossier courant).
const root = process.env.PUPITRE_ROOT ?? process.cwd();
try { process.loadEnvFile(path.join(root, '.env')); } catch { }

const env = process.env;
const home = os.homedir();
const macAudiveris = '/Applications/Audiveris.app/Contents/MacOS/Audiveris';

function findMuseScore(): string | null {
  const candidates = [
    env.MUSESCORE_BIN,
    '/Applications/MuseScore 4.app/Contents/MacOS/mscore',
    '/Applications/MuseScore 3.app/Contents/MacOS/mscore',
    ...(env.PATH ?? '').split(path.delimiter).flatMap((d) => ['mscore', 'mscore4portable', 'musescore4', 'musescore'].map((b) => path.join(d, b))),
  ];
  return candidates.find((c) => c && fs.existsSync(c)) ?? null;
}

export const config = {
  port: Number(env.PORT ?? 3000),
  host: env.HOST,
  /** postgres : installation serveur (DATABASE_URL défini) ; files : version installable, sans base de données. */
  store: (env.STORE ?? (env.DATABASE_URL ? 'postgres' : 'files')) as 'postgres' | 'files',
  databaseUrl: env.DATABASE_URL ?? 'postgresql://postgres:postgres@localhost:5432/pupitre',
  storageDir: path.resolve(env.STORAGE_DIR ?? path.join(root, 'data')),
  webDir: path.resolve(env.WEB_DIR ?? path.join(root, 'dist', 'pupitre', 'browser')),
  engineDir: path.resolve(env.ENGINE_DIR ?? path.join(root, 'engine')),
  /** Moteur autonome (PyInstaller) de la version installable ; à défaut, les scripts Python d'engineDir. */
  engineBin: env.ENGINE_BIN ?? null,
  python: env.PYTHON_BIN ?? path.join(home, 'pupitre', 'engine', '.venv', 'bin', 'python3'),
  audiveris: env.AUDIVERIS_BIN ?? (fs.existsSync(macAudiveris) ? macAudiveris : '/opt/audiveris/bin/Audiveris'),
  musescore: findMuseScore(),
  /** Serveur de lecture en ligne AIT : codes d'accès exigés, partitions séparées par chorale, CORS pour l'app mobile. */
  online: env.ACCES_EN_LIGNE === '1',
  /** Hébergement sans disque permanent (Vercel) : l'application mobile utilise la lecture directe /api/lire. */
  direct: env.LECTURE_DIRECTE === '1',
  accessPublicKey: env.ACCESS_PUBLIC_KEY_FILE ?? path.join(root, 'licence', 'cle-publique.pem'),
  /** Registre d'administration (en ligne) : base PostgreSQL, par exemple Neon via Vercel (DATABASE_URL). */
  adminDatabaseUrl: env.ADMIN_DATABASE_URL ?? env.DATABASE_URL ?? null,
  corsOrigins: (env.CORS_ORIGINS ?? 'https://localhost,capacitor://localhost,http://localhost').split(',').map((o) => o.trim()).filter(Boolean),
  maxUploadMb: Number(env.MAX_UPLOAD_MB ?? 30),
  omrTimeoutMs: Number(env.OMR_TIMEOUT_MS ?? 15 * 60_000),
  renderTimeoutMs: Number(env.RENDER_TIMEOUT_MS ?? 8 * 60_000),
};

process.env.AUDIVERIS_BIN ??= config.audiveris;
process.env.OMR_TIMEOUT_S ??= String(Math.round(config.omrTimeoutMs / 1000));

if (!env.SOUNDFONT) {
  const sf = path.join(home, 'soundfonts', 'GeneralUser-GS.sf2');
  if (fs.existsSync(sf)) process.env.SOUNDFONT = sf;
}

/** Commande pour une étape du moteur (omr, render…). */
export function engineCommand(step: 'omr' | 'render', args: string[]): [string, string[]] {
  return config.engineBin ? [config.engineBin, [step, ...args]] : [config.python, [path.join(config.engineDir, `${step}.py`), ...args]];
}

export function checkSetup(): string[] {
  const problems: string[] = [];
  if (config.engineBin) {
    if (!fs.existsSync(config.engineBin)) problems.push(`Moteur introuvable : ${config.engineBin}`);
  } else {
    if (!fs.existsSync(path.join(config.engineDir, 'render.py'))) problems.push(`Moteur introuvable dans ${config.engineDir}`);
    if (!fs.existsSync(config.python)) problems.push(`Python introuvable : ${config.python}`);
  }
  if (!fs.existsSync(config.audiveris)) problems.push(`Audiveris introuvable : ${config.audiveris}`);
  if (!process.env.SOUNDFONT) problems.push('Banque de sons introuvable : ~/soundfonts/GeneralUser-GS.sf2');
  if (!fs.existsSync(path.join(config.webDir, 'index.html'))) problems.push('Interface non compilée : lancez « npm start »');
  if (config.online && !fs.existsSync(config.accessPublicKey)) problems.push(`Clé publique des codes d’accès introuvable : ${config.accessPublicKey}`);
  return problems;
}
