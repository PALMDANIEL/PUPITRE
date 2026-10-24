import { Component } from '@angular/core';
import { RouterLink } from '@angular/router';
import { CREDITS } from '../../core/credits';

@Component({
  selector: 'app-about',
  imports: [RouterLink],
  template: `
    <section class="hero">
      <div class="logo-wrap">
        <span class="halo" aria-hidden="true"></span>
        <img [src]="credits.logo" [alt]="credits.company + ' – ' + credits.companyLong" width="720" height="628">
      </div>
      <div class="lead">
        <p class="eyebrow">À propos</p>
        <h1>Pupitre, une création <span class="gradient-text">{{ credits.company }}</span></h1>
        <p>Pupitre aide les chorales à apprendre leurs chants : chaque choriste écoute sa voix, soprano, alto, ténor ou basse, même sans lire le solfège.
           Il est né au Burkina Faso, pour les chorales liturgiques.</p>
        <a routerLink="/" class="btn">Déposer une partition</a>
      </div>
    </section>

    <section class="people" aria-label="L'équipe">
      <article class="glass card">
        <p class="eyebrow">Éditeur</p>
        <h2>{{ credits.company }}</h2>
        <p class="sub">{{ credits.companyLong }}</p>
        <dl>
          <div><dt>PDG</dt><dd>{{ credits.ceo }}</dd></div>
          <div><dt>Siège</dt><dd>{{ credits.city }}, {{ credits.country }}</dd></div>
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
}
