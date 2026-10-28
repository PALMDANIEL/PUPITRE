import { Capacitor } from '@capacitor/core';
import { Directory, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';

/** Nom de fichier sans caractères refusés par les téléphones et les ordinateurs. */
export const safeName = (name: string) => name.normalize('NFC').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim() || 'chant';

function base64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',')[1] ?? '');
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

/**
 * Enregistre un fichier pour l'utilisateur.
 * Application mobile : le fichier est préparé dans le téléphone, puis le menu de partage s'ouvre
 * (Enregistrer dans Fichiers, WhatsApp, Drive…) ; un lien « download » n'y fait rien.
 * Navigateur : téléchargement habituel.
 */
export async function saveFile(blob: Blob, name: string): Promise<void> {
  const file = safeName(name);
  if (Capacitor.isNativePlatform()) {
    const { uri } = await Filesystem.writeFile({ path: file, data: await base64(blob), directory: Directory.Cache });
    try {
      await Share.share({ title: file, files: [uri], dialogTitle: 'Enregistrer ou envoyer' });
    } catch (e) {
      if (!/cancel/i.test(String((e as Error)?.message ?? e))) throw e;  // menu fermé sans choix : rien à signaler
    }
    return;
  }
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: file });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
