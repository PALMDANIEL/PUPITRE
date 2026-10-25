# Pupitre — distribution et licences

Guide AIT pour fabriquer les installateurs, créer les licences et installer Pupitre chez les chorales.

## Les trois produits

| Produit | Pour qui | Fichier | Licence |
|---|---|---|---|
| **Pupitre pour Windows** | chef de chœur | `Pupitre-x.y.z-Windows.exe` | licence AIT liée à l'ordinateur |
| **Pupitre pour Mac** (Intel / Apple Silicon) | chef de chœur | `Pupitre-x.y.z-Mac-Intel.dmg` / `-Mac-Apple-Silicon-M1-M2-M3-M4.dmg` | licence AIT liée à l'ordinateur |
| **Pupitre mobile** (Android, iOS à venir) | choristes | `Pupitre-x.y.z-android.apk` | gratuit : lecteur des packs |

L'ordinateur lit les partitions (Audiveris + moteur Python embarqués) et crée les voix.
Le téléphone peut aussi **photographier une partition** : la photo est lue par le serveur en ligne AIT
(voir `deploy/LISEZ-MOI.md`), qui renvoie le pack de répétition ; il faut pour cela un **code d'accès** de chorale.
Le téléphone ne lit pas les partitions : il ouvre les **packs de répétition** (`.pupitre`) exportés depuis l'ordinateur
(bouton « Exporter le pack de répétition » sur la page d'une partition), envoyés par WhatsApp.

## Fabriquer les installateurs (GitHub Actions)

Tout se fabrique sur les serveurs de GitHub (un Mac ne peut pas fabriquer la version Windows).

- **Essai** : GitHub › onglet *Actions* › *Installateurs* (ou *Mobile*) › *Run workflow*.
  Les fichiers sont dans *Artifacts*, en bas de la page de l'exécution.
- **Version officielle** : créer une étiquette ; les installateurs sont joints à une *Release* GitHub.

```bash
git tag v1.0.0
```

```bash
git push origin v1.0.0
```

### Secrets GitHub pour signer l'application Android

À faire une seule fois : GitHub › *Settings* › *Secrets and variables* › *Actions* › *New repository secret*.

| Nom | Valeur |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | contenu du fichier `~/.pupitre-ait/android-pupitre.base64.txt` |
| `ANDROID_KEYSTORE_PASSWORD` | mot de passe noté dans `~/.pupitre-ait/android-pupitre.txt` |

Sans ces secrets, l'APK est signé avec une clé de test : il s'installe, mais les mises à jour devront être
désinstallées puis réinstallées.

## Créer une licence

1. Le client installe Pupitre et l'ouvre : la fenêtre d'activation affiche l'**identifiant de son ordinateur**
   (ex. `CAM5-FYCJ-J6AX-DUDE`, bouton *Copier*). Il vous l'envoie.
2. Vous créez la licence :

```bash
npm run licence -- creer --client "Chorale Sainte Cécile" --contact "00226 70 00 00 00" --machine CAM5-FYCJ-J6AX-DUDE --duree 1a
```

   Durées : `1a`, `2a`, `6m`, `30j`… ou `illimitee`. Option `--debut AAAA-MM-JJ`.
3. Vous envoyez au client le fichier `~/.pupitre-ait/licences/AIT-2026-0001.licence` (ou le texte affiché).
   Il le colle ou l'ouvre dans la fenêtre d'activation.

Autres commandes : `npm run licence -- liste` (registre), `npm run licence -- verifier <fichier>`.

Renouvellement : même commande avec la même machine ; le client saisit la nouvelle licence par
*Pupitre › Licence… › Saisir une nouvelle licence* (Windows : *Aide › Licence…*).
Pupitre prévient 30 jours avant l'expiration. Changement d'ordinateur : nouvelle licence pour le nouvel identifiant.

## Créer les licences depuis votre téléphone (Espace AIT)

1. Une seule fois, sur le Mac (dossier `pupitre-plateforme`) :

```bash
npm run licence -- export-mobile
```

2. Sur votre téléphone : Pupitre › *À propos* › tout en bas *Espace AIT (administration)* ›
   *Photographier le QR code*, puis choisir un code PIN. Effacez ensuite le Terminal du Mac (Cmd+K).
3. Ensuite : *Espace AIT* › PIN › *Licence d'ordinateur* (client, identifiant de l'ordinateur, durée)
   ou *Code de chorale*, puis *Envoyer (WhatsApp…)*. Fonctionne sans Internet.

La clé est gardée chiffrée par le PIN ; l'espace se reverrouille quand on le quitte. Les numéros créés au téléphone
sont `AIT-2026-T0001` / `ACC-2026-T0001` (ceux du Mac : `AIT-2026-0001`), registre exportable en CSV
(*Registre › Exporter*). Téléphone perdu : *Retirer la clé* n'est plus possible, mais sans le PIN la clé est illisible.

## Ce que voit le client
- **Ordinateur** : pied de page « Licence AIT-… · jusqu'au … », fiche *Votre licence* dans *À propos*
  (début, fin, jours restants, ordinateur) et alerte sur l'accueil 30 jours avant la fin.
- **Téléphone** : sous « Mes chants », « Abonnement de … : du … au … inclus · N jours restants ».

## Administrer à distance (tableau de bord AIT)
Sur votre téléphone : *Espace AIT* → onglet **Tableau de bord** (la clé AIT signe chaque demande, valable 9 minutes).
- Ordinateurs et codes de chorale par client : en ligne (moins de 15 min), dernière connexion, système, version, photos lues.
- **Désactiver / Réactiver** un ordinateur ou un code, ou **tout un client** ; motif facultatif ; journal des événements.
- Registre : base PostgreSQL Neon (`pupitre_bd`, Francfort), variable `DATABASE_URL` du projet Vercel (tables `ait_items`, `ait_events`).
- Chez le client, Pupitre se signale au démarrage puis toutes les 10 minutes (`POST /api/checkin`).
  Désactivé : il se ferme et affiche le motif. **Sans Internet pendant 30 jours** : il demande une connexion de quelques secondes.

## Codes d'accès au serveur de lecture (photos depuis le téléphone)

```bash
npm run licence -- acces --client "Chorale Sainte Cécile" --duree 1a
```

Adresse du serveur à donner avec le code : **https://pupitre-lecture.vercel.app** (essai gratuit sur Vercel, voir `deploy/LISEZ-MOI.md`).

Le code `PUPA1…` est valable pour toute la chorale (tous ses téléphones) jusqu'à sa date de fin. Les choristes le
collent avec l'adresse du serveur dans *Mes chants › Réglages du serveur de lecture*. Registre :
`~/.pupitre-ait/registre-acces.csv`. Les partitions de chaque chorale sont séparées sur le serveur.

### Le dossier `~/.pupitre-ait` — à sauvegarder

| Fichier | Rôle |
|---|---|
| `licence-privee.pem` | signe les licences. **Secret.** Perdu = impossible d'émettre des licences reconnues |
| `licences/`, `registre.csv` | licences émises |
| `android-pupitre.jks`, `android-pupitre.txt` | signature Android. Perdue = plus de mises à jour possibles de l'app Android |

Copiez ce dossier sur une clé USB chiffrée ou un coffre-fort de mots de passe. Ne le mettez jamais sur GitHub.

## Installer chez le client

Les installateurs ne sont pas encore signés par Apple / Microsoft : un avertissement apparaît la première fois.

- **Windows** : « Windows a protégé votre ordinateur » → *Informations complémentaires* → *Exécuter quand même*.
  L'installation demande d'accepter le contrat de licence.
- **Mac** : vérifier le processeur (menu Apple › *À propos de ce Mac* : « Intel » ou « Puce Apple M… »),
  télécharger le `.dmg` correspondant (la version Intel marche aussi sur les Mac M1…, en plus lent ;
  l'inverse est impossible : icône barrée 🚫). Ouvrir le `.dmg`, glisser Pupitre dans *Applications*.
  Si « l'image disque est endommagée » : éjecter d'abord tout autre volume « Pupitre » déjà ouvert. Au premier lancement, si macOS refuse :
  *Réglages Système › Confidentialité et sécurité* → *Ouvrir quand même*.
- **Android** : ouvrir le fichier `.apk` reçu → autoriser « Installer des applications inconnues » pour l'application
  qui l'ouvre (WhatsApp, Fichiers…) → *Installer*.
- **iPhone** : pas encore disponible ; il faut un compte Apple Developer (99 $/an) pour signer et publier
  (TestFlight ou App Store). Le projet iOS est prêt dans `ios/` et compile dans GitHub Actions.

Les partitions du chef de chœur sont dans **Documents/Pupitre** (menu *Fichier › Ouvrir le dossier des partitions*).

## Composants tiers

Livrés dans le dossier `licences-tierces` de l'installation : Audiveris (GNU AGPL v3, programme distinct appelé
sans modification), banque de sons GeneralUser GS, music21, OpenCV, PDFium, TinySoundFont, LAME, Electron…
Le contrat de licence d'utilisation (`desktop/assets/contrat-licence.txt`) est un modèle à faire relire par un juriste.

## Développement

- Application de bureau en mode développement : `cd desktop && npm start` (utilise le moteur Python du venv et
  l'Audiveris installé sur le Mac).
- Lecteur mobile dans un navigateur : ouvrir `http://localhost:3000/?lecteur`.
- Projets natifs : `npx cap sync` après `npx ng build` ; `npx cap open android` / `npx cap open ios`
  (Android Studio / Xcode nécessaires).
