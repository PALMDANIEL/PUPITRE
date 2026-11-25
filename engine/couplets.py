"""
Couplets sur une portée seule (psaumes : refrain à quatre voix sur deux portées, couplets du soliste sur une portée,
souvent en tons de psaume : brève « ‖o‖ » de récitation puis quelques notes, dans une mesure plus longue que la
mesure écrite). Audiveris y écarte les notes qui débordent de la mesure (la brève, ou les notes qui la suivent : la
moitié du couplet perdue, même sur une copie nette). homr, qui lit une portée sans se soucier de la mesure, lit ces
lignes presque parfaitement : les mesures des couplets sont reprises de sa lecture, ligne par ligne, quand elle donne
autant de mesures qu'Audiveris pour cette ligne.

Étape 1 (prepare) : lignes des couplets découpées sur les pages, portees.json pour pupitre-homr --portees (une
« voix » par ligne, pour savoir quelles mesures viennent de quelle ligne).
Étape 2 (apply) : mesures de la partition remplacées par celles de homr ; paroles d'Audiveris reportées sur les notes
de même hauteur ; altérations invraisemblables retirées (les deux traits de la brève passent pour un bémol).
"""
import copy
import difflib
import json
import os
import pathlib
import statistics
import sys

import cv2

import imgio
import pupitres

ENABLED = os.environ.get("PUPITRE_COUPLETS", "1") != "0"
AGREE = float(os.environ.get("PUPITRE_COUPLETS_ACCORD", "0.6"))  # part des notes d'Audiveris que homr doit retrouver
KEEP_MUTE = os.environ.get("PUPITRE_COUPLETS_MUETS", "1") != "0"  # alto muet aussi sous une ligne d'Audiveris gardée
RELOCATE = os.environ.get("PUPITRE_COUPLETS_HAUT", "1") != "0"  # couplets écrits dans la portée du haut du refrain
# page entièrement en mélodie seule (180 chants des recueils, aucun système du chœur) : chaque ligne relue par homr
# aussi, et prise à la place de celle d'Audiveris si elle en retrouve les notes (Audiveris perd des mesures entières :
# 12 mélodies du banc sur 40 en ont perdu, lues de 14 à 77 %)
MELODY_PAGES = os.environ.get("PUPITRE_MELODIES_HOMR", "1") != "0"


def layout(pages_dir: pathlib.Path):
    """Systèmes des pages, dans l'ordre : [(fichier de la page, [portées (haut, bas, gauche, droite)]), …]."""
    out = []
    for pf in sorted(pages_dir.glob("page-*.png")):
        bw = imgio.imread(str(pf), cv2.IMREAD_GRAYSCALE)
        staves = [(*s, "vue") for s in pupitres.find_staves(bw)]
        for g in pupitres.system_indexes(bw, staves, dashed=pupitres._dashed()):
            out.append((pf, [staves[i][:4] for i in g]))
    return out


def prepare(pages_dir: pathlib.Path, folder: pathlib.Path):
    """
    Lignes des couplets : systèmes d'une seule portée qui suivent tous les systèmes de plusieurs portées (refrain
    puis couplets : la disposition des psaumes). Rend la liste des systèmes, ou None si la page n'est pas ainsi faite.
    """
    systems = layout(pages_dir)
    sizes = [len(s) for _pf, s in systems]
    melody = MELODY_PAGES and bool(sizes) and max(sizes) == 1  # page de mélodie seule : toutes ses lignes
    if not sizes or (not melody and (max(sizes) < 2 or sizes[-1] != 1)):
        return None
    tail = len(sizes)
    while tail and sizes[tail - 1] == 1:
        tail -= 1
    if any(n == 1 for n in sizes[:tail]):
        return None  # couplets entre deux systèmes du refrain : pas encore
    folder.mkdir(parents=True, exist_ok=True)
    voix = []
    for k, (pf, staff) in enumerate(systems[tail:]):
        bw = imgio.imread(str(pf), cv2.IMREAD_GRAYSCALE)
        t, b, _l, _r = staff[0]
        sp = (b - t) / 4
        y0, y1 = int(max(0, t - 4 * sp)), int(min(bw.shape[0], b + 4 * sp))
        name = f"couplet-{k + 1:02d}.png"
        imgio.imwrite(str(folder / name), bw[y0:y1])
        voix.append([{"image": name, "T": t - y0, "B": b - y0}])
    (folder / "portees.json").write_text(json.dumps({"voix": voix, "passes": 1, "tout": melody}), encoding="utf-8")
    return systems[tail:]


def _sounding(m):
    return [n for n in m.recurse().notes if n.pitches and not n.duration.isGrace]


def _keysig(part, m):
    from music21 import key
    ks = m.getContextByClass(key.KeySignature)
    if ks is None:
        ks = next(iter(part.recurse().getElementsByClass(key.KeySignature)), None)
    return ks or key.KeySignature(0)


def _clean(p, ks):
    """Altération invraisemblable (bémol sans bémol à l'armure, la♯…) ramenée à l'armure."""
    from music21 import pitch
    a = ks.accidentalByStep(p.step)
    want = a.alter if a else 0
    alter = p.accidental.alter if p.accidental else 0
    if alter != want and not pupitres._plausible_accidental(p.step, alter, ks.sharps):
        p.accidental = pitch.Accidental(a.name) if a else None


def _degrees(ms):
    """Note la plus haute de chaque instant (Audiveris range les deux voix d'un couplet S+A l'une après l'autre)."""
    out = []
    for m in ms:
        tops = {}
        for n in m.recurse().notes:
            if n.pitches and not n.duration.isGrace:
                t = round(float(n.getOffsetInHierarchy(m)), 3)
                p = max(n.pitches, key=lambda q: q.ps)
                if t not in tops or p.ps > tops[t].ps:
                    tops[t] = p
        out += [(tops[t].step, tops[t].octave) for t in sorted(tops)]
    return out


def _from_homr(hm, ks, old):
    """Notes d'une mesure de homr, à la suite : [(début, élément)] ; paroles d'Audiveris reportées (même hauteur)."""
    from music21 import chord, note
    new = []
    for el in hm.recurse().notesAndRests:
        # accords gardés : couplet de soprano et alto sur une portée (Psaumes 24, 70), écrit en accords
        if isinstance(el, chord.Chord):
            n = chord.Chord(sorted({p.nameWithOctave: p for p in el.pitches}.values(), key=lambda p: p.ps),
                            quarterLength=el.quarterLength)
        elif isinstance(el, note.Note):
            n = note.Note(el.pitch, quarterLength=el.quarterLength)
        else:
            n = note.Rest(quarterLength=el.quarterLength)
        if not n.isRest:
            n.tie = el.tie
            for p in n.pitches:
                _clean(p, ks)
        new.append(n)
    top = lambda x: max(p.midi for p in x.pitches)  # noqa: E731
    a_seq = [top(o) for o in old]
    b_seq = [top(n) if not n.isRest else -1 for n in new]
    for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(a=a_seq, b=b_seq, autojunk=False).get_opcodes():
        if tag in ("equal", "replace"):
            for o, n in zip(old[a1:a2], new[b1:b2]):
                if not n.isRest and o.lyrics:
                    n.lyrics = copy.deepcopy(o.lyrics)
    out, at = [], 0.0
    for n in new:
        out.append((at, n))
        at += float(n.quarterLength)
    return out


def _voices_of(m):
    """Contenu d'une mesure d'Audiveris, voix par voix : [[(début, élément)]]."""
    srcs = list(m.voices) or [m]
    return [[(float(el.offset), copy.deepcopy(el)) for el in v.notesAndRests] for v in srcs]


def _clear(m, rest=False):
    from music21 import note
    for el in list(m.recurse().notesAndRests):
        el.activeSite.remove(el)
    for v in list(m.voices):
        m.remove(v)
    if rest:
        m.insert(0, note.Rest(quarterLength=float(m.barDuration.quarterLength)))


def _fill(m, content):
    """Couplet écrit dans la mesure m ; à une seule voix sans accord, l'alto se tait (silence caché en 2e voix) :
    la séparation des voix de la portée S. A. donnait sinon le couplet du soliste aussi à l'alto."""
    from music21 import chord, note, stream
    _clear(m)
    content = [c for c in content if c]
    if not content:
        return
    single = len(content) == 1 and not any(isinstance(el, chord.Chord) for _t, el in content[0])
    groups = content + ([[(0.0, None)]] if single else [])
    length = max((t + float(el.quarterLength) for c in content for t, el in c), default=0.0)
    for k, items in enumerate(groups, 1):
        v = stream.Voice()
        v.id = str(k)
        for t, el in items:
            if el is None:
                # silence caché, découpé en durées simples (sans makeNotation, music21 refuse d'écrire 5 ou 7 temps)
                at = 0.0
                for q in _plain(length or float(m.barDuration.quarterLength)):
                    r = note.Rest(quarterLength=q)
                    r.style.hideObjectOnPrint = True
                    v.insert(at, r)
                    at += q
                continue
            v.insert(t, el)
        m.insert(0, v)


def _plain(length):
    """Durée découpée en valeurs simples (brève, ronde pointée, ronde…)."""
    out = []
    for q in (8.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25):
        while length >= q - 1e-6:
            out.append(q)
            length -= q
    return out


def _top_staff(staves, rows, start):
    """Portée du haut du refrain (S. A.) : la première, dans l'ordre de la partition, qui chante avant les couplets en
    clé de sol. Audiveris range les lignes des couplets par leur place sur la page, parfois dans la partie T. B.
    (« Toussaint » : couplet chanté par l'alto, le ténor et la basse)."""
    from music21 import clef
    for k, r in enumerate(rows):
        sung = [m for m in r[:start] if _sounding(m)]
        if not sung:
            continue
        c = sung[0].getContextByClass(clef.Clef)
        if c is None or c.sign == "G":
            return k
    return None


def apply(partition, folder: pathlib.Path, out) -> int:
    """Mesures des couplets remplacées par la lecture de homr. Rend le nombre de lignes reprises."""
    from music21 import chord, converter, note, stream
    spec = json.loads((folder / "portees.json").read_text(encoding="utf-8"))
    lines = []
    for v in range(1, len(spec["voix"]) + 1):
        f = folder / "sortie" / f"v{v}.musicxml"
        if not f.exists():
            return 0
        sc = converter.parse(str(f))
        lines.append([m for p in sc.parts[:1] for m in p.getElementsByClass(stream.Measure)])
    if spec.get("tout"):
        return apply_melody(partition, lines, out)
    score = converter.parse(str(partition))
    import arbitre
    arbitre.drop_chord_symbols(score)
    staves = list(score.parts)
    rows = [list(p.getElementsByClass(stream.Measure)) for p in staves]
    total = max(len(r) for r in rows)
    need = sum(len(l) for l in lines)
    if not need or need >= total:
        print(f"Couplets : {need} mesures lues par homr pour {total} dans la partition, pas de reprise", file=sys.stderr)
        return 0
    start = total - need
    # mesures des couplets : une seule portée y chante (ou aucune, si Audiveris a tout perdu)
    voices = {}
    for i in range(start, total):
        singing = [k for k, r in enumerate(rows) if i < len(r) and _sounding(r[i])]
        if len(singing) > 1:
            print(f"Couplets : mesure {i + 1} chantée par {len(singing)} portées, pas de reprise", file=sys.stderr)
            return 0
        if singing:
            voices[i] = singing[0]
    if not voices:
        return 0
    staff_of = max(set(voices.values()), key=list(voices.values()).count)
    top = _top_staff(staves, rows, start) if RELOCATE else None
    taken = 0
    i = start
    for li, line in enumerate(lines):
        # homr complète la lecture d'Audiveris (notes perdues dans une mesure trop longue) ; s'il la contredit (photo
        # floue : homr y lit mal, Psaume 24 flou : soprano 85 → 60 %), la ligne d'Audiveris reste
        aud = _degrees([rows[voices.get(i + k, staff_of)][i + k] for k in range(len(line))
                        if i + k < len(rows[voices.get(i + k, staff_of)])])
        hom = _degrees(line)
        common = sum(b.size for b in difflib.SequenceMatcher(a=aud, b=hom, autojunk=False).get_matching_blocks())
        accept = not aud or common >= AGREE * len(aud)
        if not accept:
            print(f"Couplets : ligne {li + 1} gardée d'Audiveris (homr n'en retrouve que {common}/{len(aud)} notes)",
                  file=sys.stderr)
        wrote = False
        for k, hm in enumerate(line):
            idx = i + k
            src = voices.get(idx, staff_of)
            if idx >= len(rows[src]):
                continue
            m = rows[src][idx]
            ks = _keysig(staves[src], m)
            if accept:
                content = [_from_homr(hm, ks, _sounding(m))]
            elif voices.get(idx) is not None and ((top is not None and src != top) or KEEP_MUTE):
                # ligne d'Audiveris gardée : écrite elle aussi dans la portée du haut, avec l'alto muet si elle est à une
                # voix (Psaume 22 photocopie : l'alto rechantait le couplet, 100 → 44 %)
                content = _voices_of(m)
            else:
                continue
            dst = rows[top][idx] if top is not None and idx < len(rows[top]) else m
            if dst is not m:
                _clear(m, rest=True)
            _fill(dst, content)
            wrote = True
        i += len(line)
        taken += wrote
    # sans makeNotation : music21 coupait les mesures de récitation (plus longues que la mesure écrite) par des
    # liaisons, et plantait (KeyError) ou tournait sans fin sur une copie usée
    score.write("musicxml", fp=str(out), makeNotation=False)
    return taken


def apply_melody(partition, lines, out) -> int:
    """
    Page de mélodie seule : chaque ligne (système d'une portée) relue par homr remplace celle d'Audiveris quand elle en
    retrouve les notes (AGREE) ; elle apporte alors les mesures qu'Audiveris a perdues ou vidées. Lignes rangées par
    les débuts de système d'Audiveris (autant que de lignes vues sur l'image), sinon par le nombre de mesures de homr
    s'il est celui d'Audiveris ; sinon rien. Paroles d'Audiveris reportées sur les notes de même hauteur, ligne par
    ligne. Une seule partie écrite (la mélodie). Rend le nombre de lignes reprises.
    """
    from music21 import converter, layout as m21layout, note, stream
    import arbitre
    score = converter.parse(str(partition))
    arbitre.drop_chord_symbols(score)
    parts = list(score.parts)
    rows = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    total = max((len(r) for r in rows), default=0)
    if not total or not lines:
        return 0

    def cell(i):  # mesure chantée : Audiveris range parfois une ligne dans une autre partie
        for r in rows:
            if i < len(r) and _sounding(r[i]):
                return r[i]
        return rows[0][i] if i < len(rows[0]) else None

    starts = [i for i, m in enumerate(rows[0]) if any(sl.isNew for sl in m.getElementsByClass(m21layout.SystemLayout))]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    if len(starts) != len(lines):
        if sum(len(l) for l in lines) != total:
            print(f"Mélodie : {len(lines)} lignes sur l'image, {len(starts)} systèmes et {total} mesures lus, "
                  "pas de reprise", file=sys.stderr)
            return 0
        starts, at = [], 0
        for l in lines:
            starts.append(at)
            at += len(l)
    bounds = starts + [total]
    first = rows[0][0]
    ks = _keysig(parts[0], first)
    out_measures, taken = [], 0
    from music21 import clef as m21clef
    for k, line in enumerate(lines):
        aud = [m for m in (cell(i) for i in range(bounds[k], bounds[k + 1])) if m is not None]
        # clé de sol « 8 » lue par Audiveris sur une ligne de mélodie (jamais dans une mélodie de recueil) : sa ligne
        # est une octave trop bas ; comparée à homr une octave plus haut (« Ô Marie » : homr juste, Audiveris décalé)
        # clé de la ligne : celle de sa 1re mesure d'abord (getContextByClass ne voit pas la clé de la mesure même)
        c = None
        if aud:
            own = [x for x in aud[0].getElementsByClass(m21clef.Clef) if x.offset == 0]
            c = own[0] if own else aud[0].getContextByClass(m21clef.Clef)
        shift = -(getattr(c, "octaveChange", 0) or 0) if getattr(c, "sign", "G") == "G" else 0
        a_deg = [(st, o + shift) for st, o in _degrees(aud)]
        h_deg = _degrees(line)
        common = sum(b.size for b in difflib.SequenceMatcher(a=a_deg, b=h_deg, autojunk=False).get_matching_blocks())
        accept = bool(line) and (not a_deg or common >= AGREE * len(a_deg))
        # ligne de homr décalée : sa hauteur médiane doit rester à moins d'une quarte de celle d'Audiveris
        mids = [statistics.median([p.midi for m in ms for n in _sounding(m) for p in n.pitches] or [0]) for ms in (aud, line)]
        if accept and a_deg and abs(mids[0] + 12 * shift - mids[1]) > 5:
            accept = False
        if not accept:
            kept = [copy.deepcopy(m) for m in aud]
            if kept and c is not None and not [x for x in kept[0].getElementsByClass(m21clef.Clef) if x.offset == 0]:
                kept[0].insert(0, copy.deepcopy(c))  # la clé de la ligne voyage avec elle (octave corrigée au rendu)
            out_measures += kept
            continue
        old = [n for m in aud for n in _sounding(m)]
        built = []
        for j, hm in enumerate(line):
            m = stream.Measure()
            if j == 0:
                m.insert(0, m21clef.TrebleClef())  # homr lit la ligne en clé de sol
            for t, el in _from_homr(hm, ks, []):
                m.insert(t, el)
            built.append(m)
        # paroles d'Audiveris reportées sur la ligne de homr (notes de même hauteur, dans l'ordre)
        new = [n for m in built for n in m.notes]
        top = lambda x: max(p.midi for p in x.pitches)  # noqa: E731
        sm = difflib.SequenceMatcher(a=[top(o) for o in old], b=[top(n) for n in new], autojunk=False)
        for tag, a1, a2, b1, b2 in sm.get_opcodes():
            if tag in ("equal", "replace"):
                for o, n in zip(old[a1:a2], new[b1:b2]):
                    if o.lyrics:
                        n.lyrics = copy.deepcopy(o.lyrics)
        out_measures += built
        taken += 1
    if not taken:
        return 0
    part = stream.Part()
    part.partName = parts[0].partName
    from music21 import clef, meter
    for k, m in enumerate(out_measures, 1):
        m.number = k
        for el in list(m.getElementsByClass((m21layout.SystemLayout, m21layout.StaffLayout))):
            m.remove(el)
        if k == 1:
            if not m.getElementsByClass(clef.Clef):
                m.insert(0, clef.TrebleClef())
            ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
            for el in (ks, ts):
                if el is not None and not m.getElementsByClass(type(el)):
                    m.insert(0, copy.deepcopy(el))
        part.append(m)
    result = stream.Score()
    if score.metadata is not None:
        result.insert(0, copy.deepcopy(score.metadata))
    result.insert(0, part)
    result.write("musicxml", fp=str(out), makeNotation=False)
    print(f"Mélodie relue par homr : {taken} lignes sur {len(lines)} ({len(out_measures)} mesures, "
          f"{total} lues par Audiveris)", file=sys.stderr)
    return taken


def main():
    if len(sys.argv) < 3:
        sys.exit("couplets.py prepare <pages> <dossier> | apply <partition> <dossier> <sortie>")
    if sys.argv[1] == "prepare":
        systems = prepare(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
        sys.exit(0 if systems else 3)
    n = apply(sys.argv[2], pathlib.Path(sys.argv[3]), sys.argv[4])
    print(f"Couplets relus par homr : {n} lignes", file=sys.stderr)
    sys.exit(0 if n else 3)


if __name__ == "__main__":
    main()
