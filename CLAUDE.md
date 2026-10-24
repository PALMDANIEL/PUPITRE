# Pupitre — contexte du projet (reprise depuis claude.ai)

## L'utilisateur
- Développeur full-stack (Angular / NgRx / Node.js / Express / TypeScript), travaille en **français**.
- Mac **Intel x86_64**, macOS 15.5, terminal **zsh**, Homebrew.
- **Important pour les commandes** : dans son zsh, une ligne qui commence par `#` est exécutée comme une commande et provoque une erreur. Ne jamais mettre de commentaires `#` dans les commandes à coller (ils sont permis à l'intérieur des fichiers).
- Préfère du code prêt à coller dans le terminal (heredocs `cat > fichier << 'EOF'`), un bloc à la fois.
- Sensibilité design : élégance, aspect matériel (papier, encre, fils tissés), ergonomie soignée, pas de look « SaaS générique ».
- Contexte d'usage : chorales liturgiques au Burkina Faso, choristes qui ne lisent pas le solfège.

## Le produit
Plateforme web : on dépose une partition de chorale (PDF, photo JPG/PNG ou MusicXML), elle lit les notes (OMR) et produit l'audio de chaque voix (Soprano, Alto, Ténor, Basse), avec une interface pour écouter sa voix en avant, régler les volumes, le tempo, télécharger des MP3 de travail et corriger la partition.
Objectif : d'abord en local, ensuite hébergement en ligne et **commercialisation**.

## Emplacements
- Application : `~/pupitre-plateforme` (ce dossier).
- Moteur Python (fonctionne, testé) : `~/pupitre/engine` → `preprocess.py`, `render.py`, venv `.venv` (Python 3.12).
- Audiveris (OMR) : `/Applications/Audiveris.app/Contents/MacOS/Audiveris` (copié depuis le .dmg, quarantaine retirée).
- Banque de sons : `~/soundfonts/GeneralUser-GS.sf2` (variable `SOUNDFONT`, lue par render.py).
- Données (fichiers) : `~/pupitre-plateforme/data/<uuid>/` (source, pages/, audio/, partition.mxl…).
- Configuration : `~/pupitre-plateforme/.env` → `DATABASE_URL=postgresql://postgres:<mdp>@localhost:5432/pupitre`.
- Node.js : v24.15.0 installé via le pkg officiel dans /usr/local/bin. L'utilisateur a **nvm** (v20). On a fait `nvm alias default system` pour utiliser la v24. Angular 22 exige Node ≥ 22.22.3.

## Architecture actuelle (locale)
- **Un seul processus Node** (`server/main.ts`, lancé par `tsx`) : API Express 5 + fichiers statiques Angular + **file de traitement en mémoire** (séquentielle, `server/jobs.ts`), reprise automatique des traitements interrompus au démarrage (`recover()`).
- **PostgreSQL local** (géré par l'utilisateur dans pgAdmin) : table `scores` créée automatiquement (`server/store.ts`, pilote `pg`). La base `pupitre` est créée automatiquement si elle n'existe pas. Les anciens `meta.json` sont importés puis renommés en `.importe`.
- **Frontend Angular 22** (standalone, zoneless, signals, `@ngrx/signals`), `opensheetmusicdisplay` 2.2.0 pour afficher la partition, Web Audio API pour le mixage synchronisé des pistes.
- Scripts : `npm run serve` (lance) · `npm start` (recompile l'interface puis lance) · `npm run build`.
- Application : http://localhost:3000.

### Fichiers serveur
- `server/config.ts` : chemins et variables (charge `.env` via `process.loadEnvFile`), `checkSetup()` liste ce qui manque.
- `server/types.ts` : `ScoreMeta`, `Manifest`, `VoiceInfo`, `UserError` (message affiché tel quel à l'utilisateur).
- `server/store.ts` : PostgreSQL (`initDb`, `readMeta`, `writeMeta`, `patchMeta`, `listMetas`, `removeScore`).
- `server/jobs.ts` : pipeline `preprocess.py` → Audiveris `-batch -export` → `render.py`, progression en base, `enqueue()`, `recover()`.
- `server/main.ts` : routes.

### API
- `GET /api/scores`, `GET /api/scores/:id`, `POST /api/scores` (multipart `file`), `PATCH /api/scores/:id` (titre)
- `POST /api/scores/:id/render` `{tempo, timbre: 'choeur'|'piano'}`, `POST /api/scores/:id/retry`
- `PUT /api/scores/:id/partition` (MusicXML corrigé, multipart), `DELETE /api/scores/:id`
- `GET /files/:id/(audio|pages)/:file[?download]`

### Statuts
`queued → preprocessing → recognizing → rendering → ready | failed`

### Frontend (`src/app`)
- `core/api.ts`, `core/library.store.ts`, `core/score.store.ts` (polling 1,5 s pendant un traitement), `core/audio-engine.ts`
- `features/library/library.ts` : zone de dépôt en forme de portée, dont les lignes prennent les couleurs des voix au survol ; liste des partitions.
- `features/score/score-page.ts`, `score-viewer.ts` (OSMD + curseur synchronisé à l'audio, onglet scan nettoyé), `mixer.ts` (« Je chante », volumes, couper, tempo/sonorité, téléchargements, correction via MuseScore).
- Design : polices Literata (titres) + Manrope ; couleurs de voix soprano ocre, alto bissap, ténor malachite, basse indigo ; mode sombre géré.

## Moteur (testé sur une vraie partition scannée)
- `preprocess.py` : niveaux de gris, aplatissement de l'éclairage, seuillage adaptatif, suppression des bandes sombres de bord, dé-bruitage, redressement → `page-NN.png` + `clean.pdf`. Sans ce nettoyage, Audiveris ne reconnaissait que 4 mesures sur 13 ; avec, les 13 mesures et le 6/8 sont reconnus.
- `render.py` : music21. Sépare les portées à deux voix mesure par mesure (voix la plus aiguë en haut) ou éclate les accords (note haute / note basse) ; écarte les portées d'accompagnement (nom piano/orgue… ou accords de 3 notes et plus) ; trie les voix par hauteur moyenne ; nomme S/A/T/B s'il y en a 4 ; tempo par défaut 90 à la noire en 6/8, 9/8, 12/8, sinon 72 ; FluidSynth + ffmpeg → `<voix>.mp3`, `<voix>_travail.mp3` (voix en avant, autres en fond), `tutti.mp3`, `score.musicxml`, `manifest.json` (noms de notes en français). Affiche `Voix i/n : …` (utilisé pour la progression).

## État au moment de la reprise
- L'installation et la compilation Angular ont réussi.
- **Problème à corriger en premier** : à la question « Serveur », l'utilisateur a saisi `http://localhost:3000`, ce qui donne `getaddrinfo ENOTFOUND http`. Correction :
  `sed -i '' 's#@http://localhost:3000:#@localhost:#' .env`, puis `node /tmp/pupitre-pgtest.cjs` (si le fichier existe encore), puis `npm run serve`.
- **Jamais vérifié en conditions réelles** : le comportement de l'interface dans le navigateur (curseur OSMD, mixage Web Audio, envoi de fichiers) et le pipeline complet lancé depuis le serveur. Tester avec `~/Downloads/Seigneur Dieu d'amour voici tes deux enfants.pdf`.

## Limites connues
- Pas de partitions manuscrites ni de **solfa chiffré** (notation courante dans les chorales africaines) : Audiveris ne lit que la notation sur portée.
- Les paroles ne sont pas chantées (son « aah » de chœur ou piano).
- La qualité dépend du scan : page à plat, bonne lumière.

## Feuille de route (vers la commercialisation)
1. Vérifier et corriger le parcours complet en local.
2. Envoi de plusieurs partitions à la fois (répertoire d'une chorale).
3. Comptes utilisateurs et espaces par chorale (multi-tenant), avec rôles chef de chœur / choriste.
4. Hébergement : VPS Linux + Docker (Audiveris est en x86_64 ; il ne peut pas tourner sur Vercel, trop lourd et trop long), PostgreSQL en ligne, stockage des fichiers en ligne (compatible S3).
5. Abonnement et paiement (mobile money + carte).
6. Plus tard : éditeur de notes intégré (remplacer le passage par MuseScore), lecture du solfa chiffré.

## Façon de travailler avec l'utilisateur
- Expliquer simplement, en français, une étape à la fois, et vérifier le résultat avant de continuer.
- Donner des commandes sans lignes `#`.
- Quand une erreur survient, demander les dernières lignes du terminal plutôt que deviner.
