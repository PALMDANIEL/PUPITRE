#!/usr/bin/env bash
# Test de fumée du moteur et de homr tels qu'ils seront livrés (exécutables PyInstaller), sur la machine de
# construction (Windows, Mac Intel, Mac Apple Silicon) : lit un petit chœur à 4 voix (Bach, domaine public),
# voix par voix, puis crée l'audio. Sans lui, un défaut d'empaquetage (DLL, fichier de données, modèles absents)
# ne se verrait qu'au premier lancement chez le client.
set -euo pipefail
ext=""; [ "${RUNNER_OS:-}" = "Windows" ] && ext=".exe"
engine="$PWD/engine/dist/pupitre-engine/pupitre-engine$ext"
export HOMR_BIN="$PWD/engine/dist/pupitre-homr/pupitre-homr$ext"
work="${RUNNER_TEMP:-/tmp}/test-moteur"
rm -rf "$work"; mkdir -p "$work"
cp engine/tests/echantillon-4-voix.pdf "$work/source.pdf"

echo "== Lecture voix par voix (homr + RapidOCR, sans Audiveris)"
"$engine" omr "$work/source.pdf" "$work" --disposition satb 2>&1 | tee "$work/lecture.log"
grep -q "Portées lues une à une par homr" "$work/lecture.log" || { echo "::error::homr n'a pas lu les portées (repli sur Audiveris)"; exit 1; }
test -s "$work/partition.musicxml" || { echo "::error::aucune partition produite"; exit 1; }

echo "== Création de l'audio"
"$engine" render "$work/partition.musicxml" "$work/audio" --timbre choeur --omr 2>&1 | tail -3
test -s "$work/audio/tutti.mp3" || { echo "::error::aucun audio produit"; exit 1; }
echo "Test de fumée réussi"
