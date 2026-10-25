# Serveur de lecture en ligne Pupitre

Le serveur reçoit les photos de partitions envoyées par l'application mobile, lit les notes (Audiveris + moteur
Pupitre) et renvoie un pack de répétition au téléphone. L'écoute se fait ensuite sans Internet.

- Chaque chorale a un **code d'accès** signé par AIT (`npm run licence -- acces …`) ; sans code valide, rien n'est accepté.
- Une chorale ne voit jamais les partitions d'une autre.
- L'image est construite et testée par GitHub Actions (workflow *Serveur*) : `ghcr.io/palmdaniel/pupitre-serveur`.

## Ce qu'il faut

- Un **VPS Linux x86_64** (Ubuntu 24.04 conseillé) : 2 processeurs, 4 Go de mémoire, 40 Go de disque.
  Ordre de prix : 5 à 10 € par mois (Hetzner, OVH, Contabo, Scaleway…). Audiveris ne fonctionne pas sur ARM.
- Un **nom de domaine** (ex. `lecture.ait.bf`) qui pointe vers l'adresse IP du VPS (enregistrement DNS de type A).

## Installation (une seule fois, sur le VPS)

```bash
curl -fsSL https://get.docker.com | sh
```

```bash
mkdir -p ~/pupitre && cd ~/pupitre && curl -fsSLO https://raw.githubusercontent.com/PALMDANIEL/PUPITRE/main/deploy/docker-compose.yml && curl -fsSLO https://raw.githubusercontent.com/PALMDANIEL/PUPITRE/main/deploy/Caddyfile
```

```bash
DOMAINE=lecture.ait.bf docker compose up -d
```

Caddy obtient tout seul le certificat HTTPS. Vérification depuis n'importe quel navigateur :
`https://lecture.ait.bf/api/health` doit afficher `{"ok":true,"online":true,"problems":[]}`.

> Si l'image n'est pas téléchargeable (« denied »), rendez le paquet public une fois :
> GitHub › votre profil › *Packages* › `pupitre-serveur` › *Package settings* › *Change visibility* › Public.

## Donner l'accès à une chorale

Sur votre Mac (dossier `pupitre-plateforme`) :

```bash
npm run licence -- acces --client "Chorale Sainte Cécile" --duree 1a
```

Envoyez aux choristes (WhatsApp) l'adresse `https://lecture.ait.bf` et le code `PUPA1…` affiché.
Dans l'application : *Mes chants › Réglages du serveur de lecture*, coller l'adresse et le code, *Vérifier et enregistrer*.
Codes émis : `~/.pupitre-ait/registre-acces.csv`.

## Entretien

| Action | Commande (dans `~/pupitre` sur le VPS) |
|---|---|
| Mettre à jour vers la dernière version | `docker compose pull && DOMAINE=lecture.ait.bf docker compose up -d` |
| Voir ce qui se passe | `docker compose logs -f pupitre` |
| Redémarrer | `docker compose restart pupitre` |
| Sauvegarder les partitions | `docker run --rm -v pupitre_pupitre-donnees:/data -v $PWD:/sauvegarde ubuntu tar czf /sauvegarde/partitions.tgz /data` |

Les partitions sont lues une à la fois : avec beaucoup de chorales, prendre un VPS plus puissant.
