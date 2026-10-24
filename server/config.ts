import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const root = process.cwd();
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
  databaseUrl: env.DATABASE_URL ?? 'postgresql://postgres:postgres@localhost:5432/pupitre',
  storageDir: path.resolve(env.STORAGE_DIR ?? path.join(root, 'data')),
  webDir: path.join(root, 'dist', 'pupitre', 'browser'),
  engineDir: path.resolve(env.ENGINE_DIR ?? path.join(root, 'engine')),
  python: env.PYTHON_BIN ?? path.join(home, 'pupitre', 'engine', '.venv', 'bin', 'python3'),
  audiveris: env.AUDIVERIS_BIN ?? (fs.existsSync(macAudiveris) ? macAudiveris : '/opt/audiveris/bin/Audiveris'),
  musescore: findMuseScore(),
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

export function checkSetup(): string[] {
  const problems: string[] = [];
  if (!fs.existsSync(path.join(config.engineDir, 'render.py'))) problems.push(`Moteur introuvable dans ${config.engineDir}`);
  if (!fs.existsSync(config.python)) problems.push(`Python introuvable : ${config.python}`);
  if (!fs.existsSync(config.audiveris)) problems.push(`Audiveris introuvable : ${config.audiveris}`);
  if (!process.env.SOUNDFONT) problems.push('Banque de sons introuvable : ~/soundfonts/GeneralUser-GS.sf2');
  if (!fs.existsSync(path.join(config.webDir, 'index.html'))) problems.push('Interface non compilée : lancez « npm start »');
  return problems;
}
