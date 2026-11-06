# Banc d'essai de lecture

Mesure la justesse de la chaîne complète (nettoyage → Audiveris → séparation des voix) sur des chorals dont on connaît les notes.

```bash
~/pupitre/bench-venv/bin/python make_corpus.py ~/pupitre/bench-corpus 6
~/pupitre/bench-venv/bin/python make_usees.py ~/pupitre/bench-usees 6
~/pupitre/bench-venv/bin/python make_reels.py ~/pupitre/bench-reels 6
~/pupitre/engine/.venv/bin/python3 run_bench.py ~/pupitre/bench-corpus -j 3
~/pupitre/engine/.venv/bin/python3 diag.py ~/pupitre/bench-corpus
```

- `make_corpus.py` : PDF net et photo propre ; `make_usees.py` : photocopie (`copie`) et vieille copie usée (`usee`) ;
  `make_reels.py` : conditions réelles des chorales (`whatsapp`, `sombre`, `penchee`, `floue`, `dense`).
- `diag.py` classe les erreurs par famille (altération, octave, clé, degré, note oubliée ou inventée) : on corrige une
  famille entière, et on vérifie sur tout le banc qu'aucun cas ne baisse.
- `--reuse` réutilise les lectures déjà faites (pour itérer vite sur `render.py` et `coherence.py`).

Une vraie partition se teste en la copiant dans `<corpus>/reel-nom/source.pdf` (sans `truth.json` : seules les
tessitures sont affichées ; avec un `truth.json` {voix: [hauteurs MIDI]}, elle est notée comme les autres).

## Sur GitHub (`.github/workflows/banc.yml`)

Un envoi sur une branche `banc/…` fabrique les copies, les fait lire par le moteur de la branche et par une version de
référence, et compare. Dans le message de l'envoi :
- `[banc: floue,fermee-dense]` : seulement les copies dont le nom contient l'un de ces morceaux ;
- `[env: PUPITRE_SEUIL_FLOU=adaptatif]` : réglages passés au moteur de la branche (pas à la référence) ;
- `[ref: banc/conditions-reelles]` : version de comparaison (branche ou étiquette ; sinon la dernière publiée).

Résultats lisibles sans compte : annotations de la page du circuit (« Lecture », « Détail » par part, « Banc d'essai »
pour le rapport, avec le détail copie par copie quand le banc porte sur 40 copies au plus), ou par l'API anonyme
(60 requêtes par heure : `actions/runs/<id>/jobs`, puis `check-runs/<id du job rapport>/annotations`).

Résultats du 24/10/2026 (6 chorals × 2 mises en page × net/photo) : 81 % → 96 % de notes justes, 22/24 → 24/24 cas en 4 voix.
La dernière ligne courte (une mesure seule), longtemps ignorée par Audiveris, est lue depuis le 05/11/2026 (`omr.STAFF_OPTIONS`).
