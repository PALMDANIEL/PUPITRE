import { Component, computed, effect, inject, input, output, signal, untracked } from '@angular/core';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreStore } from '../../core/score.store';
import { LANGUES, Langue, ScoreMeta, Timbre, fileUrl, voiceColor } from '../../core/api';

@Component({
  selector: 'app-mixer',
  template: `
    <section class="mixer glass" aria-label="Écoute">
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
              <line x1="1" y1="6" x2="99" y2="6" vector-effect="non-scaling-stroke" [attr.stroke-width]="engine.muted().has(v.id) ? 1 : 1.5 + vol(v.id) * 4" />
            </svg>
            <span class="name">{{ v.name }}</span>
            <span class="range">{{ v.range[0] }} à {{ v.range[1] }}</span>
            <input type="range" min="0" max="1" step="0.05" [value]="vol(v.id)" (input)="setVol(v.id, $event)" [attr.aria-label]="'Volume ' + v.name">
            <button type="button" class="mute" [attr.aria-pressed]="engine.muted().has(v.id)" (click)="engine.toggleMute(v.id)">Couper</button>
          </li>
        }
      </ul>

      @if (!player()) {
      <section class="share">
        <div>
          <p class="share-title">Pour les choristes</p>
          <p class="hint">Un fichier .pupitre à envoyer par WhatsApp : ils l’ouvrent dans l’application Pupitre de leur téléphone, sans Internet.</p>
        </div>
        <a class="btn" [href]="'/api/scores/' + score().id + '/pack'" download>Exporter le pack de répétition</a>
      </section>

      }

      @if (!player() || online()) {
      <details [open]="player() && busy()">
        <summary>Tempo et sonorité</summary>
        @if (player()) { <p class="hint">Le chant est recréé par le serveur AIT, puis remplace celui du téléphone (Internet nécessaire).</p> }
        <label class="row">
          <span>Tempo : {{ tempo() }} à la noire</span>
          <input type="range" min="40" max="180" step="2" [value]="tempo()" (input)="tempo.set(num($event))">
        </label>
        <div class="seg" role="radiogroup" aria-label="Sonorité">
          <button type="button" role="radio" [attr.aria-checked]="timbre() === 'choeur'" (click)="timbre.set('choeur')">Voix de chœur</button>
          <button type="button" role="radio" [attr.aria-checked]="timbre() === 'piano'" (click)="timbre.set('piano')">Piano</button>
          <button type="button" role="radio" [attr.aria-checked]="timbre() === 'chant'" (click)="timbre.set('chant')">Voix chantées <small>essai</small></button>
        </div>
        @if (timbre() === 'chant') {
          <div class="lyrics">
            <p class="hint">Chaque note est chantée sur sa syllabe, à sa hauteur exacte. Les paroles viennent de la partition ;
              corrigez-les ici si besoin : une syllabe par note, séparées par des tirets ou des espaces (« Sain-te Ma-ri-e »),
              et « _ » pour tenir la syllabe sur la note suivante. Sans paroles, la voix chante « a ».
              @if (player()) { La création prend une à quelques minutes. }
              @else { La création prend quelques minutes ; la première fois, les voix sont téléchargées (environ 140 Mo). }</p>
            <label class="row">
              <span>Langue des paroles</span>
              <select [value]="langue()" (change)="langue.set($any($event.target).value)">
                @for (l of langues; track l.id) { <option [value]="l.id">{{ l.label }}</option> }
              </select>
            </label>
            @for (v of voices(); track v.id) {
              <label class="verse">
                <span><i class="dot" [style.background]="color(v.id)"></i>{{ v.name }}
                  <em [class.off]="count(v.id) !== (v.sung ?? v.notes)">{{ count(v.id) }} syllabe{{ count(v.id) > 1 ? 's' : '' }} pour {{ v.sung ?? v.notes }} notes</em></span>
                <textarea rows="2" spellcheck="false" [value]="lyricOf(v.id)" (input)="setLyric(v.id, $event)" placeholder="Glo-ri-a in ex-cel-sis De-o"></textarea>
              </label>
            }
          </div>
        }
        <button type="button" class="btn" [disabled]="!dirty() || busy()" (click)="regenerate()">
          {{ busy() ? 'Création de l’audio…' + (progress() !== null ? ' ' + progress() + ' %' : '') : 'Recréer l’audio' }}
        </button>
        @if (player() && failure()) { <p class="error" role="alert">{{ failure() }}</p> }
      </details>
      }

      @if (!player()) {

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
      }
    </section>
  `,
  styles: [`
    :host { display: block; }
    .mixer { display: grid; gap: 1.25rem; padding: 1.35rem; }
    .label { font-size: .7rem; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; color: var(--accent-2); margin-bottom: .6rem; }
    .choices { display: flex; flex-wrap: wrap; gap: .45rem; }
    .choices button { --c: var(--ink); border: 1.5px solid color-mix(in srgb, var(--c) 70%, transparent); background: transparent; color: var(--ink);
                      padding: .42rem .9rem; border-radius: 999px; cursor: pointer; font-weight: 700; font-size: .9rem; transition: background .2s, box-shadow .2s, color .2s; }
    .choices button:hover { box-shadow: 0 0 14px -2px var(--c); }
    .choices button[aria-checked="true"] { background: var(--c); color: #0A1022; box-shadow: 0 0 18px -2px var(--c); }
    .choices .all { --c: var(--accent-2); }
    .transport { display: flex; align-items: center; gap: 1rem; padding: .9rem; border-radius: 16px; background: var(--raised); border: 1px solid var(--hair); }
    .play { flex: none; width: 58px; height: 58px; border-radius: 50%; border: 0; cursor: pointer; display: grid; place-items: center; color: #fff;
            background: linear-gradient(135deg, var(--accent), var(--accent-2)); box-shadow: var(--glow); transition: transform .15s; }
    .play:hover:not(:disabled) { transform: scale(1.05); }
    .play svg { width: 24px; height: 24px; fill: currentColor; }
    .play:disabled { opacity: .4; cursor: progress; box-shadow: none; }
    .seek { flex: 1; display: grid; gap: .2rem; min-width: 0; }
    .seek input { width: 100%; }
    .time { font-size: .82rem; color: var(--ink-soft); font-variant-numeric: tabular-nums; }
    .lanes { list-style: none; margin: 0; padding: 0; display: grid; gap: .2rem; }
    .lanes li { display: grid; grid-template-columns: 1fr auto; grid-template-areas: "name mute" "thread thread" "range vol";
                align-items: center; column-gap: .75rem; padding: .55rem 0; border-top: 1px solid var(--hair); }
    .thread { grid-area: thread; width: 100%; height: 12px; overflow: visible; }
    .thread line { stroke: var(--c); stroke-linecap: round; transition: stroke-width .15s; filter: drop-shadow(0 0 4px var(--c)); }
    .name { grid-area: name; font-weight: 700; }
    .range { grid-area: range; font-size: .8rem; color: var(--ink-soft); }
    .lanes input { grid-area: vol; width: 130px; accent-color: var(--c); }
    .mute { grid-area: mute; border: 1px solid var(--rule); background: none; border-radius: 999px; padding: .18rem .7rem; font-size: .78rem; font-weight: 600; cursor: pointer; color: var(--ink-soft); }
    .mute:hover { border-color: var(--c); color: var(--ink); }
    .mute[aria-pressed="true"] { background: var(--danger); color: #fff; border-color: var(--danger); }
    li.off .name { color: var(--ink-soft); text-decoration: line-through; }
    li.off .thread line { filter: none; opacity: .4; }
    details { border-top: 1px solid var(--hair); padding-top: 1rem; }
    summary { cursor: pointer; font-weight: 700; list-style: none; display: flex; align-items: center; justify-content: space-between; }
    summary::-webkit-details-marker { display: none; }
    summary::after { content: ""; width: 8px; height: 8px; border-right: 2px solid var(--ink-soft); border-bottom: 2px solid var(--ink-soft); rotate: 45deg; transition: rotate .2s; margin-right: .3rem; }
    details[open] > summary::after { rotate: -135deg; }
    summary:hover { color: var(--accent-2); }
    details[open] > summary { margin-bottom: .75rem; }
    details > * + * { margin-top: .75rem; }
    .row { display: grid; gap: .3rem; }
    .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 999px; padding: 3px; background: var(--raised); }
    .seg button { border: 0; background: none; padding: .38rem .85rem; border-radius: 999px; cursor: pointer; font-weight: 700; font-size: .88rem; color: var(--ink-soft); }
    .seg button[aria-checked="true"] { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; }
    .seg small { font-size: .68rem; font-weight: 700; opacity: .75; text-transform: uppercase; letter-spacing: .06em; margin-left: .2rem; }
    .lyrics { display: grid; gap: .7rem; margin: .4rem 0 .2rem; }
    .lyrics select { border-radius: 10px; border: 1px solid var(--rule); background: var(--raised); color: var(--ink); padding: .35rem .6rem; font: inherit; }
    .verse { display: grid; gap: .3rem; }
    .verse span { display: flex; align-items: center; gap: .45rem; font-weight: 700; font-size: .88rem; }
    .verse em { margin-left: auto; font-style: normal; font-weight: 600; font-size: .78rem; color: var(--ink-soft); }
    .verse em.off { color: var(--accent-2); }
    .verse .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; }
    .verse textarea { width: 100%; border-radius: 10px; border: 1px solid var(--rule); background: var(--raised); color: var(--ink);
                      padding: .5rem .65rem; font: inherit; font-size: 14px; line-height: 1.45; resize: vertical; }
    .hint { font-size: .88rem; color: var(--ink-soft); }
    .downloads { list-style: none; padding: 0; margin: 0; display: grid; gap: .45rem; }
    .downloads li { display: flex; gap: .9rem; align-items: baseline; flex-wrap: wrap; font-size: .9rem; }
    .downloads span { min-width: 6.5rem; font-weight: 700; }
    .downloads a { color: var(--accent-2); text-underline-offset: 3px; }
    .actions { display: flex; flex-wrap: wrap; gap: .5rem; }
    .actions .btn { font-size: .88rem; }
    label.btn.disabled { opacity: .45; pointer-events: none; }
    .share { display: grid; gap: .75rem; padding: 1rem; border-radius: 16px; border: 1px solid color-mix(in srgb, var(--accent-2) 35%, transparent);
             background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 12%, transparent), color-mix(in srgb, var(--accent-2) 8%, transparent)); }
    .share-title { font-weight: 800; margin-bottom: .2rem; }
    .share .btn { justify-self: start; font-size: .9rem; }
  `],
})
export class Mixer {
  readonly score = input.required<ScoreMeta>();
  readonly busy = input(false);
  /** Lecteur mobile : pas de serveur, donc ni recréation de l'audio, ni correction, ni téléchargements. */
  readonly player = input(false);
  /** Téléphone relié au serveur de lecture AIT : il peut recréer l'audio (sonorité, voix chantées) en ligne. */
  readonly online = input(false);
  readonly progress = input<number | null>(null);
  readonly failure = input<string | null>(null);
  /** Téléphone : demande de recréation, faite par la page (le serveur AIT renvoie un nouveau pack). */
  readonly recreate = output<{ tempo: number; timbre: Timbre; langue?: Langue; paroles?: Record<string, string> }>();
  protected readonly engine = inject(AudioEngine);
  private readonly store = inject(ScoreStore, { optional: true });

  protected readonly voices = computed(() => this.score().manifest?.voices ?? []);
  protected readonly focus = signal<string>('all');
  protected readonly tempo = signal(90);
  protected readonly timbre = signal<Timbre>('choeur');
  protected readonly langue = signal<Langue>('fr');
  protected readonly langues = LANGUES;
  /** Paroles modifiées dans l'éditeur (par voix) ; les autres viennent de la partition. */
  protected readonly edits = signal<Record<string, string>>({});
  protected readonly color = voiceColor;
  protected readonly url = fileUrl;
  private readonly key = computed(() => `${this.score().id}:${this.score().revision}`);
  protected readonly dirty = computed(() => {
    const m = this.score().manifest;
    if (!m) return false;
    const sung = this.timbre() === 'chant' && (this.langue() !== (m.langue ?? 'fr') || Object.keys(this.edits()).length > 0);
    return this.tempo() !== m.tempo || this.timbre() !== m.timbre || sung;
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
        this.langue.set(s.langue ?? m.langue ?? 'fr');
        this.edits.set({});
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
  protected regenerate() {
    const chant = this.timbre() === 'chant';
    const paroles = chant && Object.keys(this.edits()).length
      ? Object.fromEntries(this.voices().map((v) => [v.id, this.lyricOf(v.id)])) : undefined;
    const opts = { tempo: this.tempo(), timbre: this.timbre(), ...(chant ? { langue: this.langue(), ...(paroles ? { paroles } : {}) } : {}) };
    if (this.player()) this.recreate.emit(opts);
    else void this.store?.render(opts);
  }
  protected lyricOf(id: string) {
    return this.edits()[id] ?? this.score().paroles?.[id] ?? this.voices().find((v) => v.id === id)?.lyrics ?? '';
  }
  protected setLyric(id: string, e: Event) { this.edits.update((x) => ({ ...x, [id]: (e.target as HTMLTextAreaElement).value })); }
  /** Syllabes saisies (comme le moteur les compte : tirets et espaces séparent, « _ » compte pour une note). */
  protected count(id: string) { return this.lyricOf(id).split(/[\s-]+/).filter(Boolean).length; }
  protected correct(e: Event) {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = '';
    if (file) void this.store?.uploadCorrection(file);
  }
  protected fmt(t: number) {
    const s = Math.max(0, Math.floor(t));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }
}
