#!/usr/bin/env bash
# Lance une commande ; en cas d'échec, recopie ses 40 dernières lignes dans une annotation GitHub
# (visible sans être connecté, contrairement aux journaux complets).
#   .github/scripts/journal.sh "Titre" commande arguments…
title="$1"; shift
log="${RUNNER_TEMP:-/tmp}/journal-$RANDOM.log"
set -o pipefail
if ! "$@" 2>&1 | tee "$log"; then
  echo "::error title=$title::$(tail -n 40 "$log" | awk 'BEGIN{ORS="%0A"}{gsub(/%/,"%25");gsub(/\r/,"");print}')"
  exit 1
fi
