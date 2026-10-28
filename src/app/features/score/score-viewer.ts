import { Component, ElementRef, computed, effect, inject, input, signal, untracked, viewChild } from '@angular/core';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreMeta, fileUrl } from '../../core/api';
import { saveFile } from '../../core/save-file';

@Component({
  selector: 'app-score-viewer',
  template: `
    <div class="tabs" role="tablist" aria-label="Affichage">
      <button role="tab" type="button" [attr.aria-selected]="view() === 'score'" (click)="view.set('score')">Partition lue</button>
      @if (score().pages.length) {
        <button role="tab" type="button" [attr.aria-selected]="view() === 'scan'" (click)="view.set('scan')">Scan d’origine</button>
      }
    </div>
    <div class="copies">
      <button type="button" class="btn quiet" [disabled]="!!making() || !score().manifest" (click)="saveRebuilt()">Partition reconstituée (PDF)</button>
      @if (score().pages.length) {
        <button type="button" class="btn quiet" [disabled]="!!making()" (click)="saveClean()">Copie nettoyée (PDF)</button>
      }
      @if (making()) { <span class="hint" role="status">{{ making() }}</span> }
      @if (pdfError()) { <span class="error" role="alert">{{ pdfError() }}</span> }
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
    .tabs { display: inline-flex; gap: .2rem; margin-bottom: .85rem; padding: 3px; border-radius: 999px; background: var(--raised); border: 1px solid var(--hair); }
    .tabs button { border: 0; background: none; padding: .42rem .95rem; border-radius: 999px; cursor: pointer; color: var(--ink-soft); font-weight: 700; font-size: .9rem; }
    .tabs button[aria-selected="true"] { background: linear-gradient(135deg, var(--accent), var(--accent-2)); color: #fff; }
    .sheet { background: var(--sheet); color: #1B1F3B; border-radius: 14px; padding: clamp(.5rem, 2vw, 1.5rem); overflow-x: auto;
             box-shadow: 0 0 0 1px var(--hair), 0 30px 70px -35px rgba(0, 0, 0, .75), 0 0 60px -30px color-mix(in srgb, var(--accent-2) 60%, transparent); }
    .note { padding: 1rem; color: #565B76; }
    .copies { display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; margin: 0 0 .85rem; }
    .copies .btn { font-size: .85rem; padding: .4rem .85rem; }
    .copies .hint { color: var(--ink-soft); font-size: .85rem; }
    .copies .error { color: var(--danger, #E5484D); font-size: .85rem; }
    .scan img { display: block; width: 100%; height: auto; border-radius: 6px; }
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

  protected readonly making = signal<string | null>(null);
  protected readonly pdfError = signal<string | null>(null);
  protected saveRebuilt() {
    void this.makePdf('Gravure de la partition…', 'partition reconstituée', async () => {
      const s = this.score();
      const m = s.manifest!;
      const xml = await (await fetch(fileUrl(s, 'audio', m.rebuilt ?? m.score))).text();
      const { rebuiltScorePdf } = await import('../../core/score-pdf');
      return rebuiltScorePdf(xml, s.title, m.rebuilt ? m.voices.map((v) => v.name) : []);
    });
  }
  protected saveClean() {
    void this.makePdf('Préparation de la copie nettoyée…', 'copie nettoyée', async () => {
      const { cleanCopyPdf } = await import('../../core/score-pdf');
      return cleanCopyPdf(this.score().pages.map((p) => this.pageUrl(p)), this.score().title);
    });
  }
  private async makePdf(message: string, label: string, make: () => Promise<Blob>) {
    this.making.set(message); this.pdfError.set(null);
    try {
      await saveFile(await make(), `${this.score().title} - ${label}.pdf`);
    } catch (e) {
      console.error(e);
      this.pdfError.set(`PDF impossible : ${(e as Error)?.message || 'erreur inconnue'}.`);
    } finally {
      this.making.set(null);
    }
  }

  private async loadScore(s: ScoreMeta) {
    this.failed.set(null);
    if (!s.manifest) return;
    try {
      // partition reconstituée (voix séparées, octaves et clés corrigées) quand le moteur l'a produite
      const res = await fetch(fileUrl(s, 'audio', s.manifest.rebuilt ?? 'score.musicxml'));
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
