import { Routes } from '@angular/router';
import { IS_PLAYER } from './core/platform';

const about = { path: 'a-propos', title: 'À propos – Pupitre par AIT', loadComponent: () => import('./features/about/about').then((m) => m.About) };

/** Ordinateur et web : lecture des partitions, création des voix. */
const studio: Routes = [
  { path: '', title: 'Pupitre', loadComponent: () => import('./features/library/library').then((m) => m.Library) },
  { path: 'partition/:id', title: 'Partition – Pupitre', loadComponent: () => import('./features/score/score-page').then((m) => m.ScorePage) },
  about,
  { path: '**', redirectTo: '' },
];

/** Téléphone (Android / iOS) : lecteur des packs de répétition, sans serveur ni Internet. */
const player: Routes = [
  { path: '', title: 'Mes chants – Pupitre', loadComponent: () => import('./features/packs/pack-library').then((m) => m.PackLibrary) },
  { path: 'chant/:id', title: 'Répétition – Pupitre', loadComponent: () => import('./features/packs/pack-player').then((m) => m.PackPlayer) },
  { path: 'photo', title: 'Photographier une partition – Pupitre', loadComponent: () => import('./features/packs/photo-reader').then((m) => m.PhotoReader) },
  { path: 'ait', title: 'Espace AIT – Pupitre', loadComponent: () => import('./features/ait/ait-page').then((m) => m.AitPage) },
  { path: 'reglages', title: 'Réglages – Pupitre', loadComponent: () => import('./features/packs/remote-settings').then((m) => m.RemoteSettingsPage) },
  about,
  { path: '**', redirectTo: '' },
];

export const routes: Routes = IS_PLAYER ? player : studio;
