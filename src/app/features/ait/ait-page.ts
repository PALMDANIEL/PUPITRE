import { Component, DestroyRef, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { AitStore, IssuedItem, readQrPhoto } from '../../core/ait';
import { frDateShort } from '../../core/dates';
import { AitDashboard } from './ait-dashboard';

type Tab = 'tableau' | 'licence' | 'acces' | 'registre';
const SERVER = 'https://pupitre-lecture.vercel.app';
const DUREES = [
  { v: '1a', l: '1 an' }, { v: '2a', l: '2 ans' }, { v: '6m', l: '6 mois' }, { v: '3m', l: '3 mois' },
  { v: '1m', l: '1 mois' }, { v: '30j', l: '30 jours (essai)' }, { v: 'illimitee', l: 'Définitive (sans fin)' },
];

@Component({
  selector: 'app-ait-page',
  imports: [FormsModule, RouterLink, AitDashboard],
  template: `
    <a routerLink="/a-propos" class="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6 8.5 12l6 6"/></svg>À propos</a>
    <section class="head">
      <p class="eyebrow">Administration</p>
      <h1>Espace AIT</h1>
      <p class="lede">Créez les licences d’ordinateur et les codes d’accès des chorales, et envoyez-les par WhatsApp.</p>
    </section>

    @if (!ait.hasKey()) {
      <section class="glass box">
        <h2>Installer la clé AIT sur ce téléphone</h2>
        <ol class="steps">
          <li>Sur le Mac, dans le dossier <b>pupitre-plateforme</b> : <code>npm run licence -- export-mobile</code></li>
          <li>Photographiez le QR code qui s’affiche :
            <label class="btn quiet">
              <input class="visually-hidden" type="file" accept="image/*" capture="environment" (change)="scan($event)">
              {{ qr() ? 'QR code lu ✓ (reprendre)' : 'Photographier le QR code' }}
            </label>
          </li>
          <li>Choisissez un code PIN de 6 à 8 chiffres, différent de celui de l’écran du téléphone, demandé à chaque ouverture de l’Espace AIT :
            <div class="pins">
              <input type="password" inputmode="numeric" autocomplete="new-password" maxlength="8" placeholder="Code PIN" [(ngModel)]="pin" name="pin">
              <input type="password" inputmode="numeric" autocomplete="new-password" maxlength="8" placeholder="Confirmer" [(ngModel)]="pin2" name="pin2">
            </div>
          </li>
        </ol>
        <button class="btn" type="button" (click)="setup()" [disabled]="!qr() || busy()">Installer la clé</button>
        <p class="hint">La clé reste chiffrée par votre PIN. Ne prêtez pas ce téléphone déverrouillé : avec la clé et le PIN, on peut créer des licences.</p>
      </section>
    } @else if (!ait.unlocked()) {
      <form class="glass box" (ngSubmit)="unlock()">
        <h2>Espace verrouillé</h2>
        <input class="pin" type="password" inputmode="numeric" autocomplete="current-password" maxlength="8" placeholder="Code PIN" [(ngModel)]="pin" name="pin" autofocus>
        <button class="btn" type="submit" [disabled]="busy()">{{ busy() ? 'Ouverture…' : 'Ouvrir' }}</button>
        <button class="link" type="button" (click)="forget()">Retirer la clé de ce téléphone</button>
      </form>
    } @else {
      <div class="tabs" role="tablist">
        <button role="tab" type="button" [attr.aria-selected]="tab() === 'tableau'" (click)="go('tableau')">Tableau de bord</button>
        <button role="tab" type="button" [attr.aria-selected]="tab() === 'licence'" (click)="go('licence')">Licence d’ordinateur</button>
        <button role="tab" type="button" [attr.aria-selected]="tab() === 'acces'" (click)="go('acces')">Code de chorale</button>
        <button role="tab" type="button" [attr.aria-selected]="tab() === 'registre'" (click)="go('registre')">Registre ({{ ait.registry().length }})</button>
        <button type="button" class="lock" (click)="ait.lock()" title="Verrouiller">🔒</button>
      </div>

      @if (tab() === 'tableau') { <app-ait-dashboard /> }
      @if (tab() === 'licence') {
        <form class="glass box" (ngSubmit)="createLicence()">
          <label><span>Client (chorale)</span><input name="client" [(ngModel)]="client" placeholder="Chorale Sainte Cécile" required></label>
          <label><span>Contact (facultatif)</span><input name="contact" [(ngModel)]="contact" inputmode="tel" placeholder="00226 70 00 00 00"></label>
          <label><span>Identifiant de l’ordinateur</span><input name="machine" [(ngModel)]="machine" class="mono" placeholder="ABCD-EFGH-JKMN-PQRS" autocapitalize="characters" required></label>
          <div class="row">
            <label><span>Durée</span><select name="duree" [(ngModel)]="duree">@for (d of durees; track d.v) { <option [value]="d.v">{{ d.l }}</option> }</select></label>
            <label><span>Début</span><input name="debut" type="date" [(ngModel)]="debut"></label>
          </div>
          <button class="btn" type="submit">Créer la licence</button>
        </form>
      }
      @if (tab() === 'acces') {
        <form class="glass box" (ngSubmit)="createAccess()">
          <p class="hint">Pour photographier les partitions depuis les téléphones des choristes (serveur {{ server }}). Un code par chorale.</p>
          <label><span>Chorale</span><input name="client" [(ngModel)]="client" placeholder="Chorale Sainte Cécile" required></label>
          <label><span>Contact (facultatif)</span><input name="contact" [(ngModel)]="contact" inputmode="tel"></label>
          <div class="row">
            <label><span>Durée</span><select name="duree" [(ngModel)]="duree">@for (d of durees; track d.v) { <option [value]="d.v">{{ d.l }}</option> }</select></label>
            <label><span>Début</span><input name="debut" type="date" [(ngModel)]="debut"></label>
          </div>
          <button class="btn" type="submit">Créer le code</button>
        </form>
      }
      @if (tab() === 'registre') {
        <section class="glass box">
          @if (!ait.registry().length) { <p class="hint">Aucune licence ni aucun code créé depuis ce téléphone.</p> }
          <ul class="reg">
            @for (i of ait.registry(); track i.id) {
              <li>
                <div><b>{{ i.client }}</b> <span class="pill">{{ i.kind === 'licence' ? 'Licence' : 'Code' }}</span></div>
                <span class="small">{{ i.id }} · du {{ date(i.issued) }} {{ i.expires ? 'au ' + date(i.expires) : '· définitive' }}{{ i.machine ? ' · ' + i.machine : '' }}</span>
                <button type="button" class="link" (click)="send(i)">Renvoyer</button>
              </li>
            }
          </ul>
          @if (ait.registry().length) { <button class="btn quiet" type="button" (click)="exportCsv()">Exporter le registre (CSV)</button> }
        </section>
      }

      @if (made(); as m) {
        <section class="glass box result" aria-live="polite">
          <p class="ok">✓ {{ m.kind === 'licence' ? 'Licence' : 'Code d’accès' }} {{ m.id }} pour <b>{{ m.client }}</b> :
            du {{ date(m.issued) }} {{ m.expires ? 'au ' + date(m.expires) + ' inclus' : '(définitive)' }}</p>
          <textarea readonly rows="4" class="mono" [value]="m.text"></textarea>
          <div class="actions">
            <button class="btn" type="button" (click)="send(m)">Envoyer (WhatsApp…)</button>
            <button class="btn quiet" type="button" (click)="copy(m)">Copier</button>
          </div>
        </section>
      }
    }
    @if (error()) { <p class="error banner" role="alert">{{ error() }}</p> }
    @if (notice()) { <p class="ok banner" role="status">{{ notice() }}</p> }
  `,
  styles: [`
    .back { display: inline-flex; align-items: center; gap: .35rem; margin: 1.1rem 0 1rem; padding: .35rem .85rem .35rem .55rem; border-radius: 999px;
            color: var(--ink-soft); font-size: .88rem; font-weight: 600; text-decoration: none; border: 1px solid var(--hair); background: var(--raised); }
    .back svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .head { display: grid; gap: .6rem; margin-bottom: 1.25rem; max-width: 40rem; }
    .head h1 { font-size: clamp(1.6rem, 6vw, 2.4rem); }
    .lede, .hint { color: var(--ink-soft); }
    .hint { font-size: .88rem; }
    .box { padding: 1.15rem; display: grid; gap: .9rem; max-width: 40rem; margin-bottom: 1rem; }
    .box h2 { font-size: 1.2rem; }
    .steps { margin: 0; padding-left: 1.2rem; display: grid; gap: .8rem; }
    .steps li > label, .steps li > .pins { margin-top: .45rem; }
    .steps li > label.btn { display: inline-flex; }
    code { font: 12.5px/1.4 ui-monospace, 'SF Mono', Consolas, monospace; padding: .15rem .4rem; border-radius: 6px; background: var(--raised); }
    label { display: grid; gap: .35rem; }
    label span { font-size: .7rem; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; color: var(--accent-2); }
    input, select, textarea { width: 100%; border-radius: 12px; border: 1px solid var(--hair); background: var(--raised); color: var(--ink); padding: .65rem .8rem; font: inherit; }
    input:focus, select:focus, textarea:focus { outline: 2px solid var(--accent-2); outline-offset: 1px; }
    .mono { font-family: ui-monospace, 'SF Mono', Consolas, monospace; letter-spacing: .04em; }
    textarea.mono { font-size: 12px; resize: none; }
    .pins, .row { display: grid; grid-template-columns: 1fr 1fr; gap: .6rem; width: 100%; }
    .pin { font-size: 1.4rem; letter-spacing: .4em; text-align: center; max-width: 14rem; }
    .btn { justify-self: start; }
    .link { justify-self: start; border: 0; background: none; color: var(--ink-soft); text-decoration: underline; text-underline-offset: 3px; cursor: pointer; padding: 0; font-size: .88rem; }
    .tabs { display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: 1rem; align-items: center; }
    .tabs button[role=tab] { border: 1px solid var(--hair); background: var(--raised); border-radius: 999px; padding: .45rem .85rem; font-weight: 700; font-size: .85rem; color: var(--ink-soft); cursor: pointer; }
    .tabs button[aria-selected="true"] { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; border-color: transparent; }
    .lock { margin-left: auto; border: 1px solid var(--hair); background: var(--raised); border-radius: 50%; width: 38px; height: 38px; cursor: pointer; }
    .reg { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
    .reg li { display: grid; gap: .2rem; padding-bottom: .6rem; border-bottom: 1px solid var(--hair); }
    .small { font-size: .8rem; color: var(--ink-soft); }
    .ok { color: var(--ok); font-weight: 600; }
    .actions { display: flex; flex-wrap: wrap; gap: .5rem; }
    .banner { max-width: 40rem; padding: .7rem 1rem; border-radius: 12px; border: 1px solid var(--hair); background: var(--raised); }
  `],
})
export class AitPage {
  protected readonly ait = inject(AitStore);
  protected readonly durees = DUREES;
  protected readonly server = SERVER;
  protected readonly date = frDateShort;
  protected readonly tab = signal<Tab>('tableau');
  protected readonly qr = signal<string | null>(null);
  protected readonly made = signal<IssuedItem | null>(null);
  protected readonly busy = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly notice = signal<string | null>(null);
  protected pin = '';
  protected pin2 = '';
  protected client = '';
  protected contact = '';
  protected machine = '';
  protected duree = '1a';
  protected debut = new Date().toISOString().slice(0, 10);

  constructor() {
    inject(DestroyRef).onDestroy(() => this.ait.lock()); // quitter l'écran referme l'espace
  }

  private reset() { this.error.set(null); this.notice.set(null); }
  protected go(t: Tab) { this.tab.set(t); this.made.set(null); this.reset(); }

  protected async scan(e: Event) {
    this.reset();
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (!file) return;
    try { this.qr.set(await readQrPhoto(file)); } catch (err) { this.error.set((err as Error).message); }
  }

  protected async setup() {
    this.reset();
    if (this.pin !== this.pin2) { this.error.set('Les deux codes PIN ne sont pas identiques.'); return; }
    this.busy.set(true);
    try { await this.ait.setup(this.qr()!, this.pin); this.qr.set(null); this.notice.set('Clé AIT installée sur ce téléphone.'); }
    catch (err) { this.error.set((err as Error).message); }
    finally { this.busy.set(false); this.pin = this.pin2 = ''; }
  }

  protected async unlock() {
    this.reset();
    this.busy.set(true);
    try { await this.ait.unlock(this.pin); } catch (err) { this.error.set((err as Error).message); }
    finally { this.busy.set(false); this.pin = ''; }
  }

  protected forget() {
    if (confirm('Retirer la clé AIT de ce téléphone ? Il faudra rephotographier le QR code du Mac pour la remettre.')) this.ait.forget();
  }

  protected createLicence() {
    this.reset();
    try { this.made.set(this.ait.createLicence({ client: this.client, contact: this.contact, machine: this.machine, duree: this.duree, debut: this.debut })); }
    catch (err) { this.error.set((err as Error).message); }
  }

  protected createAccess() {
    this.reset();
    try { this.made.set(this.ait.createAccess({ client: this.client, contact: this.contact, duree: this.duree, debut: this.debut })); }
    catch (err) { this.error.set((err as Error).message); }
  }

  private message(i: IssuedItem) {
    const period = `du ${this.date(i.issued)} ${i.expires ? `au ${this.date(i.expires)} inclus` : '(sans date de fin)'}`;
    return i.kind === 'licence'
      ? `Licence Pupitre ${i.id} pour ${i.client}, ${period}.\n\nCollez ce texte dans Pupitre (fenêtre d’activation, ou menu Licence… › Saisir une nouvelle licence) :\n\n${i.text}\n\nAIT – Artificial Intelligence & Technology`
      : `Code d’accès Pupitre de ${i.client}, ${period}.\n\nDans l’application Pupitre du téléphone : Mes chants › Réglages du serveur de lecture.\nAdresse : ${SERVER}\nCode :\n\n${i.text}\n\nAIT – Artificial Intelligence & Technology`;
  }

  protected async send(i: IssuedItem) {
    this.reset();
    const how = await this.ait.share(`Pupitre – ${i.client}`, this.message(i));
    if (how === 'copied') this.notice.set('Message copié : collez-le dans WhatsApp.');
  }

  protected async copy(i: IssuedItem) {
    this.reset();
    try { await navigator.clipboard.writeText(i.text); this.notice.set('Copié.'); } catch { this.error.set('Copie impossible : sélectionnez le texte à la main.'); }
  }

  protected async exportCsv() {
    this.reset();
    const how = await this.ait.share('Registre Pupitre (téléphone)', this.ait.csv());
    if (how === 'copied') this.notice.set('Registre copié (format CSV).');
  }
}
