import { Component, DestroyRef, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { STATUS_LABEL } from '../../core/api';
import { PackStore } from '../../core/packs';
import { RemoteJob, RemoteReader } from '../../core/remote';

interface Page { file: File; url: string }

@Component({
  selector: 'app-photo-reader',
  imports: [FormsModule, RouterLink],
  template: `
    <a routerLink="/" class="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6 8.5 12l6 6"/></svg>Mes chants</a>
    <section class="head">
      <p class="eyebrow">Lecture en ligne</p>
      <h1>Photographier une partition</h1>
      <p class="lede">Une photo par page, la feuille bien à plat, en pleine lumière. Pupitre lit les notes et prépare chaque voix.</p>
    </section>

    @if (!remote.configured()) {
      <div class="glass notice">
        <p>Pour lire une photo, indiquez d’abord le serveur et le code de votre chorale.</p>
        <a class="btn" routerLink="/reglages">Ouvrir les réglages</a>
      </div>
    } @else {
      <section class="glass pages" aria-label="Pages de la partition">
        <div class="thumbs">
          @for (p of pages(); track p.url; let i = $index) {
            <figure>
              @if (isImage(p.file)) { <img [src]="p.url" [alt]="'Page ' + (i + 1)"> } @else { <span class="doc">PDF</span> }
              <figcaption>Page {{ i + 1 }}</figcaption>
              <button type="button" class="drop" (click)="removePage(i)" [attr.aria-label]="'Retirer la page ' + (i + 1)">×</button>
            </figure>
          }
          <label class="add camera">
            <input class="visually-hidden" type="file" accept="image/*" capture="environment" (change)="add($event)" [disabled]="busy()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 8h3l1.5-2h7L17 8h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>
            <span>{{ pages().length ? 'Page suivante' : 'Prendre la photo' }}</span>
          </label>
          <label class="add">
            <input class="visually-hidden" type="file" accept="image/*,application/pdf" multiple (change)="add($event)" [disabled]="busy()">
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="5" width="16" height="14" rx="2"/><path d="m4 16 4.5-4.5 3.5 3.5 2.5-2.5L20 18"/></svg>
            <span>Galerie ou fichier</span>
          </label>
        </div>
        <label class="title">
          <span>Titre du chant</span>
          <input name="title" [(ngModel)]="title" placeholder="Ex. Tu es présent dans cette hostie" [disabled]="busy()">
        </label>
        <button class="btn" type="button" (click)="send()" [disabled]="!pages().length || busy()">
          {{ remote.uploading() ? 'Envoi… ' + remote.uploadProgress() + ' %' : 'Lire la partition' }}
        </button>
        @if (error()) { <p class="error" role="alert">{{ error() }}</p> }
      </section>
    }

    @if (remote.jobs().length) {
      <section class="jobs" aria-labelledby="jobs-title">
        <h2 id="jobs-title">Lectures</h2>
        <ul>
          @for (j of remote.jobs(); track j.id) {
            <li class="glass">
              <div class="row">
                <b>{{ j.title }}</b>
                <span class="pill" [class.busy]="isBusy(j)" [class.ok]="j.status === 'ready'" [class.failed]="j.status === 'failed'">{{ label(j) }}</span>
              </div>
              @if (isBusy(j)) {
                <span class="bar"><span [style.width.%]="j.progress"></span></span>
                <span class="hint">Vous pouvez fermer l’application : la lecture continue sur le serveur (1 à 3 minutes par page).</span>
              }
              @if (j.error) { <span class="error">{{ j.error }}</span> }
              <div class="actions">
                @if (j.status === 'ready') { <button type="button" class="btn" (click)="open(j)">Écouter</button> }
                @if (!isBusy(j)) { <button type="button" class="btn quiet" (click)="remote.dismiss(j.id)">Retirer de la liste</button> }
              </div>
            </li>
          }
        </ul>
      </section>
    }
  `,
  styles: [`
    .back { display: inline-flex; align-items: center; gap: .35rem; margin: 1.1rem 0 1rem; padding: .35rem .85rem .35rem .55rem; border-radius: 999px;
            color: var(--ink-soft); font-size: .88rem; font-weight: 600; text-decoration: none; border: 1px solid var(--hair); background: var(--raised); }
    .back svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .head { display: grid; gap: .6rem; margin-bottom: 1.25rem; max-width: 40rem; }
    .head h1 { font-size: clamp(1.6rem, 6vw, 2.4rem); }
    .lede { color: var(--ink-soft); }
    .notice { padding: 1.25rem; display: grid; gap: .8rem; justify-items: start; }
    .pages { padding: 1.1rem; display: grid; gap: 1rem; }
    .thumbs { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: .7rem; }
    figure { position: relative; margin: 0; border-radius: 12px; overflow: hidden; border: 1px solid var(--hair); background: #fff; aspect-ratio: 3 / 4; }
    figure img { width: 100%; height: 100%; object-fit: cover; display: block; }
    .doc { display: grid; place-items: center; height: 100%; font-weight: 800; color: #34479A; }
    figcaption { position: absolute; left: 0; right: 0; bottom: 0; padding: .25rem .4rem; font-size: .72rem; font-weight: 700; color: #fff;
                 background: linear-gradient(transparent, rgba(5, 9, 24, .8)); }
    .drop { position: absolute; top: .3rem; right: .3rem; width: 28px; height: 28px; border-radius: 50%; border: 0; cursor: pointer;
            background: rgba(5, 9, 24, .75); color: #fff; font-size: 1.1rem; line-height: 1; }
    .add { display: grid; place-items: center; align-content: center; gap: .4rem; aspect-ratio: 3 / 4; border-radius: 12px; cursor: pointer; text-align: center;
           border: 1.5px dashed var(--rule); color: var(--ink-soft); font-size: .8rem; font-weight: 700; padding: .5rem; }
    .add:hover { border-color: var(--accent-2); color: var(--accent-2); }
    .add.camera { border-style: solid; border-color: color-mix(in srgb, var(--accent-2) 55%, transparent); color: var(--accent-2);
                  background: color-mix(in srgb, var(--accent) 10%, transparent); }
    .add svg { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 1.7; stroke-linecap: round; stroke-linejoin: round; }
    .title { display: grid; gap: .35rem; }
    .title span { font-size: .72rem; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; color: var(--accent-2); }
    .title input { border-radius: 12px; border: 1px solid var(--hair); background: var(--raised); color: var(--ink); padding: .7rem .85rem; font: inherit; }
    .pages > .btn { justify-self: start; }
    .jobs { margin-top: 1.75rem; }
    .jobs h2 { font-size: 1.3rem; margin-bottom: .75rem; }
    .jobs ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .7rem; }
    .jobs li { padding: 1rem 1.1rem; display: grid; gap: .55rem; }
    .row { display: flex; align-items: center; justify-content: space-between; gap: .75rem; }
    .bar { height: 5px; border-radius: 5px; background: var(--hair); overflow: hidden; }
    .bar span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .6s ease; }
    .hint { font-size: .82rem; color: var(--ink-soft); }
    .actions { display: flex; flex-wrap: wrap; gap: .5rem; }
    .actions .btn { font-size: .88rem; padding: .5rem 1rem; }
  `],
})
export class PhotoReader {
  protected readonly remote = inject(RemoteReader);
  private readonly packs = inject(PackStore);
  private readonly router = inject(Router);
  protected readonly pages = signal<Page[]>([]);
  protected readonly error = signal<string | null>(null);
  protected title = '';
  protected readonly busy = computed(() => this.remote.uploading());

  constructor() {
    void this.remote.follow();
    inject(DestroyRef).onDestroy(() => this.pages().forEach((p) => URL.revokeObjectURL(p.url)));
  }

  protected isImage(f: File) { return f.type.startsWith('image/'); }
  protected isBusy(j: RemoteJob) { return j.status !== 'ready' && j.status !== 'failed'; }
  protected label(j: RemoteJob) { return j.status === 'ready' ? 'Prêt' : j.status === 'queued' ? 'En attente' : STATUS_LABEL[j.status]; }

  protected add(e: Event) {
    const input = e.target as HTMLInputElement;
    const files = [...(input.files ?? [])];
    input.value = '';
    this.pages.update((list) => [...list, ...files.map((file) => ({ file, url: URL.createObjectURL(file) }))]);
  }
  protected removePage(i: number) {
    this.pages.update((list) => { URL.revokeObjectURL(list[i].url); return list.filter((_, k) => k !== i); });
  }

  protected async send() {
    this.error.set(null);
    // noms « page-01.jpg »… : le serveur range les pages dans l'ordre des noms
    const files = this.pages().map((p, i) => {
      const ext = p.file.name.includes('.') ? p.file.name.slice(p.file.name.lastIndexOf('.')) : p.file.type === 'application/pdf' ? '.pdf' : '.jpg';
      return new File([p.file], `page-${String(i + 1).padStart(2, '0')}${ext.toLowerCase()}`, { type: p.file.type });
    });
    try {
      const title = this.title.trim() || `Partition du ${new Date().toLocaleDateString('fr-FR', { day: 'numeric', month: 'long' })}`;
      await this.remote.send(files, title);
      this.pages().forEach((p) => URL.revokeObjectURL(p.url));
      this.pages.set([]);
      this.title = '';
    } catch (e) {
      this.error.set((e as Error).message);
    }
  }

  protected async open(j: RemoteJob) {
    await this.packs.load();
    const pack = this.packs.packs().find((p) => p.title === j.title);
    if (pack) await this.router.navigate(['/chant', pack.id]);
  }
}
