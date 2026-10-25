# Pupitre — contexte du projet (reprise depuis claude.ai)

## L'utilisateur
- Développeur full-stack (Angular / NgRx / Node.js / Express / TypeScript), travaille en **français**.
- Mac **Intel x86_64**, macOS 15.5, terminal **zsh**, Homebrew.
- **Important pour les commandes** : dans son zsh, une ligne qui commence par `#` est exécutée comme une commande et provoque une erreur. Ne jamais mettre de commentaires `#` dans les commandes à coller (ils sont permis à l'intérieur des fichiers).
- Préfère du code prêt à coller dans le terminal (heredocs `cat > fichier << 'EOF'`), un bloc à la fois.
- Sensibilité design : élégance, aspect matériel (papier, encre, fils tissés), ergonomie soignée, pas de look « SaaS générique ».
- Contexte d'usage : chorales liturgiques au Burkina Faso, choristes qui ne lisent pas le solfège.

## Le produit
Plateforme web : on dépose une partition de chorale (PDF, une ou plusieurs photos JPG/PNG/HEIC/TIFF, MusicXML, MIDI, MuseScore), elle lit les notes (OMR) et produit l'audio de chaque voix (Soprano, Alto, Ténor, Basse), avec une interface pour écouter sa voix en avant, régler les volumes, le tempo, télécharger des MP3 de travail et corriger la partition.
Objectif : d'abord en local, ensuite hébergement en ligne et **commercialisation**.

## Emplacements
- Application : `~/pupitre-plateforme` (ce dossier).
- Moteur Python : **dans le dépôt**, `engine/` → `omr.py`, `preprocess.py`, `merge.py`, `render.py`, `requirements.txt`. Le venv reste `~/pupitre/engine/.venv` (Python 3.12, + pillow-heif). `~/pupitre/engine` n'est plus lu par le serveur.
- Banc d'essai : `engine/bench/` (`make_corpus.py` avec `~/pupitre/bench-venv` qui a Verovio ; `run_bench.py` avec le venv du moteur). Corpus dans `~/pupitre/bench-corpus`.
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
- `server/jobs.ts` : `omr.py` (nettoyage → Audiveris, seconde lecture si besoin → assemblage des mouvements) → `render.py`, progression en base, `enqueue()`, `recover()`. MIDI rendu directement ; MuseScore converti si `mscore` est installé.
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
- Design (24/10/2026, thème « Pupitre × AIT ») : futuriste et lisible ; nuit profonde + bleu électrique et cyan du logo AIT, panneaux de verre (`.glass`), grille de circuit en fond, fils de portée lumineux aux couleurs des voix. Sombre par défaut, clair via le bouton de l'en-tête (`data-theme`, mémorisé dans `localStorage`). Polices Sora (titres) + Manrope. Partition toujours sur feuille blanche.
- Éditeur : **AIT – Artificial Intelligence & Technology**, PDG **PALM Romeo Daratagnan** ; développeur **PALM Romeo Daratagnan**, Ouagadougou, Burkina Faso. Mentions centralisées dans `src/app/core/credits.ts` (en-tête, pied de page, page `/a-propos`). Logo détouré dans `public/ait-logo.png` et `public/ait-emblem.png`, toujours posé sur une plaque claire (il est dessiné pour fond blanc).

## Moteur (testé sur une vraie partition scannée)
- `preprocess.py` : niveaux de gris, aplatissement de l'éclairage, seuillage adaptatif, suppression des bandes sombres de bord, dé-bruitage, redressement → `page-NN.png` + `clean.pdf`. Sans ce nettoyage, Audiveris ne reconnaissait que 4 mesures sur 13 ; avec, les 13 mesures et le 6/8 sont reconnus.
- `render.py` : music21. Sépare les portées à deux voix mesure par mesure (voix la plus aiguë en haut) ou éclate les accords (note haute / note basse) ; écarte les portées d'accompagnement (nom piano/orgue… ou accords de 3 notes et plus) ; trie les voix par hauteur moyenne ; nomme S/A/T/B s'il y en a 4 ; tempo par défaut 90 à la noire en 6/8, 9/8, 12/8, sinon 72 ; FluidSynth + ffmpeg → `<voix>.mp3`, `<voix>_travail.mp3` (voix en avant, autres en fond), `tutti.mp3`, `score.musicxml`, `manifest.json` (noms de notes en français). Affiche `Voix i/n : …` (utilisé pour la progression).

## État au moment de la reprise
- L'installation et la compilation Angular ont réussi.
- **Problème à corriger en premier** : à la question « Serveur », l'utilisateur a saisi `http://localhost:3000`, ce qui donne `getaddrinfo ENOTFOUND http`. Correction :
  `sed -i '' 's#@http://localhost:3000:#@localhost:#' .env`, puis `node /tmp/pupitre-pgtest.cjs` (si le fichier existe encore), puis `npm run serve`.
- Vérifié le 24/10/2026 dans le navigateur : envoi de plusieurs photos, affichage OSMD (import corrigé), lecture audio et curseur synchronisé.
- Lancer avec `PATH=/usr/local/bin:$PATH` si le terminal est resté sur le Node v20 de nvm.

## Lecture musicale (render.py, partitions lues par OMR)
- Noms de portées ignorés (Audiveris nomme « Piano » toute accolade) ; voix dans l'ordre de la page (S, A, T, B).
- Octaves corrigées par tessiture (centres La4, Mi4, La3, Ré3) ; mesures égalisées entre voix ; couplet de soliste versé dans la voix haute.
- Armures harmonisées : la plus chargée (lue au moins deux fois) vaut pour toutes les portées.
- Banc d’essai du 24/10/2026 : 96 % de notes justes (81 % avant), 24/24 cas en 4 voix.

## Versions installables (branche feat/bureau, 24/10/2026)
- **Bureau (Windows / Mac)** : `desktop/` (Electron 44). Serveur intégré sur 127.0.0.1, stockage fichiers dans Documents/Pupitre (`STORE=files`, sans PostgreSQL), moteur PyInstaller (`engine/pupitre-engine.spec`, entrée `engine/pupitre_engine.py`), Audiveris 5.11 embarqué. Plus de fluidsynth/ffmpeg/pdftoppm : TinySoundFont + lameenc + pypdfium2.
- **Licences** : `licence/` (Ed25519, liée à l'identifiant de machine). Outil AIT : `npm run licence -- creer …`. Clé privée et clé Android dans `~/.pupitre-ait` (jamais dans Git). Guide : `docs/DISTRIBUTION.md`.
- **Mobile (Android / iOS)** : Capacitor 8 (`android/`, `ios/`), même interface en mode lecteur (`IS_PLAYER`, `?lecteur` dans un navigateur) : importe les packs `.pupitre` exportés par l'ordinateur (`GET /api/scores/:id/pack`), stockés en IndexedDB. Photo de partition depuis le téléphone : envoyée au **serveur de lecture en ligne** (`ACCES_EN_LIGNE=1` : codes d'accès PUPA1 par chorale via `npm run licence -- acces`, partitions séparées par `owner`, CORS), qui renvoie le pack. Image Docker (`Dockerfile`, `deploy/`), testée et publiée par `.github/workflows/serveur.yml` sur ghcr.io/palmdaniel/pupitre-serveur. Sans `ACCES_EN_LIGNE`, comportement local inchangé. **En ligne sur Vercel** : https://pupitre-lecture.vercel.app (`Dockerfile.vercel`, `LECTURE_DIRECTE=1` : `/api/lire` renvoie le pack dans la réponse, sans stockage ; HOME dans /tmp ; libgtk-3 requise par Audiveris au démarrage). Vercel CLI : `vercel` (nvm) ou `~/pupitre/outils/node_modules/.bin/vercel`.
- **Administration** : registre Neon (`DATABASE_URL` sur Vercel, `server/admin.ts`), `/api/checkin` (bureau : démarrage + 10 min, 30 jours hors ligne au plus, `desktop/src/licence-state.ts`), `/api/admin/*` avec jeton PUPADM1 signé par la clé AIT ; tableau de bord dans l'Espace AIT (`src/app/features/ait/ait-dashboard.ts`).
- **Construction** : GitHub Actions `.github/workflows/installateurs.yml` (exe, dmg Intel et Apple Silicon) et `mobile.yml` (APK, compilation iOS de contrôle). Étiquette `v*` = Release.
- Polices Sora et Manrope intégrées (`@fontsource-variable`), plus de Google Fonts : tout fonctionne hors ligne.

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
