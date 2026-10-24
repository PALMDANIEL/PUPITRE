import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', title: 'Pupitre', loadComponent: () => import('./features/library/library').then((m) => m.Library) },
  { path: 'partition/:id', title: 'Partition – Pupitre', loadComponent: () => import('./features/score/score-page').then((m) => m.ScorePage) },
  { path: 'a-propos', title: 'À propos – Pupitre par AIT', loadComponent: () => import('./features/about/about').then((m) => m.About) },
  { path: '**', redirectTo: '' },
];
