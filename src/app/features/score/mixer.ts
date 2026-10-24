import { Component, computed, effect, inject, input, signal, untracked } from '@angular/core';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreStore } from '../../core/score.store';
import { ScoreMeta, Timbre, fileUrl, voiceColor } from '../../core/api';

@Component({
  selector: 'app-mixer',
  template: `
    <section class="mixer" aria-label="Écoute">
      <div>
        <p class="label" id="sing-label">Je chante</p>
        <div class="choices" role="radiogroup" aria-labelledby="sing-label">
          @for (v of voices(); track v.id; let i = $index) {
            <button type="button" role="radio" [attr.aria-checked]="focus() === v.id" [style.--c]="color(v.id, i)" (click)="choose(v.id)">{{ v.name }}</button>
          }
          <button type="button" role="radio" class="all" [attr.aria-checked]="focus() === 'all'" (click)="choose('all')">Tout le chœur</button>
        </div>
      </div>

      <div class="transport">
        <button type="button" class="play" (click)="engine.toggle()" [disabled]="engine.loading() || !!engine.error()"
                [attr.aria-label]="engine.playing() ? 'Pause' : 'Écouter'">
          @if (engine.playing()) {
            <svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
          } @else {
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>
          }
        </button>
        <div class="seek">
          <input type="range" min="0" [max]="engine.duration()" step="0.05" [value]="engine.position()" (input)="seek($event)" aria-label="Position dans le chant">
          <span class="time">{{ fmt(engine.position()) }} / {{ fmt(engine.duration()) }}</span>
        </div>
      </div>
      @if (engine.loading()) { <p class="hint">Chargement des voix…</p> }
      @if (engine.error()) { <p class="error">{{ engine.error() }}</p> }

      <ul class="lanes">
        @for (v of voices(); track v.id; let i = $index) {
          <li [style.--c]="color(v.id, i)" [class.off]="engine.muted().has(v.id)">
            <svg class="thread" viewBox="0 0 100 12" preserveAspectRatio="none" aria-hidden="true">
              <line x1="0" y1="6" x2="100" y2="6" [attr.stroke-width]="engine.muted().has(v.id) ? 0.6 : 1 + vol(v.id) * 7" />
            </svg>
            <span class="name">{{ v.name }}</span>
            <span class="range">{{ v.range[0] }} à {{ v.range[1] }}</span>
            <input type="range" min="0" max="1" step="0.05" [value]="vol(v.id)" (input)="setVol(v.id, $event)" [attr.aria-label]="'Volume ' + v.name">
            <button type="button" class="mute" [attr.aria-pressed]="engine.muted().has(v.id)" (click)="engine.toggleMute(v.id)">Couper</button>
          </li>
        }
      </ul>

      <details>
        <summary>Tempo et sonorité</summary>
        <label class="row">
          <span>Tempo : {{ tempo() }} à la noire</span>
          <input type="range" min="40" max="180" step="2" [value]="tempo()" (input)="tempo.set(num($event))">
        </label>
        <div class="seg" role="radiogroup" aria-label="Sonorité">
          <button type="button" role="radio" [attr.aria-checked]="timbre() === 'choeur'" (click)="timbre.set('choeur')">Voix de chœur</button>
          <button type="button" role="radio" [attr.aria-checked]="timbre() === 'piano'" (click)="timbre.set('piano')">Piano</button>
        </div>
        <button type="button" class="btn" [disabled]="!dirty() || busy()" (click)="regenerate()">
          {{ busy() ? 'Création de l’audio…' : 'Recréer l’audio' }}
        </button>
      </details>

      <details>
        <summary>Télécharger pour répéter</summary>
        <p class="hint">La piste de travail met votre voix en avant, avec les autres en fond. Elle se partage facilement par message.</p>
        <ul class="downloads">
          @for (v of voices(); track v.id) {
            <li>
              <span>{{ v.name }}</span>
              <a [href]="url(score(), 'audio', v.practice, true)">Piste de travail</a>
              <a [href]="url(score(), 'audio', v.stem, true)">Voix seule</a>
            </li>
          }
          @if (score().manifest; as m) {
            <li><span>Tout le chœur</span><a [href]="url(score(), 'audio', m.tutti, true)">Ensemble</a></li>
          }
        </ul>
      </details>

      <details>
        <summary>Corriger la partition</summary>
        <p class="hint">La lecture automatique peut se tromper sur une note ou un rythme. Téléchargez la partition lue, corrigez-la dans MuseScore (gratuit), puis renvoyez-la : l’audio sera recréé.</p>
        <div class="actions">
          <a class="btn quiet" [href]="url(score(), 'audio', 'score.musicxml', true)">Télécharger la partition lue</a>
          <label class="btn quiet" [class.disabled]="busy()">
            Envoyer la version corrigée
            <input class="visually-hidden" type="file" accept=".musicxml,.mxl,.xml" [disabled]="busy()" (change)="correct($event)">
          </label>
        </div>
        @if (score().corrected) { <p class="hint">L’audio actuel vient de votre version corrigée.</p> }
      </details>
    </section>
  `,
  styles: [`
    :host { display: block; }
    .mixer { display: grid; gap: 1.25rem; padding: 1.25rem; background: var(--surface); border-radius: 18px; border: 1px solid var(--hair); }
    .label { font-weight: 600; margin-bottom: .5rem; }
    .choices { display: flex; flex-wrap: wrap; gap: .4rem; }
    .choices button { --c: var(--ink); border: 1.5px solid var(--c); background: transparent; color: var(--ink);
                      padding: .4rem .85rem; border-radius: 999px; cursor: pointer; font-weight: 600; font-size: .92rem; }
    .choices button[aria-checked="true"] { background: var(--c); color: var(--surface); }
    .choices .all { border-color: var(--rule); }
    .choices .all[aria-checked="true"] { background: var(--ink); border-color: var(--ink); }
    .transport { display: flex; align-items: center; gap: 1rem; }
    .play { flex: none; width: 56px; height: 56px; border-radius: 50%; border: 0; background: var(--ink); color: var(--paper); cursor: pointer; display: grid; place-items: center; }
    .play svg { width: 24px; height: 24px; fill: currentColor; }
    .play:disabled { opacity: .4; cursor: progress; }
    .seek { flex: 1; display: grid; gap: .2rem; min-width: 0; }
    .seek input { width: 100%; accent-color: var(--ink); }
    .time { font-size: .85rem; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
    .lanes { list-style: none; margin: 0; padding: 0; display: grid; gap: .35rem; }
    .lanes li { display: grid; grid-template-columns: 1fr auto; grid-template-areas: "name mute" "thread thread" "range vol";
                align-items: center; column-gap: .75rem; padding: .5rem 0; border-top: 1px solid var(--hair); }
    .thread { grid-area: thread; width: 100%; height: 12px; }
    .thread line { stroke: var(--c); stroke-linecap: round; transition: stroke-width .15s; }
    .name { grid-area: name; font-weight: 600; }
    .range { grid-area: range; font-size: .82rem; color: var(--ink-soft); }
    .lanes input { grid-area: vol; width: 120px; accent-color: var(--c); }
    .mute { grid-area: mute; border: 1px solid var(--rule); background: none; border-radius: 999px; padding: .15rem .65rem; font-size: .8rem; cursor: pointer; color: var(--ink-soft); }
    .mute[aria-pressed="true"] { background: var(--ink); color: var(--paper); border-color: var(--ink); }
    li.off .name { color: var(--ink-soft); }
    details { border-top: 1px solid var(--hair); padding-top: 1rem; }
    summary { cursor: pointer; font-weight: 600; }
    details[open] > summary { margin-bottom: .75rem; }
    details > * + * { margin-top: .75rem; }
    .row { display: grid; gap: .3rem; }
    .row input { accent-color: var(--ink); }
    .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 999px; padding: 2px; }
    .seg button { border: 0; background: none; padding: .35rem .8rem; border-radius: 999px; cursor: pointer; font-weight: 600; font-size: .9rem; }
    .seg button[aria-checked="true"] { background: var(--ink); color: var(--paper); }
    .hint { font-size: .9rem; color: var(--ink-soft); }
    .downloads { list-style: none; padding: 0; margin: 0; display: grid; gap: .4rem; }
    .downloads li { display: flex; gap: .9rem; align-items: baseline; flex-wrap: wrap; font-size: .92rem; }
    .downloads span { min-width: 6.5rem; font-weight: 600; }
    .downloads a { color: var(--basse); }
    .actions { display: flex; flex-wrap: wrap; gap: .5rem; }
    .actions .btn { font-size: .9rem; }
    label.btn.disabled { opacity: .45; pointer-events: none; }
  `],
})
export class Mixer {
  readonly score = input.required<ScoreMeta>();
  readonly busy = input(false);
  protected readonly engine = inject(AudioEngine);
  private readonly store = inject(ScoreStore);

  protected readonly voices = computed(() => this.score().manifest?.voices ?? []);
  protected readonly focus = signal<string>('all');
  protected readonly tempo = signal(90);
  protected readonly timbre = signal<Timbre>('choeur');
  protected readonly color = voiceColor;
  protected readonly url = fileUrl;
  private readonly key = computed(() => `${this.score().id}:${this.score().revision}`);
  protected readonly dirty = computed(() => {
    const m = this.score().manifest;
    return !!m && (this.tempo() !== m.tempo || this.timbre() !== m.timbre);
  });

  constructor() {
    effect(() => {
      this.key();
      untracked(() => {
        const s = this.score();
        const m = s.manifest;
        if (!m) return;
        this.tempo.set(m.tempo);
        this.timbre.set(m.timbre);
        void this.engine.load(m.voices.map((v) => ({ id: v.id, url: fileUrl(s, 'audio', v.stem) })));
      });
    });
  }

  protected choose(id: string) {
    this.focus.set(id);
    this.engine.clearMutes();
    for (const v of this.voices()) this.engine.setVolume(v.id, id === 'all' || id === v.id ? 1 : 0.25);
  }
  protected vol(id: string) { return this.engine.volumes()[id] ?? 1; }
  protected setVol(id: string, e: Event) {
    this.engine.setVolume(id, this.num(e));
    this.focus.set('custom');
  }
  protected seek(e: Event) { this.engine.seek(this.num(e)); }
  protected num(e: Event) { return Number((e.target as HTMLInputElement).value); }
  protected regenerate() { void this.store.render({ tempo: this.tempo(), timbre: this.timbre() }); }
  protected correct(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) void this.store.uploadCorrection(file);
  }
  protected fmt(t: number) {
    const s = Math.max(0, Math.floor(t));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
}
