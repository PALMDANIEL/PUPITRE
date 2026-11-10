"""
Familles d'erreurs du banc d'essai, pour corriger par famille plutôt que cas par cas.
Aligne chaque voix lue sur la vraie (truth.json) et classe chaque écart :
  alt (±1 demi-ton : armure, altération), oct (±12), cle (±19 à 22 : sol ↔ fa), deg (±2 à 5 : ligne ou interligne),
  autre, manq (note oubliée), ajout (note inventée).
Usage : <python du moteur> diag.py <dossier_corpus> [filtre] [--detail morceau,morceau]
(après run_bench.py, qui laisse partition.* dans chaque cas). --detail : pour les copies dont le nom contient l'un des
morceaux, chaque erreur avec sa mesure (« A m5 Fa4→Fa#4 » : lu Fa4 au lieu de Fa#4 ; « -Mi4 » oubliée ; « +Ré5 » en trop).
"""
import collections, json, pathlib, sys

import run_bench

NAMES = ["Soprano", "Alto", "Ténor", "Basse"]


def align(got, want, where=False):
    """Opérations qui changent la voix lue en la vraie : ("sub", écart en demi-tons), ("ajout", 0), ("manq", 0).
    where=True : (op, écart, indice de la note lue, indice de la vraie) à la place."""
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
                ops.append(("sub", got[i - 1] - want[j - 1], i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i and D[i][j] == D[i - 1][j] + 1:
            ops.append(("ajout", 0, i - 1, j))
            i -= 1
        else:
            ops.append(("manq", 0, i, j - 1))
            j -= 1
    return ops[::-1] if where else [o[:2] for o in ops]


STEPS = ["Do", "Do#", "Ré", "Mib", "Mi", "Fa", "Fa#", "Sol", "Sol#", "La", "Sib", "Si"]


def name(midi):
    return f"{STEPS[midi % 12]}{midi // 12 - 1}"


def detail(part, truth):
    """Chaque erreur de chaque voix, avec la mesure de la note lue (ou de sa voisine pour une note oubliée)."""
    from music21 import converter
    import render
    voices = render.extract_voices(converter.parse(str(part)), trust_names=False)
    lines = []
    for k, v in enumerate(voices[:4]):
        notes = [(int(max(n.pitches, key=lambda q: q.ps).midi), n.measureNumber) for n in v.recurse().notes if n.pitches]
        got = [m for m, _b in notes]
        want = truth[NAMES[k]]
        out = []
        for op, d, i, j in align(got, want, where=True):
            bar = notes[min(i, len(notes) - 1)][1] if notes else "?"
            if op == "sub":
                out.append(f"m{bar} {name(got[i])}→{name(want[j])}")
            elif op == "manq":
                out.append(f"m{bar} -{name(want[j])}")
            else:
                out.append(f"m{bar} +{name(got[i])}")
        if out:
            lines.append(f"  {NAMES[k][0]} ({len(out)}) : " + ", ".join(out[:30]) + (" …" if len(out) > 30 else ""))
    return lines


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


def main(corpus, filt="", *rest):
    show = rest[rest.index("--detail") + 1].split(",") if "--detail" in rest and rest.index("--detail") + 1 < len(rest) else []
    if filt == "--detail":
        filt, show = "", (rest[0].split(",") if rest else [])
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
        if any(m and m in case.name for m in show) and len(voices) == 4:
            try:
                print("\n".join(detail(part, truth)))
            except Exception as e:  # noqa: BLE001
                print(f"  détail impossible : {e}")
    print("\nTotal :", " ".join(f"{k}:{v}" for k, v in total.most_common()))


if __name__ == "__main__":
    main(*sys.argv[1:])
