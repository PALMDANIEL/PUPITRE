"""
Vérification guidée : les mesures signalées « à vérifier » (fiabilite.json, notes en orange) attrapent-elles les
erreurs ? Pour chaque copie lue (run_bench.py) qui a sa bonne réponse (truth.json) :
  - part des mesures signalées ;
  - notes fausses dans les mesures signalées et dans les autres (celles que le chef de chœur ne regarderait pas) ;
  - copies sans fiabilite.json : lecture jamais comparée à une seconde, aucune mesure signalée.
Une note fausse = une opération de l'alignement de diag.py (note changée, oubliée ou inventée), rangée dans la mesure de
la note lue (d'une voisine pour une note oubliée). Mesures comptées par leur rang dans la voix (1, 2, …), comme
arbitre.py numérote a_verifier.

  <python du moteur> verification.py <dossier lu> [filtre]
"""
import collections, json, pathlib, sys

import diag
import run_bench

def errors_by_measure(part_file, truth):
    """{rang de mesure: notes fausses}, nombre de notes de la bonne réponse, nombre de mesures lues."""
    from music21 import converter, stream
    import render
    voices = render.extract_voices(converter.parse(str(part_file)), trust_names=render.is_exact(part_file),
                                   systems=render.page_systems(part_file))
    wanted = [k for k in truth if not k.startswith("_")]
    want_total = sum(len(truth[n]) for n in wanted)
    bad = collections.Counter()
    measures = max((len(list(v.getElementsByClass(stream.Measure))) for v in voices), default=0)
    # voix appariées comme run_bench.run_case (par leur rang : la note du banc est la même)
    melody = wanted == ["Soprano"]
    standard = set(wanted) <= set(run_bench.NAMES)
    for i, name in enumerate(run_bench.NAMES if standard else wanted):
        if name not in truth:
            continue
        if melody:
            v = voices[0] if i == 0 and voices else None
        elif standard:
            v = voices[i] if i < len(voices) and len(voices) == 4 else None
        else:
            v = voices[i] if i < len(voices) and len(voices) == len(wanted) else None
        if v is None:
            bad[0] += len(truth[name])  # voix perdue ou voix en trop : erreur de structure, aucune mesure ne la porte
            continue
        rows = list(v.getElementsByClass(stream.Measure))
        where = {id(m): k + 1 for k, m in enumerate(rows)}
        notes = []
        for m in rows:
            for n in m.recurse().notes:
                if n.pitches and not run_bench.held(n):
                    notes.append((int(max(n.pitches, key=lambda q: q.ps).midi), where[id(m)]))
        got = [p for p, _k in notes]
        for op, _d, i2, _j in diag.align(got, truth[name], where=True):
            k = notes[min(i2, len(notes) - 1)][1] if notes else 0
            bad[k] += 1
    return bad, want_total, measures


def main(root, filt=""):
    root = pathlib.Path(root)
    tot = collections.Counter()
    rows = []
    for case in sorted(p for p in root.iterdir() if p.is_dir() and filt in p.name):
        truth_f = case / "truth.json"
        part = next((case / n for n in ("partition.musicxml", "partition.mxl") if (case / n).exists()), None)
        if not truth_f.exists() or part is None:
            continue
        truth = json.loads(truth_f.read_text(encoding="utf-8"))
        try:
            bad, notes, measures = errors_by_measure(part, truth)
        except Exception as e:  # noqa: BLE001
            print(f"{case.name} : {type(e).__name__} {e}", file=sys.stderr)
            continue
        fia = case / "fiabilite.json"
        flagged = set()
        if fia.exists():
            flagged = {int(k) for k in json.loads(fia.read_text(encoding="utf-8")).get("a_verifier", {})}
        kind = "signalee" if fia.exists() else "non controlee"
        err = sum(bad.values())
        in_flag = sum(c for k, c in bad.items() if k in flagged)
        structural = bad.get(0, 0)
        hidden = err - in_flag
        tot[kind, "copies"] += 1
        tot[kind, "notes"] += notes
        tot[kind, "erreurs"] += err
        tot[kind, "dans signalees"] += in_flag
        tot[kind, "cachees"] += hidden
        tot[kind, "structure"] += structural
        tot[kind, "mesures"] += measures
        tot[kind, "mesures signalees"] += len(flagged)
        rows.append((case.name, kind, notes, err, in_flag, hidden, structural, measures, len(flagged)))
    for r in rows:
        print(f"{r[0]:48s} {r[1]:13s} notes {r[2]:4d} fausses {r[3]:4d} (signalées {r[4]:3d}, cachées {r[5]:4d}, "
              f"structure {r[6]:3d}) mesures {r[7]:3d}, signalées {r[8]:3d}")
    print()
    for kind in ("signalee", "non controlee"):
        n = tot[kind, "notes"]
        if not tot[kind, "copies"]:
            continue
        print(f"{kind:13s} : {tot[kind, 'copies']} copies, {n} notes ; fausses {tot[kind, 'erreurs']} "
              f"({100 * tot[kind, 'erreurs'] / max(n, 1):.2f} %) ; dans des mesures signalées {tot[kind, 'dans signalees']} ; "
              f"cachées (mesures non signalées) {tot[kind, 'cachees']} ({100 * tot[kind, 'cachees'] / max(n, 1):.2f} % des notes, "
              f"dont structure {tot[kind, 'structure']}) ; mesures signalées {tot[kind, 'mesures signalees']}/{tot[kind, 'mesures']}")


if __name__ == "__main__":
    main(*sys.argv[1:])
