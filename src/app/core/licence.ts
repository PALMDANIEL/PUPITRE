import { Injectable, signal } from '@angular/core';
import { IS_PLAYER } from './platform';

/** Licence de cet ordinateur (application de bureau) : affichée dans le pied de page, « À propos » et l'accueil. */
export interface LicenceInfo {
  id: string; client: string; issued: string; expires: string | null; machine: string; daysLeft: number | null;
  /** Forfait : copies à déchiffrer par jour (limit null : illimité), et copies déjà déchiffrées aujourd'hui */
  quota?: { limit: number | null; label: string | null } | null; today?: number;
}

@Injectable({ providedIn: 'root' })
export class LicenceService {
  readonly info = signal<LicenceInfo | null>(null);

  constructor() {
    if (IS_PLAYER) return;
    fetch('/api/licence')
      .then((r) => (r.ok ? r.json() : null))
      .then((d: { licence: LicenceInfo | null } | null) => this.info.set(d?.licence ?? null))
      .catch(() => undefined);
  }
}
