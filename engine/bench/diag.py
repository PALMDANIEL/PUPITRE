"""
Familles d'erreurs du banc d'essai, pour corriger par famille plutôt que cas par cas.
Aligne chaque voix lue sur la vraie (truth.json) et classe chaque écart :
  alt (±1 demi-ton : armure, altération), oct (±12), cle (±19 à 22 : sol ↔ fa), deg (±2 à 5 : ligne ou interligne),
  autre, manq (note oubliée), ajout (note inventée).
Usage : <python du moteur> diag.py <dossier_corpus> [filtre]   (après run_bench.py, qui laisse partition.* dans chaque cas)
"""
import collections, json, pathlib, sys

import run_bench

NAMES = ["Soprano", "Alto", "Ténor", "Basse"]


def align(got, want):
    """Opérations qui changent la voix lue en la vraie : ("sub", écart en demi-tons), ("ajout", 0), ("manq", 0)."""
    n, m = len(got), len(want)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i - 1][j] + 1, D[i][j - 1] + 1, D[i - 1][j - 1] + (got[i - 1] != want[j - 1]))
    i, j, ops = n, m, []
    while i or j:
        if i and j and D[i][j] == D[i - 1][j - 1] + (got[i - 1] != want[j - 1]):
            if got[i - 1] != want[j - 1]:
                ops.append(("sub", got[i - 1] - want[j - 1]))
            i, j = i - 1, j - 1
        elif i and D[i][j] == D[i - 1][j] + 1:
            ops.append(("ajout", 0))
            i -= 1
        else:
            ops.append(("manq", 0))
            j -= 1
    return ops


def family(op, d):
    if op != "sub":
        return op
    a = abs(d)
    if a == 1:
        return "alt"
    if a in (11, 12, 13, 24):
        return "oct"
    if 19 <= a <= 22:
        return "cle"
    if 2 <= a <= 5:
        return "deg"
    return "autre"


def main(corpus, filt=""):
    total = collections.Counter()
    for case in sorted(pathlib.Path(corpus).iterdir()):
        if not case.is_dir() or case.name.startswith("_") or filt not in case.name:
            continue
        part = next(case.glob("partition.*"), None)
        tf = case / "truth.json"
        if not part or not tf.exists():
            continue
        truth = json.loads(tf.read_text(encoding="utf-8"))
        try:
            voices = run_bench.read_voices(part)
        except Exception as e:  # noqa: BLE001
            print(f"{case.name:32} séparation impossible : {e}")
            continue
        fams, per = collections.Counter(), []
        for i, name in enumerate(NAMES):
            got = voices[i] if len(voices) == 4 else []
            c = collections.Counter(family(op, d) for op, d in align(got, truth[name]))
            fams += c
            per.append(f"{name[0]}{100 - 100 * sum(c.values()) // max(len(truth[name]), 1):3d}")
        total += fams
        print(f"{case.name:32} {len(voices)}v  {' '.join(per)}  " + " ".join(f"{k}:{v}" for k, v in fams.most_common()))
    print("\nTotal :", " ".join(f"{k}:{v}" for k, v in total.most_common()))


if __name__ == "__main__":
    main(*sys.argv[1:])
