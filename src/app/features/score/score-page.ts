import { Component, computed, effect, inject, input, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreStore } from '../../core/score.store';
import { ScoreMeta, ScoreStatus } from '../../core/api';
import { Mixer } from './mixer';
import { ScoreViewer } from './score-viewer';

interface Step { key: ScoreStatus; label: string }

@Component({
  selector: 'app-score-page',
  imports: [RouterLink, Mixer, ScoreViewer],
  providers: [ScoreStore, AudioEngine],
  template: `
    <a routerLink="/" class="back"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14.5 6 8.5 12l6 6"/></svg>Toutes les partitions</a>

    @if (store.error()) {
      <p class="error" role="alert">{{ store.error() }}</p>
    } @else if (store.score(); as s) {
      <header class="head">
        <div class="title">
          <p class="eyebrow">Partition</p>
          <h1>{{ s.title }}</h1>
        </div>
        @if (s.manifest; as m) {
          <dl class="facts">
            <div><dt>Tonalité</dt><dd>{{ m.key }}</dd></div>
            @if (m.timeSignature) { <div><dt>Mesure</dt><dd>{{ m.timeSignature }}</dd></div> }
            <div><dt>Longueur</dt><dd>{{ m.measures }} mesures</dd></div>
            <div><dt>Voix</dt><dd>{{ m.voices.length }}</dd></div>
          </dl>
        }
      </header>

      @if (store.actionError()) { <p class="error" role="alert">{{ store.actionError() }}</p> }

      @if (s.status === 'failed') {
        <section class="notice failed glass" role="alert">
          <h2>La lecture n’a pas abouti</h2>
          <p>{{ s.error }}</p>
          <button type="button" class="btn" (click)="store.retry()">Relancer le traitement</button>
          @if (canReread(s) && s.lecture !== 'voix') {
            <button type="button" class="btn quiet" (click)="store.reread('satb')">Relire voix par voix (4 voix SATB)</button>
          }
        </section>
      }

      @if (s.manifest) {
        @if (store.busy()) {
          <p class="notice working glass" role="status">Création du nouvel audio, {{ s.progress }} %. Vous pouvez continuer à écouter la version actuelle.</p>
        }
        <div class="workspace">
          <app-score-viewer [score]="s" />
          <app-mixer [score]="s" [busy]="store.busy()" />
        </div>
        @if (canReread(s) && !store.busy()) {
          <section class="reread glass">
            @if (s.lecture === 'voix') {
              <p>Lue <b>voix par voix</b> : 4 portées par système reconnues (Soprano, Alto, Ténor, Basse),
                chaque voix relue à part.</p>
              <button type="button" class="btn quiet" (click)="store.reread('ordinaire')">Relire en lecture ordinaire</button>
            } @else {
              <p>Voix mélangées ou manquantes ? Si c’est un chœur à 4 voix avec <b>une portée par voix</b>
                (Soprano, Alto, Ténor, Basse de haut en bas), relisez-la voix par voix.</p>
              <button type="button" class="btn quiet" (click)="store.reread('satb')">Relire voix par voix (4 voix SATB)</button>
            }
          </section>
        }
      } @else if (s.status !== 'failed') {
        <section class="progress glass" role="status" aria-live="polite">
          <div class="scan" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div>
          <ol>
            @for (step of steps(); track step.key; let i = $index) {
              <li [class.done]="stepState(i) === 'done'" [class.current]="stepState(i) === 'current'">
                <span class="dot" aria-hidden="true"></span>{{ step.label }}
              </li>
            }
          </ol>
          <div class="bar"><span [style.width.%]="s.progress"></span></div>
          <p class="hint">
            @if (s.status === 'queued') {
              En attente : une autre partition est peut-être en cours de traitement.
            } @else if (s.status === 'recognizing') {
              La lecture des notes prend en général une à trois minutes par page.
            } @else {
              {{ s.progress }} %
            }
          </p>
        </section>
      }
    } @else {
      <p class="hint">Chargement…</p>
    }
  `,
  styles: [`
    .reread { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: .8rem; margin-top: 1rem; padding: .9rem 1.1rem; }
    .reread p { margin: 0; font-size: .88rem; color: var(--ink-soft); max-width: 44rem; }
    .reread b { color: var(--ink); }
    .back { display: inline-flex; align-items: center; gap: .35rem; margin: 1.25rem 0 1.25rem; padding: .35rem .85rem .35rem .55rem; border-radius: 999px;
            color: var(--ink-soft); font-size: .88rem; font-weight: 600; text-decoration: none; border: 1px solid var(--hair); background: var(--raised); }
    .back:hover { color: var(--ink); border-color: var(--accent-2); }
    .back svg { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
    .head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 1rem 2rem; margin-bottom: 1.75rem; }
    .title { display: grid; gap: .6rem; }
    .head h1 { font-size: clamp(1.8rem, 4vw, 2.8rem); max-width: 26ch; }
    .facts { display: flex; flex-wrap: wrap; gap: .5rem; margin: 0; }
    .facts div { display: grid; gap: .1rem; padding: .55rem .9rem; border-radius: 14px; background: var(--surface); border: 1px solid var(--hair); min-width: 5.5rem; }
    .facts dt { font-size: .68rem; letter-spacing: .16em; text-transform: uppercase; color: var(--ink-soft); }
    .facts dd { margin: 0; font: 600 1rem/1.3 var(--serif); }
    .workspace { display: grid; grid-template-columns: minmax(0, 1fr) 370px; gap: 1.75rem; align-items: start; }
    app-mixer { position: sticky; top: 5.25rem; }
    @media (max-width: 960px) {
      .workspace { grid-template-columns: 1fr; }
      app-mixer { position: static; order: -1; }
    }
    .notice { padding: 1rem 1.25rem; margin-bottom: 1.25rem; }
    .notice.failed { border-color: color-mix(in srgb, var(--danger) 50%, transparent); display: grid; gap: .6rem; justify-items: start; }
    .notice.failed h2 { font-size: 1.3rem; }
    .notice.working { color: var(--accent-2); }
    .progress { position: relative; overflow: hidden; max-width: 40rem; padding: 2rem 2rem 1.6rem; }
    .scan { position: absolute; inset: 0; display: grid; align-content: center; gap: 16px; padding: 0 1.5rem; opacity: .18; pointer-events: none; }
    .scan i { height: 1px; background: var(--ink-soft); }
    .scan::after { content: ""; position: absolute; top: 0; bottom: 0; width: 30%; left: -30%;
                   background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--accent-2) 70%, transparent), transparent);
                   animation: sweep 2.4s ease-in-out infinite; }
    @keyframes sweep { to { left: 100%; } }
    .progress ol { position: relative; list-style: none; margin: 0 0 1.5rem; padding: 0; display: grid; gap: 1rem; }
    .progress li { display: flex; align-items: center; gap: .85rem; color: var(--ink-soft); font-size: 1.05rem; }
    .progress li.current { color: var(--ink); font-weight: 700; }
    .progress li.done { color: var(--ink); }
    .dot { width: 14px; height: 14px; border-radius: 50%; border: 1.5px solid var(--rule); flex: none; }
    li.done .dot { background: var(--ok); border-color: var(--ok); box-shadow: 0 0 10px var(--ok); }
    li.current .dot { border-color: var(--accent-2); background: var(--accent-2); animation: beat 1.3s ease-in-out infinite; }
    @keyframes beat { 50% { box-shadow: 0 0 0 7px color-mix(in srgb, var(--accent-2) 18%, transparent); } }
    .bar { position: relative; height: 5px; border-radius: 5px; background: var(--hair); overflow: hidden; }
    .bar span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); box-shadow: 0 0 12px var(--accent-2); transition: width .6s ease; }
    .hint { position: relative; margin-top: .75rem; color: var(--ink-soft); font-size: .92rem; }
  `],
})
export class ScorePage {
  readonly id = input.required<string>();
  protected readonly store = inject(ScoreStore);
  /** Seules les photos et les PDF passent par la lecture des notes */
  protected canReread(s: ScoreMeta) { return s.source === 'pdf' || s.source === 'image'; }

  protected readonly steps = computed<Step[]>(() => {
    const source = this.store.score()?.source;
    const fromImage = source === 'pdf' || source === 'image';
    const steps: Step[] = [];
    if (fromImage) {
      steps.push({ key: 'preprocessing', label: 'Nettoyage de l’image' }, { key: 'recognizing', label: 'Lecture des notes' });
    }
    steps.push({ key: 'rendering', label: 'Séparation des voix et création de l’audio' });
    return steps;
  });

  constructor() {
    effect(() => {
      const id = this.id();
      untracked(() => this.store.load(id));
    });
  }

  protected stepState(i: number): 'done' | 'current' | 'todo' {
    const status = this.store.score()?.status;
    const current = this.steps().findIndex((s) => s.key === status);
    if (current === -1) return 'todo';
    return i < current ? 'done' : i === current ? 'current' : 'todo';
  }
}
