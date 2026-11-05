"""
Assemblage : Audiveris coupe la partition en plusieurs mouvements (clean.mvt1.mxl, clean.mvt2.mxl…)
dès que le nombre de portées change (couplet en solo, par exemple). On les remet bout à bout.

Photocopie abîmée (barres de mesure et accolades coupées entre les portées) : Audiveris prend chaque portée
d'un système pour un système à elle seule, et lirait Soprano, Alto, Ténor, Basse l'un après l'autre.
Les portées d'un même système partagent leurs barres de mesure : leurs mesures ont exactement les mêmes largeurs.
Deux systèmes voisins de la même page dont toutes les largeurs de mesures coïncident sont donc superposés.

Clé de tête non reconnue (photo peu nette, clé de fa collée au chiffre de la mesure) : Audiveris lit la portée en clé
de sol et la basse sort une sixte trop haut. Le journal d'Audiveris dit quelles portées sont dans ce cas ; une telle
portée qui chante plus haut que la portée du dessus est relue en clé de fa (voir fix_clefs).

Usage : python3 merge.py [--si-utile] <sortie.musicxml> <mvt1.mxl> <mvt2.mxl> ...
  --si-utile : avec un seul mouvement, n'écrit rien (code 3) s'il n'y a aucune portée à superposer ni clé à rétablir.
"""
import copy, pathlib, re, statistics, sys
from music21 import clef, converter, key, layout, meter, note, pitch, stream


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


_SHEET = r"\[[^\]#]+(?:#(\d+))?\]"
_UNREAD = re.compile(_SHEET + r".*Staff#(\d+) no recognized header clef")
_RAW = re.compile(_SHEET + r".*\| \d+ raw measures: \[(.*)\]")


def unread_clefs(sources):
    """
    Journal d'Audiveris (clean-….log à côté de clean.mxl) : nombre de systèmes de chaque feuille et portées
    (feuille, n° dans la feuille) dont la clé de tête n'a pas été reconnue. None sans journal.
    """
    src = pathlib.Path(sources[0])
    logs = sorted(src.parent.glob(f"{src.name.split('.')[0]}-*.log"))
    if not logs:
        return None
    counts, unread = {}, set()
    for line in logs[-1].read_text(encoding="utf-8", errors="replace").splitlines():
        if m := _UNREAD.search(line):
            unread.add((int(m.group(1) or 1), int(m.group(2))))
        elif m := _RAW.search(line):
            numbers = [int(x) for x in re.findall(r"system#(\d+)", m.group(2))]
            sheet = int(m.group(1) or 1)
            counts[sheet] = max([counts.get(sheet, 0), *numbers])
    return counts, unread


def _pitches(staff):
    return [p.ps for m in staff for n in m.recurse().notes for p in n.pitches]


def shift_measure(m, steps):
    """Mesure relue dans une autre clé : notes décalées de `steps` degrés, altérations recalculées pour leur nom."""
    ks = m.getContextByClass(key.KeySignature)
    altered = {}  # (nom, octave) → altération écrite plus tôt dans la mesure
    for n in sorted(m.recurse().notes, key=lambda n: n.getOffsetInHierarchy(m)):
        for p in n.pitches:
            explicit = p.accidental is not None and p.accidental.displayStatus
            alter = p.accidental.alter if explicit else None
            index = "CDEFGAB".index(p.step) + 7 * p.octave + steps
            p.step, p.octave = "CDEFGAB"[index % 7], index // 7
            if alter is None:
                by_key = ks.accidentalByStep(p.step) if ks else None
                alter = altered.get((p.step, p.octave), by_key.alter if by_key else 0)
            else:
                altered[(p.step, p.octave)] = alter
            p.accidental = pitch.Accidental(alter) if alter else None
            if explicit and p.accidental is not None:
                p.accidental.displayStatus = True


def fix_clefs(raw, sources):
    """
    Portée dont Audiveris n'a pas reconnu la clé (il suppose une clé de sol) et qui chante nettement plus haut que la
    portée du dessus : clé de fa (notes 12 degrés plus bas) si elle passe alors sous celle-ci. Une clé de sol lue à tort
    à la place d'une clé de fa met la basse une octave et une sixte trop haut, au-dessus des sopranos.
    Rend le nombre de portées rétablies ; rien n'est touché si le journal ne correspond pas aux systèmes lus.
    """
    found = unread_clefs(sources)
    if not found or not found[1] or sum(found[0].values()) != len(raw):
        return 0
    counts, unread = found
    sheets = [s for s in sorted(counts) for _ in range(counts[s])]
    fixed, base, previous = 0, 0, None
    for j, (_page, staves) in enumerate(raw):
        if sheets[j] != previous:
            base, previous = 0, sheets[j]
        heard = [_pitches(st) for st in staves]
        for i in range(1, len(staves)):
            if (sheets[j], base + i + 1) not in unread or not heard[i] or not heard[i - 1]:
                continue
            above, here = statistics.median(heard[i - 1]), statistics.median(heard[i])
            trial = copy.deepcopy(staves[i])
            for m in trial:
                shift_measure(m, -12)
            if here > above + 4 and statistics.median(_pitches(trial)) <= above:
                after = raw[j + 1][1][i] if j + 1 < len(raw) and i < len(raw[j + 1][1]) else None
                if after and not after[0].getElementsByClass(clef.Clef):
                    was = staves[i][-1].getContextByClass(clef.Clef)  # clé d'origine rendue au système suivant
                    after[0].insert(0, copy.deepcopy(was) if was is not None else clef.TrebleClef())
                for m in staves[i]:
                    shift_measure(m, -12)
                for c in list(staves[i][0].getElementsByClass(clef.Clef)):
                    staves[i][0].remove(c)
                staves[i][0].insert(0, clef.BassClef())
                fixed += 1
        base += len(staves)
    return fixed


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
    clefs = fix_clefs(raw, sources)
    systems = stack(raw)
    stacked = len(systems) < len(raw)
    if only_if_useful and len(movements) == 1 and not stacked and not clefs:
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
    extra += f", clé de fa rétablie sur {clefs} portées" if clefs else ""
    print(f"Mouvements assemblés : {len(movements)}, {number} mesures{extra}")


if __name__ == "__main__":
    args = sys.argv[1:]
    useful = "--si-utile" in args
    args = [a for a in args if a != "--si-utile"]
    if len(args) < 2:
        sys.exit(__doc__)
    main(args[0], args[1:], useful)
