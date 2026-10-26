import { Component, inject } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { AitStore } from '../../core/ait';
import { CREDITS } from '../../core/credits';
import { frDateShort } from '../../core/dates';
import { LicenceService } from '../../core/licence';
import { IS_PLAYER } from '../../core/platform';
import { SHOP_TARGET, shopUrl } from '../../core/shop';

@Component({
  selector: 'app-about',
  imports: [RouterLink],
  template: `
    <section class="hero">
      <div class="logo-wrap">
        <span class="halo" aria-hidden="true"></span>
        <img (click)="secretTap()" [src]="credits.logo" [alt]="credits.company + ' – ' + credits.companyLong" width="720" height="628">
      </div>
      <div class="lead">
        <p class="eyebrow">À propos</p>
        <h1>Pupitre, une création <span class="gradient-text">{{ credits.company }}</span></h1>
        <p>Pupitre aide les chorales à apprendre leurs chants : chaque choriste écoute sa voix, soprano, alto, ténor ou basse, même sans lire le solfège.
           Il est né au Burkina Faso, pour les chorales liturgiques.</p>
        <a routerLink="/" class="btn">Déposer une partition</a>
      </div>
    </section>

    @if (licence.info(); as l) {
      <section class="glass card licence" aria-labelledby="lic-title">
        <p class="eyebrow">Votre licence</p>
        <h2 id="lic-title">{{ l.client }}</h2>
        <dl>
          <div><dt>Numéro</dt><dd>{{ l.id }}</dd></div>
          <div><dt>Début</dt><dd>{{ date(l.issued) }}</dd></div>
          <div><dt>Fin</dt><dd>{{ l.expires ? date(l.expires) + ' inclus' : 'Licence définitive (sans date de fin)' }}</dd></div>
          @if (l.daysLeft !== null) {
            <div><dt>Reste</dt><dd [class.warn]="l.daysLeft <= 30">{{ l.daysLeft }} jour{{ l.daysLeft === 1 ? '' : 's' }}</dd></div>
          }
          <div><dt>Ordinateur</dt><dd class="mono">{{ l.machine }}</dd></div>
        </dl>
        @if (l.expires) {
          <p class="note"><a class="btn" [href]="shop(l.id, l.machine)" [target]="shopTarget" rel="noopener">Renouveler en ligne</a>
            Orange Money ou Moov Money ; la nouvelle date s’installe toute seule. Ou contactez AIT au {{ credits.phones[0].label }}.</p>
        }
      </section>
    }

    <section class="people" aria-label="L'équipe">
      <article class="glass card">
        <p class="eyebrow">Éditeur</p>
        <h2>{{ credits.company }}</h2>
        <p class="sub">{{ credits.companyLong }}</p>
        <dl>
          <div><dt>PDG</dt><dd>{{ credits.ceo }}</dd></div>
          <div><dt>Siège</dt><dd>{{ credits.city }}, {{ credits.country }}</dd></div>
          <div><dt>Téléphone</dt><dd class="phones">
            @for (p of credits.phones; track p.tel) { <a [href]="'tel:' + p.tel">{{ p.label }}</a> }
          </dd></div>
        </dl>
      </article>
      <article class="glass card">
        <p class="eyebrow">Conception et développement</p>
        <h2>{{ credits.developer }}</h2>
        <p class="sub">Développeur de Pupitre</p>
        <dl>
          <div><dt>Réside à</dt><dd>{{ credits.city }}, {{ credits.country }}</dd></div>
          <div><dt>Entreprise</dt><dd>{{ credits.company }} · {{ credits.companyLong }}</dd></div>
        </dl>
      </article>
    </section>

    <section class="how" aria-labelledby="how-title">
      <h2 id="how-title">Comment ça marche</h2>
      <ol>
        <li class="glass">
          <span class="num" style="--c: var(--soprano)">1</span>
          <h3>Déposer</h3>
          <p>Un PDF, une ou plusieurs photos prises au téléphone, un fichier MusicXML, MIDI ou MuseScore.</p>
        </li>
        <li class="glass">
          <span class="num" style="--c: var(--alto)">2</span>
          <h3>Lire</h3>
          <p>Pupitre redresse et nettoie l’image, lit les notes, corrige les erreurs d’octave, d’armure et de rythme.</p>
        </li>
        <li class="glass">
          <span class="num" style="--c: var(--tenor)">3</span>
          <h3>Séparer</h3>
          <p>Chaque pupitre reçoit sa propre piste : soprano, alto, ténor et basse.</p>
        </li>
        <li class="glass">
          <span class="num" style="--c: var(--basse)">4</span>
          <h3>Répéter</h3>
          <p>Écoutez votre voix en avant, réglez le tempo, téléchargez les pistes de travail pour la répétition.</p>
        </li>
      </ol>
    </section>

    @if (player && ait.hasKey()) { <p class="admin"><a routerLink="/ait">Espace AIT (administration)</a></p> }
  `,
  styles: [`
    .hero { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.1fr); gap: clamp(1.5rem, 5vw, 4rem); align-items: center;
            padding: clamp(2rem, 6vw, 4.5rem) 0 clamp(2rem, 5vw, 3.5rem); }
    .logo-wrap { position: relative; display: grid; place-items: center; }
    .halo { position: absolute; inset: 4%; border-radius: 40px;
            background: radial-gradient(circle, color-mix(in srgb, var(--accent-2) 45%, transparent), transparent 70%); filter: blur(36px); }
    /* plaque claire : le logo AIT (lettres bleu nuit) est dessiné pour un fond blanc */
    .logo-wrap img { position: relative; width: min(100%, 470px); height: auto; padding: clamp(1rem, 3vw, 2rem); border-radius: 32px;
                     background: radial-gradient(120% 120% at 50% 25%, #FFFFFF 45%, #E2EBFF 100%);
                     box-shadow: 0 0 0 1px rgba(47, 123, 255, .25), 0 30px 80px -40px rgba(10, 40, 120, .8); }
    :host-context([data-theme="light"]) .halo { opacity: .5; }
    .lead { display: grid; gap: 1.1rem; justify-items: start; }
    .lead h1 { font-size: clamp(2rem, 4.4vw, 3.2rem); }
    .lead > p:not(.eyebrow) { color: var(--ink-soft); font-size: 1.1rem; max-width: 36rem; }

    .licence { margin-bottom: 1.25rem; }
    .admin { margin-top: 2rem; text-align: center; font-size: .82rem; }
    .admin a { color: var(--ink-soft); text-underline-offset: 3px; }
    .warn { color: var(--danger); }
    .mono { font-family: ui-monospace, 'SF Mono', Consolas, monospace; letter-spacing: .05em; }
    .note { margin-top: .6rem; color: var(--ink-soft); font-size: .9rem; }
    .people { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.25rem; }
    .card { padding: 1.6rem 1.75rem; display: grid; gap: .45rem; position: relative; overflow: hidden; }
    .card::before { content: ""; position: absolute; inset: 0 0 auto; height: 2px;
                    background: linear-gradient(90deg, var(--accent), var(--accent-2), transparent); }
    .card h2 { font-size: 1.45rem; }
    .sub { color: var(--ink-soft); }
    dl { margin: .75rem 0 0; display: grid; gap: .55rem; }
    dl div { display: grid; grid-template-columns: 7rem 1fr; gap: .75rem; padding-top: .55rem; border-top: 1px solid var(--hair); }
    dt { color: var(--ink-soft); font-size: .88rem; }
    dd { margin: 0; font-weight: 600; }
    .phones { display: grid; gap: .2rem; }
    .phones a { color: var(--accent-2); text-decoration: none; white-space: nowrap; }
    .phones a:hover { text-decoration: underline; text-underline-offset: 3px; }

    .how { margin-top: clamp(2.5rem, 6vw, 4rem); }
    .how h2 { font-size: 1.6rem; margin-bottom: 1.25rem; }
    .how ol { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1rem; }
    @media (max-width: 980px) { .how ol { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (max-width: 520px) { .how ol { grid-template-columns: 1fr; } }
    .how li { padding: 1.4rem; display: grid; gap: .5rem; align-content: start; }
    .num { width: 36px; height: 36px; border-radius: 50%; display: grid; place-items: center; font: 700 1rem/1 var(--serif);
           color: var(--c); border: 1.5px solid var(--c); box-shadow: 0 0 18px -4px var(--c); }
    .how h3 { font-size: 1.15rem; }
    .how p { color: var(--ink-soft); font-size: .95rem; }
    @media (max-width: 820px) { .hero { grid-template-columns: 1fr; } .logo-wrap img { width: min(80%, 380px); } }
  `],
})
export class About {
  protected readonly credits = CREDITS;
  protected readonly licence = inject(LicenceService);
  protected readonly date = frDateShort;
  protected readonly player = IS_PLAYER;
  protected readonly shopTarget = SHOP_TARGET;
  protected shop(id: string, machine: string) { return shopUrl({ renouveler: id, machine }); }
  protected readonly ait = inject(AitStore);
  private readonly router = inject(Router);
  private taps: number[] = [];

  /** Accès caché à l'Espace AIT (avant l'import de la clé) : 7 touches sur le logo en moins de 4 secondes. */
  protected secretTap() {
    if (!this.player) return;
    const now = Date.now();
    this.taps = [...this.taps.filter((t) => now - t < 4000), now];
    if (this.taps.length >= 7) { this.taps = []; void this.router.navigate(['/ait']); }
  }
}
