"""
Moteur de rendu : MusicXML -> une piste audio par voix.
Usage : python3 render.py <partition.mxl|.musicxml> <dossier_sortie> [--tempo 72] [--timbre choeur|piano|chant]
        [--langue fr|la|en|mos|dyu] [--paroles paroles.json]   (chant : voix chantées avec les paroles, essai)
"""
import argparse, copy, json, os, pathlib, re, shutil, statistics, subprocess, sys, zipfile
from fractions import Fraction
from music21 import converter, chord, clef, harmony, instrument, key, meter, note, stream, tempo as m21tempo
from music21.common.numberTools import opFrac

SF2 = os.environ.get("SOUNDFONT", "/usr/share/sounds/sf2/FluidR3_GM.sf2")
LABELS = {
    4: [("soprano", "Soprano"), ("alto", "Alto"), ("tenor", "Ténor"), ("basse", "Basse")],
    3: [("voix1", "Voix haute"), ("voix2", "Voix médiane"), ("voix3", "Voix basse")],
    2: [("voix1", "Voix haute"), ("voix2", "Voix basse")],
}
FR = {"C": "Do", "D": "Ré", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si"}
ACCOMP_WORDS = ("piano", "pno", "orgue", "organ", "org.", "accomp", "clavier", "keyboard", "guitare", "guitar")


def fr_name(p, octave=True):
    acc = {"#": "♯", "-": "♭", "##": "𝄪", "--": "𝄫"}.get(p.accidental.modifier if p.accidental else "", "")
    return FR[p.step] + acc + (str(p.octave) if octave and p.octave is not None else "")


def real_chords(part):
    return [c for c in part.recurse().getElementsByClass(chord.Chord) if not isinstance(c, harmony.ChordSymbol)]


def mean_pitch(obj):
    ps = [p.ps for n in obj.recurse().notes for p in n.pitches]
    return statistics.mean(ps) if ps else None


def needs_split(part):
    """Portée qui porte deux voix (S+A, T+B) : deux voix dans une bonne part des mesures, ou beaucoup d'accords.
    Une seule mesure à deux voix est presque toujours une erreur de lecture, pas une voix de plus."""
    sung = [m for m in part.getElementsByClass(stream.Measure) if m.recurse().notes]
    doubled = sum(1 for m in sung if sum(1 for v in m.voices if v.notes) >= 2)
    n = len(part.recurse().notes)
    return (sung and doubled >= 0.3 * len(sung)) or (n and len(real_chords(part)) > n * 0.3)


def keep_highest_or_lowest(line, pick):
    for c in real_chords(line):
        n = note.Note(pick(c.pitches, key=lambda p: p.ps))
        n.duration = copy.deepcopy(c.duration)
        if c.tie is not None:
            n.tie = copy.deepcopy(c.tie)
        for lyr in c.lyrics:
            n.lyrics.append(copy.deepcopy(lyr))
        c.activeSite.replace(c, n)


def split_staff(part):
    """Portée à deux voix (ex. S et A) -> deux parties, mesure par mesure."""
    top, bottom = stream.Part(), stream.Part()
    for m in part.getElementsByClass(stream.Measure):
        mt, mb = stream.Measure(number=m.number), stream.Measure(number=m.number)
        mt.paddingLeft = mb.paddingLeft = m.paddingLeft
        for el in m.getElementsByClass((clef.Clef, key.KeySignature, meter.TimeSignature)):
            mt.insert(el.offset, copy.deepcopy(el)); mb.insert(el.offset, copy.deepcopy(el))
        sung = [v for v in m.voices if v.notes]
        if len(sung) >= 2:
            sung.sort(key=mean_pitch, reverse=True)
            src_t, src_b = sung[0], sung[-1]
        else:
            src_t = src_b = sung[0] if sung else (m.voices[0] if m.voices else m)
        for src, dst in ((src_t, mt), (src_b, mb)):
            for el in src.notesAndRests:
                dst.insert(el.offset, copy.deepcopy(el))
        top.append(mt); bottom.append(mb)
    keep_highest_or_lowest(top, max)
    keep_highest_or_lowest(bottom, min)
    return [top, bottom]


def flatten_voices(part):
    p = copy.deepcopy(part)
    for m in p.getElementsByClass(stream.Measure):
        if m.voices:
            m.flattenUnnecessaryVoices(force=True, inPlace=True)
    keep_highest_or_lowest(p, max)
    return p


def is_accompaniment(part, trust_names=True):
    """Portée d'instrument : nommée comme telle, ou remplie d'accords de 3 notes et plus.
    Audiveris nomme « Piano » toute paire de portées liées par une accolade, même un chœur SATB :
    pour une partition lue par OMR, seul le contenu compte."""
    name = f"{part.partName or ''} {part.partAbbreviation or ''}".lower()
    if trust_names and any(w in name for w in ACCOMP_WORDS):
        return True
    notes = len(part.recurse().notes)
    big = sum(1 for c in real_chords(part) if len(c.pitches) >= 3)
    return notes > 0 and big > notes * 0.25


def sounding(line):
    return {m.number for m in line.getElementsByClass(stream.Measure) if m.recurse().notes}


# --- Noms des voix ------------------------------------------------------------------------------------------
# Noms lus dans la partition (MusicXML, ou texte lu par Audiveris) : abréviations de chœur, rôles d'un dialogue.

GENERIC_NAME = re.compile(r"^(voice|voix|piano|staff|part|partie|port[ée]e|instrument|p\d+|music|musique)?[\s.#-]*\d*$", re.I)
ABBR = {
    "s": "Soprano", "sop": "Soprano", "soprano": "Soprano", "sopranos": "Soprano", "sopr": "Soprano",
    "a": "Alto", "alt": "Alto", "alto": "Alto", "altos": "Alto", "c": "Alto", "contralto": "Alto",
    "t": "Ténor", "ten": "Ténor", "tenor": "Ténor", "ténor": "Ténor", "tenors": "Ténor", "ténors": "Ténor",
    "b": "Basse", "bs": "Basse", "bass": "Basse", "basse": "Basse", "basses": "Basse",
    "bar": "Baryton", "baryton": "Baryton", "baritone": "Baryton", "mez": "Mezzo", "mezzo": "Mezzo",
}
ACCENTS = {  # mots courants des chants, écrits sans accents en majuscules sur les partitions
    "fiancee": "fiancée", "fiance": "fiancé", "fiancees": "fiancées", "fiances": "fiancés", "tenor": "ténor",
    "recitant": "récitant", "recitante": "récitante", "pretre": "prêtre", "celebrant": "célébrant", "assemblee": "assemblée",
    "mariee": "mariée", "maries": "mariés", "epoux": "époux", "epouse": "épouse", "pere": "père", "mere": "mère",
    "frere": "frère", "freres": "frères", "soeur": "sœur", "soeurs": "sœurs", "choeur": "chœur", "eleve": "élève",
    "fidele": "fidèle", "fideles": "fidèles", "ecole": "école",
}
FEMALE, MALE = {"Soprano", "Alto", "Mezzo"}, {"Ténor", "Basse", "Baryton"}


def clean_name(raw):
    s = re.sub(r"\s+", " ", (raw or "").strip())
    return None if not s or GENERIC_NAME.match(s) else s


def pretty_name(raw):
    """« LA FIANCEE » → « La fiancée » ; « S. » → « Soprano »."""
    words = re.findall(r"[^\W\d_]+|\d+", raw)
    if len(words) == 1 and words[0].lower() in ABBR:
        return ABBR[words[0].lower()]
    out = []
    for i, w in enumerate(words):
        lw = ACCENTS.get(w.lower(), w.lower() if w.isupper() or i else w)
        out.append(lw[:1].upper() + lw[1:] if i == 0 else lw)
    return " ".join(out) or raw


def staff_names(raw, n):
    """Noms des n voix d'une portée : « S. A. » → Soprano, Alto ; « A. » à deux voix → Soprano, Alto (portée des femmes)."""
    name = clean_name(raw)
    if not name:
        return [None] * n
    tokens = re.findall(r"[^\W\d_]+", name)
    mapped = [ABBR.get(t.lower()) for t in tokens]
    if n == 1:
        return [pretty_name(name)]
    if len(tokens) >= n and all(mapped[:n]) and len(set(mapped[:n])) == n:
        return mapped[:n]
    if any(mapped) and all(m is None or m in FEMALE for m in mapped):
        return ["Soprano", "Alto"] if n == 2 else [f"Soprano {i + 1}" for i in range(n)]
    if any(mapped) and all(m is None or m in MALE for m in mapped):
        return ["Ténor", "Basse"] if n == 2 else [f"Basse {i + 1}" for i in range(n)]
    base = pretty_name(name)
    return [f"{base} (haut)", f"{base} (bas)"] if n == 2 else [f"{base} {i + 1}" for i in range(n)]


def share_lyrics(lines):
    """
    Deux voix sur une même portée (S et A, T et B) : les paroles y sont écrites une seule fois, entre les deux,
    et la lecture les attache à l'une d'elles. Une voix sans paroles reçoit celles de l'autre, note par note,
    là où les deux chantent en même temps (même mesure, même instant).
    """
    with_words = [l for l in lines if any(n.lyrics for n in l.recurse().notes)]
    if len(with_words) != 1 or len(lines) < 2:
        return
    src = with_words[0]
    table = {}
    for m in src.getElementsByClass(stream.Measure):
        for n in m.recurse().notes:
            if n.lyrics:
                table[(m.number, float(n.offset))] = n.lyrics[0]
    for line in lines:
        if line is src:
            continue
        for m in line.getElementsByClass(stream.Measure):
            for n in m.recurse().notes:
                lyr = table.get((m.number, float(n.offset)))
                if lyr is not None and not n.lyrics:
                    n.lyric = lyr.text
                    n.lyrics[0].syllabic = lyr.syllabic


def _sung_voices(m):
    """Nombre de lignes chantées dans une mesure (voix séparées, ou accords de deux notes)."""
    vs = [v for v in m.voices if any(True for _ in v.notes)]
    if len(vs) >= 2:
        return 2
    notes = list(m.recurse().notes)
    return 2 if notes and sum(1 for n in notes if n.isChord) > len(notes) / 2 else (1 if notes else 0)


def _is_choir_name(name):
    tokens = re.findall(r"[^\W\d_]+", clean_name(name) or "")
    return bool(tokens) and all(ABBR.get(t.lower()) for t in tokens)


def _low_clef(m, part):
    c = m.getContextByClass(clef.Clef) or next(iter(part.recurse().getElementsByClass(clef.Clef)), None)
    if c is None:
        return False
    return isinstance(c, (clef.BassClef, clef.Treble8vbClef)) or getattr(c, "octaveChange", 0) < 0 or c.sign == "F"


def _move(src, dst):
    """Remplace le contenu de la mesure dst par celui de src (notes, silences, voix)."""
    for el in list(dst.notesAndRests) + list(dst.voices):
        dst.remove(el)
    if src.voices:
        for v in src.voices:
            dst.insert(v.offset, copy.deepcopy(v))
    else:
        for n in src.notesAndRests:
            dst.insert(n.offset, copy.deepcopy(n))
    for el in list(src.notesAndRests) + list(src.voices):
        src.remove(el)


def merge_named_parts(parts):
    """
    Partition en dialogue (soliste seul, puis avec le chœur…) : Audiveris range les portées par position sur la page,
    pas par rôle ; une portée « LA FIANCÉE » peut ainsi contenir, sur certaines lignes, la portée ténor-basse du chœur.
    1. Dans les portées nommées d'après un rôle, les mesures à deux voix sont du chœur : elles vont à la portée de
       chœur de même registre (clé de fa → T. B., sinon S. A.) ; faute de place, le rôle garde la voix du haut.
    2. Les portées de même nom sont réunies en une seule voix, mesure par mesure.
    """
    sung_in = lambda m: any(True for _ in m.recurse().notes)
    parts = [copy.deepcopy(p) for p in parts]
    choirs = [p for p in parts if _is_choir_name(p.partName)]
    if choirs:
        for p in parts:
            if p in choirs or not clean_name(p.partName):
                continue
            for m in p.getElementsByClass(stream.Measure):
                if _sung_voices(m) < 2:
                    continue  # une seule voix : c'est le rôle qui chante
                low = _low_clef(m, p)
                moved = False
                for c in choirs:
                    tokens = [ABBR.get(t.lower()) for t in re.findall(r"[^\W\d_]+", clean_name(c.partName))]
                    if (low and any(t in MALE for t in tokens)) or (not low and any(t in FEMALE for t in tokens)):
                        target = next((x for x in c.getElementsByClass(stream.Measure) if x.number == m.number), None)
                        if target is not None and not sung_in(target):
                            _move(m, target)
                            moved = True
                            break
                if not moved and m.voices:  # pas de place au chœur : le rôle garde sa voix du haut, jamais coupé en deux
                    top = max((v for v in m.voices if any(True for _ in v.notes)), key=lambda v: mean_pitch(v) or 0)
                    for v in list(m.voices):
                        if v is not top:
                            m.remove(v)
    groups, order = {}, []
    for p in parts:
        key = (clean_name(p.partName) or "").lower().replace(".", "").strip() or f"#{id(p)}"
        if key not in groups:
            groups[key] = []; order.append(key)
        groups[key].append(p)
    merged = []
    for key in order:
        ps = groups[key]
        if len(ps) == 1:
            merged.append(ps[0]); continue
        base = ps[0]
        by_number = [{m.number: m for m in p.getElementsByClass(stream.Measure)} for p in ps[1:]]
        for m in base.getElementsByClass(stream.Measure):
            if sung_in(m):
                continue
            for table in by_number:
                other = table.get(m.number)
                if other is not None and sung_in(other):
                    _move(other, m)
                    break
        merged.append(base)
    return merged


def name_by_range(voices):
    """Voix sans nom : nommées d'après leur tessiture (Soprano, Alto, Ténor, Basse), numérotées si besoin."""
    taken = [v.partName for v in voices if v.partName]
    for v in voices:
        if v.partName:
            continue
        m = mean_pitch(v) or 60
        v.partName = "Soprano" if m >= 67 else "Alto" if m >= 60 else "Ténor" if m >= 53 else "Basse"
    counts = {}
    for v in voices:
        counts[v.partName] = counts.get(v.partName, 0) + 1
    seen = {}
    for v in voices:
        if counts[v.partName] > 1:
            seen[v.partName] = seen.get(v.partName, 0) + 1
            v.partName = f"{v.partName} {seen[v.partName]}"
    return voices


def voice_id(name, used):
    import unicodedata
    base = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "", base)[:20] or "voix"
    vid, k = base, 2
    while vid in used:
        vid = f"{base}{k}"; k += 1
    used.add(vid)
    return vid


def fold_solos(voices):
    """Une ligne qui ne chante que là où tout le chœur se tait (couplet d'un soliste) n'est pas une voix de plus :
    on la verse dans la voix la plus aiguë, qui porte la mélodie."""
    if len(voices) <= 4:
        return voices
    kept = list(voices)
    for v in sorted(voices, key=lambda v: len(v.recurse().notes)):
        others = [o for o in kept if o is not v]
        if len(kept) <= 4:
            break
        if getattr(v, "partName", None):  # voix nommée (soliste d'un dialogue…) : elle garde sa piste
            continue
        mine, rest = sounding(v), set().union(*(sounding(o) for o in others))
        if not mine or len(mine & rest) > 0.2 * len(mine):
            continue
        target = max(others, key=lambda o: mean_pitch(o) or 0)
        by_number = {m.number: m for m in target.getElementsByClass(stream.Measure)}
        for m in v.getElementsByClass(stream.Measure):
            if m.number in mine and m.number in by_number:
                dst = by_number[m.number]
                for el in list(dst.notesAndRests):
                    dst.remove(el)
                for el in m.notesAndRests:
                    dst.insert(el.offset, copy.deepcopy(el))
        kept.remove(v)
    return kept


def harmonize_keys(score):
    """Armure oubliée sur une portée (fréquent sur photo : 3 dièses lus au lieu de 4, ou aucun) :
    toutes les voix d'un chœur partagent la même armure, et la lecture perd des altérations bien plus
    souvent qu'elle n'en invente. Si toutes les armures lues vont dans le même sens, on prend la plus chargée
    pour toute la partition ; sinon (vrai changement dièses <-> bémols), la plus chargée de chaque mesure.
    Les notes sans altération écrite reçoivent alors l'altération de l'armure."""
    parts = [p for p in score.parts if p.recurse().notes]
    rows = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    if not rows:
        return 0
    count = min(len(r) for r in rows)
    keys = []  # armure en vigueur, par portée et par mesure
    for r in rows:
        current, ks = 0, []
        for m in r[:count]:
            if m.keySignature is not None:
                current = m.keySignature.sharps
            ks.append(current)
        keys.append(ks)
    # armures réellement imprimées (début de système), pour écarter un dièse vu une seule fois dans une tache
    printed = [m.keySignature.sharps for r in rows for m in r[:count] if m.keySignature is not None]
    seen = {k for k in printed if k}
    one_way = all(k > 0 for k in seen) or all(k < 0 for k in seen)
    trusted = [k for k in sorted(seen, key=abs, reverse=True) if printed.count(k) >= 2]
    best = trusted[0] if trusted else (statistics.mode(printed) if printed else 0)
    fixed = 0
    for j in range(count):
        target = best if one_way else max((ks[j] for ks in keys), key=abs)
        tks = key.KeySignature(target)
        for i, r in enumerate(rows):
            if keys[i][j] == target:
                continue
            carried = set()  # une altération écrite vaut pour la suite de la mesure
            for n in r[j].recurse().notes:
                for p in n.pitches:
                    if p.accidental is not None and p.accidental.displayStatus:
                        carried.add((p.step, p.octave))
                        continue
                    if (p.step, p.octave) in carried:
                        continue
                    want = tks.accidentalByStep(p.step)
                    have = p.accidental.alter if p.accidental is not None else 0
                    if (want.alter if want else 0) != have:
                        p.accidental = copy.deepcopy(want) if want else None
                        fixed += 1
    return fixed


# Centre de la tessiture de chaque pupitre (MIDI) : La4, Mi4, La3, Ré3.
CENTERS = {4: [69, 64, 57, 50]}


def pitches_of(obj):
    return [p.ps for n in obj.recurse().notes for p in n.pitches]


def shift_octaves(obj, octaves):
    if octaves:
        for n in obj.recurse().notes:
            for p in n.pitches:
                p.octave = (p.octave if p.octave is not None else 4) + octaves


def fix_octaves(voice, center=None):
    """Erreurs d'octave de la lecture optique, corrigées comme le ferait un chef de chœur :
    - toute la voix hors de sa tessiture (clé de sol du ténor lue sans le « 8 ») -> ramenée d'une octave ;
    - une mesure isolée à plus d'une sixte du reste de la voix (fausse indication 8va, clé mal lue) -> idem."""
    ps = pitches_of(voice)
    if not ps:
        return 0
    moved = 0
    if center is not None:
        med = statistics.median(ps)
        whole = -round((med - center) / 12) if abs(med - center) > 7 else 0
        shift_octaves(voice, whole)
        moved += abs(whole) * len(ps)
    ref = statistics.median(pitches_of(voice))
    for m in voice.getElementsByClass(stream.Measure):
        mp = pitches_of(m)
        if not mp:
            continue
        gap = statistics.median(mp) - ref
        if abs(gap) > 9:
            k = -round(gap / 12) or (-1 if gap > 0 else 1)
            shift_octaves(m, k)
            moved += len(mp)
    return moved


def lift_melody(voices):
    """Couplet écrit sur une seule portée en clé de sol, qu'Audiveris rattache parfois à la portée du bas :
    si seuls ténor et basse « chantent » une mesure, dans le registre aigu, c'est la mélodie des voix hautes."""
    rows = [list(v.getElementsByClass(stream.Measure)) for v in voices]
    for k in range(min(len(r) for r in rows)):
        s, a, t, b = (r[k] for r in rows)
        low = pitches_of(t) + pitches_of(b)
        if s.notes or a.notes or not low or statistics.median(low) < 64:
            continue
        for src, dst in ((t, s), (b, a)):
            for el in list(dst.notesAndRests):
                dst.remove(el)
            for el in list(src.notesAndRests):
                src.remove(el)
                dst.insert(el.offset, el)


def content_length(m):
    return max((el.offset + el.quarterLength for el in m.notesAndRests), default=0.0)


def align_measures(voices):
    """Même durée pour chaque mesure dans toutes les voix, sinon les pistes se décalent à l'écoute.
    Mesure trop courte (silence oublié) : complétée par un silence ; trop longue (point ou crochet mal lu) :
    ramenée à la bonne durée en resserrant proportionnellement ses notes."""
    measures = [list(v.getElementsByClass(stream.Measure)) for v in voices]
    count = max((len(ms) for ms in measures), default=0)
    bar = 4.0
    rebuilt = [stream.Part() for _ in voices]
    for k in range(count):
        row = [ms[k] if k < len(ms) else None for ms in measures]
        for m in row:
            ts = m.timeSignature if m is not None else None
            if ts is not None:
                bar = ts.barDuration.quarterLength
        # seules les voix qui chantent comptent : une voix qui se tait pendant le couplet d'un soliste n'a que des silences
        lengths = [round(content_length(m), 3) for m in row if m is not None and m.notes]
        target = bar
        if lengths:
            common = statistics.mode(lengths)
            edge = k == 0 or k == count - 1
            if lengths.count(common) * 2 > len(lengths):
                # la majorité a raison quand la mesure est plus longue (récitatif libre) ou incomplète en levée / en fin ;
                # ailleurs, une mesure trop courte dans toutes les voix est un silence oublié par la lecture : on complète
                target = common if common > bar or edge else bar
            elif len(set(lengths)) == len(lengths):
                target = max(lengths)    # aucune majorité (un seul chanteur, ou tous différents) : on ne coupe rien
        for i, m in enumerate(row):
            if m is None:
                m = stream.Measure(number=k + 1)
            if not m.notes:
                for el in list(m.notesAndRests):
                    m.remove(el)
            length = content_length(m)
            if length > target + 1e-6:
                ratio = target / length
                for el in sorted(m.notesAndRests, key=lambda e: e.offset):
                    off = opFrac(Fraction(el.offset * ratio).limit_denominator(48))
                    m.remove(el)
                    el.quarterLength = opFrac(max(Fraction(el.quarterLength * ratio).limit_denominator(48), Fraction(1, 48)))
                    m.insert(off, el)
                last = max(m.notesAndRests, key=lambda e: e.offset + e.quarterLength)
                over = content_length(m) - target
                if over > 1e-6:
                    last.quarterLength = opFrac(max(last.quarterLength - over, Fraction(1, 48)))
            length = content_length(m)
            if length < target - 1e-6:
                m.insert(opFrac(length), note.Rest(quarterLength=opFrac(target - length)))
            rebuilt[i].append(m)
    for v, r in zip(voices, rebuilt):
        r.partName = v.partName
    return rebuilt


def extract_voices(score, trust_names=True):
    """Les voix dans l'ordre de la page (portées de haut en bas, hampes en haut avant hampes en bas) :
    c'est ainsi qu'un chœur est écrit, et cet ordre ne dépend pas des erreurs d'octave de la lecture.
    Pour un fichier MusicXML ou MIDI (hauteurs exactes, ordre des pistes parfois quelconque), on trie par hauteur."""
    if not trust_names:
        harmonize_keys(score)
    sung = [p for p in score.parts if p.recurse().notes and not is_accompaniment(p, trust_names)]
    if not sung:
        sung = [p for p in score.parts if p.recurse().notes]
    sung = merge_named_parts(sung)
    voices = []
    for part in sung:
        lines = split_staff(part) if needs_split(part) else [flatten_voices(part)]
        for line, name in zip(lines, staff_names(part.partName or part.partAbbreviation, len(lines))):
            line.partName = name
        share_lyrics(lines)
        voices.extend(l for l in lines if l.recurse().notes)
    voices = fold_solos(voices)
    if len(voices) == 4 and not trust_names:
        lift_melody(voices)
    if trust_names:
        voices.sort(key=lambda v: mean_pitch(v) or 0, reverse=True)
    else:
        centers = CENTERS.get(len(voices))
        named = {"Soprano": 69, "Alto": 64, "Ténor": 57, "Basse": 50, "Mezzo": 66, "Baryton": 53}
        for i, v in enumerate(voices):
            fix_octaves(v, named.get((v.partName or "").split(" ")[0]) or (centers[i] if centers else None))
    if not any(v.partName for v in voices) and len(voices) == 4:
        for v, n in zip(voices, ("Soprano", "Alto", "Ténor", "Basse")):
            v.partName = n
    return name_by_range(align_measures(voices))


def detect_tempo(score):
    marks = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
    if marks and marks[0].number:
        return int(round(marks[0].getQuarterBPM()))
    ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
    return 90 if ts and ts.numerator in (6, 9, 12) and ts.denominator == 8 else 72


def prepare(part, tempo_qpm, timbre, velocity=None):
    p = copy.deepcopy(part)
    for el in list(p.recurse().getElementsByClass((instrument.Instrument, m21tempo.MetronomeMark))):
        el.activeSite.remove(el)
    first = p.getElementsByClass(stream.Measure).first() or p
    first.insert(0, instrument.Piano() if timbre == "piano" else instrument.Choir())
    first.insert(0, m21tempo.MetronomeMark(number=tempo_qpm, referent="quarter"))
    if velocity is not None:
        for n in p.recurse().notes:
            n.volume.velocity = velocity
    return p


RATE = 44100
_synth = None


def synth():
    """Synthétiseur SoundFont intégré (TinySoundFont) : ni fluidsynth ni ffmpeg à installer, sur Mac comme sur Windows."""
    global _synth
    if _synth is None:
        import tinysoundfont
        _synth = tinysoundfont.Synth(samplerate=RATE, gain=-3)
        _synth.sfload(SF2)
    return _synth


SFID = 0  # première (et seule) banque chargée


def encode_mp3(pcm, base: pathlib.Path):
    """PCM flottant (mono ou stéréo entrelacé) → MP3 160 kb/s."""
    import lameenc, numpy as np
    pcm = np.clip(pcm, -1, 1)
    enc = lameenc.Encoder()
    enc.set_bit_rate(160); enc.set_in_sample_rate(RATE); enc.set_channels(2); enc.set_quality(5)  # 5 : réglage standard de LAME, inaudible à 160 kb/s, 2,4 fois plus rapide que 2
    if pcm.ndim == 1:
        pcm = np.repeat(pcm, 2)
    elif pcm.ndim == 2:
        pcm = pcm.reshape(-1)  # (échantillons, 2) → gauche, droite entrelacés
    mp3 = base.with_suffix(".mp3")
    mp3.write_bytes(enc.encode((pcm * 32767).astype("<i2").tobytes()) + enc.flush())
    return mp3.name


def lyrics_text(part):
    """Paroles d'une voix sous la forme « Sain-te Ma-ri-e _ » (« _ » : la note tient la syllabe précédente)."""
    from chant import clean_syllable
    words, current, seen = [], "", False
    for n in part.stripTies().flatten().notes:
        lyr = n.lyrics[0] if getattr(n, "lyrics", None) else None
        text = clean_syllable(lyr.text) if lyr is not None else None
        if lyr is None or not text:
            if current:          # note tenue au milieu d'un mot : « ex-cel-_-sis »
                current += "_-"
            elif seen:
                words.append("_")
            continue
        seen = True
        current += text
        if lyr.syllabic in ("begin", "middle"):
            current += "-"
        else:
            words.append(current); current = ""
    if current:
        words.append(current)
    while words and words[-1] == "_":
        words.pop()
    return " ".join(words)


def to_mp3(sc, base: pathlib.Path):
    """Joue la partition note par note dans le synthétiseur (tempo exact, sans fichier MIDI intermédiaire)."""
    import lameenc, numpy as np
    s = synth()
    s.notes_off()
    events = []  # (seconde, 0 = relâcher / 1 = jouer, canal, note, vélocité)
    for chan, part in enumerate(sc.parts):
        mark = next(iter(part.recurse().getElementsByClass(m21tempo.MetronomeMark)), None)
        qpm = mark.getQuarterBPM() if mark else 72
        inst = next(iter(part.recurse().getElementsByClass(instrument.Instrument)), None)
        program = inst.midiProgram if inst is not None and inst.midiProgram is not None else 52
        s.program_select(chan, SFID, 0, program)
        sec = 60.0 / qpm
        for n in part.stripTies().flatten().notes:
            start, end = float(n.offset) * sec, float(n.offset + n.quarterLength) * sec
            vel = int(n.volume.velocity or 90)
            for p in n.pitches:
                events.append((start, 1, chan, int(p.midi), vel))
                events.append((max(start + 0.02, end - 0.01), 0, chan, int(p.midi), 0))
    events.sort()
    chunks, now = [], 0.0
    for t, kind, chan, key, vel in events + [(events[-1][0] + 2.0 if events else 1.0, -1, 0, 0, 0)]:
        frames = int(round((t - now) * RATE))
        if frames > 0:
            chunks.append(np.frombuffer(s.generate(frames), dtype=np.float32).copy())
            now += frames / RATE
        if kind == 1:
            s.noteon(chan, key, vel)
        elif kind == 0:
            s.noteoff(chan, key)
    pcm = np.concatenate(chunks) if chunks else np.zeros(2, np.float32)
    # même volume perçu que les autres sonorités (−14 LUFS), clarté et basses audibles sur téléphone
    import mixage
    kind = "piano" if any(getattr(next(iter(p.recurse().getElementsByClass(instrument.Instrument)), None), "midiProgram", None) == 0 for p in sc.parts) else "choeur"
    midis = [int(x.midi) for p in sc.parts for n in p.recurse().notes for x in n.pitches]
    return encode_mp3(mixage.finish(pcm.reshape(-1, 2), kind, midis), base)


def export_musicxml(src: pathlib.Path, dst: pathlib.Path, score):
    if src.suffix.lower() in (".mid", ".midi"):
        score.write("musicxml", fp=str(dst))  # MIDI : l'afficheur de partition a besoin de MusicXML
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            root = None
            if "META-INF/container.xml" in z.namelist():
                m = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml"))
                root = m.group(1).decode() if m else None
            root = root or next(n for n in z.namelist()
                                if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
            dst.write_bytes(z.read(root))
    else:
        shutil.copy(src, dst)


def mix(tracks, wet=0.16, pans=None):
    """Voix chantées ou chœur réel → fichier stéréo final : voix réparties dans l'espace, salle, −14 LUFS, limiteur."""
    import mixage
    pans = pans or mixage.pan_positions(len(tracks))
    return mixage.master(mixage.mix_stereo([(t, g, pans[i] if len(tracks) > 1 else 0.0) for i, (t, g) in enumerate(tracks)]), wet)


def real_choir(voices, labels, tempo_qpm, a):
    """Chœur réel : chaque voix jouée par de vrais chanteurs enregistrés, sur « aah » ou « ouh »."""
    import choeur, mixage
    if not choeur.available():
        sys.exit(f"Enregistrements du chœur réel introuvables : {choeur.pack_dir()}")
    hints = {"soprano": "S", "alto": "A", "tenor": "T", "basse": "B"}
    out = []
    for i, v in enumerate(voices):
        vid, vname = labels[i]
        print(f"Chœur {i+1}/{len(voices)} : {vname}", flush=True)
        x = choeur.sing_part(v, tempo_qpm, a.voyelle, hints.get(vid))
        x = mixage.phone_bass(x, mixage.bass_amount([p.midi for n in v.recurse().notes for p in n.pitches]))
        out.append(mixage.level_to(x, mixage.TARGET_VOICE))
    return out


def sing_voices(voices, labels, tempo_qpm, a):
    """Voix chantées : voix de femme pour les voix hautes, d'homme pour les voix basses ; paroles saisies ou de la partition."""
    import chant, mixage
    missing = chant.missing_voices()
    if missing:
        sys.exit(f"Voix de synthèse introuvables dans {chant.voice_dir()} : {', '.join(missing)}")
    typed = json.loads(pathlib.Path(a.paroles).read_text()) if a.paroles else {}
    sung = []
    for i, v in enumerate(voices):
        vid, vname = labels[i]
        midis = [p.midi for n in v.recurse().notes for p in n.pitches]
        kind = "femme" if statistics.mean(midis) >= 60 else "homme"
        print(f"Chant {i+1}/{len(voices)} : {vname} ({chant.ensemble_size()} voix {'de femme' if kind == 'femme' else 'd’homme'})", flush=True)
        x = mixage.polish_voice(chant.sing_part(v, tempo_qpm, kind, a.langue, typed.get(vid)), kind)
        sung.append(mixage.level_to(mixage.phone_bass(x, mixage.bass_amount(midis)), mixage.TARGET_VOICE))
    return sung


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--tempo", type=int, default=0)
    ap.add_argument("--timbre", choices=["choeur", "piano", "chant", "reel"], default="choeur")
    ap.add_argument("--voyelle", choices=["ah", "oo"], default="ah", help="chœur réel : « aah » ou « ouh »")
    ap.add_argument("--langue", choices=["fr", "la", "en", "mos", "dyu"], default="fr")
    ap.add_argument("--paroles", help="fichier JSON { id de voix : paroles } saisies par l'utilisateur")
    ap.add_argument("--omr", action="store_true", help="partition lue par Audiveris : ignorer les noms de portées")
    ap.add_argument("--sans-travail", action="store_true", help="pas de pistes de travail (lecture directe pour le mobile, qui mixe lui-même)")
    a = ap.parse_args()

    if not pathlib.Path(SF2).exists():
        sys.exit(f"Banque de sons introuvable : {SF2}")
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    score = converter.parse(a.src)
    tempo_qpm = a.tempo or detect_tempo(score)
    voices = extract_voices(score, trust_names=not a.omr)
    if not voices:
        sys.exit("Aucune note n’a été reconnue dans la partition.")

    used = set()
    labels = [(voice_id(v.partName, used), v.partName) for v in voices]  # noms lus dans la partition, ou tessiture
    sung = sing_voices(voices, labels, tempo_qpm, a) if a.timbre == "chant" else real_choir(voices, labels, tempo_qpm, a) if a.timbre == "reel" else None
    wet = 0.06 if a.timbre == "reel" else 0.16  # le chœur réel a déjà sa salle dans les enregistrements
    # paroles saisies : gardées dans le manifeste, pour les retrouver à la prochaine modification
    typed_lyrics = json.loads(pathlib.Path(a.paroles).read_text()) if a.paroles else {}
    entries = []
    for i, v in enumerate(voices):
        vid, vname = labels[i]
        if sung:
            stem = encode_mp3(mix([(sung[i], 1.0)], wet), out / vid)
        else:
            stem = to_mp3(stream.Score([prepare(v, tempo_qpm, a.timbre)]), out / vid)
        work = ""
        if not a.sans_travail:
            if sung:
                # piste de travail : sa voix au centre, 12 dB devant ; les autres écartées sur les côtés
                side = [(-0.6 if k % 2 == 0 else 0.6) for k in range(len(sung))]
                pans = [0.0 if j == i else side[j] for j in range(len(sung))]
                work = encode_mp3(mix([(x, 1.0 if i == j else 0.25) for j, x in enumerate(sung)], wet, pans), out / f"{vid}_travail")
            else:
                practice = stream.Score()
                for j, other in enumerate(voices):
                    practice.insert(0, prepare(other, tempo_qpm, a.timbre, 112 if i == j else 27))  # sa voix ≈ 12 dB devant
                work = to_mp3(practice, out / f"{vid}_travail")
        pitches = [p for n in v.recurse().notes for p in n.pitches]
        lo, hi = min(pitches, key=lambda p: p.ps), max(pitches, key=lambda p: p.ps)
        entries.append({"id": vid, "name": vname, "stem": stem, "practice": work,
                        "notes": len(v.recurse().notes), "range": [fr_name(lo), fr_name(hi)],
                        "lyrics": typed_lyrics.get(vid) or lyrics_text(v), "sung": len(v.stripTies().flatten().notes)})
        print(f"Voix {i+1}/{len(voices)} : {vname} ({fr_name(lo)} à {fr_name(hi)})", flush=True)

    if sung:
        tutti = encode_mp3(mix([(x, 1.0) for x in sung], wet), out / "tutti")
    else:
        tutti = to_mp3(stream.Score([prepare(v, tempo_qpm, a.timbre) for v in voices]), out / "tutti")
    export_musicxml(pathlib.Path(a.src), out / "score.musicxml", score)
    ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
    ks = score.analyze("key")
    manifest = {
        "tempo": tempo_qpm, "timbre": a.timbre, "tutti": tutti, "score": "score.musicxml",
        **({"langue": a.langue} if a.timbre == "chant" else {}),
        **({"voyelle": a.voyelle} if a.timbre == "reel" else {}),
        "measures": len(score.parts[0].getElementsByClass(stream.Measure)),
        "timeSignature": ts.ratioString if ts else None,
        "key": f"{fr_name(ks.tonic, octave=False)} {'majeur' if ks.mode == 'major' else 'mineur'}",
        "voices": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Terminé : {len(voices)} voix, tonalité {manifest['key']}, fichiers dans {out}")


if __name__ == "__main__":
    main()
