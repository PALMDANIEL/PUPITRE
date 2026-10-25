/**
 * Pupitre, application de bureau (Electron) :
 * 1. vérifie la licence de cette machine (sinon : fenêtre d'activation) ;
 * 2. démarre le serveur Pupitre en interne, joignable seulement depuis cet ordinateur (127.0.0.1, port libre) ;
 * 3. ouvre l'interface dans une fenêtre.
 */
import { app, BrowserWindow, clipboard, dialog, ipcMain, Menu, shell } from 'electron';
import { spawnSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import { daysLeft, frDate } from '../../licence/core';
import { CREDITS } from '../../src/app/core/credits';
import { currentStatus, install, type LicenceStatus } from './licence-state';

const DEV = !app.isPackaged;
const REPO = path.resolve(__dirname, '..', '..');
const RES = DEV ? REPO : process.resourcesPath;
const BG = '#050918';

let mainWindow: BrowserWindow | null = null;
let activation: BrowserWindow | null = null;
let serverStarted = false;

if (!app.requestSingleInstanceLock()) app.quit();
app.on('second-instance', () => {
  const w = mainWindow ?? activation;
  if (w) { if (w.isMinimized()) w.restore(); w.focus(); }
});

/** Premier fichier trouvé (Audiveris n'a pas le même chemin selon le système et l'installateur). */
function find(dir: string, names: string[], depth = 5): string | null {
  if (!fs.existsSync(dir) || depth < 0) return null;
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isFile() && names.includes(entry.name)) return full;
    if (entry.isDirectory()) { const hit = find(full, names, depth - 1); if (hit) return hit; }
  }
  return null;
}

/**
 * Mac : une application téléchargée a tous ses fichiers marqués « en quarantaine ». L'utilisateur autorise Pupitre,
 * mais le moteur et Audiveris embarqués, lancés ensuite, pourraient être bloqués à leur tour : on lève la marque
 * sur nos propres ressources (sans effet si l'application est sur un disque en lecture seule).
 */
function releaseQuarantine() {
  if (DEV || process.platform !== 'darwin') return;
  for (const dir of ['engine', 'audiveris']) {
    spawnSync('/usr/bin/xattr', ['-dr', 'com.apple.quarantine', path.join(RES, dir)], { stdio: 'ignore' });
  }
}

/** Emplacements du moteur, d'Audiveris et des sons : embarqués dans l'installation, ou ceux du développeur. */
function configureEnvironment() {
  releaseQuarantine();
  const exe = process.platform === 'win32' ? '.exe' : '';
  const env = process.env;
  env.PUPITRE_EMBEDDED = '1';
  env.STORE = 'files';
  env.HOST = '127.0.0.1';
  env.STORAGE_DIR = path.join(app.getPath('documents'), 'Pupitre');
  env.PUPITRE_ROOT = RES;
  if (DEV) {
    env.WEB_DIR = path.join(REPO, 'dist', 'pupitre', 'browser');
  } else {
    env.WEB_DIR = path.join(RES, 'web');
    env.ENGINE_BIN = path.join(RES, 'engine', `pupitre-engine${exe}`);
    env.SOUNDFONT = path.join(RES, 'soundfont', 'GeneralUser-GS.sf2');
    const audiveris = process.platform === 'darwin'
      ? path.join(RES, 'audiveris', 'Audiveris.app', 'Contents', 'MacOS', 'Audiveris')
      : find(path.join(RES, 'audiveris'), ['Audiveris.exe', 'Audiveris.bat']);
    if (audiveris) env.AUDIVERIS_BIN = audiveris;
    env.MUSESCORE_BIN ??= '';
  }
}

function licenceText(status: LicenceStatus & { ok: true }) {
  const lic = status.licence;
  const left = daysLeft(lic, new Date());
  return [
    `Licence ${lic.id}`,
    `Client : ${lic.client}`,
    `Ordinateur : ${status.machine}`,
    lic.expires ? `Valable jusqu’au ${frDate(lic.expires)} inclus (${left} jour${left === 1 ? '' : 's'} restant${left === 1 ? '' : 's'})` : 'Licence définitive (sans date de fin)',
  ].join('\n');
}

function buildMenu() {
  const about = async () => {
    const status = currentStatus();
    await dialog.showMessageBox({
      type: 'info', title: 'À propos de Pupitre', message: `Pupitre ${app.getVersion()}`,
      detail: `Conçu et développé par ${CREDITS.company} · ${CREDITS.companyLong}\nPDG : ${CREDITS.ceo}\nDéveloppeur : ${CREDITS.developer}, ${CREDITS.city}, ${CREDITS.country}\nTéléphone : ${CREDITS.phones.map((p) => p.label).join(' · ')}\n\n${status.ok ? licenceText(status) : status.message}`,
    });
  };
  const licence = async () => {
    const status = currentStatus();
    const { response } = await dialog.showMessageBox({
      type: status.ok ? 'info' : 'warning', title: 'Licence', message: status.ok ? 'Pupitre est activé' : 'Licence à renouveler',
      detail: status.ok ? licenceText(status) : status.message,
      buttons: ['Fermer', 'Copier l’identifiant de l’ordinateur', 'Saisir une nouvelle licence…'], defaultId: 0, cancelId: 0,
    });
    if (response === 1) clipboard.writeText(status.machine);
    if (response === 2) openActivation(status);
  };
  const library = () => shell.openPath(process.env.STORAGE_DIR ?? app.getPath('documents'));
  const mac = process.platform === 'darwin';
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(mac ? [{ label: 'Pupitre', submenu: [
      { label: 'À propos de Pupitre', click: about }, { label: 'Licence…', click: licence }, { type: 'separator' as const },
      { role: 'hide' as const, label: 'Masquer Pupitre' }, { role: 'hideOthers' as const, label: 'Masquer les autres' },
      { type: 'separator' as const }, { role: 'quit' as const, label: 'Quitter Pupitre' },
    ] }] : []),
    { label: 'Fichier', submenu: [
      { label: 'Ouvrir le dossier des partitions', click: library },
      ...(mac ? [] : [{ type: 'separator' as const }, { role: 'quit' as const, label: 'Quitter' }]),
    ] },
    { label: 'Édition', submenu: [
      { role: 'undo', label: 'Annuler' }, { role: 'redo', label: 'Rétablir' }, { type: 'separator' },
      { role: 'cut', label: 'Couper' }, { role: 'copy', label: 'Copier' }, { role: 'paste', label: 'Coller' }, { role: 'selectAll', label: 'Tout sélectionner' },
    ] },
    { label: 'Affichage', submenu: [
      { role: 'reload', label: 'Actualiser' }, { role: 'togglefullscreen', label: 'Plein écran' },
      { role: 'zoomIn', label: 'Zoom avant' }, { role: 'zoomOut', label: 'Zoom arrière' }, { role: 'resetZoom', label: 'Taille réelle' },
      ...(DEV ? [{ role: 'toggleDevTools' as const, label: 'Outils de développement' }] : []),
    ] },
    { label: 'Aide', submenu: [
      ...(mac ? [] : [{ label: 'À propos de Pupitre', click: about }, { label: 'Licence…', click: licence }]),
      { label: 'Contacter AIT', click: () => dialog.showMessageBox({ type: 'info', title: 'Contacter AIT', message: `${CREDITS.company} · ${CREDITS.companyLong}`, detail: `${CREDITS.city}, ${CREDITS.country}\nTéléphone : ${CREDITS.phones.map((p) => p.label).join('\n')}` }) },
    ] },
  ]));
}

/** Liens externes (téléphone, sites) : ouverts par le système, jamais dans la fenêtre de Pupitre. */
function keepInside(win: BrowserWindow, base: string) {
  win.webContents.setWindowOpenHandler(({ url }) => { void shell.openExternal(url); return { action: 'deny' }; });
  win.webContents.on('will-navigate', (event, url) => {
    if (!url.startsWith(base)) { event.preventDefault(); void shell.openExternal(url); }
  });
}

/** L'interface affiche la licence (dates, jours restants) : le serveur intégré la lit dans ce même processus. */
function publishLicence(status = currentStatus()) {
  if (!status.ok) { delete process.env.PUPITRE_LICENCE; return; }
  const l = status.licence;
  process.env.PUPITRE_LICENCE = JSON.stringify({
    id: l.id, client: l.client, issued: l.issued, expires: l.expires, machine: status.machine, daysLeft: daysLeft(l, new Date()),
  });
}

async function openMain() {
  configureEnvironment();
  publishLicence();
  const { start } = await import('../../server/main');
  const { url } = await start({ port: 0, host: '127.0.0.1' });
  serverStarted = true;
  mainWindow = new BrowserWindow({
    width: 1320, height: 880, minWidth: 380, minHeight: 600, backgroundColor: BG, title: 'Pupitre', show: false,
    webPreferences: { contextIsolation: true, sandbox: true },
  });
  keepInside(mainWindow, url);
  mainWindow.once('ready-to-show', () => mainWindow?.show());
  mainWindow.on('closed', () => { mainWindow = null; });
  await mainWindow.loadURL(url);
}

function openActivation(status: LicenceStatus) {
  if (activation) { activation.focus(); return; }
  activation = new BrowserWindow({
    width: 620, height: 720, resizable: false, backgroundColor: BG, title: 'Activer Pupitre', show: false,
    webPreferences: { preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, sandbox: false },
  });
  activation.removeMenu();
  activation.once('ready-to-show', () => activation?.show());
  activation.on('closed', () => { activation = null; if (!serverStarted) app.quit(); });
  void activation.loadFile(path.join(__dirname, 'activation.html'), { query: { status: JSON.stringify(status) } });
}

ipcMain.handle('licence:status', () => currentStatus());
ipcMain.handle('licence:copy', () => { clipboard.writeText(currentStatus().machine); return true; });
ipcMain.handle('licence:open-file', async () => {
  const { canceled, filePaths } = await dialog.showOpenDialog(activation ?? undefined as never, {
    title: 'Choisir le fichier de licence', filters: [{ name: 'Licence Pupitre', extensions: ['licence', 'txt'] }], properties: ['openFile'],
  });
  return canceled || !filePaths[0] ? null : fs.readFileSync(filePaths[0], 'utf8');
});
ipcMain.handle('licence:install', async (_e, text: string) => {
  const status = install(String(text ?? ''));
  if (status.ok) {
    publishLicence(status);
    mainWindow?.webContents.reload();
    activation?.close();
    if (!serverStarted) await openMain();
  }
  return status;
});
ipcMain.handle('credits', () => CREDITS);

app.whenReady().then(async () => {
  buildMenu();
  const status = currentStatus();
  if (!status.ok) return openActivation(status);
  await openMain();
  const left = daysLeft(status.licence, new Date());
  if (left !== null && left <= 30) {
    void dialog.showMessageBox(mainWindow!, {
      type: 'warning', title: 'Licence', message: `Votre licence expire dans ${left} jour${left === 1 ? '' : 's'}.`,
      detail: `Elle est valable jusqu’au ${frDate(status.licence.expires!)} inclus. Contactez AIT pour la renouveler : ${CREDITS.phones.map((p) => p.label).join(' · ')}`,
    });
  }
}).catch((e) => {
  dialog.showErrorBox('Pupitre ne peut pas démarrer', String(e?.message ?? e));
  app.quit();
});

app.on('window-all-closed', () => app.quit());
