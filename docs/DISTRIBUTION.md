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
Accès : le lien *Espace AIT* n'apparaît (dans *À propos*) que sur un téléphone qui a la clé AIT. Pour la première importation, **touchez 7 fois le logo AIT** de la page *À propos*. PIN de 6 à 8 chiffres ; après 3 PIN faux, attente de 30 s, puis doublée à chaque erreur (jusqu'à 1 h).
Sur votre téléphone : *Espace AIT* → onglet **Tableau de bord** (la clé AIT signe chaque demande, valable 9 minutes).
- Ordinateurs et codes de chorale par client : en ligne (moins de 15 min), dernière connexion, système, version, photos lues.
- **Désactiver / Réactiver** un ordinateur ou un code, ou **tout un client** ; motif facultatif ; journal des événements.
- Registre : base PostgreSQL Neon (`pupitre_bd`, Francfort), variable `DATABASE_URL` du projet Vercel (tables `ait_items`, `ait_events`).
- Chez le client, Pupitre se signale au démarrage puis toutes les 10 minutes (`POST /api/checkin`).
  Désactivé : il se ferme et affiche le motif. **Sans Internet pendant 30 jours** : il demande une connexion de quelques secondes.

## Vente en ligne (Orange Money, Moov Money)
Le client paie lui-même sur **https://pupitre-lecture.vercel.app/acheter** ; la licence ou le code est créé et remis aussitôt.
- **Ordinateur** : fenêtre d'activation › *Acheter une licence* (l'identifiant de l'ordinateur est déjà rempli) ;
  la licence s'installe toute seule dès le paiement reçu. *Renouveler en ligne* : menu *Licence…*, page *À propos*,
  ou l'alerte 30 jours avant la fin ; la nouvelle date arrive à la prochaine vérification (10 min au plus).
- **Téléphone** : *Réglages du serveur de lecture* › *Acheter un code pour la chorale* ; sous « Mes chants », *Renouveler* :
  les téléphones de la chorale reçoivent le code prolongé tout seuls.
- Un renouvellement prolonge à partir de la fin actuelle (ou d'aujourd'hui si elle est passée). Numéros vendus : `AIT-2026-V0001`, `ACC-2026-V0001`.
- **Tarifs** : Espace AIT › *Tableau de bord* › *Ventes en ligne* (une formule cochée avec un prix apparaît sur la page d'achat). Ventes du mois et total au même endroit.
- **Clé de vente** (`npm run licence -- cle-vente`) : distincte de la clé AIT, elle ne sert qu'à signer ce qui est payé ; clé publique
  `licence/cle-vente.pem` dans l'application, clé privée `~/.pupitre-ait/vente-privee.pem` et sur le serveur (`VENTE_CLE_PRIVEE`, en base64).
  Le serveur refuse tout texte signé par elle qu'il n'a pas vendu, et elle ne permet pas d'administrer.
- **Deux moyens de paiement**, au choix du client sur la page d'achat :
  - **Transfert au numéro d'AIT** (gratuit, sans agrégateur) : la page affiche le montant exact et les numéros
    (`PAIEMENT_DIRECT_ORANGE`, par défaut 77 41 91 06 ; `PAIEMENT_DIRECT_MOOV`, par défaut 73 63 08 82 ; `PAIEMENT_DIRECT=0` pour fermer),
    le client envoie l'argent puis recopie la **référence du SMS**. Au tableau de bord, *Paiements à confirmer* : comparez avec le SMS
    de votre opérateur, puis **Confirmer** (la licence ou le code part aussitôt) ou **Refuser** (motif montré au client).
    Une référence ne peut servir qu'une fois. **Alerte sonore** (carillon) et vibration à chaque nouveau paiement, tant que le tableau
    de bord est ouvert (vérification toutes les 20 secondes) ; case à cocher et bouton *Tester le son*.
  - **LigdiCash** (automatique, compte marchand avec IFU et RCCM) : `LIGDICASH_API_KEY`, `LIGDICASH_AUTH_TOKEN`, `LIGDICASH_MODE=live`
    pour encaisser pour de vrai. Le serveur redemande toujours l'état de la facture à LigdiCash (montant vérifié) avant de remettre quoi que ce soit.
- Dans tous les cas : `VENTE_CLE_PRIVEE` sur le serveur. Sans moyen de paiement, la page d'achat affiche « bientôt disponible ».

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

## Voix chantées (essai)
Sonorité *Voix chantées* (table de mixage › *Tempo et sonorité*), version de bureau seulement : chaque note est chantée
sur sa syllabe, à sa hauteur et pour sa durée exactes (`engine/chant.py` : Piper prononce la syllabe, Praat règle la hauteur,
la voyelle est tenue jusqu'à la fin de la note, vibrato léger, effet de petit ensemble). Trois chanteurs par pupitre (deux sur le serveur en ligne, `CHANT_ENSEMBLE`), voix de femme pour les voix
hautes, d'homme pour les voix basses ; hauteur vivante (glissés, vibrato variable), nuances, respirations. Paroles : celles de la partition (MusicXML, MuseScore), modifiables voix par voix
(« Sain-te Ma-ri-e », « _ » pour tenir une syllabe) ; langues : français, latin d'église, anglais, mooré, dioula
(ces deux-là prononcés à partir de la voix française : l'accent reste). Les voix (~140 Mo) sont téléchargées au premier
usage dans le dossier de l'application (`VOIX_DIR`, environ 220 Mo). Compter quelques minutes de calcul par chant.
Dépendances : `engine/requirements-chant.txt` (installées par la construction des installateurs, pas sur le serveur en ligne).

## Composants tiers

Livrés dans le dossier `licences-tierces` de l'installation : Audiveris (GNU AGPL v3, programme distinct appelé
sans modification), banque de sons GeneralUser GS, music21, OpenCV, PDFium, TinySoundFont, LAME, Electron…
Voix chantées : Piper (GNU GPL v3, avec espeak-ng), onnxruntime (MIT), Praat/parselmouth (GNU GPL v3) ;
voix téléchargées au premier usage, SIWIS et MLS (CC BY 4.0), UPMC « Pierre » (CC BY-SA 4.0), créditées dans *À propos*.
Le contrat de licence d'utilisation (`desktop/assets/contrat-licence.txt`) est un modèle à faire relire par un juriste.

## Développement

- Application de bureau en mode développement : `cd desktop && npm start` (utilise le moteur Python du venv et
  l'Audiveris installé sur le Mac).
- Lecteur mobile dans un navigateur : ouvrir `http://localhost:3000/?lecteur`.
- Projets natifs : `npx cap sync` après `npx ng build` ; `npx cap open android` / `npx cap open ios`
  (Android Studio / Xcode nécessaires).
