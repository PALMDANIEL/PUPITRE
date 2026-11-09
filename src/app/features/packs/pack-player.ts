import { Component, DestroyRef, effect, inject, input, signal, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreMeta } from '../../core/api';
import { PackStore } from '../../core/packs';
import { RemoteReader } from '../../core/remote';
import { Mixer } from '../score/mixer';
import { ScoreViewer } from '../score/score-viewer';

@Component({
  selector: 'app-pack-player',
  imports: [RouterLink, Mixer, ScoreViewer],
  providers: [AudioEngine],
  template: `
    <a routerLink="/" class="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6 8.5 12l6 6"/></svg>Mes chants</a>
    @if (missing()) {
      <p class="error" role="alert">Ce chant n’est plus sur ce téléphone.</p>
    } @else if (score(); as s) {
      <header class="head">
        <p class="eyebrow">Répétition</p>
        <h1>{{ s.title }}</h1>
        @if (s.manifest; as m) {
          <dl class="facts">
            <div><dt>Tonalité</dt><dd>{{ m.key }}</dd></div>
            @if (m.timeSignature) { <div><dt>Mesure</dt><dd>{{ m.timeSignature }}</dd></div> }
            <div><dt>Voix</dt><dd>{{ m.voices.length }}</dd></div>
          </dl>
        }
      </header>
      <div class="workspace">
        <app-mixer [score]="s" [player]="true" [online]="remote.configured()" [busy]="busy()" [progress]="progress()" [failure]="failure()"
                   (recreate)="recreate($event)" (renamed)="renameVoice($event)" />
        <app-score-viewer [score]="s" [saveCorrection]="remote.configured() && !busy() ? saveNotes : null" [correctionStatus]="fixing()" />
      </div>
    } @else {
      <p class="hint">Chargement…</p>
    }
  `,
  styles: [`
    .back { display: inline-flex; align-items: center; gap: .35rem; margin: 1.1rem 0 1rem; padding: .35rem .85rem .35rem .55rem; border-radius: 999px;
            color: var(--ink-soft); font-size: .88rem; font-weight: 600; text-decoration: none; border: 1px solid var(--hair); background: var(--raised); }
    .back svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .head { display: grid; gap: .55rem; margin-bottom: 1.25rem; }
    .head h1 { font-size: clamp(1.6rem, 6vw, 2.5rem); }
    .facts { display: flex; flex-wrap: wrap; gap: .45rem; margin: .2rem 0 0; }
    .facts div { padding: .45rem .8rem; border-radius: 12px; background: var(--surface); border: 1px solid var(--hair); }
    .facts dt { font-size: .66rem; letter-spacing: .16em; text-transform: uppercase; color: var(--ink-soft); }
    .facts dd { margin: 0; font: 600 .95rem/1.3 var(--serif); }
    .workspace { display: grid; grid-template-columns: 370px minmax(0, 1fr); gap: 1.5rem; align-items: start; }
    @media (max-width: 960px) { .workspace { grid-template-columns: 1fr; } }
    .hint { color: var(--ink-soft); }
  `],
})
export class PackPlayer {
  readonly id = input.required<string>();
  private readonly packs = inject(PackStore);
  protected readonly score = signal<ScoreMeta | null>(null);
  protected readonly missing = signal(false);
  protected readonly remote = inject(RemoteReader);
  protected readonly busy = signal(false);
  protected readonly progress = signal<number | null>(null);
  protected readonly failure = signal<string | null>(null);

  protected async renameVoice(e: { voice: string; name: string }) {
    await this.packs.renameVoice(this.id(), e.voice, e.name);
    this.score.set(await this.packs.open(this.id()));
  }

  /** Sonorité, tempo ou voix chantées : le serveur AIT recrée le chant, qui remplace celui du téléphone. */
  protected async recreate(opts: Parameters<RemoteReader['recreate']>[1]) {
    const id = this.id();
    this.busy.set(true); this.failure.set(null); this.progress.set(0);
    try {
      const fresh = await this.remote.recreate(id, opts, (p) => this.progress.set(p));
      this.score.set(await this.packs.open(fresh));
    } catch (e) {
      this.failure.set((e as Error).message);
    } finally {
      this.busy.set(false); this.progress.set(null);
    }
  }

  /**
   * Notes corrigées sur le téléphone : le serveur AIT recrée le chant à partir de la partition corrigée, avec la même
   * sonorité et le même tempo, et il remplace celui du téléphone (comme une nouvelle sonorité).
   */
  protected readonly saveNotes = (file: File, aVerifier: Record<string, number>) => void this.correctNotes(file, aVerifier);

  protected readonly fixing = signal<string | null>(null);

  private async correctNotes(file: File, aVerifier: Record<string, number>) {
    const m = this.score()?.manifest;
    if (!m) return;
    const step = (pct: number) => {
      this.progress.set(pct);
      this.fixing.set(`Correction envoyée : le serveur AIT recrée l’audio (${pct} %)…`);
    };
    this.busy.set(true); this.failure.set(null); step(0);
    try {
      const fresh = await this.remote.recreate(this.id(), { tempo: m.tempo, timbre: m.timbre, langue: m.langue, voyelle: m.voyelle },
        step, { file, aVerifier, moyenne: m.fiabilite?.moyenne });
      this.score.set(await this.packs.open(fresh));
      this.fixing.set('Correction enregistrée : l’audio du chant est recréé.');
    } catch (e) {
      this.fixing.set(`Correction non enregistrée : ${(e as Error).message}`);
    } finally {
      this.busy.set(false); this.progress.set(null);
    }
  }

  constructor() {
    effect(() => {
      const id = this.id();
      untracked(async () => {
        const s = await this.packs.open(id);
        this.missing.set(!s);
        this.score.set(s);
      });
    });
    inject(DestroyRef).onDestroy(() => this.packs.close(this.id()));
  }
}
