import { Component, ElementRef, computed, effect, inject, input, signal, untracked, viewChild } from '@angular/core';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreMeta, fileUrl } from '../../core/api';

@Component({
  selector: 'app-score-viewer',
  template: `
    <div class="tabs" role="tablist" aria-label="Affichage">
      <button role="tab" type="button" [attr.aria-selected]="view() === 'score'" (click)="view.set('score')">Partition lue</button>
      @if (score().pages.length) {
        <button role="tab" type="button" [attr.aria-selected]="view() === 'scan'" (click)="view.set('scan')">Scan d’origine</button>
      }
    </div>
    <div class="sheet" [hidden]="view() !== 'score'">
      @if (failed()) { <p class="note">{{ failed() }}</p> }
      <div #host class="osmd"></div>
    </div>
    @if (view() === 'scan') {
      <div class="sheet scan">
        @for (p of score().pages; track p; let i = $index) {
          <img [src]="pageUrl(p)" [alt]="'Page ' + (i + 1) + ' du scan nettoyé'" loading="lazy">
        }
      </div>
    }
  `,
  styles: [`
    :host { display: block; min-width: 0; }
    .tabs { display: flex; gap: .25rem; margin-bottom: .75rem; }
    .tabs button { border: 0; background: none; padding: .4rem .8rem; border-radius: 999px; cursor: pointer; color: var(--ink-soft); font-weight: 600; }
    .tabs button[aria-selected="true"] { background: var(--surface); color: var(--ink); box-shadow: inset 0 0 0 1px var(--hair); }
    .sheet { background: var(--sheet); color: #1B1F3B; border-radius: 4px; padding: clamp(.5rem, 2vw, 1.5rem);
             box-shadow: 0 1px 0 rgba(27,31,59,.06), 0 12px 32px -18px rgba(27,31,59,.35); overflow-x: auto; }
    .note { padding: 1rem; color: #565B76; }
    .scan img { display: block; width: 100%; height: auto; }
    .scan img + img { margin-top: 1.5rem; }
  `],
})
export class ScoreViewer {
  readonly score = input.required<ScoreMeta>();
  private readonly engine = inject(AudioEngine);
  private readonly host = viewChild.required<ElementRef<HTMLDivElement>>('host');
  protected readonly view = signal<'score' | 'scan'>('score');
  protected readonly failed = signal<string | null>(null);

  private readonly key = computed(() => `${this.score().id}:${this.score().revision}`);
  private osmd: any = null;
  private stamps: number[] = [];
  private index = 0;

  constructor() {
    effect(() => {
      this.key();
      untracked(() => void this.loadScore(this.score()));
    });
    effect(() => {
      const t = this.engine.position();
      const tempo = this.score().manifest?.tempo ?? 90;
      untracked(() => this.follow(t, tempo));
    });
  }

  protected pageUrl(p: string) { return fileUrl(this.score(), 'pages', p); }

  private async loadScore(s: ScoreMeta) {
    this.failed.set(null);
    if (!s.manifest) return;
    try {
      const res = await fetch(fileUrl(s, 'audio', 'score.musicxml'));
      if (!res.ok) throw new Error('score');
      const xml = await res.text();
      // OSMD est publié en module CommonJS : selon l'outil de compilation, la classe est sur l'export nommé ou sur « default ».
      const mod: any = await import('opensheetmusicdisplay');
      const OpenSheetMusicDisplay = mod.OpenSheetMusicDisplay ?? mod.default?.OpenSheetMusicDisplay ?? mod.default;
      this.osmd ??= new OpenSheetMusicDisplay(this.host().nativeElement, {
        autoResize: true, backend: 'svg', drawTitle: false, drawComposer: false, drawCredits: false,
        followCursor: true,
        cursorsOptions: [{ type: 0, color: '#34479A', alpha: 0.3, follow: true }],
      } as any);
      await this.osmd.load(xml);
      this.osmd.render();
      this.collectStamps();
    } catch (err) {
      console.error('Affichage de la partition impossible', err);
      this.failed.set('La partition lue ne peut pas être affichée, mais l’audio reste disponible.');
    }
  }

  private collectStamps() {
    const c = this.osmd.cursor;
    c.show();
    c.reset();
    this.stamps = [];
    let guard = 0;
    while (!c.Iterator.EndReached && guard++ < 20000) {
      this.stamps.push(c.Iterator.currentTimeStamp.RealValue);
      c.next();
    }
    c.reset();
    this.index = 0;
  }

  private follow(seconds: number, quarterBpm: number) {
    if (!this.osmd || !this.stamps.length) return;
    const whole = (seconds * quarterBpm) / 240;
    let k = 0;
    while (k + 1 < this.stamps.length && this.stamps[k + 1] <= whole + 1e-6) k++;
    if (k === this.index) return;
    const c = this.osmd.cursor;
    if (k < this.index) { c.reset(); this.index = 0; }
    while (this.index < k) { c.next(); this.index++; }
  }
}
