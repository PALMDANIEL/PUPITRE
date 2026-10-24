import { Component, DestroyRef, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { LibraryStore } from '../../core/library.store';
import { ACCEPT, BUSY, STATUS_LABEL, ScoreMeta, voiceColor } from '../../core/api';

@Component({
  selector: 'app-library',
  imports: [RouterLink, DatePipe],
  template: `
    <section class="intro">
      <h1>Chaque voix de votre chant, à écouter séparément.</h1>
      <p>Déposez une partition de chorale. Pupitre lit les notes et crée une piste pour la soprano, l’alto, le ténor et la basse.</p>
    </section>

    <label class="drop" [class.over]="over()" [class.sending]="store.uploading()"
           (dragover)="$event.preventDefault(); over.set(true)" (dragleave)="over.set(false)" (drop)="drop($event)">
      <span class="stave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
      <input class="visually-hidden" type="file" [accept]="accept" [disabled]="store.uploading()" (change)="pick($event)">
      <span class="drop-body">
        @if (store.uploading()) {
          <span class="drop-title">Envoi en cours, {{ store.uploadProgress() }} %</span>
          <span class="meter"><span [style.width.%]="store.uploadProgress()"></span></span>
        } @else {
          <span class="drop-title">Déposez une partition ici</span>
          <span class="drop-hint">PDF, photo (JPG, PNG) ou MusicXML, 30 Mo maximum</span>
          <span class="btn">Choisir un fichier</span>
        }
      </span>
    </label>
    @if (store.error()) { <p class="error" role="alert">{{ store.error() }}</p> }

    <section class="list" aria-labelledby="list-title">
      <h2 id="list-title">Vos partitions</h2>
      @if (store.loaded() && !store.scores().length) {
        <p class="empty">Aucune partition pour l’instant. La première que vous déposez apparaîtra ici.</p>
      }
      <ul>
        @for (s of store.scores(); track s.id) {
          <li>
            <a [routerLink]="['/partition', s.id]">
              <span class="title">{{ s.title }}</span>
              <span class="threads" aria-hidden="true">
                @for (v of s.manifest?.voices ?? []; track v.id; let i = $index) { <i [style.background]="color(v.id, i)"></i> }
              </span>
              <span class="state" [class.busy]="isBusy(s)" [class.failed]="s.status === 'failed'">{{ label(s) }}</span>
              <time [attr.datetime]="s.createdAt">{{ s.createdAt | date: 'd MMM y' }}</time>
            </a>
            <button class="remove" type="button" (click)="remove(s)" [disabled]="isBusy(s)" [attr.aria-label]="'Supprimer ' + s.title">Supprimer</button>
          </li>
        }
      </ul>
    </section>
  `,
  styles: [`
    .intro { max-width: 40rem; padding: clamp(1.5rem, 5vw, 3.5rem) 0 2rem; }
    .intro h1 { font-size: clamp(2rem, 4.6vw, 3.2rem); letter-spacing: -.01em; }
    .intro p { margin-top: 1rem; color: var(--ink-soft); font-size: 1.1rem; max-width: 34rem; }
    .drop { position: relative; display: grid; place-items: center; min-height: 260px; padding: 2rem;
            border-radius: 18px; background: var(--surface); border: 1px solid var(--hair); cursor: pointer; overflow: hidden; }
    .drop.sending { cursor: progress; }
    .stave { position: absolute; inset: 50% 0 auto; translate: 0 -50%; display: grid; gap: 22px; padding: 0 1.5rem; }
    .stave i { display: block; height: 1.5px; background: var(--rule); transition: background .35s ease, height .35s ease; }
    .drop.over .stave i { height: 3px; }
    .drop.over .stave i:nth-child(1) { background: var(--soprano); }
    .drop.over .stave i:nth-child(2) { background: var(--alto); transition-delay: .05s; }
    .drop.over .stave i:nth-child(3) { background: var(--tenor); transition-delay: .1s; }
    .drop.over .stave i:nth-child(4) { background: var(--basse); transition-delay: .15s; }
    .drop.over .stave i:nth-child(5) { background: var(--ink); transition-delay: .2s; }
    .drop-body { position: relative; display: grid; justify-items: center; gap: .6rem; text-align: center;
                 padding: 1.25rem 1.75rem; background: var(--surface); border-radius: 12px; }
    .drop-title { font: 500 1.5rem/1.2 var(--serif); }
    .drop-hint { color: var(--ink-soft); font-size: .95rem; }
    .drop-body .btn { margin-top: .4rem; }
    .drop:focus-within { outline: 2px solid var(--basse); outline-offset: 3px; }
    .meter { width: min(260px, 60vw); height: 4px; border-radius: 4px; background: var(--hair); overflow: hidden; }
    .meter span { display: block; height: 100%; background: var(--ink); transition: width .2s; }
    .error { margin-top: 1rem; }
    .list { margin-top: 3rem; }
    .list h2 { font-size: 1.5rem; margin-bottom: .75rem; }
    .empty { color: var(--ink-soft); }
    ul { list-style: none; margin: 0; padding: 0; border-top: 1px solid var(--hair); }
    li { display: flex; align-items: center; border-bottom: 1px solid var(--hair); }
    li a { flex: 1; display: grid; grid-template-columns: 1fr auto 9.5rem 6.5rem; align-items: center; gap: 1rem;
           padding: 1rem .25rem; text-decoration: none; min-width: 0; }
    li a:hover .title { text-decoration: underline; text-underline-offset: 3px; }
    .title { font: 500 1.1rem/1.3 var(--serif); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .threads { display: grid; gap: 3px; width: 28px; }
    .threads i { display: block; height: 2px; border-radius: 2px; }
    .state { font-size: .9rem; color: var(--ink-soft); }
    .state.busy { color: var(--basse); }
    .state.failed { color: var(--danger); }
    time { font-size: .9rem; color: var(--ink-soft); text-align: right; }
    .remove { border: 0; background: none; color: var(--ink-soft); font-size: .85rem; padding: .5rem; cursor: pointer; }
    .remove:hover:not(:disabled) { color: var(--danger); }
    .remove:disabled { opacity: .35; cursor: not-allowed; }
    @media (max-width: 640px) {
      li a { grid-template-columns: 1fr auto; row-gap: .2rem; }
      .threads { grid-row: 1; grid-column: 2; }
      time { text-align: left; }
    }
  `],
})
export class Library {
  protected readonly store = inject(LibraryStore);
  private readonly router = inject(Router);
  protected readonly over = signal(false);
  protected readonly accept = ACCEPT;
  protected readonly color = voiceColor;

  constructor() {
    void this.store.load();
    const timer = setInterval(() => { if (this.store.anyBusy()) void this.store.load(); }, 3000);
    inject(DestroyRef).onDestroy(() => clearInterval(timer));
  }

  protected isBusy(s: ScoreMeta) { return BUSY.includes(s.status); }
  protected label(s: ScoreMeta) {
    return s.status === 'ready' && s.manifest ? `${s.manifest.voices.length} voix` : STATUS_LABEL[s.status];
  }
  protected pick(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) void this.send(file);
  }
  protected drop(e: DragEvent) {
    e.preventDefault();
    this.over.set(false);
    const file = e.dataTransfer?.files?.[0];
    if (file && !this.store.uploading()) void this.send(file);
  }
  protected remove(s: ScoreMeta) {
    if (confirm(`Supprimer « ${s.title} » et ses pistes audio ?`)) void this.store.remove(s.id);
  }
  private async send(file: File) {
    try {
      const meta = await this.store.upload(file);
      await this.router.navigate(['/partition', meta.id]);
    } catch { }
  }
}
