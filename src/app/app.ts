import { Component, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { CREDITS } from './core/credits';
import { IS_PLAYER } from './core/platform';

type Theme = 'dark' | 'light';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <a class="skip" href="#contenu">Aller au contenu</a>
    <header class="bar">
      <div class="bar-in">
        <a routerLink="/" class="mark" aria-label="Pupitre, accueil">
          <svg viewBox="0 0 30 22" aria-hidden="true">
            <path d="M1 2.5h28" stroke="var(--soprano)"/><path d="M1 8.2h28" stroke="var(--alto)"/>
            <path d="M1 13.8h28" stroke="var(--tenor)"/><path d="M1 19.5h28" stroke="var(--basse)"/>
          </svg>
          <span>Pupitre</span>
        </a>

        <nav aria-label="Navigation principale">
          <a routerLink="/" routerLinkActive="on" [routerLinkActiveOptions]="{ exact: true }">{{ player ? 'Mes chants' : 'Partitions' }}</a>
          <a routerLink="/a-propos" routerLinkActive="on">À propos</a>
        </nav>

        <div class="tools">
          <button type="button" class="theme" (click)="toggleTheme()"
                  [attr.aria-label]="theme() === 'dark' ? 'Passer en mode clair' : 'Passer en mode sombre'">
            @if (theme() === 'dark') {
              <svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.3 5.3l1.6 1.6M17.1 17.1l1.6 1.6M5.3 18.7l1.6-1.6M17.1 6.9l1.6-1.6"/></svg>
            } @else {
              <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8.5 8.5 0 0 1 9.5 4a8.5 8.5 0 1 0 10.5 10.5z"/></svg>
            }
          </button>
          <a routerLink="/a-propos" class="by" [attr.aria-label]="'Conçu par ' + credits.company + ', ' + credits.companyLong">
            <span>par</span><span class="plate"><img [src]="credits.emblem" alt="" width="44" height="32"></span>
          </a>
        </div>
      </div>
    </header>

    <main id="contenu"><router-outlet /></main>

    <footer class="foot">
      <div class="foot-in">
        <span class="plate foot-plate"><img class="foot-logo" [src]="credits.emblem" [alt]="'Logo ' + credits.company" width="80" height="58" loading="lazy"></span>
        <div class="foot-text">
          <p class="made">Conçu et développé par <strong>{{ credits.company }}</strong> · {{ credits.companyLong }}</p>
          <p>PDG : <strong>{{ credits.ceo }}</strong></p>
          <p>Développeur : <strong>{{ credits.developer }}</strong> · {{ credits.city }}, {{ credits.country }}</p>
          <p class="phones">Téléphone :
            @for (p of credits.phones; track p.tel; let last = $last) {
              <a [href]="'tel:' + p.tel">{{ p.label }}</a>@if (!last) { <span aria-hidden="true"> · </span> }
            }
          </p>
        </div>
        <p class="copy">© {{ year }} {{ credits.company }} · Pupitre, pour les chorales</p>
      </div>
    </footer>
  `,
  styles: [`
    :host { display: flex; flex-direction: column; min-height: 100vh; }
    .skip { position: absolute; left: -999px; top: .5rem; z-index: 20; padding: .5rem 1rem; border-radius: 999px; background: var(--accent); color: #fff; }
    .skip:focus { left: 1rem; }

    .bar { position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--hair);
           background: color-mix(in srgb, var(--paper) 72%, transparent);
           backdrop-filter: blur(16px) saturate(150%); -webkit-backdrop-filter: blur(16px) saturate(150%); }
    .bar::after { content: ""; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
                  background: linear-gradient(90deg, transparent, var(--accent-2), var(--accent), transparent); opacity: .55; }
    .bar-in { max-width: 1240px; margin: 0 auto; padding: .7rem clamp(1rem, 4vw, 2.5rem);
              display: flex; align-items: center; gap: clamp(.75rem, 3vw, 2.5rem); }
    .mark { display: inline-flex; align-items: center; gap: .7rem; text-decoration: none; font: 700 1.35rem/1 var(--serif); letter-spacing: -.01em; }
    .mark svg { width: 30px; height: 22px; fill: none; stroke-width: 2.4; stroke-linecap: round;
                filter: drop-shadow(0 0 6px color-mix(in srgb, var(--accent-2) 55%, transparent)); }
    nav { display: flex; gap: .25rem; }
    nav a { padding: .45rem .9rem; border-radius: 999px; white-space: nowrap; text-decoration: none; font-weight: 600; font-size: .93rem; color: var(--ink-soft);
            transition: color .2s, background .2s; }
    nav a:hover { color: var(--ink); }
    nav a.on { color: var(--ink); background: var(--raised); box-shadow: inset 0 0 0 1px var(--hair); }
    .tools { margin-left: auto; display: flex; align-items: center; gap: .6rem; }
    .theme { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--hair); background: var(--raised);
             display: grid; place-items: center; cursor: pointer; color: var(--ink); transition: border-color .2s, color .2s; }
    .theme:hover { border-color: var(--accent-2); color: var(--accent-2); }
    .theme svg { width: 19px; height: 19px; fill: none; stroke: currentColor; stroke-width: 1.8; stroke-linecap: round; stroke-linejoin: round; }
    .by { display: inline-flex; align-items: center; gap: .45rem; text-decoration: none; font-size: .68rem; font-weight: 700; letter-spacing: .18em;
          text-transform: uppercase; color: var(--ink-soft); }
    .by:hover .plate { box-shadow: 0 0 0 1px rgba(47, 123, 255, .5), 0 0 22px -2px rgba(39, 170, 255, .7); }
    /* le logo AIT est dessiné pour un fond clair : on le pose toujours sur une plaque lumineuse */
    .plate { display: grid; place-items: center; border-radius: 12px; padding: 3px 8px;
             background: radial-gradient(120% 140% at 50% 30%, #FFFFFF 40%, #DCE7FF 100%);
             box-shadow: 0 0 0 1px rgba(47, 123, 255, .25), 0 0 18px -6px rgba(39, 170, 255, .6); transition: box-shadow .2s; }
    .by img { height: 32px; width: auto; display: block; }

    main { flex: 1; width: 100%; max-width: 1240px; margin: 0 auto; padding: 0 clamp(1rem, 4vw, 2.5rem) 4rem; }

    .foot { border-top: 1px solid var(--hair); background: color-mix(in srgb, var(--paper) 60%, transparent); }
    .foot-in { max-width: 1240px; margin: 0 auto; padding: 1.75rem clamp(1rem, 4vw, 2.5rem);
               display: grid; grid-template-columns: auto 1fr auto; gap: .5rem 1.5rem; align-items: center; }
    .foot-plate { padding: 6px 12px; border-radius: 16px; }
    .foot-logo { height: 52px; width: auto; display: block; }
    .foot-text { display: grid; gap: .15rem; font-size: .9rem; color: var(--ink-soft); }
    .foot-text strong { color: var(--ink); font-weight: 700; }
    .made { color: var(--ink); }
    .phones a { color: var(--accent-2); font-weight: 700; text-decoration: none; white-space: nowrap; }
    .phones a:hover { text-decoration: underline; text-underline-offset: 3px; }
    .copy { font-size: .8rem; color: var(--ink-soft); text-align: right; }
    @media (max-width: 720px) {
      .by > span:first-child { display: none; }
      .mark span { display: none; }
      .bar-in { gap: .5rem; }
      nav a { padding: .4rem .65rem; font-size: .88rem; }
      .tools { gap: .4rem; }
      .theme { width: 36px; height: 36px; }
      .foot-in { grid-template-columns: auto 1fr; }
      .copy { grid-column: 1 / -1; text-align: left; }
    }
  `],
})
export class App {
  protected readonly credits = CREDITS;
  protected readonly player = IS_PLAYER;
  protected readonly year = new Date().getFullYear();
  protected readonly theme = signal<Theme>(document.documentElement.dataset['theme'] === 'light' ? 'light' : 'dark');

  protected toggleTheme() {
    const next: Theme = this.theme() === 'dark' ? 'light' : 'dark';
    this.theme.set(next);
    document.documentElement.dataset['theme'] = next;
    try { localStorage.setItem('pupitre-theme', next); } catch { /* navigation privée : le choix vaut pour la session */ }
  }
}
