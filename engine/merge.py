"""
Assemblage : Audiveris coupe la partition en plusieurs mouvements (clean.mvt1.mxl, clean.mvt2.mxl…)
dès que le nombre de portées change (couplet en solo, par exemple). On les remet bout à bout.

Photocopie abîmée (barres de mesure et accolades coupées entre les portées) : Audiveris prend chaque portée
d'un système pour un système à elle seule, et lirait Soprano, Alto, Ténor, Basse l'un après l'autre.
Les portées d'un même système partagent leurs barres de mesure : leurs mesures ont exactement les mêmes largeurs.
Deux systèmes voisins de la même page dont toutes les largeurs de mesures coïncident sont donc superposés.

Usage : python3 merge.py [--si-utile] <sortie.musicxml> <mvt1.mxl> <mvt2.mxl> ...
  --si-utile : avec un seul mouvement, n'écrit rien (code 3) s'il n'y a aucune portée à superposer.
"""
import copy, sys
from music21 import clef, converter, key, layout, meter, note, stream


def rest_measure(model: stream.Measure) -> stream.Measure:
    m = stream.Measure()
    r = note.Rest(quarterLength=model.barDuration.quarterLength if model.timeSignature else model.highestTime or 4)
    m.append(r)
    return m


def _breaks(m):
    """(nouveau système, nouvelle page) au début de cette mesure."""
    ls = list(m.getElementsByClass((layout.SystemLayout, layout.PageLayout)))
    page = any(isinstance(l, layout.PageLayout) and l.isNew for l in ls)
    return page or any(isinstance(l, layout.SystemLayout) and l.isNew for l in ls), page


def systems_of(mv):
    """Systèmes d'un mouvement, dans l'ordre : (nouvelle page ?, [mesures de chaque portée])."""
    parts = list(mv.parts)
    cuts = []  # découpage lu sur la première portée, appliqué à toutes
    measures = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    for k, m in enumerate(measures[0]):
        new, page = _breaks(m)
        if k == 0 or new:
            cuts.append((k, page))
    out = []
    for j, (start, page) in enumerate(cuts):
        end = cuts[j + 1][0] if j + 1 < len(cuts) else None
        out.append((page, [ms[start:end] for ms in measures]))
    return out


def _widths(staff):
    return [m.layoutWidth for m in staff]


def same_system(a, b):
    """Mêmes barres de mesure : même nombre de mesures (au moins 2) et mêmes largeurs, à 2 % près."""
    wa, wb = _widths(a[1][0]), _widths(b[1][0])
    if b[0] or len(wa) < 2 or len(wa) != len(wb) or None in wa or None in wb:
        return False
    return all(abs(x - y) <= max(4.0, 0.02 * x) for x, y in zip(wa, wb))


def stack(systems):
    """Systèmes voisins de la même page partageant leurs barres de mesure : réunis (portées superposées)."""
    out = []
    for sysm in systems:
        if out and same_system(out[-1][-1], sysm):
            out[-1].append(sysm)
        else:
            out.append([sysm])
    return [(group[0][0], [staff for _page, staves in group for staff in staves]) for group in out]


def _with_context(m, orig):
    """Mesure copiée en tête de portée : on lui rend sa clé, son armure et sa mesure (lues dans le contexte d'origine)."""
    for cls in (clef.Clef, key.KeySignature, meter.TimeSignature):
        if not m.getElementsByClass(cls):
            ctx = orig.getContextByClass(cls)
            if ctx is not None:
                m.insert(0, copy.deepcopy(ctx))
    return m


def main(out, sources, only_if_useful=False):
    movements = [converter.parse(s) for s in sources]
    raw = [s for mv in movements for s in systems_of(mv)]
    systems = stack(raw)
    stacked = len(systems) < len(raw)
    if only_if_useful and len(movements) == 1 and not stacked:
        sys.exit(3)
    width = max(len(staves) for _page, staves in systems)
    first = list(movements[0].parts)
    merged = [stream.Part() for _ in range(width)]
    for i, part in enumerate(first[:width]):
        merged[i].partName = part.partName
        merged[i].id = part.id
    number = 0
    for _page, staves in systems:
        count = max(len(s) for s in staves)
        model = staves[0]
        for i in range(width):
            measures = staves[i] if i < len(staves) else []
            for k in range(count):
                if k < len(measures):
                    m = copy.deepcopy(measures[k])
                    if k == 0 and stacked:
                        _with_context(m, measures[k])
                else:
                    m = rest_measure(model[min(k, len(model) - 1)])
                m.number = number + k + 1
                merged[i].append(m)
        number += count
    score = stream.Score(merged)
    try:
        score.write("musicxml", fp=out, makeNotation=False)
    except Exception:  # durée « complexe » mal lue (ex. 5/12 de noire) : ramenée à la durée simple la plus proche
        simple = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.125]
        for n in score.recurse().notesAndRests:
            if n.duration.type in ("complex", "inexpressible"):
                n.duration.quarterLength = min(simple, key=lambda d: abs(d - float(n.duration.quarterLength)))
        score.write("musicxml", fp=out, makeNotation=False)
    extra = f", {len(raw) - len(systems)} portées remises dans leur système" if stacked else ""
    print(f"Mouvements assemblés : {len(movements)}, {number} mesures{extra}")


if __name__ == "__main__":
    args = sys.argv[1:]
    useful = "--si-utile" in args
    args = [a for a in args if a != "--si-utile"]
    if len(args) < 2:
        sys.exit(__doc__)
    main(args[0], args[1:], useful)
