import { Component, computed, inject } from '@angular/core';
import { frDateShort } from '../../core/dates';
import { RemoteReader, decodeCode } from '../../core/remote';
import { SHOP_SERVER, SHOP_TARGET, shopUrl } from '../../core/shop';

/**
 * Bandeau de renouvellement de l'abonnement de la chorale (code d'accès au serveur de lecture) :
 * visible dès que le code a expiré ou se termine dans moins de 30 jours — même si le serveur l'a déjà refusé,
 * car il est lu directement dans le code enregistré sur le téléphone.
 */
@Component({
  selector: 'app-renew-access',
  template: `
    @if (state(); as s) {
      <div class="renew" [class.expired]="s.expired" role="status">
        <p>
          @if (s.expired) { L’abonnement de <b>{{ s.client }}</b> a expiré le <b>{{ date(s.expires) }}</b>. }
          @else { L’abonnement de <b>{{ s.client }}</b> se termine le <b>{{ date(s.expires) }}</b> ({{ s.left }} jour{{ s.left > 1 ? 's' : '' }}). }
        </p>
        <a class="btn" [href]="s.url" [target]="target" rel="noopener">Renouveler en ligne</a>
        <span class="small">Orange Money ou Moov Money ; le code prolongé arrive tout seul sur les téléphones de la chorale.</span>
      </div>
    }
  `,
  styles: [`
    .renew { display: grid; gap: .5rem; justify-items: start; padding: .9rem 1rem; margin: .6rem 0 1rem; border-radius: 14px;
             border: 1px solid color-mix(in srgb, var(--accent-2) 55%, transparent); background: var(--raised); }
    .renew.expired { border-color: color-mix(in srgb, var(--danger) 60%, transparent); }
    .renew p { margin: 0; }
    .small { font-size: .8rem; color: var(--ink-soft); }
  `],
})
export class RenewAccess {
  private readonly remote = inject(RemoteReader);
  protected readonly date = frDateShort;
  protected readonly target = SHOP_TARGET;

  protected readonly state = computed(() => {
    const s = this.remote.settings();
    const code = decodeCode(s.code);
    const id = s.info?.id ?? code?.id;
    const expires = s.info?.expires ?? code?.expires ?? null;
    if (!id || !expires) return null;
    const today = new Date().toISOString().slice(0, 10);
    const left = Math.round((Date.parse(`${expires}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / 86_400_000);
    if (left > 30) return null;
    return { id, client: s.info?.client ?? code?.client ?? 'votre chorale', expires, left: Math.max(0, left), expired: left < 0,
      url: shopUrl({ renouveler: id }, s.url || SHOP_SERVER) };
  });
}
