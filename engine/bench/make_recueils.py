"""
Copies d'entraînement dans le style des recueils « Chants notés » (scans à 170 points par pouce, petites portées), dont
on connaît les notes exactes. Les vrais recueils n'ont pas de bonne réponse (et leurs chants ne sont pas libres de
droits) : on grave ici de la musique du domaine public comme ils la gravent, puis on l'abîme comme leurs scans.

Ce qui imite les recueils (mesuré sur les 728 chants lus) :
  - mises en page : mélodie seule (55 % des chants), deux portées S+A / T+B (34 %), chant + chœur sur deux portées
    (8 %), quatre portées ;
  - noms d'accords en français au-dessus de la portée (« MI », « Fa#m », « SI7 »), 1 à 4 couplets numérotés sous la
    mélodie, titre suivi de sa cote (« A 108 »), mentions « Texte : … / Musique : … », indication de mouvement ;
  - indication de mesure « C » ou « ¢ » (4/4, 2/2 : le « C » des recueils n'est souvent pas lu), chiffres sinon ;
  - interligne ≈ 10 px sur une page de 1405 px (A4 à 170 points par pouce) ; scan noir et blanc : encre qui bave ou
    s'amincit, petites taches, léger flou, page à peine penchée.

Sources (domaine public, encodages du corpus de music21) : chorals de Bach (sauf ceux du banc de Bach, make_corpus.py)
et chansons populaires allemandes de la collection d'Essen. Le manifeste (manifeste.json) donne pour chaque copie
l'œuvre, la source de l'encodage et la licence. Les pages fabriquées ne vont pas dans le dépôt.

  <python du banc (bench-venv)> make_recueils.py <dossier> [nombre] [--graine N] [--mises melodie,fermee,...]
      chaque cas : <dossier>/<œuvre>-<mise en page>/source.png, truth.json (hauteurs MIDI par voix ; « _mesures »,
      « _indication » : nombre de mesures et indication de mesure gravés), gravure.musicxml
"""
import copy, json, pathlib, random, re, sys

import cairosvg, cv2, numpy as np, verovio
from music21 import (chord, clef, corpus, expressions, harmony, key, layout, metadata, meter, note, stream, tempo)

BENCH = {"bwv269", "bwv347", "bwv153.1", "bwv86.6", "bwv267", "bwv281", "bwv40.6", "bwv244.3", "bwv66.6", "bwv145.5"}
NAMES = ["Soprano", "Alto", "Ténor", "Basse"]
WIDTH = 1405          # page A4 à 170 points par pouce (recueils scannés)
MAX_MEASURES = 24     # chants des recueils : 18 mesures en médiane
LAYOUTS = {"melodie": 0.28, "fermee": 0.16, "chantchoeur": 0.06, "ouverte": 0.04, "mixte": 0.46}
FONTS = ["Leipzig", "Bravura", "Gootville", "Leland"]  # polices de musique de Verovio

FR_ROOTS = {"C": "DO", "C#": "DO#", "D-": "RÉb", "D": "RÉ", "D#": "RÉ#", "E-": "MIb", "E": "MI", "F": "FA", "F#": "FA#",
            "G-": "SOLb", "G": "SOL", "G#": "SOL#", "A-": "LAb", "A": "LA", "A#": "LA#", "B-": "SIb", "B": "SI"}
SYLLABLES = ("sei gneur nous ve nons vers toi ta pa ro le est lu miè re sur nos pas chan tons la joie du ciel "
             "peu ple de dieu mar che dans la paix l'a mour de jé sus nous ras sem ble pain de vie don ne nous "
             "ta grâ ce Ô ma ri e mè re des hom mes viens es prit saint ré veil le nos cœurs al lé lu ia").split()
TEMPI = ["Tempo de marche", "Sans presser", "Bien rythmé", "Allant", "Calme", "Joyeux", "Modéré", "Bien lié"]
NAMES_POOL = ["J. DUPUIS", "M. LEROY", "A. MARTIN", "P. GIRARD", "C. BERNARD", "R. FAURE", "L. MOREAU", "D. ROUX"]


# ---------------------------------------------------------------------------------------------------- sources
def bach_chorales(rng, part=0, parts=1):
    """Chorals à 4 voix du corpus de music21 (hors banc de Bach), dans un ordre tiré au sort ; part/parts : une part
    des œuvres (fabrication en parallèle, sans doublon)."""
    paths = sorted(p for p in corpus.getComposer("bach") if re.search(r"bwv\d", p.name))
    rng.shuffle(paths)
    for p in paths[part::parts]:
        name = p.stem
        if name in BENCH:
            continue
        try:
            sc = corpus.parse(p)
        except Exception:  # noqa: BLE001
            continue
        parts = [q for q in sc.parts if q.recurse().notes]
        if len(parts) != 4:
            continue
        yield name, parts, dict(oeuvre=f"J.-S. Bach, choral {name}", source="corpus de music21 (encodage MuseData/CCARH)",
                                licence="œuvre du domaine public")


def folk_melodies(rng, part=0, parts=1):
    """Chansons populaires (collection d'Essen, corpus de music21), une à une."""
    paths = sorted(corpus.getComposer("essenFolksong"))
    rng.shuffle(paths)
    for p in paths[part::parts]:
        try:
            op = corpus.parse(p)
        except Exception:  # noqa: BLE001
            continue
        scores = list(getattr(op, "scores", [op]))
        rng.shuffle(scores)
        for k, sc in enumerate(scores):
            parts = [q for q in sc.parts if q.recurse().notes] or ([sc] if sc.recurse().notes else [])
            if len(parts) != 1 or len(parts[0].getElementsByClass(stream.Measure)) < 6:
                continue
            yield f"{p.stem}-{k}", parts, dict(oeuvre=f"chanson populaire ({p.stem}, n° {k})",
                                               source="corpus de music21 (collection d'Essen, EsAC)",
                                               licence="mélodie traditionnelle, domaine public")


# ---------------------------------------------------------------------------------------------------- musique
def trim(parts, rng):
    """Au plus MAX_MEASURES mesures (même coupe pour toutes les voix), liaisons de prolongation gardées."""
    n = min(len(p.getElementsByClass(stream.Measure)) for p in parts)
    last = min(n, MAX_MEASURES)
    out = []
    for p in parts:
        q = p.measures(0, last)
        for sp in list(q.recurse().getElementsByClass("Spanner")):
            q.remove(sp, recurse=True)
        out.append(q)
    return out


def truth(parts, names):
    return {names[i]: [int(n.pitch.midi) for n in p.stripTies(inPlace=False).recurse().notes if n.isNote]
            for i, p in enumerate(parts)}


def fr_chord(ch):
    try:
        cs = harmony.chordSymbolFromChord(chord.Chord(ch.pitches))
    except Exception:  # noqa: BLE001
        return None
    if cs is None or cs.root() is None or "Cannot Be Identified" in (cs.figure or ""):
        return None
    root = cs.root().name
    name = FR_ROOTS.get(root)
    if name is None:
        return None
    fig = cs.figure or ""
    qual = "m" if re.search(r"m(?!aj)", fig[len(cs.root().name.replace("-", "b")):]) else ""
    seventh = "7" if "7" in fig else ""
    dim = " dim." if "dim" in fig or "o" in fig[1:] else ""
    return name + qual + seventh + dim


def style_name(text, rng):
    """« MI », « Fa#m », « SI7 » : les recueils mêlent capitales et minuscules."""
    if rng.random() < 0.4 and len(text) > 2:
        return text[0] + text[1:].lower().replace("é", "é")
    return text


def add_chord_names(top, harmony_parts, rng):
    """Noms d'accords en français au-dessus de la portée du haut : un par mesure (ou par demi-mesure s'il change)."""
    sc = stream.Score([copy.deepcopy(p) for p in harmony_parts])
    ch = sc.chordify()
    measures = list(top.getElementsByClass(stream.Measure))
    for m, cm in zip(measures, ch.getElementsByClass(stream.Measure)):
        chords = [c for c in cm.recurse().getElementsByClass(chord.Chord) if len(c.pitches) >= 2]
        if not chords:
            continue
        bar = m.barDuration.quarterLength if m.barDuration else 4
        picks = [chords[0]]
        mid = [c for c in chords if c.offset >= bar / 2]
        if mid and rng.random() < 0.5:
            picks.append(mid[0])
        last = None
        for c in picks:
            name = fr_chord(c)
            if not name or name == last:
                continue
            last = name
            te = expressions.TextExpression(style_name(name, rng))
            te.placement = "above"
            te.style.fontStyle = "bolditalic"
            m.insert(c.offset, te)


def simple_harmony(melody, rng):
    """Accords pour une mélodie seule : I, IV ou V de la tonalité, celui qui contient le plus de notes de la mesure."""
    k = melody.analyze("key")
    triads = [k.pitchFromDegree(d) for d in (1, 4, 5)]
    out = stream.Part()
    for m in melody.getElementsByClass(stream.Measure):
        pcs = [n.pitch.pitchClass for n in m.recurse().notes if n.isNote]
        best = None
        for root in triads:
            ch = chord.Chord([root, root.transpose("M3" if k.mode == "major" or root != triads[0] else "m3"),
                              root.transpose("P5")])
            score = sum(1 for pc in pcs if pc in {p.pitchClass for p in ch.pitches})
            if best is None or score > best[0]:
                best = (score, ch)
        mm = stream.Measure(number=m.number)
        c = best[1]
        c.quarterLength = m.barDuration.quarterLength if m.barDuration else 4
        mm.append(c)
        out.append(mm)
    return out


def add_lyrics(melody, verses, rng):
    """Couplets numérotés (syllabes françaises au hasard) sous la mélodie : une syllabe par note attaquée."""
    for n in melody.recurse().notes:
        n.lyrics = []
    notes = [n for n in melody.recurse().notes if n.isNote and not (n.tie is not None and n.tie.type in ("stop", "continue"))]
    for v in range(1, verses + 1):
        k = 0
        while k < len(notes):
            word = rng.randint(1, 3)
            for j in range(word):
                if k >= len(notes):
                    break
                syl = rng.choice(SYLLABLES)
                if k == 0:
                    syl = f"{v}. {syl}" if verses > 1 else syl
                kind = "single" if word == 1 else ("begin" if j == 0 else "end" if j == word - 1 else "middle")
                ly = note.Lyric(text=syl, number=v, syllabic=kind)
                notes[k].lyrics.append(ly)
                k += 1


def set_time_symbol(parts, rng):
    """« C » pour 4/4, « ¢ » pour 2/2 (indication des recueils), le plus souvent."""
    for p in parts:
        for ts in p.recurse().getElementsByClass(meter.TimeSignature):
            if ts.ratioString == "4/4" and rng.random() < 0.8:
                ts.symbol = "common"
            elif ts.ratioString == "2/2" and rng.random() < 0.8:
                ts.symbol = "cut"


def staff_of(voices, cl, name, stems):
    """Une portée à une ou deux voix (hampes en haut pour la 1re, en bas pour la 2e), mesure par mesure."""
    staff = stream.Part()
    staff.partName = name
    rows = [list(v.getElementsByClass(stream.Measure)) for v in voices]
    for k, ms in enumerate(zip(*rows)):
        m = stream.Measure(number=ms[0].number)
        if k == 0:
            m.insert(0, copy.deepcopy(cl))
            for el in ms[0].getElementsByClass((key.KeySignature, meter.TimeSignature)):
                m.insert(0, copy.deepcopy(el))
        else:
            for el in ms[0].getElementsByClass(meter.TimeSignature):
                m.insert(0, copy.deepcopy(el))
        for el in ms[0].getElementsByClass((expressions.TextExpression, tempo.MetronomeMark, layout.SystemLayout)):
            m.insert(el.offset, copy.deepcopy(el))
        if len(voices) == 1:
            for el in ms[0].notesAndRests:
                m.insert(el.offset, copy.deepcopy(el))
        else:
            for vid, src, stem in zip(("1", "2"), ms, stems):
                v = stream.Voice(id=vid)
                for el in src.notesAndRests:
                    e = copy.deepcopy(el)
                    if e.isNote or e.isChord:
                        e.stemDirection = stem
                        if vid == "2":
                            e.lyrics = []
                    v.insert(el.offset, e)
                m.insert(0, v)
        staff.append(m)
    return staff


def build(kind, parts, rng):
    """Partition gravée (music21) et bonne réponse pour une mise en page."""
    if kind == "melodie":
        mel = parts[0]
        add_lyrics(mel, rng.randint(1, 4), rng)
        add_chord_names(mel, [mel, simple_harmony(mel, rng)] if len(parts) == 1 else parts, rng)
        staves = [staff_of([mel], clef.TrebleClef(), "", ["up"])]
        return staves, {"Soprano": truth([mel], ["Soprano"])["Soprano"]}
    s, a, t, b = parts
    add_lyrics(s, rng.randint(1, 3), rng)
    add_chord_names(s, parts, rng)
    answer = truth(parts, NAMES)
    if kind == "ouverte":
        staves = [staff_of([v], c, n, ["up"]) for v, c, n in zip(parts, (clef.TrebleClef(), clef.TrebleClef(),
                  clef.Treble8vbClef(), clef.BassClef()), ("S", "A", "T", "B"))]
    elif kind == "fermee":
        staves = [staff_of([s, a], clef.TrebleClef(), "S. A.", ["up", "down"]),
                  staff_of([t, b], clef.BassClef(), "T. B.", ["up", "down"])]
    else:  # chant + chœur : la mélodie seule au-dessus (avec les paroles), le chœur sur deux portées
        chant = copy.deepcopy(s)
        for n in s.recurse().notes:
            n.lyrics = []
        for te in list(s.recurse().getElementsByClass(expressions.TextExpression)):
            te.activeSite.remove(te)  # noms d'accords au-dessus du chant seulement
        staves = [staff_of([chant], clef.TrebleClef(), "Chant", ["up"]),
                  staff_of([s, a], clef.TrebleClef(), "Chœur", ["up", "down"]),
                  staff_of([t, b], clef.BassClef(), "", ["up", "down"])]
        answer = {"Chant": answer["Soprano"], **answer}
    return staves, answer


def part_of(measures, name=""):
    p = stream.Part()
    p.partName = name
    for k, m in enumerate(measures, 1):
        m.number = k
        if k > 1:  # clé, armure et indication seulement au début de la partie
            for el in list(m.getElementsByClass((clef.Clef, key.KeySignature, meter.TimeSignature))):
                m.remove(el)
        p.append(m)
    return p


def build_mixte(parts, melody, rng):
    """Refrain en chœur (S+A / T+B) et couplets en mélodie seule (plusieurs couplets), comme la moitié des chants des
    recueils : des systèmes de deux portées, puis d'une (ou l'inverse). Les deux parties sont gravées à part et
    posées l'une sous l'autre sur la page. Bonne réponse : la mélodie des couplets à la voix du haut (soliste), les
    autres voix seulement au refrain."""
    refrain = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    couplet = list(melody.getElementsByClass(stream.Measure))
    r_n = min(len(refrain[0]), rng.randint(4, 10))
    c_n = min(len(couplet), rng.randint(4, 10))
    s, a, t, b = (part_of([copy.deepcopy(m) for m in ms[:r_n]]) for ms in refrain)
    solo = part_of([copy.deepcopy(m) for m in couplet[:c_n]])
    first = refrain[0][0]
    for part, src in ((s, refrain[0]), (a, refrain[1]), (t, refrain[2]), (b, refrain[3]), (solo, couplet)):
        m1 = part.getElementsByClass(stream.Measure).first()
        for el in src[0].getElementsByClass((key.KeySignature, meter.TimeSignature)):
            if not m1.getElementsByClass(type(el)):
                m1.insert(0, copy.deepcopy(el))
    add_lyrics(s, rng.randint(1, 2), rng)
    add_lyrics(solo, rng.randint(2, 4), rng)
    add_chord_names(s, [s, a, t, b], rng)
    add_chord_names(solo, [solo, simple_harmony(solo, rng)], rng)
    for part, label in ((s, "REFRAIN"), (solo, rng.choice(["COUPLETS", "STROPHES", "SOLISTE"]))):
        te = expressions.TextExpression(label)
        te.placement = "above"
        te.style.fontWeight = "bold"
        part.getElementsByClass(stream.Measure).first().insert(0, te)
    answer = truth([s, a, t, b], NAMES)
    mel = truth([solo], ["x"])["x"]
    refrain_first = rng.random() < 0.6
    # couplets sur des systèmes d'une portée (« COUPLETS », « SOLISTE ») : chantés par le soliste, à la voix du haut ;
    # l'alto se tait, comme dans les partitions des chorales (« Toussaint » : soprano 45 notes, alto 14). Une ligne
    # seule à l'intérieur du chœur se chante, elle, à l'unisson (« Un signe grandiose ») : pas dans ces copies.
    answer["Soprano"] = (answer["Soprano"] + mel) if refrain_first else (mel + answer["Soprano"])
    choir = [staff_of([s, a], clef.TrebleClef(), "", ["up", "down"]), staff_of([t, b], clef.BassClef(), "", ["up", "down"])]
    verse = [staff_of([solo], clef.TrebleClef(), "", ["up"])]
    return ([choir, verse] if refrain_first else [verse, choir]), answer


def score_of(staves, title, rng):
    sc = stream.Score()
    if title:
        md = metadata.Metadata()
        md.title = f"{title}   {rng.choice('ABCDEKP')} {rng.randint(10, 299)}" + (f"-{rng.randint(1, 3)}" if rng.random() < 0.3 else "")
        md.composer = f"Musique : {rng.choice(NAMES_POOL)}"
        md.lyricist = f"Texte : {rng.choice(NAMES_POOL)}"
        sc.insert(0, md)
        first = staves[0].getElementsByClass(stream.Measure).first()
        te = expressions.TextExpression(rng.choice(TEMPI))
        te.placement = "above"
        te.style.fontWeight = "bold"
        first.insert(0, te)
    for st in staves:
        sc.insert(0, st)
    if len(staves) > 1:
        sc.insert(0, layout.StaffGroup(staves, symbol="bracket", barTogether=True))
    return sc


# ---------------------------------------------------------------------------------------------------- image
def look(rng):
    """Police et épaisseurs d'une page (les mêmes pour toutes ses parties)."""
    # lignes de portée d'au moins 0,21 : plus minces, le seuillage les rendait pointillées (« Ô Marie », 17 %), ce
    # que les vrais scans des recueils ne montrent pas (lignes continues)
    return {"font": rng.choice(FONTS), "staffLineWidth": rng.uniform(0.21, 0.28), "stemWidth": rng.uniform(0.18, 0.3),
            "barLineWidth": rng.uniform(0.22, 0.42), "ledgerLineThickness": 0.3}


def engrave(sc, xml_path, scale, style, fit=False, header=True):
    sc.write("musicxml", fp=str(xml_path))
    tk = verovio.toolkit()
    tk.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": scale, "adjustPageHeight": fit,
                   "footer": "none", "header": "auto" if header else "none", "breaks": "auto", "lyricSize": 4.0,
                   "spacingSystem": 10, "pageMarginLeft": 100, "pageMarginRight": 100,
                   "pageMarginTop": 80 if header else 20, "pageMarginBottom": 20 if fit else 80, **style})
    tk.loadFile(str(xml_path))
    pages = []
    for i in range(1, tk.getPageCount() + 1):
        png = cairosvg.svg2png(bytestring=tk.renderToSVG(i).encode(), output_width=2 * WIDTH, background_color="white")
        pages.append(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE))
    return pages


def stack(images, width):
    """Parties gravées à part posées l'une sous l'autre sur une page A4."""
    height = int(width * 297 / 210)
    page = np.full((height, width), 255, np.uint8)
    y = 0
    for img in images:
        h = min(img.shape[0], height - y)
        if h <= 0:
            return None
        page[y:y + h] = img[:h]
        y += h
    return page if y < height else None


def as_scan(img, rng):
    """Scan d'un recueil imprimé : encre qui bave ou s'amincit, réduit à 170 points par pouce, léger flou, page à peine
    penchée, seuillé en noir et blanc par le scanner (seuil variable), petites taches."""
    ink = 255 - img
    k = rng.choice([0, 0, 1, 2])
    if k:
        ker = np.ones((k + 1, k + 1), np.uint8)
        ink = cv2.dilate(ink, ker) if rng.random() < 0.6 else cv2.erode(ink, np.ones((2, 2), np.uint8))
    img = 255 - ink
    img = cv2.resize(img, (WIDTH, int(img.shape[0] * WIDTH / img.shape[1])), interpolation=cv2.INTER_AREA)
    h, w = img.shape
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-0.8, 0.8), 1.0)
    img = cv2.warpAffine(img, rot, (w, h), borderValue=255, flags=cv2.INTER_LINEAR)
    img = cv2.GaussianBlur(img.astype(np.float32), (0, 0), rng.uniform(0.35, 0.9))
    img += np.random.default_rng(rng.randint(0, 2**31)).normal(0, rng.uniform(4, 14), img.shape)
    if rng.random() < 0.8:  # scanner en noir et blanc
        img = np.where(img < rng.uniform(150, 200), 0, 255).astype(np.float32)
    specks = rng.randint(50, 600)
    rs = np.random.default_rng(rng.randint(0, 2**31))
    ys, xs = rs.integers(0, h, specks), rs.integers(0, w, specks)
    for y, x in zip(ys, xs):
        r = int(rs.integers(1, 3))
        cv2.circle(img, (int(x), int(y)), r, 0 if rs.random() < 0.7 else 255, -1)
    return np.clip(img, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------------------------------------------- main
def main():
    args = sys.argv[1:]
    seed = 1
    kinds = list(LAYOUTS)
    if "--graine" in args:
        i = args.index("--graine"); seed = int(args[i + 1]); args = args[:i] + args[i + 2:]
    if "--mises" in args:
        i = args.index("--mises"); kinds = args[i + 1].split(","); args = args[:i] + args[i + 2:]
    scale = 32
    if "--echelle" in args:
        i = args.index("--echelle"); scale = int(args[i + 1]); args = args[:i] + args[i + 2:]
    shard, shards = 0, 1
    if "--part" in args:  # « --part 2/4 » : 3e quart des œuvres (plusieurs fabrications en parallèle)
        i = args.index("--part"); shard, shards = map(int, args[i + 1].split("/")); args = args[:i] + args[i + 2:]
    out = pathlib.Path(args[0])
    count = int(args[1]) if len(args) > 1 else 20
    rng = random.Random(seed)
    out.mkdir(parents=True, exist_ok=True)
    choral, folk = bach_chorales(random.Random(seed), shard, shards), folk_melodies(random.Random(seed + 1), shard, shards)
    rng = random.Random(seed * 1009 + shard)
    weights = [LAYOUTS[k] for k in kinds]
    manifest = []
    made = 0
    while made < count:
        kind = rng.choices(kinds, weights)[0]
        try:
            name, parts, src = next(folk) if kind == "melodie" and rng.random() < 0.6 else next(choral)
        except StopIteration:
            break
        parts = trim([copy.deepcopy(p) for p in parts], rng)
        if kind == "melodie" and len(parts) == 4:
            parts = parts[:1]  # mélodie d'un choral : la voix de soprano seule
        if kind != "melodie" and len(parts) != 4:
            continue
        melody = None
        if kind == "mixte":
            want = next(iter(parts[0].recurse().getElementsByClass(meter.TimeSignature)), None)
            for _ in range(6):
                try:
                    _n2, p2, _s2 = next(choral)
                except StopIteration:
                    break
                ts2 = next(iter(p2[0].recurse().getElementsByClass(meter.TimeSignature)), None)
                if want is not None and ts2 is not None and ts2.ratioString == want.ratioString:
                    melody = trim([copy.deepcopy(p2[0])], rng)[0]
                    try:  # couplets transposés dans l'armure du refrain (même armure, comme dans les recueils)
                        from music21 import interval
                        ks1 = next(iter(parts[0].recurse().getElementsByClass(key.KeySignature)), key.KeySignature(0))
                        ks2 = next(iter(melody.recurse().getElementsByClass(key.KeySignature)), key.KeySignature(0))
                        iv = interval.Interval(ks2.asKey("major").tonic, ks1.asKey("major").tonic)
                        if iv.semitones > 6:  # le plus court chemin : jamais plus d'une quarte augmentée
                            iv = interval.Interval("-" + iv.complement.name)
                        elif iv.semitones < -6:
                            iv = interval.Interval(iv.complement.name)
                        melody = melody.transpose(iv)
                        for ks in melody.recurse().getElementsByClass(key.KeySignature):
                            ks.sharps = ks1.sharps
                        # tessiture d'une mélodie de recueil (médiane vers mi4 à la4) : une octave plus bas ou plus
                        # haut si la transposition l'en a sortie (sinon le moteur la ramène, à raison)
                        import statistics
                        med = statistics.median(n.pitch.midi for n in melody.recurse().notes if n.isNote)
                        if med > 73:
                            melody = melody.transpose(-12)
                        elif med < 60:
                            melody = melody.transpose(12)
                    except Exception:  # noqa: BLE001
                        pass
                    break
            if melody is None:
                continue
        set_time_symbol(parts + ([melody] if melody is not None else []), rng)
        try:
            if kind == "mixte":
                sections, answer = build_mixte(parts, melody, rng)
            else:
                staves, answer = build(kind, parts, rng)
                sections = [staves]
            title = rng.choice(["Seigneur, nous chantons", "Peuple de Dieu", "Viens, Esprit", "Ô Marie", "Pain de vie",
                                "Joie du ciel", "Vers toi", "Lumière"])
            case = out / f"{name}-{kind}"
            case.mkdir(parents=True, exist_ok=True)
            style = look(rng)
            if len(sections) == 1:
                pages = engrave(score_of(sections[0], title, rng), case / "gravure.musicxml", scale, style)
            else:
                images = []
                for k, staves in enumerate(sections):
                    sub = engrave(score_of(staves, title if k == 0 else None, rng), case / f"gravure-{k + 1}.musicxml",
                                  scale, style, fit=True, header=(k == 0))
                    if len(sub) != 1:
                        raise ValueError("partie sur plusieurs pages")
                    images.append(sub[0])
                page = stack(images, images[0].shape[1])
                pages = [page] if page is not None else []
        except Exception as e:  # noqa: BLE001
            print(f"écarté {name} ({kind}) : {type(e).__name__}: {e}", flush=True)
            continue
        if len(pages) != 1:  # une page, comme la plupart des chants des recueils
            for f in case.iterdir():
                f.unlink()
            case.rmdir()
            continue
        cv2.imwrite(str(case / "source.png"), as_scan(pages[0], rng))
        ts = next(iter(parts[0].recurse().getElementsByClass(meter.TimeSignature)), None)
        answer["_mesures"] = sum(len(st[0].getElementsByClass(stream.Measure)) for st in sections)
        answer["_indication"] = (ts.ratioString + (f" {ts.symbol}" if ts.symbol else "")) if ts else None
        (case / "truth.json").write_text(json.dumps(answer), encoding="utf-8")
        manifest.append(dict(cas=case.name, mise=kind, **src))
        made += 1
        print(case.name, flush=True)
    name = "manifeste.json" if shards == 1 else f"manifeste-{shard + 1}.json"
    (out / name).write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
