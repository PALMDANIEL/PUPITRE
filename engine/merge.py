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


def _head_clef(m):
    """Clé en vigueur au début d'une mesure : la sienne (getContextByClass ne regarde que ce qui précède), sinon celle d'avant."""
    own = [c for c in m.getElementsByClass(clef.Clef) if c.offset == 0]
    return own[0] if own else m.getContextByClass(clef.Clef)


def _bottom(c):
    """Note de la 1re ligne (degrés diatoniques, mi4 = 31) d'une clé, octave comprise : la clé générique lue dans le
    MusicXML (sol avec « 8 ») n'a pas toujours lowestLine juste."""
    ref = {"G": 33, "F": 25, "C": 29}.get(c.sign)
    if ref is None or not c.line:
        return c.lowestLine
    return ref - 2 * (c.line - 1) + 7 * (c.octaveChange or 0)


def _clef_key(c):
    return (c.sign, c.line, c.octaveChange) if c is not None else None


def fix_odd_clefs(raw):
    """
    Clé lue de travers sur un système : la même portée a une autre clé sur tous les autres systèmes (au moins deux) et
    ses notes, lues dans cette clé, sautent de registre (plus d'une quinte loin de leur hauteur habituelle), alors
    que relues dans la clé des autres systèmes elles y retombent (à une tierce près). Petites portées : Audiveris prend
    une clé de sol pour une clé d'ut, ou le contraire. Les notes sont relues dans la bonne clé (même place sur la
    portée), la clé d'origine est rendue au système suivant. Rend le nombre de portées rétablies.
    """
    fixed = 0
    width = max((len(st) for _p, st in raw), default=0)
    for i in range(width):
        rows = [(j, staves[i]) for j, (_page, staves) in enumerate(raw) if i < len(staves) and staves[i]]
        clefs = [_clef_key(_head_clef(staff[0])) for _j, staff in rows]
        known = [c for c in clefs if c is not None]
        if len(rows) < 3 or not known:
            continue
        usual = max(set(known), key=known.count)
        if known.count(usual) < max(2, len(rows) - 1):
            continue
        model = next(_head_clef(staff[0]) for _j, staff in rows if _clef_key(_head_clef(staff[0])) == usual)
        for (j, staff), c in zip(rows, clefs):
            if c is None or c == usual:
                continue
            others = [p for (k, st), ck in zip(rows, clefs) if k != j and ck == usual for p in _pitches(st)]
            here = _pitches(staff)
            if len(others) < 8 or len(here) < 3 or any(m.getElementsByClass(clef.Clef) for m in staff[1:]):
                continue  # changement de clé en cours de ligne : pas une clé de tête mal lue
            read = _head_clef(staff[0])
            steps = _bottom(model) - _bottom(read)
            centre = statistics.median(others)
            trial = copy.deepcopy(staff)
            for m in trial:
                shift_measure(m, steps)
            if abs(statistics.median(here) - centre) > 7 and abs(statistics.median(_pitches(trial)) - centre) <= 4:
                after = raw[j + 1][1][i] if j + 1 < len(raw) and i < len(raw[j + 1][1]) and raw[j + 1][1][i] else None
                if after and not after[0].getElementsByClass(clef.Clef):
                    after[0].insert(0, copy.deepcopy(read))  # clé lue rendue au système suivant (elle y vaut peut-être)
                for m in staff:
                    shift_measure(m, steps)
                for old in list(staff[0].getElementsByClass(clef.Clef)):
                    staff[0].remove(old)
                staff[0].insert(0, copy.deepcopy(model))
                fixed += 1
    return fixed


# clés d'une partition de chœur : sol, sol octaviée (ténor), fa ; hauteur médiane attendue de chaque portée d'un
# système selon leur nombre (de haut en bas : S A T B ; S/A et T/B ; contrechant, S/A, T/B ; une voix seule)
COMMON_CLEFS = {("G", 2), ("F", 4)}  # octave à part (« 8 » sous ou sur la clé : remis par render.fix_octaves)
CENTRES = {1: [64], 2: [67, 53], 3: [69, 64, 52], 4: [69, 64, 57, 50]}
PLACE_CLEFS = {1: "G", 2: "GF", 3: "GGF", 4: "GGGF"}  # clé de chaque portée d'un système de chœur, de haut en bas


def _octave_free(staff):
    """Hauteurs d'une portée ramenées à sa clé sans « 8 » (sol octaviée lue pour une clé de sol : une octave de trop)."""
    c = _head_clef(staff[0])
    shift = 12 * ((c.octaveChange or 0) if c is not None else 0)
    return [p - shift for p in _pitches(staff)]


def fix_rare_clefs(raw):
    """
    Clé de tête lue en une clé qu'un chœur n'emploie pas (fa 3e ligne, ut 3e ligne… : sur petites portées, Audiveris
    lit ainsi la clé de sol de la portée S/A, et toutes ses notes tombent une treizième plus bas) : la portée est relue
    en clé de sol ou de fa, celle qui la ramène à la hauteur de la même portée sur les autres systèmes (sinon à la
    tessiture attendue de sa place dans le système), à une quinte près. Les clés courantes ne sont pas touchées (une
    voix rangée par Audiveris dans la portée d'une autre est remise en place à l'assemblage). Rend le nombre de
    portées rétablies.
    """
    fixed = 0
    for j, (_page, staves) in enumerate(raw):
        for i, staff in enumerate(staves):
            if not staff:
                continue
            read = _head_clef(staff[0])
            here = _pitches(staff)
            if read is None or _clef_key(read)[:2] in COMMON_CLEFS or len(here) < 4 \
                    or any(m.getElementsByClass(clef.Clef) for m in staff[1:]):
                continue
            usual = [p for k, (_pg, st) in enumerate(raw) if k != j and i < len(st) and st[i]
                     and _clef_key(_head_clef(st[i][0]))[:2] in COMMON_CLEFS
                     for p in _octave_free(st[i])]
            if len(usual) >= 8:
                centre = statistics.median(usual)
            elif len(staves) in CENTRES:
                centre = CENTRES[len(staves)][i]
            else:
                continue
            gap = abs(statistics.median(here) - centre)
            best = None
            for cand in (clef.TrebleClef(), clef.BassClef()):
                steps = _bottom(cand) - _bottom(read)
                trial = copy.deepcopy(staff)
                for m in trial:
                    shift_measure(m, steps)
                d = abs(statistics.median(_pitches(trial)) - centre)
                if best is None or d < best[0]:
                    best = (d, cand, steps)
            if best[0] > 7 or best[0] + 5 > gap:
                continue
            _d, cand, steps = best
            after = raw[j + 1][1][i] if j + 1 < len(raw) and i < len(raw[j + 1][1]) and raw[j + 1][1][i] else None
            if after and not after[0].getElementsByClass(clef.Clef):
                after[0].insert(0, copy.deepcopy(read))  # le système suivant gardait la clé lue
            for m in staff:
                shift_measure(m, steps)
            for old in list(staff[0].getElementsByClass(clef.Clef)):
                staff[0].remove(old)
            staff[0].insert(0, cand)
            fixed += 1
    return fixed


def fix_clefs_by_place(raw):
    """
    Clé courante mais fausse pour la place de la portée : clé de fa lue en tête de la portée du haut d'un système à deux
    portées (petites portées : soprano et alto lus une octave et une sixte trop bas), clé de sol sur celle du bas… La
    portée chante alors à plus d'une sixte de la hauteur de la même portée sur les autres systèmes (ou, à défaut, de la
    tessiture attendue à cette place) ; relue dans l'autre clé (sol ou fa), elle y revient à une quarte près : on
    change la clé. Rend le nombre de portées rétablies.
    """
    fixed = 0
    for j, (_page, staves) in enumerate(raw):
        n = len(staves)
        if n not in CENTRES or n < 2:  # une portée seule (couplet de soliste) : sa clé peut être l'une ou l'autre
            continue
        for i, staff in enumerate(staves):
            if not staff:
                continue
            read = _head_clef(staff[0])
            here = _pitches(staff)
            if read is None or len(here) < 4 or any(m.getElementsByClass(clef.Clef) for m in staff[1:]):
                continue
            centre = CENTRES[n][i]
            others = [p for k, (_pg, st) in enumerate(raw) if k != j and len(st) == n and st[i] for p in _pitches(st[i])]
            if len(others) >= 8 and abs(statistics.median(others) - centre) <= 7:
                centre = statistics.median(others)
            gap = abs(statistics.median(here) - centre)
            if gap <= 9:
                continue
            # la clé attendue à cette place (sol en haut, fa en bas) : une clé de sol lue sans son « 8 » (ténor) met aussi
            # la portée loin de sa tessiture, mais c'est une octave à rendre (render.fix_octaves), pas une clé à changer
            want = PLACE_CLEFS[n][i]
            if read.sign == want:
                continue
            cand = clef.TrebleClef() if want == "G" else clef.BassClef()
            steps = _bottom(cand) - _bottom(read)
            trial = copy.deepcopy(staff)
            for m in trial:
                shift_measure(m, steps)
            d = abs(statistics.median(_pitches(trial)) - centre)
            if d > 6 or d + 8 > gap:
                continue
            after = raw[j + 1][1][i] if j + 1 < len(raw) and i < len(raw[j + 1][1]) and raw[j + 1][1][i] else None
            if after and not after[0].getElementsByClass(clef.Clef):
                after[0].insert(0, copy.deepcopy(read))  # le système suivant gardait la clé lue
            for m in staff:
                shift_measure(m, steps)
            for old in list(staff[0].getElementsByClass(clef.Clef)):
                staff[0].remove(old)
            staff[0].insert(0, cand)
            fixed += 1
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
    clefs += fix_odd_clefs(raw)
    clefs += fix_rare_clefs(raw)
    clefs += fix_clefs_by_place(raw)
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
    extra += f", clé rétablie sur {clefs} portées" if clefs else ""
    print(f"Mouvements assemblés : {len(movements)}, {number} mesures{extra}")


if __name__ == "__main__":
    args = sys.argv[1:]
    useful = "--si-utile" in args
    args = [a for a in args if a != "--si-utile"]
    if len(args) < 2:
        sys.exit(__doc__)
    main(args[0], args[1:], useful)
