// Rassemble dans desktop/vendor ce que l'installateur embarque à côté de l'application :
//   web/ (interface Angular compilée), engine/ (moteur PyInstaller), soundfont/, licences-tierces/
// Audiveris est déposé à part dans vendor/audiveris (copie de Audiveris.app sur Mac, MSI extrait sur Windows).
import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..', '..');
const vendor = path.resolve(import.meta.dirname, '..', 'vendor');
const SOUNDFONT_URL = 'https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2';
const SOUNDFONT_LICENSE = 'https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/documentation/LICENSE.txt';

function copy(from, to) {
  if (!fs.existsSync(from)) throw new Error(`Introuvable : ${from}`);
  fs.rmSync(to, { recursive: true, force: true });
  fs.cpSync(from, to, { recursive: true, verbatimSymlinks: true });
  console.log(`  ${path.relative(root, from)} → vendor/${path.relative(vendor, to)}`);
}

async function download(url, to) {
  if (fs.existsSync(to)) return;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Téléchargement impossible (${res.status}) : ${url}`);
  fs.mkdirSync(path.dirname(to), { recursive: true });
  fs.writeFileSync(to, Buffer.from(await res.arrayBuffer()));
  console.log(`  ${url} → vendor/${path.relative(vendor, to)}`);
}

fs.mkdirSync(vendor, { recursive: true });
copy(path.join(root, 'dist', 'pupitre', 'browser'), path.join(vendor, 'web'));
copy(path.join(root, 'engine', 'dist', 'pupitre-engine'), path.join(vendor, 'engine'));
// homr : programme distinct (AGPL), lecture des notes des copies usées ; facultatif (sans lui : Audiveris seul)
const homrDist = path.join(root, 'engine', 'dist', 'pupitre-homr');
if (fs.existsSync(homrDist)) copy(homrDist, path.join(vendor, 'homr'));
else console.log('  ⚠ engine/dist/pupitre-homr manquant : copies usées lues par Audiveris seul');
const localSf = path.join(process.env.HOME ?? '', 'soundfonts', 'GeneralUser-GS.sf2');
if (fs.existsSync(localSf) && !fs.existsSync(path.join(vendor, 'soundfont', 'GeneralUser-GS.sf2'))) {
  fs.mkdirSync(path.join(vendor, 'soundfont'), { recursive: true });
  fs.copyFileSync(localSf, path.join(vendor, 'soundfont', 'GeneralUser-GS.sf2'));
}
await download(SOUNDFONT_URL, path.join(vendor, 'soundfont', 'GeneralUser-GS.sf2'));
await download(SOUNDFONT_LICENSE, path.join(vendor, 'licences-tierces', 'GeneralUser-GS.txt'));
fs.writeFileSync(path.join(vendor, 'licences-tierces', 'LISEZ-MOI.txt'), `Composants tiers livrés avec Pupitre

- Audiveris (lecture optique des partitions) : logiciel libre sous licence GNU AGPL v3.
  Programme distinct, appelé par Pupitre sans modification. Code source : https://github.com/Audiveris/audiveris
- homr (lecture des notes des copies usées, réseau de neurones) : logiciel libre sous licence GNU AGPL v3.
  Programme distinct (dossier homr), appelé par Pupitre sans modification. Code source : https://github.com/liebharc/homr
- RapidOCR (lecture des paroles) : Apache 2.0, https://github.com/RapidAI/RapidOCR ; ONNX Runtime (MIT).
- GeneralUser GS (banque de sons) : S. Christian Collins, licence dans GeneralUser-GS.txt.
- music21 (BSD), OpenCV (Apache 2.0), NumPy (BSD), Pillow (MIT-CMU), pypdfium2 / PDFium (Apache 2.0 / BSD),
  TinySoundFont (MIT), LAME via lameenc (LGPL), pillow-heif (BSD / LGPL libheif), Electron (MIT).

Pupitre lui-même est un logiciel propriétaire d'AIT – Artificial Intelligence & Technology.
`);
const audiveris = path.join(vendor, 'audiveris');
console.log(fs.existsSync(audiveris) ? '  Audiveris présent dans vendor/audiveris' : '  ⚠ vendor/audiveris manquant : copiez Audiveris.app (Mac) ou le MSI extrait (Windows)');
