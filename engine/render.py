"""
Moteur de rendu : MusicXML -> une piste audio par voix.
Usage : python3 render.py <partition.mxl|.musicxml> <dossier_sortie> [--tempo 72] [--timbre choeur|piano|chant]
        [--langue fr|la|en|mos|dyu] [--paroles paroles.json]   (chant : voix chantées avec les paroles, essai)
"""
import argparse, copy, json, os, pathlib, re, shutil, statistics, subprocess, sys, zipfile
from fractions import Fraction
from music21 import converter, chord, clef, harmony, instrument, key, layout, meter, note, pitch, stream, tempo as m21tempo
from music21.common.numberTools import opFrac
import coherence

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


def needs_split(part, choir=None):
    """Portée qui porte deux voix (S+A, T+B) : deux voix dans une bonne part des mesures, ou beaucoup d'accords.
    Une seule mesure à deux voix est presque toujours une erreur de lecture, pas une voix de plus.
    choir : numéros des mesures où le chœur chante ensemble (plusieurs portées) ; on n'y juge que celles-là quand la
    portée y chante assez, pour qu'un couplet de soliste rangé dans la même partie que le refrain S. A. ne fasse pas
    passer celle-ci pour une seule voix (« Toussaint » usée : alto du refrain perdu)."""
    sung = [m for m in part.getElementsByClass(stream.Measure) if m.recurse().notes]
    if choir is not None and CHOIR_ONLY:
        together = [m for m in sung if m.number in choir]
        if len(together) >= 2 and len(together) < len(sung):
            sung = together
            notes = [n for m in sung for n in m.recurse().notes]
            chords = [c for c in notes if isinstance(c, chord.Chord) and not isinstance(c, harmony.ChordSymbol)]
            doubled = sum(1 for m in sung if sum(1 for v in m.voices if v.notes) >= 2)
            return doubled >= 0.3 * len(sung) or (notes and len(chords) > len(notes) * 0.3)
    doubled = sum(1 for m in sung if sum(1 for v in m.voices if v.notes) >= 2)
    n = len(part.recurse().notes)
    return (sung and doubled >= 0.3 * len(sung)) or (n and len(real_chords(part)) > n * 0.3)


CHOIR_ONLY = os.environ.get("PUPITRE_DEUX_VOIX_CHOEUR", "1") == "1"


def choir_measures(parts):
    """Numéros des mesures chantées par au moins deux portées (le chœur ensemble, pas un couplet de soliste)."""
    count = {}
    for p in parts:
        for m in p.getElementsByClass(stream.Measure):
            if m.recurse().notes:
                count[m.number] = count.get(m.number, 0) + 1
    return {k for k, v in count.items() if v >= 2}


def keep_highest_or_lowest(line, pick):
    for c in real_chords(line):
        if not c.pitches:
            continue  # accord sans tête (lecture abîmée) : laissé muet
        n = note.Note(pick(c.pitches, key=lambda p: p.ps))
        n.duration = copy.deepcopy(c.duration)
        if c.tie is not None:
            n.tie = copy.deepcopy(c.tie)
        for lyr in c.lyrics:
            n.lyrics.append(copy.deepcopy(lyr))
        c.activeSite.replace(c, n)


GAPS = os.environ.get("PUPITRE_TROUS", "1") != "0"  # banc d'essai : 0 pour comparer sans fill_gaps
MAIN_VOICES = os.environ.get("PUPITRE_VOIX_PRINCIPALES", "1") != "0"  # 0 : 3 voix lues ou plus → la plus aiguë et la plus grave, comme avant


def _sounding(dst):
    """Intervalles (début, fin) où la ligne chante déjà une note."""
    return [(float(n.offset), float(n.offset + n.quarterLength)) for n in dst.notes]


def _place(dst, n):
    """Note posée dans un silence de la ligne : les silences qu'elle recouvre sont raccourcis autour d'elle."""
    a, b = float(n.offset), float(n.offset + n.quarterLength)
    for r in list(dst.getElementsByClass(note.Rest)):
        ra, rb = float(r.offset), float(r.offset + r.quarterLength)
        if rb <= a + 1e-6 or ra >= b - 1e-6:
            continue
        dst.remove(r)
        for x, y in ((ra, a), (b, rb)):
            if y - x > 1e-6:
                dst.insert(opFrac(x), note.Rest(quarterLength=opFrac(y - x)))
    dst.insert(n.offset, n)


def _free(dst, a, b):
    return all(y <= a + 1e-6 or x >= b - 1e-6 for x, y in _sounding(dst))


def fill_gaps(mt, mb, others, lost=None):
    """
    Notes qu'une lecture serrée perd en séparant deux voix d'une portée : (1) accord de la voix du haut là où celle du
    bas se tait (la lecture a rattaché les deux têtes à la même hampe) : sa note basse va à la voix du bas, et
    inversement ; (2) troisième « voix » créée par la lecture (tête isolée) : ses notes vont dans le silence de la
    voix la plus proche en hauteur. Rend le nombre de notes rendues.
    """
    added = 0
    for src, dst, pick in ((mt, mb, min), (mb, mt, max)):
        for c in [c for c in src.getElementsByClass(chord.Chord) if len(c.pitches) >= 2]:
            a, b = float(c.offset), float(c.offset + c.quarterLength)
            if _free(dst, a, b):
                n = note.Note(pick(c.pitches, key=lambda p: p.ps))
                n.duration = copy.deepcopy(c.duration)
                if c.tie is not None:  # note liée par-dessus la barre : une seule attaque, comme dans l'autre voix
                    n.tie = copy.deepcopy(c.tie)
                n.offset = c.offset
                _place(dst, n)
                added += 1
    for v in others:
        for n in v.notes:
            if not n.pitches:
                continue  # accord sans tête (lecture abîmée)
            a, b = float(n.offset), float(n.offset + n.quarterLength)
            ps = statistics.mean(p.ps for p in n.pitches)
            near = sorted((mt, mb), key=lambda line: abs((mean_pitch(line) or ps) - ps))
            for line in near:
                if _free(line, a, b):
                    m = copy.deepcopy(n)
                    m.offset = n.offset
                    _place(line, m)
                    added += 1
                    break
            else:
                if lost is not None:
                    lost.append(n)  # aucune des deux voix n'a de place pour elle
    return added


def _leaps(line, pick):
    """Somme des sauts mélodiques d'une voix dans la mesure (demi-tons), d'après la note que la voix garde d'un accord."""
    ps = [pick(p.ps for p in n.pitches) for n in sorted(line.notes, key=lambda n: float(n.offset)) if n.pitches]
    return sum(abs(b - a) for a, b in zip(ps, ps[1:]))


def _crossings(mt, mb):
    """Nombre de moments où la voix du haut passe sous celle du bas."""
    count = 0
    for a in mt.notes:
        for b in mb.notes:
            if a.pitches and b.pitches and float(a.offset) < float(b.offset + b.quarterLength) - 1e-6 \
                    and float(b.offset) < float(a.offset + a.quarterLength) - 1e-6 \
                    and max(p.ps for p in a.pitches) < min(p.ps for p in b.pitches):
                count += 1
    return count


def two_voices(m, sung, model):
    """
    Mesure où la lecture a créé trois ou quatre « voix » sur une portée à deux voix (tête isolée, rythme mal compris) :
    quelles sont les deux voix du chœur ? Chaque paire est essayée (les autres notes vont dans les silences des deux
    voix, fill_gaps) et jugée comme le ferait un chef : le moins de notes perdues, les lignes les plus conjointes, pas
    de croisement. À égalité, la plus aiguë et la plus grave (l'ancien choix). Rend (mesure du haut, mesure du bas).
    """
    best = None
    for i in range(len(sung)):
        for j in range(i + 1, len(sung)):
            mt, mb = copy.deepcopy(model), copy.deepcopy(model)
            for src, dst in ((sung[i], mt), (sung[j], mb)):
                for el in src.notesAndRests:
                    dst.insert(el.offset, copy.deepcopy(el))
            lost = []
            fill_gaps(mt, mb, [v for k, v in enumerate(sung) if k not in (i, j)], lost)
            cost = 5 * len(lost) + _leaps(mt, max) + _leaps(mb, min) + 4 * _crossings(mt, mb)
            rank = (cost, 0 if (i, j) == (0, len(sung) - 1) else 1)
            if best is None or rank < best[0]:
                best = (rank, mt, mb)
    return best[1], best[2]


STEMS = os.environ.get("PUPITRE_QUEUES", "1") == "1"


def stem_way(v):
    """Sens des queues d'une voix : « up » ou « down » si les deux tiers au moins vont dans ce sens, sinon None."""
    dirs = [n.stemDirection for n in v.notes if getattr(n, "stemDirection", None) in ("up", "down")]
    if len(dirs) < max(1, 0.5 * len(v.notes)):
        return None
    for way in ("up", "down"):
        if dirs.count(way) >= 2 / 3 * len(dirs):
            return way
    return None


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
            sung.sort(key=lambda v: mean_pitch(v) or 0.0, reverse=True)  # accord sans hauteur (lecture abîmée) : en bas
            if len(sung) == 2 and STEMS:
                # voix croisées (basse un instant au-dessus du ténor) : le sens des queues dit qui est en haut
                ways = [stem_way(v) for v in sung]
                if ways == ["down", "up"]:
                    sung.reverse()
            src_t, src_b = sung[0], sung[-1]
        else:
            src_t = src_b = sung[0] if sung else (m.voices[0] if m.voices else m)
            # voix muette écrite exprès (silence caché : couplet du soliste, couplets.py) : la voix du bas se tait,
            # au lieu de chanter la mélodie à l'unisson
            mute = [v for v in m.voices if not v.notes and v.notesAndRests
                    and all(r.style.hideObjectOnPrint for r in v.notesAndRests)]
            if len(sung) == 1 and mute:
                src_b = mute[0]
        if len(sung) >= 3 and GAPS and MAIN_VOICES:
            mt, mb = two_voices(m, sung, mt)
            top.append(mt); bottom.append(mb)
            continue
        for src, dst in ((src_t, mt), (src_b, mb)):
            for el in src.notesAndRests:
                dst.insert(el.offset, copy.deepcopy(el))
        if len(sung) >= 2 and GAPS:
            fill_gaps(mt, mb, sung[1:-1])
        top.append(mt); bottom.append(mb)
    keep_highest_or_lowest(top, max)
    keep_highest_or_lowest(bottom, min)
    return [top, bottom]


SOLO_SYSTEMS = os.environ.get("PUPITRE_SYSTEMES_SOLO", "1") == "1"
SOLO_RUN = int(os.environ.get("PUPITRE_SOLO_MESURES", "4"))  # mesures de suite chantées par une seule portée
SOLOIST = os.environ.get("PUPITRE_COUPLETS_SOLISTE", "1") == "1"  # page mêlée : ligne seule sans accord = soliste


def solo_systems(parts, soloist=False, systems=None):
    """
    Système d'une seule portée entre des systèmes en chœur (couplet en mélodie seule après un refrain sur S+A / T+B :
    la moitié des chants des recueils mêlent ainsi les mises en page). Audiveris range cette portée dans l'une des
    parties, souvent celle du bas : la mélodie passait au ténor ou à la basse (clé de sol puis de fa dans la même
    partie), ou à la soprano et à l'alto à l'unisson (vrais recueils : alto presque entièrement recopié sur la
    soprano dans 13 % des lectures à quatre voix). Au moins SOLO_RUN mesures de suite chantées par une seule partie,
    en clé de sol, à une seule voix (ou dès la 1re si Audiveris a marqué les autres portées non imprimées,
    staff-details print-object="no" ; les lectures assemblées de plusieurs images ne le marquent presque jamais) :
    la mélodie va à la partie du haut (soprano et alto à l'unisson, comme une ligne seule sur la portée des femmes
    dans les partitions des chorales) ; la partie d'où elle vient se tait. Essayé et écarté : alto muet pendant la
    mélodie (soliste seul) — les partitions des chorales la font chanter à l'unisson (Psaume 85, Psaume 24, « Un signe
    grandiose » : alto 100 → 67 %). Moins de SOLO_RUN mesures : passage du chœur où les autres voix se taisent un
    instant, laissé comme avant. Rend le nombre de mesures déplacées.
    """
    if not SOLO_SYSTEMS or len(parts) < 2:
        return 0
    rows = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    n = min(len(r) for r in rows)
    hidden = [False] * len(parts)
    clefs = [None] * len(parts)
    solo = []  # (mesure, partie qui chante seule, portées absentes marquées)
    for k in range(n):
        for i, r in enumerate(rows):
            for sl in r[k].getElementsByClass(layout.StaffLayout):
                if sl.hidden is not None:
                    hidden[i] = bool(sl.hidden)
            head = [c for c in r[k].getElementsByClass(clef.Clef) if c.offset == 0]
            if head:
                clefs[i] = head[0]
        sounding = [i for i, r in enumerate(rows) if r[k].recurse().notes]
        if len(sounding) != 1:
            solo.append(None)
            continue
        i = sounding[0]
        m = rows[i][k]
        c = clefs[i]
        sung = [v for v in m.voices if v.notes] if m.voices else [m]
        if c is None or c.sign != "G" or (c.octaveChange or 0) != 0 or len(sung) != 1:
            solo.append(None)
            continue
        marked = sum(1 for j in range(len(parts)) if not hidden[j]) == 1
        solo.append((i, marked))
    # une suite d'au moins SOLO_RUN mesures (couplet, soliste) ; plus court, c'est un passage du chœur où les autres
    # voix se taisent un instant (laissé comme avant) ; portées absentes marquées par Audiveris : dès la 1re mesure
    keep = [False] * n
    k = 0
    while k < n:
        if solo[k] is None:
            k += 1
            continue
        j = k
        while j < n and solo[j] is not None:
            j += 1
        if j - k >= SOLO_RUN or any(solo[x][1] for x in range(k, j)):
            for x in range(k, j):
                keep[x] = True
        k = j
    # page mêlée (systèmes d'une portée vus sur l'image, omr.mark_systems) : une ligne seule sans accord y est un
    # couplet du soliste, chanté à la voix du haut seulement (« Toussaint », Psaume 22 des chorales : l'alto se tait)
    runs, k = [], 0
    while k < n:
        if not keep[k]:
            k += 1
            continue
        j = k
        while j < n and keep[j]:
            j += 1
        runs.append((k, j))
        k = j
    single = single_staff_measures(rows[0], n, systems) if soloist else set()
    done = 0
    for a, b in runs:
        chords = any(isinstance(el, chord.Chord) for x in range(a, b) for el in rows[solo[x][0]][x].recurse().notes)
        # soliste : toute la ligne dans des systèmes d'une seule portée (« Toussaint », psaumes) ; une ligne seule sur
        # la portée des femmes pendant que celle des hommes montre des pauses (« Un signe grandiose ») se chante à
        # l'unisson, même si sa fin tombe dans un dernier système d'une portée
        mute_alto = soloist and not chords and all(x in single for x in range(a, b))
        for k in range(a, b):
            i = solo[k][0]
            if i == 0 and not mute_alto:
                continue  # déjà dans la partie du haut : la soprano et l'alto la chantent à l'unisson, comme avant
            m = rows[i][k]
            sung = [v for v in m.voices if v.notes] if m.voices else [m]
            line = [copy.deepcopy(el) for el in sung[0].notesAndRests]
            dur = max((float(el.offset + el.duration.quarterLength) for el in line), default=0.0)
            # la mesure du haut reçoit la mélodie ; celle d'où elle vient (ténor, basse) se tait
            for target in {id(rows[0][k]): rows[0][k], id(m): m}.values():
                for el in list(target.notesAndRests) + list(target.voices):
                    target.remove(el)
            top = rows[0][k]
            if mute_alto:
                v1, v2 = stream.Voice(id="1"), stream.Voice(id="2")
                for el in line:
                    v1.insert(el.offset, el)
                at = 0.0
                for q in _plain_lengths(dur or 4.0):  # silence caché de l'alto, en durées simples
                    r = note.Rest(quarterLength=q)
                    r.style.hideObjectOnPrint = True
                    v2.insert(at, r)
                    at += q
                top.insert(0, v1)
                top.insert(0, v2)
            else:
                for el in line:
                    top.insert(el.offset, el)
            if i != 0:
                m.insert(0, note.Rest(quarterLength=dur or 4.0))
            done += 1
    return done


def single_staff_measures(top_row, n, systems):
    """Mesures (indices) des systèmes d'une seule portée. Débuts de système écrits par Audiveris s'ils sont autant que
    les systèmes vus sur l'image ; sinon mesures comptées sur les barres de l'image, si leur total est celui de la
    lecture (à une mesure près). Sinon : aucune (inconnu, l'alto n'est pas rendu muet)."""
    if not systems:
        return set()
    starts = [k for k in range(n) if any(sl.isNew for sl in top_row[k].getElementsByClass(layout.SystemLayout))]
    if not starts or starts[0] != 0:
        starts = [0] + starts
    if len(starts) == len(systems):
        bounds = starts + [n]
    else:
        counts = [m for _s, m in systems]
        if not all(counts) or abs(sum(counts) - n) > 1:
            return set()
        bounds = [0]
        for c in counts:
            bounds.append(min(n, bounds[-1] + c))
        bounds[-1] = n
    out = set()
    for (st, _m), a, b in zip(systems, bounds, bounds[1:]):
        if st == 1:
            out.update(range(a, b))
    return out


def _plain_lengths(length):
    out = []
    for q in (8.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25):
        while length >= q - 1e-6:
            out.append(q)
            length -= q
    return out


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
# noms de voix mal lus par l'OCR (« ’I‘cnor » pour Tenor : T lu ’I‘, e lu c) : un mot d'au moins 4 lettres à 2 lettres
# près d'un nom de voix est ce nom (« Song bal la Wende », photo WhatsApp : ténor coupé en deux voix, 7 voix pour 4)
FUZZY_NAMES = os.environ.get("PUPITRE_NOMS_APPROCHES", "1") == "1"
DEBRIS = os.environ.get("PUPITRE_DEBRIS", "1") == "1"  # fold_solos : voix fantôme de quelques notes écartée
OVERLAP = int(os.environ.get("PUPITRE_MESURE_COMMUNE", "1"))  # merge_named_parts : mesures communes tolérées
SOLO_APART = os.environ.get("PUPITRE_SOLO_A_PART", "1") == "1"  # merge_named_parts : ligne seule ≠ portée à deux voix
NAMED_FIRST = os.environ.get("PUPITRE_NOMMEES_DABORD", "1") == "1"  # merge_named_parts : parties bien nommées d'abord
_FULL = [k for k in ABBR if len(k) >= 4]


def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def abbr(token):
    """Voix désignée par un mot du nom de la portée (abréviation, nom complet, ou nom complet mal lu), sinon None."""
    t = token.lower()
    if t in ABBR:
        return ABBR[t]
    if FUZZY_NAMES and len(t) >= 4:
        best = min(_FULL, key=lambda k: _lev(t, k))
        if _lev(t, best) <= 2 and _lev(t, best) < len(t) - 2:
            return ABBR[best]
    return None


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
    mapped = [abbr(t) for t in tokens]
    if n == 1:
        return [pretty_name(name)]
    if len(tokens) >= n and all(mapped[:n]) and len(set(mapped[:n])) == n:
        return mapped[:n]
    if any(mapped) and all(m is None or m in FEMALE for m in mapped):
        return ["Soprano", "Alto"] if n == 2 else [f"Soprano {i + 1}" for i in range(n)]
    if any(mapped) and all(m is None or m in MALE for m in mapped):
        return ["Ténor", "Basse"] if n == 2 else [f"Basse {i + 1}" for i in range(n)]
    words = {t.lower() for t in tokens}
    if words & {"femmes", "dames", "women", "ladies"}:
        return ["Soprano", "Alto"] if n == 2 else [f"Soprano {i + 1}" for i in range(n)]
    if words & {"hommes", "men"}:
        return ["Ténor", "Basse"] if n == 2 else [f"Basse {i + 1}" for i in range(n)]
    # « Chœur » devant une portée à deux voix (ou ce nom mal lu : « Chciuur ») : un chef de chœur nomme ces voix
    # d'après leur tessiture et leur place (Soprano, Alto, Ténor, Basse), pas « Chœur (haut) » et « Chœur (bas) »
    return [None] * n


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
    return bool(tokens) and all(abbr(t) for t in tokens)


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

    def home(low):
        # portée de chœur du registre : clé de fa → T. B., clé de sol → S. A.
        for c in choirs:
            tokens = [abbr(t) for t in re.findall(r"[^\W\d_]+", clean_name(c.partName))]
            if (low and any(t in MALE for t in tokens)) or (not low and any(t in FEMALE for t in tokens)):
                return c
        return None

    if choirs:
        # Audiveris range les portées d'une ligne par leur position, pas par leur rôle : sur une ligne « soliste, S. A.,
        # T. B. », la portée S. A. peut se retrouver dans la partie « B. », et T. B. dans celle du soliste.
        # Toute mesure à deux voix est du chœur : elle va à la portée de chœur de sa clé, si elle y est libre.
        for _round in range(3):
            changed = False
            for p in parts:
                for m in p.getElementsByClass(stream.Measure):
                    if _sung_voices(m) < 2:
                        continue
                    target_part = home(_low_clef(m, p))
                    if target_part is None or target_part is p:
                        continue
                    target = next((x for x in target_part.getElementsByClass(stream.Measure) if x.number == m.number), None)
                    if target is not None and not sung_in(target):
                        _move(m, target)
                        changed = True
            if not changed:
                break
        for p in parts:
            if p in choirs or not clean_name(p.partName):
                continue
            for m in p.getElementsByClass(stream.Measure):
                if _sung_voices(m) >= 2 and m.voices:  # pas de place au chœur : le rôle garde sa voix du haut
                    top = max((v for v in m.voices if any(True for _ in v.notes)), key=lambda v: mean_pitch(v) or 0)
                    for v in list(m.voices):
                        if v is not top:
                            m.remove(v)
    def name_key(p):
        # « S. » sur les lignes suivantes = « Soprano » de la première ligne ; « S. A. » = « Soprano Alto »
        name = clean_name(p.partName)
        if not name:
            return f"#{id(p)}"
        tokens = re.findall(r"[^\W\d_]+", name)
        mapped = [abbr(t) for t in tokens]
        if tokens and all(mapped):
            return "|".join(mapped)
        whole = abbr("".join(tokens)) if len(tokens) > 1 else None  # « ’I‘cnor » : l'apostrophe coupait le mot
        return whole or name.lower().replace(".", "").strip()

    def sung_numbers(p):
        return {m.number for m in p.getElementsByClass(stream.Measure) if sung_in(m)}

    def weak(p):
        # nom absent, générique ou mal lu par l'OCR (« I‘. », « Voice ») : on ne s'y fie pas
        name = clean_name(p.partName)
        if not name:
            return True
        tokens = re.findall(r"[^\W\d_]+", name)
        return not tokens or (not all(abbr(t) for t in tokens) and len("".join(tokens)) <= 2)

    def low(p):
        c = next(iter(p.recurse().getElementsByClass(clef.Clef)), None)
        return c is not None and (c.sign == "F" or getattr(c, "octaveChange", 0) < 0)

    # Audiveris crée une nouvelle portée logique dès que le nom change d'une ligne à l'autre (« Soprano » puis « S. »,
    # ou un nom mal lu) : chaque portée est rangée dans la « voix » qui ne chante pas en même temps qu'elle,
    # de même nom ; à défaut (nom absent ou mal lu), de même clé et de même registre.
    slots = []
    # parties bien nommées d'abord, puis celles au nom absent ou illisible, rangées par clé et registre : une partie
    # « Voice » venue en tête ouvrait sa propre voix, que « S. » ne rejoignait plus (« Song bal la Wende », portées vides
    # masquées par MuseScore : 6 voix pour 4)
    order_parts = parts if not NAMED_FIRST else [p for p in parts if not weak(p)] + [p for p in parts if weak(p)]
    for p in order_parts:
        key, mine, w, lp, pitch = name_key(p), sung_numbers(p), weak(p), low(p), mean_pitch(p) or 60
        two = bool(needs_split(p)) if SOLO_APART else None
        # une mesure en commun au plus est tolérée : la dernière mesure lue des deux côtés (nouvelles parties d'Audiveris
        # pour le dernier système, Psaume 22 WhatsApp : 8 voix au lieu de 4)
        free = [sl for sl in slots
                if len(mine & sl["sung"]) <= max(OVERLAP, 0.2 * max(1, min(len(mine), len(sl["sung"]))))]
        same = next((sl for sl in free if key in sl["keys"]), None)
        if same is None and (w or all(sl_w for sl in free for sl_w in [sl["weak"]])):
            # une ligne seule (couplet du soliste, sur sa propre portée) ne rejoint pas une portée à deux voix (S. A. du
            # refrain) : séparée, elle est versée dans la voix la plus aiguë (fold_solos) ; réunie, la séparation des
            # voix la donnait aussi à l'alto, en unisson (Psaume 118 des chorales : 13 notes de trop à l'alto)
            same = next((sl for sl in free if (w or sl["weak"]) and sl["low"] == lp and abs(sl["pitch"] - pitch) <= 7
                         and (two is None or sl["two"] is None or sl["two"] == two)), None)
        if same is None:
            slots.append({"parts": [p], "keys": {key}, "sung": set(mine), "weak": w, "low": lp, "pitch": pitch, "two": two})
        else:
            same["parts"].append(p); same["keys"].add(key); same["sung"] |= mine
            same["weak"] = same["weak"] and w
    # ordre de la page : chaque voix à la place de sa première portée (parties nommées rangées en premier ci-dessus)
    # (d'après les parties bien nommées : une basse nommée « TI » venue tôt faisait passer la basse avant le ténor ;
    # et quand chaque voix porte un nom de voix, dans l'ordre des noms : Audiveris ne range pas toujours ses parties
    # dans l'ordre de la page, la première peut venir d'un système du milieu)
    rank = {"Soprano": 0, "Mezzo": 0.5, "Alto": 1, "Ténor": 2, "Baryton": 2.5, "Basse": 3}
    ranks = [next((rank[k] for k in sl["keys"] if k in rank), None) for sl in slots]
    if all(r is not None for r in ranks) and len(set(ranks)) == len(ranks):
        slots = [sl for _r, sl in sorted(zip(ranks, slots), key=lambda t: t[0])]
    else:
        slots.sort(key=lambda sl: min((parts.index(p) for p in sl["parts"] if not weak(p)),
                                      default=min(parts.index(p) for p in sl["parts"])))
    for sl in slots:
        sl["parts"].sort(key=parts.index)
    groups = {i: sl["parts"] for i, sl in enumerate(slots)}
    order = list(groups)
    merged = []
    for key in order:
        ps = groups[key]
        if len(ps) == 1:
            merged.append(ps[0]); continue
        base = ps[0]
        own = list(base.getElementsByClass(stream.Measure))
        others = [list(p.getElementsByClass(stream.Measure)) for p in ps[1:]]
        for k, m in enumerate(own):
            if sung_in(m):
                continue
            for ms in others:
                # mesures appariées par position (Audiveris donne parfois le même numéro à deux mesures :
                # mesure coupée en fin de ligne) ; par numéro seulement si les portées n'ont pas le même nombre de mesures
                other = ms[k] if len(ms) == len(own) else next((x for x in ms if x.number == m.number and sung_in(x)), None)
                if other is not None and sung_in(other):
                    _move(other, m)
                    break
        merged.append(base)
    return merged


def regroup_by_place(parts):
    """
    Audiveris crée une partie par nom lu devant les portées : « Soprano » sur la 1re ligne, « S. » ensuite, et des noms
    mal lus (« Îénor », « ' B. », « Voice ») ; réunies d'après leur nom, il restait 5 ou 6 voix au lieu de 4. Un chœur
    garde sur chaque ligne le même nombre de portées, dans le même ordre : quand presque toutes les mesures sont
    chantées par N portées (N < nombre de parties), chaque partie prend la place qu'elle occupe parmi elles (de haut en
    bas, ordre d'Audiveris), et les parties de même place sont réunies, mesure par mesure. Rend None si ce n'est pas net
    (dialogue avec soliste, place qui change, deux parties de même place dans une mesure).
    """
    rows = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    if len(parts) < 3:
        return None
    numbers = None
    if len({len(r) for r in rows}) != 1:
        # une partie plus courte que les autres (photo floue : 10 mesures contre 12) : mesures appariées par numéro,
        # si chaque numéro est unique dans chaque partie et connu de la plus longue
        numbers = [m.number for m in max(rows, key=len)]
        aligned = []
        for r in rows:
            own = [m.number for m in r]
            if len(set(own)) != len(own) or not set(own) <= set(numbers) or len(set(numbers)) != len(numbers):
                return None
            by_number = {m.number: m for m in r}
            aligned.append([by_number.get(n) for n in numbers])
        rows = aligned
    count = len(rows[0])
    sings = lambda m: m is not None and any(not n.duration.isGrace for n in m.recurse().notes)
    sung = [[i for i, r in enumerate(rows) if sings(r[k])] for k in range(count)]
    sizes = [len(s) for s in sung if s]
    if not sizes:
        return None
    n = statistics.mode(sizes)
    full = [s for s in sung if len(s) == n]
    if n < 2 or n >= len(parts) or len(full) < 0.6 * len(sizes) or any(x > n for x in sizes):
        return None
    votes = [{} for _ in parts]
    for s in full:
        for place, i in enumerate(s):
            votes[i][place] = votes[i].get(place, 0) + 1
    place_of = {}
    for i, v in enumerate(votes):
        if not v:
            if any(i in s for s in sung):
                return None  # partie qui ne chante que dans des mesures incomplètes : soliste, on ne devine pas
            continue
        place, c = max(v.items(), key=lambda x: x[1])
        if c < 0.8 * sum(v.values()):
            return None
        place_of[i] = place
    groups = [[i for i in sorted(place_of) if place_of[i] == p] for p in range(n)]
    if any(not g for g in groups):
        return None
    merged = []
    for g in groups:
        first = max(g, key=lambda i: sum(m is not None for m in rows[i]))  # la plus longue (à égalité, la première)
        base = copy.deepcopy(parts[first])
        own = list(base.getElementsByClass(stream.Measure))
        if numbers is not None:
            by_number = {m.number: m for m in own}
            own = [by_number.get(n) for n in numbers]
        for k in range(count):
            singers = [i for i in g if i in sung[k]]
            if len(singers) > 1:
                return None
            if singers and singers[0] != first:
                if own[k] is None:
                    return None
                _move(copy.deepcopy(rows[singers[0]][k]), own[k])
        names = {abbr(t) for i in g for t in re.findall(r"[^\W\d_]+", clean_name(parts[i].partName) or "")}
        names.discard(None)
        # nom canonique commun, sinon aucun (pas None : music21 reprendrait le nom d'instrument, « Balme »)
        base.partName = names.pop() if len(names) == 1 else ""
        base.partAbbreviation = ""
        merged.append(base)
    return merged


def name_by_range(voices):
    """Voix sans nom : nommées d'après leur tessiture (Soprano, Alto, Ténor, Basse), numérotées si besoin.
    Un nom générique (« Voice », nom d'instrument qu'Audiveris donne à toute portée) ne compte pas pour un nom."""
    for v in voices:
        if clean_name(v.partName):
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
    if DEBRIS and len(kept) > 4:
        # débris de lecture (accords chiffrés, signes, texte lus comme une portée : nom illisible et quelques notes,
        # pendant que le chœur chante ; Psaume 79 sombre : 5 notes contre 21 à 22 par voix) : écartés
        sizes = sorted(len(v.recurse().notes) for v in kept)
        median = sizes[len(sizes) // 2]
        for v in sorted(kept, key=lambda v: len(v.recurse().notes)):
            if len(kept) <= 4:
                break
            readable = clean_name(v.partName or "") and re.search(r"[^\W\d_]{2,}", v.partName or "")
            if not readable and len(v.recurse().notes) < 0.3 * median:
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
NOMS_PAR_PLACE = os.environ.get("PUPITRE_NOMS_PLACE", "1") == "1"  # nom contraire à la place et à la tessiture : écarté


def pitches_of(obj):
    return [p.ps for n in obj.recurse().notes for p in n.pitches]


def shift_octaves(obj, octaves):
    if octaves:
        for n in obj.recurse().notes:
            for p in n.pitches:
                p.octave = (p.octave if p.octave is not None else 4) + octaves


TOP_PLAIN_G = os.environ.get("PUPITRE_SOL_HAUT", "1") == "1"  # voix du haut : la clé de sol sans 8 l'emporte


def fix_octaves(voice, center=None, top=False):
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
    # clé mal lue sur une ligne entière : clé de sol lue « avec un 8 » sur une photo (ou le 8 du ténor oublié).
    # Seule la portion sous une clé dont l'octave diffère de celle du reste de la voix est ramenée, et seulement
    # si ses notes sont bien décalées dans ce sens (au moins 4 notes de chaque côté).
    measures = list(voice.getElementsByClass(stream.Measure))
    cuts = [i for i, m in enumerate(measures) if i == 0 or m.clef is not None] + [len(measures)]
    segs = []
    for a, b in zip(cuts, cuts[1:]):
        c = measures[a].clef or measures[a].getContextByClass(clef.Clef)
        segs.append((a, b, getattr(c, "octaveChange", 0) or 0, [p for m in measures[a:b] for p in pitches_of(m)]))
    weight = {}
    for _a, _b, oc, ps_ in segs:
        weight[oc] = weight.get(oc, 0) + len(ps_)
    usual = max(weight, key=weight.get) if weight else 0
    # voix du haut ou mélodie seule : la clé de sol sans 8 est la sienne ; un système lu « avec un 8 » (photo, copie
    # au style des recueils : 18 notes contre 17) l'emportait, et le reste de la mélodie descendait d'une octave
    if top and TOP_PLAIN_G and 0 in weight and usual != 0:
        usual = 0
    for a, b, oc, seg in segs:
        k = usual - oc
        rest = [p for m in measures[:a] + measures[b:] for p in pitches_of(m)]
        if not k or len(seg) < 4 or len(rest) < 4:
            continue
        gap = statistics.median(seg) - statistics.median(rest)
        if gap * k < 0 and abs(gap + 12 * k) < abs(gap):
            for m in measures[a:b]:
                shift_octaves(m, k)
            moved += len(seg)
    ref = statistics.median(pitches_of(voice))
    for m in voice.getElementsByClass(stream.Measure):
        mp = pitches_of(m)
        if not mp:
            continue
        gap = statistics.median(mp) - ref
        if abs(gap) > 9:
            k = -1 if gap > 0 else 1  # une erreur de lecture décale d'une octave, jamais deux
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


INFER_TS = os.environ.get("PUPITRE_INDICATION_DEDUITE", "1") == "1"
TS_BY_LENGTH = {4.0: "4/4", 2.0: "2/4", 6.0: "6/4", 1.5: "3/8", 4.5: "9/8", 5.0: "5/4", 2.5: "5/8", 3.5: "7/8", 1.0: "1/4"}


def infer_time_signature(score):
    """
    Indication de mesure oubliée par la lecture (le « C » des recueils, petites portées : Audiveris ne le lit pas ; sur
    les copies au style des recueils, les 16 indications perdues sur 117 étaient des « C ») : sans elle, align_measures
    supposait 4 temps et complétait chaque mesure d'un 3/4 par un silence d'un temps (rythme faux à l'écoute, notes
    justes). Déduite de la durée de la plupart des mesures (première et dernière à part : levée, fin) ; 3 temps : 6/8
    si les notes commencent plus souvent au milieu de la mesure (1,5) qu'au 2e ou 3e temps, sinon 3/4. Posée au début
    de chaque partie. Rend l'indication posée, ou None (indication lue, ou mesures sans majorité nette).
    """
    if not INFER_TS or any(score.recurse().getElementsByClass(meter.TimeSignature)):
        return None
    lengths, onsets = [], {1.0: 0, 1.5: 0, 2.0: 0}
    for p in score.parts:
        ms = list(p.getElementsByClass(stream.Measure))
        for m in ms[1:-1]:
            flat = m.flatten()
            if not flat.notes:
                continue
            lengths.append(round(max((float(el.offset + el.quarterLength) for el in flat.notesAndRests), default=0.0), 3))
            for n in flat.notes:
                o = round(float(n.offset), 3)
                if o in onsets:
                    onsets[o] += 1
    if len(lengths) < 3:
        return None
    bar = statistics.mode(lengths)
    if lengths.count(bar) < 0.5 * len(lengths):
        return None
    if bar == 3.0:
        ratio = "6/8" if onsets[1.5] > onsets[1.0] + onsets[2.0] else "3/4"
    else:
        ratio = TS_BY_LENGTH.get(bar)
    if ratio is None:
        return None
    for p in score.parts:
        first = p.getElementsByClass(stream.Measure).first()
        if first is not None:
            ts = meter.TimeSignature(ratio)
            first.insert(0, ts)
    return ratio


def align_measures(voices):
    """Même durée pour chaque mesure dans toutes les voix, sinon les pistes se décalent à l'écoute.
    Mesure trop courte (silence oublié) : complétée par un silence ; trop longue (point ou crochet mal lu) :
    ramenée à la bonne durée en resserrant proportionnellement ses notes. Deux mesures voisines incomplètes dont les
    durées s'additionnent en une mesure entière (mesure coupée par une double barre, au début du refrain) restent telles
    quelles ; dans une levée, le silence manquant se place avant les notes."""
    measures = [list(v.getElementsByClass(stream.Measure)) for v in voices]
    count = max((len(ms) for ms in measures), default=0)
    bars, commons = [], []
    bar = 4.0
    for k in range(count):
        row = [ms[k] if k < len(ms) else None for ms in measures]
        for m in row:
            ts = m.timeSignature if m is not None else None
            if ts is not None:
                bar = ts.barDuration.quarterLength
        # seules les voix qui chantent comptent : une voix qui se tait pendant le couplet d'un soliste n'a que des silences
        lengths = [round(content_length(m), 3) for m in row if m is not None and m.notes]
        common = statistics.mode(lengths) if lengths and lengths.count(statistics.mode(lengths)) * 2 > len(lengths) else None
        bars.append(bar)
        commons.append((common, lengths))

    def split_bar(k):
        c = commons[k][0]
        if c is None or c >= bars[k] - 1e-6:
            return False
        return any(0 <= j < count and commons[j][0] is not None and abs(c + commons[j][0] - bars[k]) < 1e-6
                   for j in (k - 1, k + 1))

    rebuilt = [stream.Part() for _ in voices]
    for k in range(count):
        row = [ms[k] if k < len(ms) else None for ms in measures]
        bar = bars[k]
        common, lengths = commons[k]
        target = bar
        if lengths:
            edge = k == 0 or k == count - 1
            if common is not None:
                # la majorité a raison quand la mesure est plus longue (récitatif libre) ou incomplète en levée / en fin ;
                # ailleurs, une mesure trop courte dans toutes les voix est un silence oublié par la lecture : on complète
                target = common if common > bar or edge or split_bar(k) else bar
            elif len(set(lengths)) == len(lengths):
                target = max(lengths)    # aucune majorité (un seul chanteur, ou tous différents) : on ne coupe rien
            elif k == 0:
                target = min(bar, max(lengths))   # levée : la plus longue lecture dit sa durée
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
                gap = opFrac(target - length)
                if k == 0 and m.notes:  # levée : les notes mènent au premier temps, le silence est devant
                    for off, el in sorted(((e.offset, e) for e in m.notesAndRests), key=lambda x: -x[0]):
                        m.remove(el)
                        m.insert(opFrac(off + gap), el)
                    m.insert(0, note.Rest(quarterLength=gap))
                else:
                    m.insert(opFrac(length), note.Rest(quarterLength=gap))
            rebuilt[i].append(m)
    for v, r in zip(voices, rebuilt):
        r.partName = v.partName
    return rebuilt


def drop_chord_symbols(score):
    """Accords chiffrés pour la guitare (G, Em, Am7 au-dessus de la portée) : Audiveris les lit comme des accords sans
    durée, que music21 compte parmi les notes. Ils ne se chantent pas, et faussaient la hauteur moyenne des voix,
    leur nombre de notes et le banc d'essai."""
    if os.environ.get("PUPITRE_ACCORDS_CHIFFRES") == "garder":
        return 0
    found = list(score.recurse().getElementsByClass(harmony.Harmony))
    for h in found:
        h.activeSite.remove(h)
    return len(found)


BY_CLEF = os.environ.get("PUPITRE_VOIX_PAR_CLE", "1") == "1"
MIN_PARTS_CLEF = int(os.environ.get("PUPITRE_VOIX_PAR_CLE_PARTIES", "4"))
CLEF_STABLE = os.environ.get("PUPITRE_VOIX_PAR_CLE_STABLES", "1") == "1"  # 4 parties stables : pas de regroupement


def _clef_kind(c):
    if c is None:
        return None
    if c.sign == "F":
        return "F"
    if c.sign == "G":
        return "G8" if getattr(c, "octaveChange", 0) < 0 else "G"
    return None


def regroup_by_clef(parts):
    """
    Chœur sur quatre portées séparées (S., A., T., B.) dont MuseScore masque les portées vides (systèmes de 2, 3 ou 4
    portées) : Audiveris crée une partie par nom lu et range des portées dans la partie d'une autre voix (passage du
    ténor dans la partie de la basse ; « Song bal la Wende » : 8 à 19 parties). Chaque mesure est rendue à sa voix
    d'après la clé de sa portée : fa → basse ; sol avec 8 → ténor ; sol, de haut en bas → soprano, alto (puis ténor).
    Rend les quatre voix, ou None si la partition n'est pas ainsi faite.
    """
    if len(parts) < MIN_PARTS_CLEF:
        return None
    rows = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    n = max(len(r) for r in rows)
    kinds = []  # clé en vigueur, par partie et par mesure
    for r in rows:
        cur, ks = None, []
        for m in r:
            cs = [c for c in m.recurse().getElementsByClass(clef.Clef) if float(c.offset) == 0.0]
            if cs:
                cur = _clef_kind(cs[0])
            ks.append(cur)
        kinds.append(ks)
    if CLEF_STABLE and len(parts) == 4 and all(len({k for k in ks if k}) <= 1 for ks in kinds):
        seq = [next((k for k in ks if k), None) for ks in kinds]
        if seq[0] in ("G", None) and seq[1] in ("G", None) and seq[3] == "F":
            # quatre parties d'une voix chacune, chacune toujours dans sa clé, déjà dans l'ordre S, A, T, B : rien à
            # regrouper ; une soprano qui se tait n'est pas une portée masquée (l'alto passait à la soprano :
            # bwv269 ouverte usée S 92 → 84 %)
            return None
    plan, fours, typical, doubled, sung = [], 0, 0, 0, 0
    for i in range(n):
        singing = [k for k, r in enumerate(rows) if i < len(r) and r[i].recurse().notes]
        for k in singing:
            sung += 1
            doubled += sum(1 for v in rows[k][i].voices if v.notes) >= 2
        got = {}
        gs = [k for k in singing if kinds[k][i] in ("G", None)]
        fs = [k for k in singing if kinds[k][i] == "F"]
        g8 = [k for k in singing if kinds[k][i] == "G8"]
        if g8:
            got["Ténor"] = g8[0]
        if len(fs) >= 2 and "Ténor" not in got:
            got["Ténor"], got["Basse"] = fs[0], fs[1]  # ténor et basse tous deux en clé de fa, de haut en bas
        elif fs:
            got["Basse"] = fs[-1]
        for name, k in zip(("Soprano", "Alto", "Ténor"), gs):
            got.setdefault(name, k)
        if set(singing) - set(got.values()):
            return None  # une portée qui chante resterait sans voix : on ne regroupe pas d'après les clés
        if len(singing) >= 3:
            fours += 1
            typical += any(kinds[k][i] in ("F", "G8") for k in singing)
        plan.append(got)
    # quatre portées d'une voix chacune (peu de mesures à deux voix), avec des clés de ténor ou de basse
    if not fours or typical < 0.6 * fours or doubled > 0.15 * max(1, sung):
        return None
    out = []
    for name, cl in (("Soprano", clef.TrebleClef()), ("Alto", clef.TrebleClef()), ("Ténor", clef.Treble8vbClef()),
                     ("Basse", clef.BassClef())):
        part = stream.Part()
        part.partName = name
        for i in range(n):
            k = plan[i].get(name)
            if k is not None:
                m = copy.deepcopy(rows[k][i])
                for c in list(m.recurse().getElementsByClass(clef.Clef)):
                    c.activeSite.remove(c)
            else:
                ref = next((r[i] for r in rows if i < len(r)), None)
                m = stream.Measure(number=ref.number if ref is not None else i + 1)
                for el in (ref.getElementsByClass((key.KeySignature, meter.TimeSignature)) if ref is not None else []):
                    m.insert(el.offset, copy.deepcopy(el))
                bar = ref.barDuration.quarterLength if ref is not None else 4.0
                m.insert(0, note.Rest(quarterLength=bar))
            if i == 0:
                m.insert(0, copy.deepcopy(cl))
            part.append(m)
        out.append(part)
    return out


UNPITCHED = os.environ.get("PUPITRE_SANS_HAUTEUR", "1") == "1"


def unpitched_to_notes(score):
    """
    Portée de chœur lue en percussion (clé de sol mal reconnue sur une petite portée) : notes « sans hauteur » ; leur
    place sur la portée (display-step, display-octave) reste lue, comme en clé de sol : elles redeviennent des notes à
    cette place (l'armure est appliquée ensuite par harmonize_keys). Vrais recueils : 2 chants sur 728. Rend le nombre
    de notes rendues à leur hauteur.
    """
    if not UNPITCHED:
        return 0
    from music21 import percussion
    perc = getattr(percussion, "PercussionChord", None)
    kinds = (note.Unpitched, perc) if perc is not None else (note.Unpitched,)
    done = 0
    for el in list(score.recurse().getElementsByClass(kinds)):
        try:
            if perc is not None and isinstance(el, perc):
                heads = [n for n in el.notes if isinstance(n, note.Unpitched)]
                new = chord.Chord([pitch.Pitch(f"{n.displayStep}{n.displayOctave}") for n in heads])
            else:
                new = note.Note(f"{el.displayStep}{el.displayOctave}")
        except Exception:  # noqa: BLE001
            continue
        new.duration = copy.deepcopy(el.duration)
        new.lyrics = list(el.lyrics)
        if el.tie is not None:
            new.tie = copy.deepcopy(el.tie)
        site = el.activeSite
        if site is None:
            continue
        site.replace(el, new)
        done += 1
    return done


def extract_voices(score, trust_names=True, systems=None):
    """Les voix dans l'ordre de la page (portées de haut en bas, hampes en haut avant hampes en bas) :
    c'est ainsi qu'un chœur est écrit, et cet ordre ne dépend pas des erreurs d'octave de la lecture.
    Pour un fichier MusicXML ou MIDI (hauteurs exactes, ordre des pistes parfois quelconque), on trie par hauteur."""
    drop_chord_symbols(score)
    if not trust_names:
        unpitched_to_notes(score)
        harmonize_keys(score)
        guessed = infer_time_signature(score)
        if guessed:
            print(f"Indication de mesure déduite de la durée des mesures : {guessed}", file=sys.stderr)
    sung = [p for p in score.parts if p.recurse().notes and not is_accompaniment(p, trust_names)]
    if not sung:
        sung = [p for p in score.parts if p.recurse().notes]
    if not trust_names:
        sizes = [st for st, _m in systems] if systems else []
        mixed = bool(sizes) and 1 in sizes and max(sizes) > 1  # page mêlée : couplets d'une portée
        moved = solo_systems(sung, soloist=mixed and SOLOIST, systems=systems if mixed else None)
        if moved:
            print(f"Systèmes d'une seule portée : {moved} mesures de mélodie à la voix du haut", file=sys.stderr)
            sung = [p for p in sung if p.recurse().notes]
    by_clef = regroup_by_clef(sung) if BY_CLEF and not trust_names else None
    if by_clef is not None:
        sung = by_clef
    else:
        named = merge_named_parts(sung)
        placed = regroup_by_place(sung) if not trust_names and len(named) > 2 else None
        sung = placed if placed is not None and len(placed) < len(named) else named
    if not trust_names:
        for i, a, b, s in coherence.fix_staff_shifts(sung):
            print(f"Portée {i + 1}, mesures {a + 1} à {b + 1} : recalée d'un degré vers le {'bas' if s < 0 else 'haut'} "
                  "(harmonie et altérations)", file=sys.stderr)
    voices = []
    choir = choir_measures(sung)
    for part in sung:
        lines = split_staff(part) if needs_split(part, choir) else [flatten_voices(part)]
        for line, name in zip(lines, staff_names(part.partName or part.partAbbreviation, len(lines))):
            line.partName = name or ""  # None ferait reparaître le nom d'instrument d'Audiveris (« Voice », « Balme »)
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
        if centers and NOMS_PAR_PLACE:
            for i, v in enumerate(voices):
                # nom mal lu (« Alto » pour « Basse », parties d'Audiveris regroupées par place) : la voix est à sa
                # place et chante dans sa tessiture ; le nom, lui, la ferait monter d'une octave
                c = named.get((v.partName or "").split(" ")[0])
                ps = pitches_of(v)
                if c is not None and ps and c != centers[i]:
                    med = statistics.median(ps)
                    if abs(med - c) > 7 and abs(med - centers[i]) < abs(med - c):
                        print(f"Voix {i + 1} : nom lu « {v.partName} » écarté (tessiture de sa place)", file=sys.stderr)
                        v.partName = ""
        for i, v in enumerate(voices):
            fix_octaves(v, named.get((v.partName or "").split(" ")[0]) or (centers[i] if centers else None), top=i == 0)
    satb = ("Soprano", "Alto", "Ténor", "Basse")
    if len(voices) == 4 and all(not clean_name(v.partName) or v.partName == n for v, n in zip(voices, satb)):
        for v, n in zip(voices, satb):  # quatre voix dans l'ordre de la page : celles sans nom le prennent de leur place
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
    print(f"actif:mp3:{base.name}", flush=True)  # signe de vie pour la surveillance du serveur
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


def export_rebuilt(voices, labels, dst: pathlib.Path) -> bool:
    """Partition reconstituée : une portée par voix, nommée, dans la bonne octave et la bonne clé, avec ses paroles
    (les corrections de la lecture y sont appliquées). Facultative : en cas d'échec, l'audio n'en dépend pas."""
    try:
        sc = stream.Score()
        for v, (_vid, name) in zip(voices, labels):
            p = copy.deepcopy(v)
            p.partName, p.partAbbreviation = name, None
            ms = list(p.getElementsByClass(stream.Measure))
            for m in ms:
                for c in list(m.recurse().getElementsByClass(clef.Clef)):
                    c.activeSite.remove(c)
            mp, first = mean_pitch(p) or 60, (name or "").split(" ")[0]
            if first in ("Basse", "Baryton") or (first not in FEMALE | {"Ténor"} and mp < 52):
                c = clef.BassClef()
            elif first == "Ténor" or (first not in FEMALE and mp < 59):
                c = clef.Treble8vbClef()
            else:
                c = clef.TrebleClef()
            if ms:
                ms[0].insert(0, c)
            sc.insert(0, p)
        sc.write("musicxml", fp=str(dst))
        return True
    except Exception as e:  # noqa: BLE001
        print(f"Partition reconstituée impossible : {e}", file=sys.stderr, flush=True)
        dst.unlink(missing_ok=True)
        return False


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


def typed_for(typed, vid, i, count):
    """Paroles saisies pour une voix : sous son identifiant, sinon sous sa place (« #2/4 » : 3e voix sur 4), que le serveur
    ajoute quand une version précédente du moteur nommait autrement les voix."""
    return typed.get(vid) or typed.get(f"#{i}/{count}")


def sing_voices(voices, labels, tempo_qpm, a):
    """Voix chantées : voix de femme pour les voix hautes, d'homme pour les voix basses ; paroles saisies ou de la partition."""
    import chant, mixage
    missing = chant.missing_voices()
    if missing:
        sys.exit(f"Voix de synthèse introuvables dans {chant.voice_dir()} : {', '.join(missing)}")
    typed = json.loads(pathlib.Path(a.paroles).read_text(encoding="utf-8")) if a.paroles else {}
    sung = []
    for i, v in enumerate(voices):
        vid, vname = labels[i]
        midis = [p.midi for n in v.recurse().notes for p in n.pitches]
        kind = "femme" if statistics.mean(midis) >= 60 else "homme"
        print(f"Chant {i+1}/{len(voices)} : {vname} ({chant.ensemble_size()} voix {'de femme' if kind == 'femme' else 'd’homme'})", flush=True)
        x = mixage.polish_voice(chant.sing_part(v, tempo_qpm, kind, a.langue, typed_for(typed, vid, i, len(voices))), kind)
        sung.append(mixage.level_to(mixage.phone_bass(x, mixage.bass_amount(midis)), mixage.TARGET_VOICE))
    return sung


EXACT_TAG = "<!-- pupitre:exacte -->"  # écrit dans la partition : la marque voyage avec elle (téléphone → /api/recreer)


SYSTEMS_TAG = re.compile(rb"pupitre:systemes ([0-9,/]+)")


def page_systems(src):
    """Disposition des systèmes de la page (omr.mark_systems) : [(portées, mesures vues)], ou None."""
    p = pathlib.Path(src)
    try:
        if p.suffix == ".mxl":
            with zipfile.ZipFile(p) as z:
                name = next(n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META-INF"))
                head = z.read(name)[:8192]
        else:
            with open(p, "rb") as f:
                head = f.read(8192)
    except (OSError, StopIteration, zipfile.BadZipFile):
        return None
    m = SYSTEMS_TAG.search(head)
    if not m:
        return None
    out = []
    for cell in m.group(1).decode().split(","):
        if cell:
            a, _s, b = cell.partition("/")
            out.append((int(a), int(b) if b else 0))
    return out


def is_exact(src):
    """Partition exacte (PDF gravé lu directement, chant reconnu dans le répertoire) : fichier « partition.exacte » à
    côté, ou marque dans la partition elle-même."""
    p = pathlib.Path(src)
    if (p.parent / "partition.exacte").exists():
        return True
    try:
        with open(p, "rb") as f:
            return EXACT_TAG.encode() in f.read(4096)
    except OSError:
        return False


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
    # partition exacte (PDF gravé lu directement, chant reconnu dans le répertoire) : voix prises telles quelles, sans
    # les retouches d'une lecture d'image (octaves, places des voix), qui abîmaient le ténor et la basse de 6 chants sur 15
    voices = extract_voices(score, trust_names=not a.omr or is_exact(a.src), systems=page_systems(a.src))
    if not voices:
        sys.exit("Aucune note n’a été reconnue dans la partition.")

    used = set()
    labels = [(voice_id(v.partName, used), v.partName) for v in voices]  # noms lus dans la partition, ou tessiture
    rebuilt = export_rebuilt(voices, labels, out / "reconstituee.musicxml")
    sung = sing_voices(voices, labels, tempo_qpm, a) if a.timbre == "chant" else real_choir(voices, labels, tempo_qpm, a) if a.timbre == "reel" else None
    wet = 0.06 if a.timbre == "reel" else 0.16  # le chœur réel a déjà sa salle dans les enregistrements
    # paroles saisies : gardées dans le manifeste, pour les retrouver à la prochaine modification
    typed_lyrics = json.loads(pathlib.Path(a.paroles).read_text(encoding="utf-8")) if a.paroles else {}
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
        pitches = [p for n in v.recurse().notes for p in n.pitches] or [pitch.Pitch("C4")]
        lo, hi = min(pitches, key=lambda p: p.ps), max(pitches, key=lambda p: p.ps)
        entries.append({"id": vid, "name": vname, "stem": stem, "practice": work,
                        "notes": len(v.recurse().notes), "range": [fr_name(lo), fr_name(hi)],
                        "lyrics": typed_for(typed_lyrics, vid, i, len(voices)) or lyrics_text(v), "sung": len(v.stripTies().flatten().notes)})
        print(f"Voix {i+1}/{len(voices)} : {vname} ({fr_name(lo)} à {fr_name(hi)})", flush=True)

    if sung:
        tutti = encode_mp3(mix([(x, 1.0) for x in sung], wet), out / "tutti")
    else:
        tutti = to_mp3(stream.Score([prepare(v, tempo_qpm, a.timbre) for v in voices]), out / "tutti")
    export_musicxml(pathlib.Path(a.src), out / "score.musicxml", score)
    ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
    ks = score.analyze("key")
    # fiabilité de la lecture (vote entre plusieurs passes, pupitres.py) : à côté de la partition lue
    reliability = None
    try:
        fid = pathlib.Path(a.src).with_name("fiabilite.json")
        if fid.exists():
            reliability = json.loads(fid.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        reliability = None
    manifest = {
        "tempo": tempo_qpm, "timbre": a.timbre, "tutti": tutti, "score": "score.musicxml",
        **({"rebuilt": "reconstituee.musicxml"} if rebuilt else {}),
        **({"fiabilite": reliability} if reliability else {}),
        **({"exacte": True} if is_exact(a.src) else {}),  # PDF gravé lu directement, chant reconnu au répertoire
        **({"langue": a.langue} if a.timbre == "chant" else {}),
        **({"voyelle": a.voyelle} if a.timbre == "reel" else {}),
        "measures": len(score.parts[0].getElementsByClass(stream.Measure)),
        "timeSignature": ts.ratioString if ts else None,
        "key": f"{fr_name(ks.tonic, octave=False)} {'majeur' if ks.mode == 'major' else 'mineur'}",
        "voices": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Terminé : {len(voices)} voix, tonalité {manifest['key']}, fichiers dans {out}")


if __name__ == "__main__":
    main()
