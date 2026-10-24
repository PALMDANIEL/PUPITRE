# Banc d'essai de lecture

Mesure la justesse de la chaîne complète (nettoyage → Audiveris → séparation des voix) sur des chorals dont on connaît les notes.

```bash
~/pupitre/bench-venv/bin/python make_corpus.py ~/pupitre/bench-corpus 6
~/pupitre/engine/.venv/bin/python3 run_bench.py ~/pupitre/bench-corpus -j 3
```

`--reuse` réutilise les lectures Audiveris déjà faites (pour itérer vite sur `render.py`).
Une vraie partition se teste en la copiant dans `<corpus>/reel-nom/source.pdf` (sans `truth.json` : seules les tessitures sont affichées).

Résultats du 24/10/2026 (6 chorals × 2 mises en page × net/photo) : 81 % → 94 % de notes justes, 22/24 → 24/24 cas en 4 voix.
