import { Component } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink],
  template: `
    <header class="bar">
      <a routerLink="/" class="mark" aria-label="Pupitre, accueil">
        <svg viewBox="0 0 28 20" aria-hidden="true">
          <path d="M1 2h26" stroke="var(--soprano)"/><path d="M1 7.3h26" stroke="var(--alto)"/>
          <path d="M1 12.6h26" stroke="var(--tenor)"/><path d="M1 18h26" stroke="var(--basse)"/>
        </svg>
        Pupitre
      </a>
    </header>
    <main><router-outlet /></main>
  `,
  styles: [`
    .bar { max-width: 1240px; margin: 0 auto; padding: 1.25rem clamp(1rem, 4vw, 2.5rem); }
    .mark { display: inline-flex; align-items: center; gap: .65rem; text-decoration: none; font: 600 1.35rem/1 var(--serif); letter-spacing: .01em; }
    .mark svg { width: 28px; height: 20px; fill: none; stroke-width: 2.2; stroke-linecap: round; }
    main { max-width: 1240px; margin: 0 auto; padding: 0 clamp(1rem, 4vw, 2.5rem) 4rem; }
  `],
})
export class App {}
