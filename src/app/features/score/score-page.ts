import { Component, computed, effect, inject, input, untracked } from '@angular/core';
import { RouterLink } from '@angular/router';
import { AudioEngine } from '../../core/audio-engine';
import { ScoreStore } from '../../core/score.store';
import { ScoreStatus } from '../../core/api';
import { Mixer } from './mixer';
import { ScoreViewer } from './score-viewer';

interface Step { key: ScoreStatus; label: string }

@Component({
  selector: 'app-score-page',
  imports: [RouterLink, Mixer, ScoreViewer],
  providers: [ScoreStore, AudioEngine],
  template: `
    <a routerLink="/" class="back">Toutes les partitions</a>

    @if (store.error()) {
      <p class="error" role="alert">{{ store.error() }}</p>
    } @else if (store.score(); as s) {
      <header class="head">
        <h1>{{ s.title }}</h1>
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
        <section class="notice failed" role="alert">
          <h2>La lecture n’a pas abouti</h2>
          <p>{{ s.error }}</p>
          <button type="button" class="btn" (click)="store.retry()">Relancer le traitement</button>
        </section>
      }

      @if (s.manifest) {
        @if (store.busy()) {
          <p class="notice working" role="status">Création du nouvel audio, {{ s.progress }} %. Vous pouvez continuer à écouter la version actuelle.</p>
        }
        <div class="workspace">
          <app-score-viewer [score]="s" />
          <app-mixer [score]="s" [busy]="store.busy()" />
        </div>
      } @else if (s.status !== 'failed') {
        <section class="progress" role="status" aria-live="polite">
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
    .back { display: inline-block; margin: .5rem 0 1.5rem; color: var(--ink-soft); font-size: .92rem; text-underline-offset: 3px; }
    .head { display: flex; flex-wrap: wrap; align-items: end; justify-content: space-between; gap: 1rem 2rem; margin-bottom: 1.75rem; }
    .head h1 { font-size: clamp(1.8rem, 4vw, 2.8rem); max-width: 26ch; }
    .facts { display: flex; flex-wrap: wrap; gap: 1.5rem; margin: 0; }
    .facts div { display: grid; }
    .facts dt { font-size: .8rem; color: var(--ink-soft); }
    .facts dd { margin: 0; font: 500 1.05rem/1.3 var(--serif); }
    .workspace { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 1.75rem; align-items: start; }
    app-mixer { position: sticky; top: 1rem; }
    @media (max-width: 960px) {
      .workspace { grid-template-columns: 1fr; }
      app-mixer { position: static; order: -1; }
    }
    .notice { padding: 1rem 1.25rem; border-radius: 12px; background: var(--surface); border: 1px solid var(--hair); margin-bottom: 1.25rem; }
    .notice.failed { border-color: var(--danger); display: grid; gap: .6rem; justify-items: start; }
    .notice.failed h2 { font-size: 1.3rem; }
    .notice.working { color: var(--basse); }
    .progress { max-width: 34rem; padding: 2rem 0; }
    .progress ol { list-style: none; margin: 0 0 1.5rem; padding: 0; display: grid; gap: .9rem; }
    .progress li { display: flex; align-items: center; gap: .8rem; color: var(--ink-soft); font-size: 1.05rem; }
    .progress li.current { color: var(--ink); font-weight: 600; }
    .progress li.done { color: var(--ink); }
    .dot { width: 12px; height: 12px; border-radius: 50%; border: 1.5px solid var(--rule); flex: none; }
    li.done .dot { background: var(--tenor); border-color: var(--tenor); }
    li.current .dot { border-color: var(--basse); box-shadow: 0 0 0 4px color-mix(in srgb, var(--basse) 20%, transparent); }
    .bar { height: 4px; border-radius: 4px; background: var(--hair); overflow: hidden; }
    .bar span { display: block; height: 100%; background: var(--ink); transition: width .6s ease; }
    .hint { margin-top: .75rem; color: var(--ink-soft); font-size: .92rem; }
  `],
})
export class ScorePage {
  readonly id = input.required<string>();
  protected readonly store = inject(ScoreStore);

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
