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
- **Vente en ligne** : transfert direct au numéro d'AIT confirmé au tableau de bord (alerte sonore) et LigdiCash (`server/passerelles.ts`), vente dans `server/paiement.ts` ( page `server/boutique/acheter.html` sur `/acheter`), tables `ait_prices`, `ait_orders`, `ait_counters` ; licences et codes signés par la **clé de vente** (`licence/cle-vente.pem`, privée dans `VENTE_CLE_PRIVEE`), acceptée à côté de la clé AIT sauf pour l'administration ; renouvellements remis par `/api/checkin` (champ `renewal`) et `/api/paiement/renouvellement` ; tarifs et ventes dans le tableau de bord.
- **Construction** : GitHub Actions `.github/workflows/installateurs.yml` (exe, dmg Intel et Apple Silicon) et `mobile.yml` (APK, compilation iOS de contrôle). Étiquette `v*` = Release.
- Polices Sora et Manrope intégrées (`@fontsource-variable`), plus de Google Fonts : tout fonctionne hors ligne.

## Voix chantées (branche feat/voix-chantees, 26/10/2026)
- Sonorité `chant` (en plus de `choeur` et `piano`) : `engine/chant.py` (Piper : SIWIS femme, UPMC « Pierre » homme ; Praat/parselmouth pour la hauteur ; voyelle tenue par grains calés sur la période ; vibrato par ligne à retard). `render.py --timbre chant --langue fr|la|en|mos|dyu --paroles paroles.json`.
- Paroles : manifeste `voices[].lyrics` (lues dans la partition) et `voices[].sung` (notes après liaisons) ; saisie dans la table de mixage, enregistrée dans `ScoreMeta.paroles` / `langue`.
- Voix téléchargées par le serveur au premier usage (`server/voix.ts`, `VOIX_DIR`, ~/pupitre/voix en local, userData/voix sur le bureau). Refusé en lecture directe (Vercel).
- Souffle et sifflements (27/10/2026, suite) : la voix Piper porte déjà 62 % de souffle au-dessus de 2 kHz → `_harmonic_clean` (STFT 93 ms sur la voyelle à hauteur fixe : hors harmoniques −26 dB au-dessus de 1 kHz, −18 dB dessous, retire aussi les sous-harmoniques « éraillés ») ; `_enrich` (harmoniques 2–4 de Tchebychev, dosées pour ramener la fondamentale à 60 % : plus de timbre « flûte ») ; consonnes soufflées repérées (`_is_fricative`, centre > 1,8 kHz) : sans renfort, aigus −12 dB dès 2,2 kHz, 8 dB sous la voyelle, 90/80 ms au plus. Mesuré : HNR des aigus 4,9 → 16 dB, sifflantes 0, flûte 0, aucune note octaviée (66 syllabes).
- Sifflements supprimés (27/10/2026) : rééchantillonnage 22→44 kHz par FFT (l'interpolation linéaire créait des images au-dessus de 11 kHz et un ton vers 13 kHz), passe-bas 10,5 kHz au mastering, dé-esseur (`mixage.deess`, aigus > 4,5 kHz ramenés à −4/−6 dB du médium), renfort des consonnes limité au médium, respirations sans aigus. Mesuré : images −23 → −70 dB, pire sifflante +16 → −6 dB.
- Ensemble (27/10/2026) : `chant.SINGERS` = 3 chanteurs par pupitre (femmes SIWIS + MLS 54, 14 ; hommes UPMC Pierre + MLS 28, 117, choisis sur 125 pour la clarté), décalages ±11 ms et ±7 cents, notes des choristes contrôlées (`in_tune`, sinon silence), hauteur vivante `_express` (glissé legato, attaque par en dessous, dérive, vibrato variable), nuances (+0,13 dB/demi-ton), respirations avant les phrases. `CHANT_ENSEMBLE=2` sur Vercel.
- Son (`engine/mixage.py`, numpy seul) : niveau réglé par syllabe, consonnes +3,5 dB, composante continue retirée après la resynthèse Praat (sinon les notes aiguës sortaient à −15 dB), égaliseur à phase nulle, compresseur doux, voix à −18 dB puis fichiers à −16 dB, stéréo (S/T à gauche, A/B à droite), petite salle, limiteur à −1 dB. Mesuré : voix au même niveau, ≤ 1,8 dB d'écart entre notes.
- Moteur autonome : `engine/requirements-chant.txt` ; espeak-ng refuse les chemins longs → copie dans `~/.pupitre-espeak` si besoin ; `ESPEAK_DATA_PATH` réglé avant l'import de piper.

- Chœur réel (27/10/2026) : sonorité `reel` (`engine/choeur.py`, `--voyelle ah|oo`), 79 enregistrements mono 6 s (`engine/choeur/`, 42 Mo, VocalSet via epic-choir, CC BY 4.0), `index.json` = plage, centre, `start` (chœur posé), `tune` (cents) ; rééchantillonnage FFT ≤ 1 demi-ton, notes liées, boucle fondue > 6 s. Mesuré : justesse ≤ 7 cents, ≤ 2,9 dB entre notes. `ScoreMeta.voyelle`.

- Audibilité (27/10/2026) : toutes les sonorités passent par `mixage.finish` → −14 LUFS (BS.1770, `mixage.lufs`), limiteur −1 dB ; Chœur synthé et Piano (TinySoundFont) étaient à −31 et −26 LUFS. `phone_bass` : renfort des harmoniques naturelles 300 Hz–1 kHz (+6 dB × dose selon tessiture, `bass_amount`) et −3 dB sous 140 Hz, pour les téléphones ; égalisation `SYNTH_EQ` (synthé, piano) ; pistes de travail : sa voix ≈ 12 dB devant, au centre, les autres sur les côtés (vélocité 27 pour le synthé). Chœur réel : réverbération ajoutée réduite (0,06).

- Noms des voix (27/10/2026) : OCR Audiveris activé (`engine/tessdata/fra.traineddata` complet — le mode « legacy » d'Audiveris refuse tessdata_fast). `render.py` : `merge_named_parts` (portées de même nom réunies ; mesures à deux voix d'une portée de rôle → chœur du même registre, sinon voix du haut), `staff_names`/`pretty_name`/`ACCENTS`, `share_lyrics` (paroles écrites une fois entre S et A), `name_by_range`, `voice_id` (identifiants = noms). `chant.clean_syllable` nettoie les paroles lues (« 1a) », « frère(x) », « V0 »). Renommage : `PATCH /api/scores/:id/voix/:voice` (`ScoreMeta.voiceNames`, réappliqué après rendu), `PackStore.renameVoice` sur le téléphone. Couleurs des autres voix : `voiceColor` (hachage du nom).
- FFT rapides (`mixage.fast_len`, `apply_curve`) : une longueur à grand facteur premier rendait chaque transformée ~2 s ; le Cantique complet passait de 10 min à 2 min 53.
- Téléphone, abonnement expiré : `features/packs/renew-access.ts` (bandeau « Renouveler en ligne » sur Mes chants, Photo, Réglages ; code lu par `decodeCode`, même expiré, enregistré quand même) ; `/api/paiement/renouvellement` inscrit au registre un code jamais vu.

- Surveillance des calculs (27/10/2026) : `jobs.run` n'arrête plus à durée fixe ; arrêt seulement sans signe d'avancement pendant `ENGINE_IDLE_MS` (5 min) ou au-delà de `ENGINE_MAX_MS` (1 h) ; sur Vercel (`LECTURE_DIRECTE`), limites courtes gardées avec message clair. Le moteur imprime des signes de vie (`actif:omr` toutes les 20 s, `actif:chant`/`actif:choeur` toutes les 25 notes, `actif:mp3`).

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
