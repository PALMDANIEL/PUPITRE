import { Capacitor } from '@capacitor/core';

/**
 * Application mobile (Android / iOS, via Capacitor) : lecteur de packs de répétition, sans serveur.
 * Dans un navigateur, « ?lecteur » permet d'essayer ce mode (mémorisé pour l'onglet).
 */
function detect(): boolean {
  if (Capacitor.isNativePlatform()) return true;
  try {
    if (new URLSearchParams(location.search).has('lecteur')) sessionStorage.setItem('pupitre-lecteur', '1');
    return sessionStorage.getItem('pupitre-lecteur') === '1';
  } catch {
    return false;
  }
}

export const IS_PLAYER = detect();
