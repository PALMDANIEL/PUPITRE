#!/bin/zsh
# Répertoire commun d'AIT sur le VPS : chaque PDF gravé (MuseScore, Sibelius, Finale…) d'un dossier est lu exactement
# sur le Mac, puis l'ensemble est envoyé au serveur Pupitre en une seule connexion SSH. Les copies photographiées de ces
# chants seront ensuite reconnues et rendues exactes. Les partitions ne vont jamais dans Git.
#   zsh deploy/envoyer-repertoire.sh [dossier des PDF]      (par défaut : ~/Downloads/PARTITION)
#   SANS_ENVOI=1 zsh deploy/envoyer-repertoire.sh           (prépare seulement, sur le Mac)
set -euo pipefail
SRC=${1:-$HOME/Downloads/PARTITION}
REPO=${0:A:h:h}
PY=$HOME/pupitre/engine/.venv/bin/python3
WORK=$(mktemp -d)
trap 'rm -rf "${WORK:?}"' EXIT  # dossier de travail effacé même si l'envoi échoue
mkdir -p "$WORK/commun"
n=0; skip=0; dup=0; review=()
for pdf in "$SRC"/*.pdf(N); do
  title=$(basename "$pdf" .pdf | sed -E 's/( ?\([0-9]\))+$//; s/-[0-9]$//; s/ copie$//')  # « Laetamini 1.pdf » : copie du fichier
  name=$("$PY" -c 'import re, sys, unicodedata
s = "".join(c for c in unicodedata.normalize("NFKD", sys.argv[1]) if not unicodedata.combining(c)).lower()
print(re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60])' "$title")
  [[ -z "$name" ]] && continue
  base=$name; k=1
  while [[ -e "$WORK/commun/$name.musicxml" ]]; do k=$((k + 1)); name="$base-$k"; done
  if PYTHONHASHSEED=0 "$PY" "$REPO/engine/pdf_vectoriel.py" "$pdf" "$WORK/$name.musicxml" > /dev/null 2>&1; then
    out=$(PYTHONHASHSEED=0 "$PY" "$REPO/engine/repertoire.py" ajouter "$WORK/$name.musicxml" "$WORK/commun" "$name" "$title" --pdf "$pdf" 2>&1 || true)
    if [[ "$out" == *"aux voix de durées différentes"* ]]; then
      # une à trois mesures aux voix de durées différentes : gardé dans la bibliothèque d'AIT (bien meilleur que la lecture
      # d'une photo pour les chorales), signalé à revoir ; la règle stricte vaut pour les ajouts automatiques des chorales
      out=$(PUPITRE_REPERTOIRE_PDF_STRICT=0 PYTHONHASHSEED=0 "$PY" "$REPO/engine/repertoire.py" ajouter "$WORK/$name.musicxml" "$WORK/commun" "$name" "$title" --pdf "$pdf" 2>&1 || true)
      [[ "$out" == *"Ajouté"* ]] && review+=("$name")
    fi
    rm -f "$WORK/$name.musicxml"
    if [[ "$out" == *"Déjà dans le répertoire"* ]]; then dup=$((dup + 1))
    elif [[ "$out" == *"incohérente"* ]]; then skip=$((skip + 1))
    else n=$((n + 1)); fi
  else
    skip=$((skip + 1))  # scan, photo, ou police musicale illisible : pas une version exacte
  fi
done
echo "$n chant(s) lus exactement, $dup en double, $skip PDF laissé(s) de côté (scans, polices illisibles ou lecture incohérente)."
(( ${#review} )) && echo "À revoir par AIT (une à trois mesures aux voix de durées différentes) : ${review[*]}"
(( n > 0 )) || { echo "Rien à envoyer."; exit 1; }
[[ -n "${SANS_ENVOI:-}" ]] && { trap - EXIT; echo "Répertoire préparé (non envoyé) : $WORK/commun"; exit 0; }
# sans les attributs étendus du Mac (com.apple.provenance…) : docker cp refuse de les recopier
# (« lsetxattr … operation not supported ») et l'envoi s'arrête
COPYFILE_DISABLE=1 tar --no-xattrs --no-mac-metadata -C "$WORK" -cf - commun | ssh -o ConnectTimeout=20 ubuntu@102.204.24.173 '
  set -e
  c=$(sudo docker ps --filter "label=com.docker.compose.service=pupitre" --format "{{.Names}}" | head -1)
  sudo docker exec "$c" mkdir -p /data/repertoire
  sudo docker cp - "$c":/data/repertoire
  echo "Répertoire commun du serveur : $(sudo docker exec "$c" sh -c "ls /data/repertoire/commun/*.musicxml | wc -l") chant(s)."'
