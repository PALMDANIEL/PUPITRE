import { Component, ElementRef, computed, effect, inject, input, signal, untracked, viewChild } from '@angular/core';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreMeta, fileUrl } from '../../core/api';
import { saveFile } from '../../core/save-file';
import { ScoreStore } from '../../core/score.store';
import { NoteEdit, NoteRef, editNote, indexNotes, noteLabel } from './note-editor';

/** Orange des notes dont la lecture est à vérifier (lisible sur la feuille blanche) */
const DOUBT_COLOR = '#E8590C';
/** Bleu des notes corrigées, et de la note choisie */
const EDIT_COLOR = '#1C7ED6';
const PICK_COLOR = '#0B7285';

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
      @if (canEdit()) {
        <button type="button" class="btn quiet" [class.on]="editing()" [disabled]="!!making()" (click)="toggleEdit()">
          {{ editing() ? 'Terminer la correction' : 'Corriger des notes' }}
        </button>
      }
      @if (making()) { <span class="hint" role="status">{{ making() }}</span> }
      @if (correctionStatus(); as c) { <span class="hint" role="status">{{ c }}</span> }
      @if (pdfError()) { <span class="error" role="alert">{{ pdfError() }}</span> }
    </div>
    @if (editing() && view() === 'score') {
      <div class="editbar glass" role="toolbar" aria-label="Correction des notes">
        @if (picked(); as n) {
          <p><b>{{ n.label }}</b> · {{ n.voice }} · mesure {{ n.measure }}</p>
          <div class="keys">
            <button type="button" class="btn quiet" (click)="apply('haut')" title="Un degré plus haut">▲ Plus haut</button>
            <button type="button" class="btn quiet" (click)="apply('bas')" title="Un degré plus bas">▼ Plus bas</button>
            <button type="button" class="btn quiet sign" (click)="apply('diese')" aria-label="Dièse">♯</button>
            <button type="button" class="btn quiet sign" (click)="apply('bemol')" aria-label="Bémol">♭</button>
            <button type="button" class="btn quiet sign" (click)="apply('becarre')" aria-label="Bécarre">♮</button>
            @if (isDoubtful(n.measure)) {
              <button type="button" class="btn quiet ok" (click)="markRight(n.measure)">Mesure {{ n.measure }} juste</button>
            }
          </div>
        } @else {
          <p>Touchez une note de la partition pour la corriger. Les notes en orange sont celles dont la lecture est douteuse :
            comparez-les au scan d’origine.</p>
        }
        @if (edits() || verified().size) {
          <div class="save">
            <span>{{ edits() }} note{{ edits() > 1 ? 's' : '' }} corrigée{{ edits() > 1 ? 's' : '' }}@if (verified().size) { · {{ verified().size }} mesure{{ verified().size > 1 ? 's' : '' }} vérifiée{{ verified().size > 1 ? 's' : '' }} }</span>
            <button type="button" class="btn quiet" (click)="cancelEdits()">Annuler</button>
            <button type="button" class="btn" (click)="saveEdits()">Enregistrer et recréer l’audio</button>
          </div>
        }
      </div>
    }
    <div class="sheet" [hidden]="view() !== 'score'" [class.editing]="editing()">
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
    .copies .btn.on { border-color: var(--accent-2); color: var(--accent-2); }
    .editbar { position: sticky; top: 4.6rem; z-index: 5; display: grid; gap: .55rem; margin: 0 0 .85rem; padding: .75rem .9rem; }
    .editbar p { margin: 0; font-size: .9rem; color: var(--ink-soft); }
    .editbar p b { color: var(--ink); font-size: 1.05rem; }
    .editbar .keys, .editbar .save { display: flex; flex-wrap: wrap; gap: .45rem; align-items: center; }
    .editbar .keys .btn { font-size: .95rem; padding: .45rem .8rem; min-width: 2.6rem; }
    .editbar .keys .sign { font: 400 1.35rem/1 'Bravura Text', 'Noto Music', 'Segoe UI Symbol', 'Apple Symbols', serif; padding: .3rem .8rem; }
    .editbar .keys .ok { border-color: #2F9E6B; color: #2F9E6B; }
    .editbar .save { padding-top: .5rem; border-top: 1px solid var(--hair); }
    .editbar .save span { font-size: .88rem; color: var(--ink); margin-right: auto; }
    .sheet.editing :is(.vf-stavenote, .vf-note) { cursor: pointer; }
    .scan img { display: block; width: 100%; height: auto; border-radius: 6px; }
    .scan img + img { margin-top: 1.5rem; }
  `],
})
export class ScoreViewer {
  readonly score = input.required<ScoreMeta>();
  /**
   * Téléphone (chants en pack, sans ScoreStore) : enregistrement d'une correction, fait par la page du lecteur
   * (le serveur AIT recrée l'audio). Absent : correction impossible (téléphone non relié au serveur).
   */
  readonly saveCorrection = input<((file: File, aVerifier: Record<string, number>) => void) | null>(null);
  /** Téléphone : où en est l'enregistrement de la correction (recréation en ligne), affiché près de la partition */
  readonly correctionStatus = input<string | null>(null);
  private readonly engine = inject(AudioEngine);
  /** Ordinateur : la correction est envoyée au serveur de l'application */
  private readonly store = inject(ScoreStore, { optional: true });
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
      this.doc = new DOMParser().parseFromString(xml, 'application/xml');
      this.resetEdits();
      await this.show(xml);
    } catch (err) {
      console.error('Affichage de la partition impossible', err);
      this.failed.set('La partition lue ne peut pas être affichée, mais l’audio reste disponible.');
    }
  }

  // --- Correction des notes ------------------------------------------------------------------------------
  // La partition affichée (reconstituée : une portée par voix) est corrigée en place, note par note, puis envoyée
  // comme version corrigée : le serveur recrée l'audio, et garde en orange les mesures douteuses non vérifiées.

  private doc: Document | null = null;
  private notes = new Map<string, NoteRef>();
  private edited = new Set<string>();
  protected readonly editing = signal(false);
  protected readonly picked = signal<{ key: string; label: string; voice: string; measure: number } | null>(null);
  protected readonly edits = signal(0);
  protected readonly verified = signal<Set<number>>(new Set());
  protected canEdit() {
    const s = this.score();
    return (!!this.store || !!this.saveCorrection()) && !!s.manifest?.rebuilt && s.status === 'ready';
  }
  protected isDoubtful(measure: number) {
    return measure in (this.score().manifest?.fiabilite?.a_verifier ?? {}) && !this.verified().has(measure);
  }
  protected toggleEdit() {
    this.editing.update((v) => !v);
    this.picked.set(null);
    void this.redraw();
  }
  private resetEdits() {
    this.edited.clear();
    this.edits.set(0);
    this.verified.set(new Set());
    this.picked.set(null);
  }
  protected cancelEdits() {
    void this.loadScore(this.score());
  }
  protected apply(edit: NoteEdit) {
    const p = this.picked();
    const ref = p && this.notes.get(p.key);
    if (!p || !ref) return;
    editNote(ref, edit);
    if (!this.edited.has(p.key)) { this.edited.add(p.key); this.edits.update((n) => n + 1); }
    this.picked.set({ ...p, label: noteLabel(ref.el) });
    void this.redraw();
  }
  protected markRight(measure: number) {
    this.verified.update((set) => new Set(set).add(measure));
    void this.redraw();
  }
  protected saveEdits() {
    const save = this.saveCorrection();
    if (!this.doc || (!this.store && !save)) return;
    const xml = new XMLSerializer().serializeToString(this.doc);
    const file = new File([xml], 'corrigee.musicxml', { type: 'application/vnd.recordare.musicxml+xml' });
    const left = Object.fromEntries(Object.entries(this.score().manifest?.fiabilite?.a_verifier ?? {})
      .filter(([m]) => !this.verified().has(Number(m))));
    this.editing.set(false);
    if (save) save(file, left);
    else void this.store!.uploadCorrection(file, left);
  }

  private async redraw() {
    if (!this.doc) return;
    const y = window.scrollY;  // la partition redessinée garde sa place à l'écran
    await this.show(new XMLSerializer().serializeToString(this.doc));
    window.scrollTo({ top: y });
  }

  /** Affiche la partition (OSMD), colore les notes douteuses, corrigées et choisie, et rend les notes cliquables. */
  private async show(xml: string) {
    // OSMD est publié en module CommonJS : selon l'outil de compilation, la classe est sur l'export nommé ou sur « default ».
    const mod: any = await import('opensheetmusicdisplay');
    const OpenSheetMusicDisplay = mod.OpenSheetMusicDisplay ?? mod.default?.OpenSheetMusicDisplay ?? mod.default;
    this.osmd ??= new OpenSheetMusicDisplay(this.host().nativeElement, {
      autoResize: true, backend: 'svg', drawTitle: false, drawComposer: false, drawCredits: false,
      followCursor: true,
      cursorsOptions: [{ type: 0, color: '#34479A', alpha: 0.3, follow: true }],
    } as any);
    await this.osmd.load(xml);
    this.notes = this.doc ? indexNotes(this.doc) : new Map();
    this.markDoubtful(this.score());
    this.colorEdits();
    this.osmd.render();
    this.collectStamps();
    if (this.editing()) this.bindNotes();
  }

  /** Notes corrigées en bleu, note choisie en bleu-vert (après les notes douteuses, qu'elles recouvrent). */
  private colorEdits() {
    const pick = this.picked()?.key;
    const measures = this.osmd?.Sheet?.SourceMeasures ?? [];
    measures.forEach((measure: any, m: number) => {
      for (const container of measure?.VerticalSourceStaffEntryContainers ?? []) {
        for (const entry of container?.StaffEntries ?? []) {
          const staff = entry?.ParentStaff?.idInMusicSheet ?? 0;
          for (const voice of entry?.VoiceEntries ?? []) {
            const at = Math.round((voice?.Timestamp?.RealValue ?? 0) * 960);
            let rank = 0;
            for (const note of voice?.Notes ?? []) {
              if (note.isRest?.()) continue;
              const key = `${staff}:${m}:${at}:${rank++}`;
              const color = key === pick ? PICK_COLOR : this.edited.has(key) ? EDIT_COLOR : null;
              if (color) { note.NoteheadColor = color; note.StemColorXml = color; }
            }
          }
        }
      }
    });
  }

  /** Chaque note dessinée, avec sa clé (portée:mesure:temps:rang) commune à indexNotes et à colorEdits. */
  private eachNote(fn: (key: string, graphical: any) => void) {
    const list: any[][] = this.osmd?.GraphicSheet?.MeasureList ?? [];
    list.forEach((row, m) => row.forEach((measure) => {
      const staff = measure?.ParentStaff?.idInMusicSheet ?? 0;
      for (const entry of measure?.staffEntries ?? []) {
        for (const gve of entry?.graphicalVoiceEntries ?? []) {
          const at = Math.round((gve.parentVoiceEntry?.Timestamp?.RealValue ?? 0) * 960);
          let rank = 0;
          for (const gn of gve.notes ?? []) {
            const note = gn.sourceNote;
            if (!note || note.isRest?.()) continue;
            fn(`${staff}:${m}:${at}:${rank++}`, gn);
          }
        }
      }
    }));
  }

  private bindNotes() {
    this.eachNote((key, gn) => {
      const el: Element | undefined = gn.getSVGGElement?.();
      const ref = this.notes.get(key);
      if (!el || !ref) return;
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        this.picked.set({ key, label: noteLabel(ref.el), voice: ref.voice, measure: ref.measure });
        void this.redraw();
      });
    });
  }

  /** Notes des mesures où les passes de lecture ne s'accordent pas : en orange, pour les comparer au scan d'origine. */
  private markDoubtful(s: ScoreMeta) {
    const doubtful = Object.keys(s.manifest?.fiabilite?.a_verifier ?? {}).map(Number).filter((n) => n > 0 && !this.verified().has(n));
    const measures = this.osmd?.Sheet?.SourceMeasures;
    if (!doubtful.length || !measures) return;
    for (const n of doubtful) {
      for (const container of measures[n - 1]?.VerticalSourceStaffEntryContainers ?? []) {
        for (const entry of container?.StaffEntries ?? []) {
          for (const voice of entry?.VoiceEntries ?? []) {
            for (const note of voice?.Notes ?? []) {
              note.NoteheadColor = DOUBT_COLOR;
              note.StemColorXml = DOUBT_COLOR;
            }
          }
        }
      }
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
