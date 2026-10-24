import { Component, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { Router, RouterLink } from '@angular/router';
import { PackStore, PackSummary } from '../../core/packs';
import { voiceColor } from '../../core/api';

@Component({
  selector: 'app-pack-library',
  imports: [RouterLink, DatePipe],
  template: `
    <section class="intro">
      <p class="eyebrow">Lecteur de répétition</p>
      <h1>Vos chants, <span class="gradient-text">voix par voix.</span></h1>
      <p class="lede">Ouvrez le fichier <b>.pupitre</b> envoyé par votre chef de chœur, puis choisissez votre voix.</p>
    </section>

    <label class="import glass" [class.over]="over()" [class.busy]="store.importing()"
           (dragover)="$event.preventDefault(); over.set(true)" (dragleave)="over.set(false)" (drop)="drop($event)">
      <input class="visually-hidden" type="file" multiple [disabled]="store.importing()" (change)="pick($event)">
      <span class="import-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="M12 4.5v11M7.5 11 12 15.5 16.5 11"/><path d="M4.5 15.5v2a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2v-2"/></svg>
      </span>
      <span class="import-text">
        <b>{{ store.importing() ? 'Import en cours…' : 'Ouvrir un pack .pupitre' }}</b>
        <span>Reçu par WhatsApp, e-mail ou clé USB · enregistré dans le téléphone</span>
      </span>
    </label>
    @if (store.error()) { <p class="error banner" role="alert">{{ store.error() }}</p> }

    <section class="list" aria-labelledby="t">
      <h2 id="t">Mes chants</h2>
      @if (store.loaded() && !store.packs().length) {
        <div class="empty glass">
          <p><b>Aucun chant pour l’instant.</b></p>
          <ol>
            <li>Votre chef de chœur prépare le chant dans Pupitre sur ordinateur.</li>
            <li>Il vous envoie le fichier <b>.pupitre</b> (par exemple sur WhatsApp).</li>
            <li>Enregistrez-le, puis ouvrez-le ici avec le bouton ci-dessus.</li>
          </ol>
        </div>
      }
      <ul class="cards">
        @for (p of store.packs(); track p.id) {
          <li class="card glass">
            <a [routerLink]="['/chant', p.id]" class="card-link">
              <span class="threads" aria-hidden="true">
                @for (v of p.manifest.voices; track v.id; let i = $index) { <i [style.--c]="color(v.id, i)"></i> }
              </span>
              <span class="title">{{ p.title }}</span>
              <span class="meta">
                <span class="pill ok">{{ p.manifest.voices.length }} voix</span>
                <span class="facts">{{ p.manifest.key }}</span>
                <time [attr.datetime]="p.importedAt">{{ p.importedAt | date: 'd MMM y' }}</time>
              </span>
            </a>
            <button class="remove" type="button" (click)="remove(p)" [attr.aria-label]="'Retirer ' + p.title" title="Retirer du téléphone">
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12"/></svg>
            </button>
          </li>
        }
      </ul>
    </section>
  `,
  styles: [`
    .intro { display: grid; gap: .8rem; padding: clamp(1.5rem, 6vw, 3.5rem) 0 1.5rem; max-width: 40rem; }
    .intro h1 { font-size: clamp(2rem, 7vw, 3.2rem); }
    .lede { color: var(--ink-soft); font-size: 1.05rem; }
    .import { display: flex; align-items: center; gap: 1rem; padding: 1.1rem 1.25rem; cursor: pointer; transition: border-color .2s, box-shadow .2s; }
    .import:hover, .import.over { border-color: var(--accent-2); box-shadow: var(--glow); }
    .import.busy { cursor: progress; opacity: .8; }
    .import-icon { flex: none; width: 52px; height: 52px; border-radius: 50%; display: grid; place-items: center; color: #fff;
                   background: linear-gradient(135deg, var(--accent), var(--accent-2)); box-shadow: var(--glow); }
    .import-icon svg { width: 24px; height: 24px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .import-text { display: grid; gap: .15rem; }
    .import-text b { font: 600 1.1rem/1.3 var(--serif); }
    .import-text span { font-size: .85rem; color: var(--ink-soft); }
    .banner { margin-top: 1rem; padding: .8rem 1rem; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--danger) 45%, transparent);
              background: color-mix(in srgb, var(--danger) 10%, transparent); }
    .list { margin-top: 2.25rem; }
    .list h2 { font-size: 1.4rem; margin-bottom: .9rem; }
    .empty { padding: 1.25rem 1.4rem; display: grid; gap: .6rem; color: var(--ink-soft); }
    .empty b { color: var(--ink); }
    .empty ol { margin: 0; padding-left: 1.2rem; display: grid; gap: .3rem; }
    .cards { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: .9rem; }
    .card { position: relative; }
    .card-link { display: grid; gap: .7rem; padding: 1.15rem; text-decoration: none; }
    .threads { display: grid; gap: 4px; width: 60px; }
    .threads i { display: block; height: 3px; border-radius: 3px; background: var(--c); box-shadow: 0 0 8px color-mix(in srgb, var(--c) 60%, transparent); }
    .title { font: 600 1.1rem/1.3 var(--serif); padding-right: 2.2rem; }
    .meta { display: flex; flex-wrap: wrap; align-items: center; gap: .4rem .7rem; }
    .facts, time { font-size: .82rem; color: var(--ink-soft); }
    time { margin-left: auto; }
    .remove { position: absolute; top: .7rem; right: .7rem; width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center;
              border: 1px solid var(--hair); background: none; color: var(--ink-soft); cursor: pointer; }
    .remove:hover { color: var(--danger); border-color: color-mix(in srgb, var(--danger) 40%, transparent); }
    .remove svg { width: 17px; height: 17px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
  `],
})
export class PackLibrary {
  protected readonly store = inject(PackStore);
  private readonly router = inject(Router);
  protected readonly over = signal(false);
  protected readonly color = voiceColor;

  constructor() { void this.store.load(); }

  protected pick(e: Event) {
    const input = e.target as HTMLInputElement;
    const files = [...(input.files ?? [])];
    input.value = '';
    if (files.length) void this.add(files);
  }
  protected drop(e: DragEvent) {
    e.preventDefault();
    this.over.set(false);
    const files = [...(e.dataTransfer?.files ?? [])];
    if (files.length) void this.add(files);
  }
  protected remove(p: PackSummary) {
    if (confirm(`Retirer « ${p.title} » de ce téléphone ?`)) void this.store.remove(p.id);
  }
  private async add(files: File[]) {
    const id = await this.store.import(files);
    if (id && files.length === 1) await this.router.navigate(['/chant', id]);
  }
}
