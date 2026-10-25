import { Component, DestroyRef, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { LibraryStore } from '../../core/library.store';
import { LicenceService } from '../../core/licence';
import { frDateShort } from '../../core/dates';
import { ACCEPT, BUSY, STATUS_LABEL, ScoreMeta, voiceColor } from '../../core/api';

@Component({
  selector: 'app-library',
  imports: [RouterLink, DatePipe],
  template: `
    <section class="intro">
      <div class="intro-text">
        <p class="eyebrow">Répétition de chorale · lecture intelligente</p>
        <h1>Chaque voix de votre chant, <span class="gradient-text">à écouter séparément.</span></h1>
        <p class="lede">Déposez une partition. Pupitre lit les notes et crée une piste pour la soprano, l’alto, le ténor et la basse.</p>
      </div>
      <ul class="voices" aria-label="Les quatre pupitres">
        <li style="--c: var(--soprano)">Soprano</li>
        <li style="--c: var(--alto)">Alto</li>
        <li style="--c: var(--tenor)">Ténor</li>
        <li style="--c: var(--basse)">Basse</li>
      </ul>
    </section>

    @if (licence.info(); as l) {
      @if (l.daysLeft !== null && l.daysLeft <= 30) {
        <p class="renew" role="status">Votre licence se termine le <b>{{ date(l.expires!) }}</b> ({{ l.daysLeft }} jour{{ l.daysLeft === 1 ? '' : 's' }}). <a routerLink="/a-propos">Voir la licence</a></p>
      }
    }
    <label class="drop glass" [class.over]="over()" [class.sending]="store.uploading()"
           (dragover)="$event.preventDefault(); over.set(true)" (dragleave)="over.set(false)" (drop)="drop($event)">
      <span class="stave" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></span>
      <input class="visually-hidden" type="file" [accept]="accept" multiple [disabled]="store.uploading()" (change)="pick($event)">
      <span class="drop-body">
        @if (store.uploading()) {
          <span class="drop-title">Envoi en cours · {{ store.uploadProgress() }} %</span>
          <span class="meter"><span [style.width.%]="store.uploadProgress()"></span></span>
        } @else {
          <span class="drop-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path d="M12 15.5V4.5M7.5 9 12 4.5 16.5 9"/><path d="M4.5 14.5v3a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-3"/></svg>
          </span>
          <span class="drop-title">Déposez votre partition ici</span>
          <span class="drop-hint">ou</span>
          <span class="btn">Choisir des fichiers</span>
          <span class="formats">
            <span>PDF</span><span>Photos · plusieurs pages d’un coup</span><span>MusicXML</span><span>MIDI</span><span>MuseScore</span>
          </span>
          <span class="drop-hint small">30 Mo au plus par fichier · photos bien à plat, en pleine lumière</span>
        }
      </span>
    </label>
    @if (store.error()) { <p class="error banner" role="alert">{{ store.error() }}</p> }

    <section class="list" aria-labelledby="list-title">
      <div class="list-head">
        <h2 id="list-title">Vos partitions</h2>
        @if (store.scores().length) { <span class="pill">{{ store.scores().length }}</span> }
      </div>
      @if (store.loaded() && !store.scores().length) {
        <p class="empty glass">Aucune partition pour l’instant. La première que vous déposez apparaîtra ici.</p>
      }
      <ul class="cards">
        @for (s of store.scores(); track s.id) {
          <li class="card glass" [class.is-busy]="isBusy(s)">
            <a [routerLink]="['/partition', s.id]" class="card-link">
              <span class="threads" aria-hidden="true">
                @for (v of s.manifest?.voices ?? []; track v.id; let i = $index) { <i [style.--c]="color(v.id, i)"></i> }
                @if (!s.manifest) { <i></i><i></i><i></i><i></i> }
              </span>
              <span class="title">{{ s.title }}</span>
              <span class="meta">
                <span class="pill" [class.busy]="isBusy(s)" [class.ok]="s.status === 'ready'" [class.failed]="s.status === 'failed'">{{ label(s) }}</span>
                @if (s.manifest; as m) { <span class="facts">{{ m.key }} · {{ m.measures }} mesures</span> }
                <time [attr.datetime]="s.createdAt">{{ s.createdAt | date: 'd MMM y' }}</time>
              </span>
              @if (isBusy(s)) { <span class="progress" aria-hidden="true"><span [style.width.%]="s.progress"></span></span> }
            </a>
            <button class="remove" type="button" (click)="remove(s)" [disabled]="isBusy(s)" [attr.aria-label]="'Supprimer ' + s.title" title="Supprimer">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/></svg>
            </button>
          </li>
        }
      </ul>
    </section>
  `,
  styles: [`
    .intro { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: end; gap: 2rem;
             padding: clamp(2rem, 6vw, 4rem) 0 clamp(1.5rem, 3vw, 2.25rem); }
    .intro-text { display: grid; gap: 1rem; max-width: 46rem; }
    .intro h1 { font-size: clamp(2.1rem, 5vw, 3.6rem); }
    .lede { color: var(--ink-soft); font-size: 1.12rem; max-width: 36rem; }
    .voices { list-style: none; margin: 0; padding: 0; display: grid; gap: .55rem; }
    .voices li { display: flex; align-items: center; gap: .7rem; font-size: .82rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; color: var(--ink-soft); }
    .voices li::before { content: ""; width: 74px; height: 3px; border-radius: 3px; background: var(--c); box-shadow: 0 0 12px var(--c); }

    .renew { margin-bottom: 1rem; padding: .75rem 1rem; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--soprano) 50%, transparent);
             background: color-mix(in srgb, var(--soprano) 12%, transparent); }
    .renew a { color: var(--accent-2); }
    .drop { position: relative; display: grid; place-items: center; min-height: 300px; padding: 2rem; cursor: pointer; overflow: hidden;
            transition: border-color .25s, box-shadow .25s; }
    .drop::after { content: ""; position: absolute; inset: 10px; border-radius: calc(var(--radius) - 8px); border: 1.5px dashed var(--rule);
                   pointer-events: none; transition: border-color .25s; }
    .drop:hover::after, .drop.over::after { border-color: var(--accent-2); }
    .drop.over { box-shadow: var(--glow); }
    .drop.sending { cursor: progress; }
    .stave { position: absolute; inset: 50% 0 auto; translate: 0 -50%; display: grid; gap: 24px; padding: 0 2.5rem; opacity: .7; }
    .stave i { display: block; height: 1.5px; background: var(--rule); transition: background .35s ease, height .35s ease, box-shadow .35s; }
    .drop:hover .stave i, .drop.over .stave i { height: 2.5px; }
    .drop:hover .stave i:nth-child(1), .drop.over .stave i:nth-child(1) { background: var(--soprano); box-shadow: 0 0 14px var(--soprano); }
    .drop:hover .stave i:nth-child(2), .drop.over .stave i:nth-child(2) { background: var(--alto); box-shadow: 0 0 14px var(--alto); transition-delay: .05s; }
    .drop:hover .stave i:nth-child(3), .drop.over .stave i:nth-child(3) { background: var(--tenor); box-shadow: 0 0 14px var(--tenor); transition-delay: .1s; }
    .drop:hover .stave i:nth-child(4), .drop.over .stave i:nth-child(4) { background: var(--basse); box-shadow: 0 0 14px var(--basse); transition-delay: .15s; }
    .drop:hover .stave i:nth-child(5), .drop.over .stave i:nth-child(5) { background: var(--accent-2); box-shadow: 0 0 14px var(--accent-2); transition-delay: .2s; }
    .drop-body { position: relative; display: grid; justify-items: center; gap: .55rem; text-align: center; padding: 1.5rem 2rem;
                 border-radius: 16px; background: color-mix(in srgb, var(--surface-solid) 88%, transparent); border: 1px solid var(--hair);
                 box-shadow: 0 20px 60px -30px rgba(0, 0, 0, .7); max-width: 34rem; }
    .drop-icon { width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; margin-bottom: .2rem;
                 background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 25%, transparent), color-mix(in srgb, var(--accent-2) 20%, transparent));
                 border: 1px solid color-mix(in srgb, var(--accent-2) 45%, transparent); color: var(--accent-2); }
    .drop-icon svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .drop-title { font: 600 1.45rem/1.2 var(--serif); }
    .drop-hint { color: var(--ink-soft); font-size: .92rem; }
    .drop-hint.small { font-size: .8rem; }
    .formats { display: flex; flex-wrap: wrap; justify-content: center; gap: .35rem; margin-top: .5rem; }
    .formats span { font-size: .75rem; font-weight: 600; padding: .22rem .6rem; border-radius: 999px; color: var(--ink-soft); border: 1px solid var(--hair); background: var(--raised); }
    .meter { width: min(280px, 60vw); height: 5px; border-radius: 5px; background: var(--hair); overflow: hidden; }
    .meter span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .2s; }
    .banner { margin-top: 1rem; padding: .8rem 1rem; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
              background: color-mix(in srgb, var(--danger) 10%, transparent); }

    .list { margin-top: clamp(2.5rem, 5vw, 3.5rem); }
    .list-head { display: flex; align-items: center; gap: .75rem; margin-bottom: 1rem; }
    .list-head h2 { font-size: 1.5rem; }
    .empty { padding: 1.25rem 1.5rem; color: var(--ink-soft); }
    .cards { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 1rem; }
    .card { position: relative; transition: transform .2s ease, border-color .2s, box-shadow .2s; }
    .card:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--accent-2) 45%, transparent); box-shadow: var(--glow); }
    .card-link { display: grid; gap: .8rem; padding: 1.25rem 1.25rem 1.1rem; text-decoration: none; min-height: 150px; }
    .threads { display: grid; gap: 4px; width: 64px; }
    .threads i { --c: var(--rule); display: block; height: 3px; border-radius: 3px; background: var(--c); box-shadow: 0 0 8px color-mix(in srgb, var(--c) 60%, transparent); }
    .is-busy .threads i { animation: shimmer 1.6s ease-in-out infinite; }
    .is-busy .threads i:nth-child(2) { animation-delay: .15s; } .is-busy .threads i:nth-child(3) { animation-delay: .3s; } .is-busy .threads i:nth-child(4) { animation-delay: .45s; }
    @keyframes shimmer { 50% { opacity: .3; } }
    .title { font: 600 1.12rem/1.3 var(--serif); padding-right: 2rem; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .meta { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .7rem; margin-top: auto; }
    .facts, time { font-size: .82rem; color: var(--ink-soft); }
    time { margin-left: auto; }
    .progress { height: 3px; border-radius: 3px; background: var(--hair); overflow: hidden; }
    .progress span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width .6s ease; }
    .remove { position: absolute; top: .8rem; right: .8rem; width: 34px; height: 34px; border-radius: 50%; display: grid; place-items: center;
              border: 1px solid transparent; background: none; color: var(--ink-soft); cursor: pointer; opacity: 0; transition: opacity .2s, color .2s, border-color .2s; }
    .card:hover .remove, .remove:focus-visible { opacity: 1; }
    .remove:hover:not(:disabled) { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 40%, transparent); }
    .remove:disabled { display: none; }
    .remove svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    @media (hover: none) { .remove { opacity: 1; } }
    @media (max-width: 760px) { .intro { grid-template-columns: 1fr; } .voices { grid-template-columns: repeat(2, auto); justify-content: start; } }
    @media (max-width: 520px) {
      .drop { padding: 1rem; min-height: 0; }
      .drop-body { padding: 1.25rem 1rem; }
      .drop-title { font-size: 1.25rem; }
      .voices li::before { width: 40px; }
    }
  `],
})
export class Library {
  protected readonly store = inject(LibraryStore);
  protected readonly licence = inject(LicenceService);
  protected readonly date = frDateShort;
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
    const files = [...(input.files ?? [])];
    input.value = '';
    if (files.length) void this.send(files);
  }
  protected drop(e: DragEvent) {
    e.preventDefault();
    this.over.set(false);
    const files = [...(e.dataTransfer?.files ?? [])];
    if (files.length && !this.store.uploading()) void this.send(files);
  }
  protected remove(s: ScoreMeta) {
    if (confirm(`Supprimer « ${s.title} » et ses pistes audio ?`)) void this.store.remove(s.id);
  }
  private async send(files: File[]) {
    try {
      const meta = await this.store.upload(files);
      await this.router.navigate(['/partition', meta.id]);
    } catch { }
  }
}
