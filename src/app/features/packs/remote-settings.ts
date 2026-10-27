import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { frDateShort } from '../../core/dates';
import { AccessInfo, RemoteReader, decodeCode } from '../../core/remote';
import { RenewAccess } from './renew-access';
import { SHOP_SERVER, SHOP_TARGET, shopUrl } from '../../core/shop';

@Component({
  selector: 'app-remote-settings',
  imports: [FormsModule, RouterLink, RenewAccess],
  template: `
    <a routerLink="/" class="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6 8.5 12l6 6"/></svg>Mes chants</a>
    <section class="head">
      <p class="eyebrow">Réglages</p>
      <h1>Lecture des photos en ligne</h1>
      <p class="lede">Pour lire une photo de partition, le téléphone l’envoie au serveur AIT. Votre chef de chœur vous donne l’adresse et le <b>code de la chorale</b>.</p>
    </section>

    <form class="glass form" (ngSubmit)="verify()">
      <label>
        <span>Adresse du serveur</span>
        <input name="url" type="url" inputmode="url" autocomplete="url" placeholder="https://lecture.exemple.bf" [(ngModel)]="url" required>
      </label>
      <label>
        <span>Code de la chorale</span>
        <textarea name="code" rows="4" spellcheck="false" placeholder="PUPA1.…" [(ngModel)]="code" required></textarea>
      </label>
      <button class="btn" type="submit" [disabled]="checking()">{{ checking() ? 'Vérification…' : 'Vérifier et enregistrer' }}</button>
      @if (error()) { <p class="error" role="alert">{{ error() }}</p> }
      @if (info(); as i) {
        <p class="ok" role="status">✓ Code valable pour <b>{{ i.client }}</b>{{ i.issued ? ', du ' + date(i.issued) : '' }}{{ i.expires ? ' au ' + date(i.expires) + ' inclus' : ' (sans date de fin)' }}.</p>
      }
    </form>
    <app-renew-access />
    <p class="hint">Pas encore de code ? <a [href]="buy" [target]="shopTarget" rel="noopener">Acheter un code pour la chorale</a> (Orange Money, Moov Money).</p>
    <p class="hint">L’écoute des chants déjà enregistrés n’a jamais besoin d’Internet.</p>
  `,
  styles: [`
    .back { display: inline-flex; align-items: center; gap: .35rem; margin: 1.1rem 0 1rem; padding: .35rem .85rem .35rem .55rem; border-radius: 999px;
            color: var(--ink-soft); font-size: .88rem; font-weight: 600; text-decoration: none; border: 1px solid var(--hair); background: var(--raised); }
    .back svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .head { display: grid; gap: .6rem; margin-bottom: 1.25rem; max-width: 40rem; }
    .head h1 { font-size: clamp(1.6rem, 6vw, 2.4rem); }
    .lede { color: var(--ink-soft); }
    .form { display: grid; gap: 1rem; padding: 1.25rem; max-width: 40rem; }
    label { display: grid; gap: .35rem; }
    label span { font-size: .72rem; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; color: var(--accent-2); }
    input, textarea { width: 100%; border-radius: 12px; border: 1px solid var(--hair); background: var(--raised); color: var(--ink); padding: .7rem .85rem; font: inherit; }
    textarea { font: 13px/1.4 ui-monospace, 'SF Mono', Consolas, monospace; resize: vertical; }
    input:focus, textarea:focus { outline: 2px solid var(--accent-2); outline-offset: 1px; }
    .btn { justify-self: start; }
    .ok { color: var(--ok); font-weight: 600; }
    .hint { margin-top: 1rem; color: var(--ink-soft); font-size: .9rem; }
  `],
})
export class RemoteSettingsPage {
  private readonly remote = inject(RemoteReader);
  private readonly router = inject(Router);
  protected url = this.remote.settings().url;
  protected code = this.remote.settings().code;
  protected readonly shopTarget = SHOP_TARGET;
  protected readonly buy = shopUrl({ produit: 'acces' }, this.remote.settings().url || SHOP_SERVER);
  protected readonly checking = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly info = signal<AccessInfo | null>(this.remote.settings().info ?? null);
  protected readonly date = frDateShort;

  protected async verify() {
    this.error.set(null);
    this.info.set(null);
    if (!/^https?:\/\//.test(this.url.trim())) { this.error.set('L’adresse doit commencer par https://'); return; }
    this.checking.set(true);
    try {
      const info = await this.remote.check({ url: this.url, code: this.code });
      if (!info.client) throw new Error('Ce serveur n’est pas un serveur de lecture en ligne Pupitre.');
      this.remote.save({ url: this.url, code: this.code, direct: !!info.direct, info });
      this.info.set(info);
      setTimeout(() => void this.router.navigate(['/photo']), 900);
    } catch (e) {
      this.error.set((e as Error).message);
      // code expiré : on le garde quand même, pour afficher le bouton de renouvellement
      const code = decodeCode(this.code);
      if (code?.expires && code.expires < new Date().toISOString().slice(0, 10)) {
        this.remote.save({ url: this.url, code: this.code, direct: true,
          info: { client: code.client, id: code.id, issued: code.issued, expires: code.expires, direct: true } });
      }
    } finally {
      this.checking.set(false);
    }
  }
}
