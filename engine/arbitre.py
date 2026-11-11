"""
Double lecture : la même page lue par Audiveris (lecture ordinaire) et par homr (réseau de neurones, portée par
portée), puis arbitrage mesure par mesure et portée par portée.

Les deux lecteurs se trompent rarement au même endroit : Audiveris confond les accords serrés (seconde, unisson),
les croches à crochet, les points ; homr oublie parfois une tête de note dans un accord. Une lecture juste d'une portée
de chœur se reconnaît à sa cohérence rythmique :
  - chaque instant de la mesure est chanté par 1 à V notes (V = voix sur la portée : 2 pour S+A ou T+B, 1 sinon),
    jamais plus (sinon une durée est fausse et déborde sur la note suivante) ;
  - la dernière note s'arrête exactement à la fin de la mesure (durée commune lue sur toutes les portées, pour
    respecter une levée ou une mesure coupée par une double barre) ;
  - pas de durées hors grille (triolets inventés : 1/3, 2/3 de temps).
On garde, pour chaque portée de chaque mesure, la lecture qui commet le moins de ces fautes ; à égalité celle
d'Audiveris (banc d'essai : sur les altérations, Audiveris a plus souvent raison que homr, qui se trompe parfois
d'armure). Deux portées à deux voix toutes deux fautives : la meilleure lecture de chaque voix. Les mesures où les
deux lectures divergent sans qu'une seule soit cohérente sont signalées (fiabilite.json : notes en orange).
Avant de comparer : une voix qu'Audiveris a coupée en deux parties (nom lu « Soprano » puis « S. ») est réunie, et
les mesures sont appariées d'après leurs notes (une barre vue par un seul lecteur ne décale pas la suite).

Usage : python3 arbitre.py <partition_audiveris> <partition_homr> <sortie.musicxml> <satb|grand>
Écrit <sortie> et fiabilite.json à côté.
"""
import copy, json, os, pathlib, re, statistics, sys
from fractions import Fraction

from music21 import converter, key, layout, note, chord, stream
from music21.common.numberTools import opFrac

# À égalité de fautes, l'oreille du musicien : la lecture dont les notes sonnent juste avec les autres portées et
# appartiennent à la tonalité l'emporte, si elle l'emporte nettement (sinon Audiveris, comme avant). Désactivé par
# défaut (PUPITRE_MUSICAL=1 pour l'essayer) : banc complet du 06/11, total identique (76,6 %), PDF nets 98,8 → 98,4 %.
MUSICAL = os.environ.get("PUPITRE_MUSICAL", "0") == "1"
MUSIC_MARGIN = 0.15
GRID = 0.25      # double croche : pas de contrôle de la couverture
OFF_GRID = 4     # poids d'une durée hors grille, d'une fin de mesure fausse
END = 4


def events(m):
    """Notes d'une mesure : (début, hauteur en demi-tons, durée, Pitch), têtes en double fusionnées."""
    seen, out = set(), []
    for n in m.recurse().notes:
        if n.duration.isGrace or not n.quarterLength:
            continue
        off = round(float(n.getOffsetInHierarchy(m)), 4)
        for p in n.pitches:
            k = (off, p.ps, round(float(n.quarterLength), 4))
            if k not in seen:
                seen.add(k)
                out.append((off, p.ps, k[2], p))
    return sorted(out, key=lambda e: (e[0], -e[1]))


# consonance de deux sons (demi-tons modulo 12), comme coherence.CONSONANCE : tierces, quinte, sixtes, octave
_CONSONANCE = {0: 1.0, 3: 1.0, 4: 1.0, 7: 1.0, 8: 1.0, 9: 1.0, 5: 0.5, 6: 0.2, 1: 0.0, 2: 0.0, 10: 0.0, 11: 0.0}


def _scale(ks):
    """Classes de hauteur de la tonalité de l'armure (majeur) et de son relatif mineur, sensible comprise."""
    sharps = ks.sharps if ks is not None else 0
    tonic = (7 * sharps) % 12                      # do majeur + 1 dièse = sol majeur…
    major = {(tonic + i) % 12 for i in (0, 2, 4, 5, 7, 9, 11)}
    return major | {(tonic + 8) % 12}              # sensible du relatif mineur (sol dièse en la mineur)


def musical(ev, others, ks):
    """
    Note musicale d'une lecture d'une portée dans sa mesure (0 à 1,5) : consonance de ses notes avec celles des autres
    portées et entre ses propres voix, pondérée par la durée commune, plus la part de ses notes dans la tonalité.
    """
    if not ev:
        return 0.0
    good = total = 0.0
    pairs = [(a, b) for a in ev for b in others] + [(a, b) for i, a in enumerate(ev) for b in ev[i + 1:]]
    for (oa, pa, da, _x), (ob, pb, db, _y) in pairs:
        w = min(oa + da, ob + db) - max(oa, ob)
        if w > 1e-6:
            good += w * _CONSONANCE[int(round(abs(pa - pb))) % 12]
            total += w
    scale = _scale(ks)
    in_key = sum(1 for _o, ps, _d, _p in ev if int(round(ps)) % 12 in scale) / len(ev)
    return (good / total if total else 0.5) + 0.5 * in_key


REDONDANT = os.environ.get("PUPITRE_REDONDANT", "1") == "1"
VOTE = os.environ.get("PUPITRE_VOTE", "1") == "1"  # trois lectures (deux portées) : deux contre une
PAD = os.environ.get("PUPITRE_VIDES", "1") == "1"  # mesures jetées par Audiveris sur une portée : laissées vides
IMAGE_MAP = os.environ.get("PUPITRE_RECOUPE", "1") == "1"  # mesures d'Audiveris recoupées d'après les barres de l'image
OCTAVE = os.environ.get("PUPITRE_OCTAVE_HOMR", "1") == "1"  # mesure de homr hors tessiture : pas reprise
INSERT = os.environ.get("PUPITRE_INSERTION", "1") == "1"  # mesure perdue sur toutes les portées : reprise de homr
RESCUE = os.environ.get("PUPITRE_SECOURS", "1") == "1"
SPLIT_BAR = os.environ.get("PUPITRE_MESURE_COUPEE", "1") == "1"  # mesure courte + levée d'Audiveris : durée gardée  # lectures trop différentes : homr ne remplit que ces mesures
# à égalité : le nombre de têtes pleines de l'image. Désactivé par défaut (PUPITRE_TETES=1 pour l'essayer) : banc
# complet du 10/11, bwv153.1 ouverte nette A 98 → 100 mais bwv269 ouverte photo et sombre A 100 → 88 (homr pris à tort)
HEADS = os.environ.get("PUPITRE_TETES", "0") == "1"
# voix séparées (deux portées) : mesures appariées par leur place sur l'image quand celle d'Audiveris y correspond une à
# une ; arbitrage complet même si les lectures diffèrent beaucoup (homr y lit une voix seule, pas des accords)
GEO = os.environ.get("PUPITRE_APPARIEMENT_IMAGE", "1") == "1"
TIE_HOMR = os.environ.get("PUPITRE_EGALITE_HOMR", "0") == "1"  # voix séparées : égalité → homr (banc 96,0 → 95,9 ; Kyrie réel 95,5 → 97,3)


def _alter(p):
    return float(p.accidental.alter) if p.accidental is not None else 0.0


def only_accidentals(x, y):
    """Deux lectures d'une portée qui ne diffèrent que par des altérations (mêmes notes, même place, même rythme)."""
    return len(x) == len(y) and x != y and all(
        a[0] == b[0] and a[2] == b[2] and a[3].step == b[3].step and a[3].octave == b[3].octave for a, b in zip(x, y)) \
        and any(_alter(a[3]) != _alter(b[3]) for a, b in zip(x, y))


def needless(ev, ks):
    """
    Notes portant une altération écrite qui ne sert à rien : celle que l'armure et les altérations plus tôt dans la
    mesure donnent déjà (bécarre sur un sol quand l'armure n'a qu'un fa♯). Un graveur n'en met pas ; une lecture de
    photo en invente en prenant un dièse pour un bécarre. Rend l'ensemble des indices de ces notes.
    """
    implied, out = {}, set()
    for k, (_o, _ps, _d, p) in enumerate(ev):
        here = (p.step, p.octave)
        by_key = ks.accidentalByStep(p.step) if ks is not None else None
        before = implied.get(here, float(by_key.alter) if by_key is not None else 0.0)
        if p.accidental is not None and p.accidental.displayStatus:
            if float(p.accidental.alter) == before:
                out.add(k)
            implied[here] = float(p.accidental.alter)
    return out


def _key_at(m):
    """Armure en vigueur dans une mesure : la sienne (getContextByClass ne regarde que ce qui précède), sinon la précédente."""
    own = list(m.getElementsByClass(key.KeySignature))
    return own[0] if own else m.getContextByClass(key.KeySignature)


def _shown(p):
    return p.accidental is not None and bool(p.accidental.displayStatus)


def mix_accidentals(x, y, ks):
    """
    Mêmes notes, altérations différentes : note par note, celle de homr quand il a vu un signe qu'Audiveris n'a pas vu
    (sol♯ écrit contre sol) ou quand le signe d'Audiveris ne sert à rien (bécarre sur une note déjà naturelle : dièse
    mal lu) ; sinon celle d'Audiveris (un bécarre qui annule l'armure, fa♮ avec fa♯ à la clé, est un vrai signe que homr
    oublie). Une altération reprise vaut pour la suite de la mesure. Rend (lecture mêlée, nombre de notes prises à homr).
    """
    odd, odd_h, carry, out, n = needless(x, ks), needless(y, ks), {}, [], 0
    for k, (a, b) in enumerate(zip(x, y)):
        here = (a[3].step, a[3].octave)
        # un signe de homr qui ne sert à rien (ré♯ écrit quand l'armure a déjà ré♯) est lui aussi mal lu (un bécarre)
        if _alter(a[3]) != _alter(b[3]) and (k in odd or (_shown(b[3]) and not _shown(a[3]) and k not in odd_h)):
            out.append(b)
            n += 1
            if _shown(b[3]):
                carry[here] = _alter(b[3])
        elif _alter(a[3]) != _alter(b[3]) and not _shown(a[3]) and carry.get(here) == _alter(b[3]):
            out.append(b)  # même note plus loin dans la mesure : l'altération reprise vaut encore
            n += 1
        else:
            out.append(a)
            if _shown(a[3]):
                carry[here] = _alter(a[3])
    return out, n


def signature(ev):
    return [(o, ps, d) for o, ps, d, _p in ev]


def end_of(ev):
    return max((o + d for o, _ps, d, _p in ev), default=0.0)


def coverage(ev, length):
    """Nombre de notes qui sonnent à chaque pas de la grille, de 0 à la fin de la mesure."""
    steps = max(1, round(length / GRID))
    return [sum(1 for o, _ps, d, _p in ev if o <= k * GRID + 1e-6 < o + d - 1e-6) for k in range(steps)]


def faults(ev, other, length, voices):
    """Fautes de cohérence d'une lecture de portée (voir en tête) ; other : l'autre lecture, pour les notes seules."""
    if not ev:
        return 0 if not other else 2 * END
    cov, cov_o = coverage(ev, length), coverage(other, length)
    first = min(o for o, *_ in ev)
    f = 0
    for k, c in enumerate(cov):
        if k * GRID + 1e-6 < first:
            continue                               # silence de début (levée, entrée après les autres)
        if c == 0:
            f += 1                                 # trou : une durée trop courte
        elif c > voices:
            f += c - voices                        # chevauchement : une durée trop longue
        elif voices == 2 and c == 1 and k < len(cov_o) and cov_o[k] == 2:
            f += 1                                 # note seule là où l'autre lecture voit les deux voix
    if abs(end_of(ev) - length) > 1e-6:
        f += END
    f += OFF_GRID * sum(1 for o, _ps, d, _p in ev if abs(o / GRID - round(o / GRID)) > 1e-3 or abs(d / GRID - round(d / GRID)) > 1e-3)
    return f


def lines(ev, voices, length, dropped=None):
    """
    Répartit les notes en voix (la plus aiguë d'abord) ; unisson (une seule tête pour deux voix libres) : dans les deux.
    dropped : liste où ranger les notes qu'aucune voix ne peut prendre (accord de trop, durée qui déborde).
    """
    out = [[] for _ in range(voices)]
    free = [0.0] * voices
    by_onset = {}
    for e in ev:
        by_onset.setdefault(e[0], []).append(e)
    for off in sorted(by_onset):
        group = sorted(by_onset[off], key=lambda e: -e[1])
        ready = [v for v in range(voices) if free[v] <= off + 1e-6]
        if not ready:
            ready = [min(range(voices), key=lambda v: free[v])]
        if voices == 2 and len(group) == 1 and len(ready) == 2:
            pairs = [(0, group[0]), (1, group[0])]
        elif len(group) >= len(ready):
            # plus de têtes que de voix libres : les extrêmes vont aux voix libres, l'intérieur à la plus proche
            pairs = [(ready[0], group[0])] + ([(ready[-1], group[-1])] if len(ready) > 1 else [])
        else:
            pairs = list(zip(ready, group)) if ready[0] == 0 else list(zip(reversed(ready), reversed(group)))
        if dropped is not None:
            taken = {id(e) for _v, e in pairs}
            dropped.extend(e for e in group if id(e) not in taken)
        for v, e in pairs:
            out[v].append(e)
            free[v] = off + e[2]
    return out


def line_faults(line, length, median):
    """Fautes d'une voix seule : trous entre ses notes, fin de mesure fausse, notes hors de sa tessiture (plus d'une
    octave de sa hauteur habituelle sur la pièce : tête lue sur la mauvaise portée ou à la mauvaise octave)."""
    if not line:
        return 2 * END
    f, at = 0, None
    for off, ps, dur, _p in line:
        if at is not None and off > at + 1e-6:
            f += round((off - at) / GRID)
        at = off + dur
        if median is not None and abs(ps - median) > 12:
            f += 1
    if abs(at - length) > 1e-6:
        f += END
    return f


def composite(x, y, voices, length, medians):
    """
    Voix par voix, la meilleure des deux lectures (ex. ténor juste chez Audiveris, basse juste chez homr). Rend les
    notes réunies et les voix telles quelles (à ne pas répartir à nouveau : une note seule de la basse, ténor en
    silence, serait prise pour un unisson et chantée aussi par le ténor).
    """
    drop_x, drop_y = [], []
    lx, ly = lines(x, voices, length, drop_x), lines(y, voices, length, drop_y)

    def nearest(e):
        return min(range(voices), key=lambda v: abs(e[1] - medians[v]) if medians[v] is not None else 0)

    pen_x, pen_y = [0] * voices, [0] * voices
    for e in drop_x:
        pen_x[nearest(e)] += 1
    for e in drop_y:
        pen_y[nearest(e)] += 1
    out, seen, chosen = [], set(), []
    for v in range(voices):
        fx = line_faults(lx[v], length, medians[v]) + pen_x[v]
        fy = line_faults(ly[v], length, medians[v]) + pen_y[v]
        chosen.append(ly[v] if fy < fx else lx[v])
        for e in chosen[-1]:
            k = (e[0], e[1], e[2])
            if k not in seen:
                seen.add(k)
                out.append(e)
    return sorted(out, key=lambda e: (e[0], -e[1])), chosen


def _q(x):
    return opFrac(Fraction(x).limit_denominator(48))


def rebuild(m, ev, voices, length, split=None):
    """
    Remplace le contenu de la mesure m (lecture Audiveris) par les notes ev (lecture homr), voix par voix ; split :
    voix déjà réparties (composite). Une durée qui déborde sur la note suivante de la même voix est raccourcie.
    """
    lyrics = {}
    for n in m.recurse().notes:  # paroles d'Audiveris gardées, accrochées à la note qui commence au même endroit
        if n.lyrics:
            lyrics.setdefault(round(float(n.getOffsetInHierarchy(m)), 4), [copy.deepcopy(l) for l in n.lyrics])
    for v in list(m.voices):
        m.remove(v)
    for el in list(m.notesAndRests):
        m.remove(el)
    if voices == 1:
        groups = {}
        for e in ev:
            groups.setdefault(e[0], []).append(e)
        parts = [[(off, g[0][2], [e[3] for e in g]) for off, g in sorted(groups.items())]]
        target = [m]
    else:
        parts = [[(off, dur, [p]) for off, _ps, dur, p in line] for line in (split or lines(ev, voices, length))]
        target = [stream.Voice(id=str(i + 1)) for i in range(voices)]
    for i, (line, dst) in enumerate(zip(parts, target)):
        at, prev = 0.0, None
        for off, dur, pitches in line:
            if off < at - 1e-6:
                if prev is None or off <= prev.offset + 1e-6:
                    continue
                prev.quarterLength = _q(off - float(prev.offset))
                at = off
            if off > at + 1e-6:
                dst.insert(_q(at), note.Rest(quarterLength=_q(off - at)))
            n = (chord.Chord([copy.deepcopy(p) for p in pitches], quarterLength=_q(dur)) if len(pitches) > 1
                 else note.Note(copy.deepcopy(pitches[0]), quarterLength=_q(dur)))
            if i == 0 and off in lyrics:
                for l in lyrics.pop(off):
                    n.lyrics.append(l)
            dst.insert(_q(off), n)
            prev, at = n, off + dur
        if at < length - 1e-6:
            dst.insert(_q(at), note.Rest(quarterLength=_q(length - at)))
    if voices > 1:
        for v in target:
            m.insert(0, v)


class HeadCounter:
    """
    Têtes pleines visibles sur la page, mesure par mesure, d'après la disposition de la lecture par homr (place des
    portées et des barres de chaque système) : à égalité de fautes, la lecture dont le nombre de têtes pleines
    (noires, croches…) est celui de l'image l'emporte (Audiveris fond parfois deux croches liées par une barre en une
    noire : do4-ré4 lu ré4).
    """

    def __init__(self, voix):
        self.ok = False
        try:
            import cv2
            self.cv2 = cv2
            d = json.loads((pathlib.Path(voix) / "disposition.json").read_text(encoding="utf-8"))
            self.pages = pathlib.Path(voix).parent.parent / "pages"
            self.systems = d["systems"]
            self.cache = {}
            self.ok = all("barres" in s_ for s_ in self.systems) and self.pages.exists()
        except Exception:  # noqa: BLE001 : sans disposition, pas de comptage
            self.ok = False

    def _blobs(self, page):
        if page not in self.cache:
            import numpy as np
            cv2 = self.cv2
            img = cv2.imread(str(self.pages / page), cv2.IMREAD_GRAYSCALE)
            sps = [(b - t) / 4 for s_ in self.systems for t, b, *_r in s_["staves"]]
            sp = float(np.median(sps)) if sps else 20.0
            ink = (img < 128).astype(np.uint8)
            k = max(3, int(0.55 * sp)) | 1
            heads = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            _n, _l, st, cen = cv2.connectedComponentsWithStats(heads, 8)
            keep = [(c[0], c[1], s_[cv2.CC_STAT_WIDTH]) for s_, c in zip(st[1:], cen[1:])
                    if 0.6 * sp <= s_[cv2.CC_STAT_HEIGHT] <= 1.6 * sp and 0.8 * sp <= s_[cv2.CC_STAT_WIDTH] <= 2.6 * sp]
            self.cache[page] = (keep, sp)
        return self.cache[page]

    def count(self, staff, j):
        """Têtes pleines de la mesure j (numérotation de homr) sur la portée staff, ou None."""
        if not self.ok:
            return None
        k = j
        for s_ in self.systems:
            n = len(s_["barres"])
            if k < n:
                blobs, sp = self._blobs(s_["page"])
                if staff >= len(s_["staves"]):
                    return None
                t, b = s_["staves"][staff][0], s_["staves"][staff][1]
                x1 = s_["barres"][k]
                x0 = s_["barres"][k - 1] if k else x1 - 12 * sp  # 1re mesure : depuis la tête de ligne (approché)
                if not k:
                    return None
                heads = 0
                for x, y, w in blobs:
                    if x0 + 0.3 * sp < x < x1 - 0.3 * sp and t - 3 * sp <= y <= b + 3 * sp:
                        heads += max(1, int(round(w / (1.35 * sp))))  # deux têtes accolées (seconde) : un seul blob
                return heads
            k -= n
        return None


def filled(m_events):
    """Têtes pleines d'une lecture de mesure (noires et plus courtes ; blanches et rondes sont creuses)."""
    return sum(1 for _o, _ps, d, _p in m_events if d <= 1.5 + 1e-6)


def _mkey(m):
    return (m.number, m.numberSuffix or "")


def pad_missing(score):
    """
    Mesures qu'Audiveris a jetées sur une portée seulement (mesure jugée fausse : la portée de sol perd ses mesures
    7 et 8, celle de fa les garde) : remplacées par des mesures vides, pour que les portées aient le même nombre de
    mesures et que l'autre lecture puisse les remplir (une mesure vide est la plus fautive). Seulement si une partie
    porte tous les numéros des autres. Rend les mesures ajoutées {(n° de partie, rang de la mesure)}.
    """
    parts = list(score.parts)
    keys = [[_mkey(m) for m in p.getElementsByClass(stream.Measure)] for p in parts]
    if len(parts) < 2 or all(k == keys[0] for k in keys):
        return set()
    full = max(keys, key=len)
    if len(set(full)) != len(full) or any(not set(k) <= set(full) for k in keys):
        return set()
    if any([x for x in full if x in set(k)] != k for k in keys):
        return set()  # numéros dans un autre ordre
    model = parts[keys.index(full)]
    by_key = {_mkey(m): m for m in model.getElementsByClass(stream.Measure)}
    added = set()
    for pi, (part, k) in enumerate(zip(parts, keys)):
        if k == full:
            continue
        have = {_mkey(m): m for m in part.getElementsByClass(stream.Measure)}
        rebuilt = []
        for pos, key_ in enumerate(full):
            if key_ in have:
                rebuilt.append(have[key_])
                continue
            ref = by_key[key_]
            m = stream.Measure(number=ref.number)
            m.numberSuffix = ref.numberSuffix
            m.append(note.Rest(quarterLength=ref.duration.quarterLength or 4.0))
            m.pupitre_vide = True  # repérée ensuite même si des mesures sont insérées avant elle
            rebuilt.append(m)
            added.add((pi, pos))
        for m in list(part.getElementsByClass(stream.Measure)):
            part.remove(m)
        offset = 0.0
        for m in rebuilt:
            part.insert(offset, m)
            offset += float(by_key[_mkey(m)].duration.quarterLength) if _mkey(m) in by_key else float(m.duration.quarterLength)
    return added


def image_measures(voix):
    """Nombre de mesures vu sur l'image (barres de chaque système, disposition de la lecture par homr), ou None."""
    try:
        d = json.loads((pathlib.Path(voix) / "disposition.json").read_text(encoding="utf-8"))
        return sum(int(s_["mesures"]) for s_ in d["systems"])
    except Exception:  # noqa: BLE001
        return None


def _audiveris_systems(part):
    """Systèmes d'une lecture d'Audiveris : [(marge gauche, [fin de chaque mesure])] en dixièmes, et (système, rang) de
    chaque mesure ; None sans largeurs de mesures."""
    systems, where = [], []
    for k, m in enumerate(part.getElementsByClass(stream.Measure)):
        if m.layoutWidth is None:
            return None, None
        sl = list(m.getElementsByClass(layout.SystemLayout))
        pl = list(m.getElementsByClass(layout.PageLayout))
        if k == 0 or any(x.isNew for x in sl) or any(x.isNew for x in pl):
            systems.append([next((x.leftMargin for x in sl if x.leftMargin is not None), None), []])
        ends = systems[-1][1]
        ends.append((ends[-1] if ends else 0.0) + float(m.layoutWidth))
        where.append((len(systems) - 1, len(ends) - 1))
    return systems, where


def image_map(score, voix):
    """
    Mesures d'Audiveris replacées sur l'image : largeurs et marges (dixièmes d'interligne) mises à l'échelle de la page,
    comparées aux barres vues sur l'image (disposition de la lecture par homr). Rend, pour chaque mesure d'Audiveris,
    les mesures de l'image qu'elle couvre (plusieurs : barres manquées, mesures fusionnées ; aucune image non couverte :
    mesure perdue), ou None si les deux découpages ne se correspondent pas (systèmes coupés autrement).
    """
    try:
        img = json.loads((pathlib.Path(voix) / "disposition.json").read_text(encoding="utf-8"))["systems"]
    except Exception:  # noqa: BLE001
        return None
    for part in score.parts:
        systems, where = _audiveris_systems(part)
        if systems is not None:
            break
    else:
        return None
    if len(systems) != len(img) or any(left is None or not ends for left, ends in systems) or \
            any(not s_.get("barres") for s_ in img):
        return None
    scale = statistics.median(s_["barres"][-1] / (left + ends[-1]) for (left, ends), s_ in zip(systems, img))
    sp = statistics.median((st[1] - st[0]) / 4 for s_ in img for st in s_["staves"])
    starts, base = [], 0
    for s_ in img:
        starts.append(base)
        base += len(s_["barres"])
    out = []
    for si, mi in where:
        left, ends = systems[si]
        bars = img[si]["barres"]
        a0, a1 = (left + (ends[mi - 1] if mi else 0.0)) * scale, (left + ends[mi]) * scale
        covered = []
        for q, hi in enumerate(bars):
            lo = bars[q - 1] if q else min(left * scale, hi - sp)  # 1re mesure : depuis le début du système
            if a0 - 0.5 * sp < (lo + hi) / 2 < a1 + 0.5 * sp and hi > a0 + sp:
                covered.append(starts[si] + q)
        out.append(covered)
    flat = [q for c in out for q in c]
    if flat != sorted(set(flat)) or sum(len(c) == 1 for c in out) < 0.7 * len(out):
        return None  # image couverte deux fois, dans le désordre : découpages incompatibles
    return out


def restructure(a, sh, voices, mapping, total):
    """
    Mesures d'Audiveris qui en couvrent plusieurs sur l'image (barres manquées : notes perdues, durées fausses) et
    mesures de l'image qu'aucune ne couvre (perdues) : remplacées par celles de homr, découpées comme l'image. Rend
    le nombre de mesures reprises.
    """
    if len(sh[0]) != total:
        return 0
    plan, taken = [], set()  # plan : pour chaque mesure de sortie, ("a", i) ou ("h", j)
    sa = staves(a)
    sa_used = sa[len(sa) - len(sh):]

    def lost(i, cov):
        """La mesure fusionnée d'Audiveris a perdu des notes (barre manquée seule : ses notes sont souvent toutes là,
        et celles de homr, sur deux portées, moins sûres)."""
        n_a = sum(len(events(st[i])) for st in sa_used)
        n_h = sum(len(events(st[q])) for st in sh for q in cov)
        return n_a < 0.6 * n_h

    def sound(cov):
        """Les mesures de homr sont toutes rythmiquement justes (sinon, sur deux portées, ses accords sont peu sûrs)."""
        for q in cov:
            bar = float(sh[0][q].duration.quarterLength) or 4.0
            evs = [events(st[q]) for st in sh]
            ends = {round(end_of(e), 3) for e in evs if e}
            if len(ends) == 1 and 0 < min(ends) <= bar:
                bar = min(ends)
            if not all(e and faults(e, [], bar, voices) == 0 for e in evs):
                return False
        return True

    for i, cov in enumerate(mapping):
        gap = [q for q in range(max(taken, default=-1) + 1, cov[0])] if cov else []
        for q in gap:
            plan.append(("h", q))
            taken.add(q)
        if len(cov) > 1 and (lost(i, cov) or sound(cov)):
            plan.extend(("h", q) for q in cov)
        else:
            plan.append(("a", i))
        taken.update(cov)
    for q in range(max(taken, default=-1) + 1, total):
        plan.append(("h", q))
    redone = sum(1 for kind, _ in plan if kind == "h")
    if not redone:
        return 0
    parts = list(a.parts)
    offset_parts = len(parts) - len(sh)
    for pi, part in enumerate(parts):
        ms = list(part.getElementsByClass(stream.Measure))
        out = []
        for kind, idx in plan:
            if kind == "a":
                out.append(ms[idx])
                continue
            evs = [events(st[idx]) for st in sh]
            bar = float(sh[0][idx].duration.quarterLength) or 4.0
            ends = {round(end_of(e), 3) for e in evs if e}
            if len(ends) == 1 and 0 < min(ends) <= bar:
                bar = min(ends)
            new = stream.Measure()
            new.append(note.Rest(quarterLength=bar))
            new.pupitre_insere = True
            if pi >= offset_parts and evs[pi - offset_parts]:
                rebuild(new, evs[pi - offset_parts], voices, bar)
            out.append(new)
        first = ms[0] if ms else None
        for x in ms:
            part.remove(x)
        at, number = 0.0, (first.number if first is not None else 1)
        for k, x in enumerate(out):
            if k == 0 and x is not first and first is not None:
                for el in first.getElementsByClass(("Clef", "KeySignature", "TimeSignature")):
                    x.insert(0, copy.deepcopy(el))  # clé, armure et mesure du début gardées
            x.number = number + k
            part.insert(at, x)
            at += float(x.duration.quarterLength)
    return redone


def insert_missing(a, sh, pairs, voices, seen):
    """
    Mesure perdue par Audiveris sur toutes les portées (barre lue comme un arpège, mesure jugée fausse) : homr la lit et
    son nombre de mesures est celui de l'image (seen). Entre deux mesures appariées qui se suivent chez Audiveris, une
    ou deux mesures de homr sans correspondante sont insérées, si elles sont rythmiquement justes sur chaque portée.
    Rend le nombre de mesures insérées.
    """
    parts = list(a.parts)
    sa = staves(a)
    n, m = len(sa[0]), len(sh[0])
    if seen is None or m != seen or n >= m:
        return 0
    inserts = []  # (après la mesure i d'Audiveris, [mesures j de homr])
    for (i0, j0), (i1, j1) in zip([(-1, -1)] + pairs, pairs + [(n, m)]):
        if i1 == i0 + 1 and 1 <= j1 - j0 - 1 <= 2:
            inserts.append((i0, list(range(j0 + 1, j1))))
    plan = []
    for i0, js in inserts:
        for j in js:
            bar = float(sh[0][j].duration.quarterLength) or 4.0
            evs = [events(st[j]) for st in sh]
            ends = {round(end_of(e), 3) for e in evs if e}
            if len(ends) == 1 and 0 < min(ends) <= bar:
                bar = min(ends)  # mesure courte (levée après une double barre), comme Audiveris l'écrit
            if not all(e and faults(e, [], bar, voices) == 0 for e in evs):
                break
            plan.append((i0, j, bar, evs))
    if not plan:
        return 0
    offset_parts = len(parts) - len(sh)  # disposition « grand » : portée d'instrument au-dessus, non lue par homr
    for pi, part in enumerate(parts):
        ms = list(part.getElementsByClass(stream.Measure))
        out = []
        for i in range(-1, len(ms)):
            if i >= 0:
                out.append(ms[i])
            for i0, j, bar, evs in plan:
                if i0 == i:
                    new = stream.Measure()
                    new.append(note.Rest(quarterLength=bar))
                    new.pupitre_insere = True  # mesure à vérifier (lue par homr seul)
                    if pi >= offset_parts:
                        rebuild(new, evs[pi - offset_parts], voices, bar)
                    out.append(new)
        for x in ms:
            part.remove(x)
        at, number = 0.0, (ms[0].number if ms else 1)
        for k, x in enumerate(out):
            x.number = number + k
            part.insert(at, x)
            at += float(x.duration.quarterLength)
    return len(plan)


def staves(score):
    return [list(p.getElementsByClass(stream.Measure)) for p in score.parts]


def pickup(ea, eh, bar):
    """Levée : notée courte par Audiveris (un temps), parfois en mesure entière précédée d'un silence par homr : ramenée au début."""
    end_a = max((end_of(e) for e in ea if e), default=0.0)
    end_h = max((end_of(e) for e in eh if e), default=0.0)
    start_a = min((e[0][0] for e in ea if e), default=0.0)
    shift = min((e[0][0] for e in eh if e), default=0.0) - start_a
    if end_a < bar - 1e-6 and shift > 1e-6 and abs(end_h - shift - end_a) < 1e-6:
        return [[(o - shift, ps, d, p) for o, ps, d, p in e] for e in eh]
    return eh


def _sings(m):
    return any(not n.duration.isGrace for n in m.recurse().notes)


def _initial(part):
    words = re.findall(r"[^\W\d_]+", part.partName or "")
    return words[0][0].lower() if words else ""


def collapse(score, target):
    """
    Audiveris rend parfois une même voix en deux parties, une par nom lu (« Soprano, Alto… » au 1er système, « S., A.… »
    ensuite) : deux parties qui ne chantent jamais dans la même mesure, de même initiale et de même registre (ou, sans
    nom commun, de registre très proche), sont réunies dans la première, jusqu'à n'en garder que target. L'ordre des
    portées est gardé. Rend False si ce n'est pas possible.
    """
    while len(score.parts) > target:
        parts, st = list(score.parts), staves(score)
        sings = [[_sings(m) for m in s] for s in st]
        pitch = [statistics.median(ps) if (ps := [e[1] for m in s for e in events(m)]) else None for s in st]
        best = None
        for i in range(len(parts)):
            for j in range(i + 1, len(parts)):
                if len(st[i]) != len(st[j]) or any(a and b for a, b in zip(sings[i], sings[j])):
                    continue
                dist = abs(pitch[i] - pitch[j]) if pitch[i] is not None and pitch[j] is not None else 0
                same = _initial(parts[i]) == _initial(parts[j]) != ""
                if dist > (7 if same else 4):
                    continue
                if best is None or (not same, dist) < best[0]:
                    best = ((not same, dist), i, j)
        if best is None:
            return False
        _rank, keep, drop = best
        for a, b, used in zip(st[keep], st[drop], sings[drop]):
            if not used:
                continue
            for el in list(a.voices) + list(a.notesAndRests):
                a.remove(el)
            moved = [(el.offset, el) for el in list(b.voices) + list(b.notesAndRests)]
            for off, el in moved:
                b.remove(el)
                a.insert(off, el)
        score.remove(parts[drop])
    return True


def _pitch_sim(x, y):
    """Ressemblance de deux mesures d'une portée (suite des hauteurs), de 0 à 1."""
    a, b = [round(e[1]) for e in x], [round(e[1]) for e in y]
    if not a and not b:
        return 1.0
    prev = list(range(len(b) + 1))
    for i, p in enumerate(a, 1):
        cur = [i]
        for j, q in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (p != q)))
        prev = cur
    return 1 - prev[-1] / max(len(a), len(b))


PAIR = 0.6  # ressemblance minimale de deux mesures pour les comparer


def pair_measures(sa, sh):
    """
    Mesures correspondantes des deux lectures [(i, j)] : alignement des suites de mesures d'après leurs notes, même à
    nombre égal (une barre vue par un seul lecteur au milieu, une mesure oubliée plus loin : le reste serait décalé).
    Les mesures sans correspondante sûre gardent la lecture d'Audiveris ; une ou deux mesures non appariées de chaque
    côté, entre deux mesures appariées (ou au bout), se correspondent : les barres s'accordent, seul le contenu diffère
    (accord final lu comme un silence par l'un des lecteurs).
    """
    n, m = len(sa[0]), len(sh[0])
    ea = [[events(st[i]) for st in sa] for i in range(n)]
    eh = [[events(st[j]) for st in sh] for j in range(m)]
    sim = [[statistics.mean(_pitch_sim(x, y) for x, y in zip(ea[i], eh[j])) for j in range(m)] for i in range(n)]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best[i][j] = max(best[i - 1][j], best[i][j - 1],
                             best[i - 1][j - 1] + sim[i - 1][j - 1] if sim[i - 1][j - 1] >= PAIR else -1.0)
    pairs, i, j = [], n, m
    while i and j:
        if sim[i - 1][j - 1] >= PAIR and best[i][j] == best[i - 1][j - 1] + sim[i - 1][j - 1]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    filled = []
    for (i0, j0), (i1, j1) in zip([(-1, -1)] + pairs, pairs + [(n, m)]):
        gap = i1 - i0 - 1
        if gap == j1 - j0 - 1 and 0 < gap <= 2:
            filled.extend((i0 + t, j0 + t) for t in range(1, gap + 1))
        if i1 < n:
            filled.append((i1, j1))
    return filled


def _keys(score):
    """Armures imprimées ; une portée qui n'en porte aucune en tête compte pour zéro."""
    out = []
    for p in score.parts:
        measures = list(p.getElementsByClass(stream.Measure))
        if measures and measures[0].keySignature is None:
            out.append(0)
        out += [k.sharps for k in p.recurse().getElementsByClass(key.KeySignature)]
    return out


def adopt_key(a, h, voix=None, layout=None):
    """
    Armure perdue par Audiveris, lue en entier par homr : petites portées (dièses réduits à des points au seuillage :
    1 dièse lu au lieu de 3), photo bougée (chaque dièse n'est plus que deux taches : aucune armure lue). homr, entraîné
    sur des photos, lit alors la bonne (banc : 3 et 4 dièses sur les six copies examinées), et sur les pages nettes les
    deux lecteurs s'accordent. On ne prend celle de homr que si elle est la même sur toutes ses portées, qu'Audiveris n'a
    lu nulle part plus d'altérations qu'elle ni d'un autre genre, et qu'il en a lu moins au moins une fois (la lecture en
    perd bien plus souvent qu'elle n'en invente ; photo : 4 dièses lus sur une portée, 3 ou aucun sur les autres).
    Les notes sans altération écrite prennent celle de la nouvelle armure. Rend l'armure adoptée, ou None.
    """
    if os.environ.get("PUPITRE_ARMURE") == "audiveris":
        return None
    found = set(_keys(h))
    if len(found) != 1 or not (target := found.pop()):
        return None
    if voix and layout and abs(target) >= 2:
        # dièses ou bémols ? homr les confond sur photo floue (4 bémols lus pour 4 dièses) : la place des signes sur
        # l'image (les dièses descendent d'abord, les bémols montent) tranche
        try:
            import pupitres
            sign = pupitres.key_sign_from_image(pathlib.Path(voix), layout, abs(target))
        except Exception:  # noqa: BLE001
            sign = 0
        if sign and sign * target < 0:
            print(f"Armure de homr retournée d'après la place des signes : {target:+d} → {-target:+d}", file=sys.stderr)
            target = -target
    read = _keys(a)
    if any(k * target < 0 or abs(k) > abs(target) for k in read) or all(k == target for k in read):
        return None
    wanted = key.KeySignature(target)
    for part in a.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        if not measures:
            continue
        current = 0  # armure lue par Audiveris en vigueur
        for m in measures:
            if m.keySignature is not None:
                current = m.keySignature.sharps
            for ks in m.getElementsByClass(key.KeySignature):
                ks.sharps = target
            if current == target:
                continue  # notes déjà écrites dans la bonne armure
            carried = set()  # une altération écrite vaut pour la suite de la mesure
            for n in m.recurse().notes:
                if n.tie is not None and n.tie.type in ("stop", "continue"):
                    continue  # note liée depuis la mesure d'avant : elle garde son altération
                for pt in n.pitches:
                    if pt.accidental is not None and pt.accidental.displayStatus:
                        carried.add((pt.step, pt.octave))
                    elif (pt.step, pt.octave) not in carried:
                        want = wanted.accidentalByStep(pt.step)
                        pt.accidental = copy.deepcopy(want) if want else None
                        if pt.accidental is not None:  # due à l'armure, pas écrite (render la prendrait pour une lue)
                            pt.accidental.displayStatus = False
        if measures[0].keySignature is None:
            measures[0].insert(0, key.KeySignature(target))
    return target


def arbitrate(a_path, h_path, out, layout, voix=None, third=None, split=False):
    a, h = converter.parse(a_path), converter.parse(h_path)
    before = sorted(set(_keys(a)))
    adopted = adopt_key(a, h, voix, layout)
    if adopted is not None:
        print(f"Armure lue par homr adoptée : {adopted:+d} (Audiveris : {before or 'aucune'})", file=sys.stderr)
    keyed = copy.deepcopy(a) if adopted is not None else None  # _arbitrate réunit des parties avant de renoncer
    try:
        _arbitrate(a, h, out, layout, third, voix, split)
    except SystemExit as e:
        if keyed is None:
            raise
        keyed.write("musicxml", fp=out, makeNotation=False)  # pas d'arbitrage mesure par mesure, mais l'armure est rétablie
        print(f"{e} ; lecture d'Audiveris gardée, avec l'armure de homr", file=sys.stderr)


def _arbitrate(a, h, out, layout, third=None, voix=None, split=False):
    sh = staves(h)
    voices = 2 if layout == "grand" else 1
    # mêmes portées des deux côtés ; seule exception : la portée d'instrument au-dessus du chœur (disposition « grand »),
    # que homr ne lit pas.
    if sh and len(a.parts) > len(sh) + (layout == "grand"):
        # parties d'Audiveris éparpillées (une par nom lu, photo floue : 8 parties pour 4 portées) : chacune prend sa
        # place parmi les portées qui chantent ensemble (render.regroup_by_place, comme pour séparer les voix) ;
        # sinon, réunion deux à deux (collapse)
        try:
            import render
            placed = render.regroup_by_place(list(a.parts))
        except Exception:  # noqa: BLE001
            placed = None
        if placed and len(placed) in (len(sh), len(sh) + (layout == "grand")):
            for part in list(a.parts):
                a.remove(part)
            for part in placed:
                a.insert(0, part)
            print(f"Parties d'Audiveris regroupées par place : {len(placed)}", file=sys.stderr)
        else:
            collapse(a, len(sh) + (layout == "grand"))
    padded = set()
    if PAD:
        padded = pad_missing(a)
        if padded:
            print(f"Mesures absentes d'une portée chez Audiveris, laissées vides pour l'autre lecture : {len(padded)}",
                  file=sys.stderr)
    restructured, mapping = 0, None
    if IMAGE_MAP and voix and sh:
        total = image_measures(voix)
        mapping = image_map(a, voix) if total and len(sh[0]) == total else None
        if mapping is not None:
            restructured = restructure(a, sh, voices, mapping, total)
            if restructured:
                print(f"Mesures d'Audiveris recoupées d'après les barres de l'image, reprises de homr : {restructured}",
                      file=sys.stderr)
    sa = staves(a)
    if not sh or not (len(sa) == len(sh) or (layout == "grand" and len(sa) == len(sh) + 1)):
        raise SystemExit(f"Portées différentes ({len(sa)} contre {len(sh)}) : pas d'arbitrage")
    sa_used = sa[len(sa) - len(sh):]  # disposition « grand » : la portée d'instrument au-dessus n'est pas lue par homr
    count = len(sa_used[0])
    if any(len(x) != count for x in sa_used) or any(len(x) != len(sh[0]) for x in sh):
        raise SystemExit("Nombres de mesures différents d'une portée à l'autre : pas d'arbitrage")
    pairs = pair_measures(sa_used, sh)
    # voix séparées : chaque mesure d'Audiveris tombe sur une seule mesure de l'image, homr en a autant que l'image ;
    # elles se correspondent par leur place, même quand leurs notes diffèrent trop pour être appariées (copie usée :
    # Audiveris y perd des notes, 6 mesures sur 11 appariées par les notes, aucun arbitrage)
    geo = split and GEO and mapping is not None and not restructured and len(mapping) == count and \
        all(len(c) == 1 for c in mapping) and len(sh[0]) == image_measures(voix)
    if geo:
        if len(pairs) < count:
            print(f"Mesures appariées par leur place sur l'image : {count} (par les notes : {len(pairs)})", file=sys.stderr)
        pairs = [(i, c[0]) for i, c in enumerate(mapping)]
    if len(pairs) < 0.6 * count:
        raise SystemExit(f"Mesures impossibles à apparier ({len(pairs)}/{count}) : pas d'arbitrage")
    # mesures replacées sur l'image : les mesures vraiment perdues y ont déjà été reprises (restructure) ; sinon, d'après
    # l'appariement des notes (une mesure fusionnée par Audiveris y passerait pour perdue : notes en double)
    inserted = insert_missing(a, sh, pairs, voices, image_measures(voix)) if INSERT and voix and mapping is None else 0
    if inserted:
        n_ins = inserted
        print(f"Mesures perdues par Audiveris, reprises de homr (nombre vu sur l'image) : {n_ins}", file=sys.stderr)
        sa = staves(a)
        sa_used = sa[len(sa) - len(sh):]
        count = len(sa_used[0])
        pairs = pair_measures(sa_used, sh)
    # hauteur habituelle de chaque voix de chaque portée, sur les mesures où les deux lectures s'accordent
    medians = []
    for st_a, st_h in zip(sa_used, sh):
        per = [[] for _ in range(voices)]
        for i, j in pairs:
            ea_ = events(st_a[i])
            if signature(ea_) == signature(events(st_h[j])):
                for v, line in enumerate(lines(ea_, voices, 0)):
                    per[v].extend(e[1] for e in line)
        medians.append([statistics.median(p) if p else None for p in per])
    same = sum(signature(events(st_a[i])) == signature(events(st_h[j])) for st_a, st_h in zip(sa_used, sh) for i, j in pairs)
    rescue = same < 0.4 * len(pairs) * len(sh) and not geo
    if rescue and not RESCUE:
        # lectures trop différentes pour être comparées mesure à mesure (mesures décalées, portées mal appariées)
        raise SystemExit(f"Lectures trop différentes ({same}/{len(pairs) * len(sh)} portées-mesures identiques) : pas d'arbitrage")
    if rescue:
        # secours seulement : homr ne remplit que les mesures qu'Audiveris a laissées vides ou jetées (pad_missing)
        print(f"Lectures trop différentes ({same}/{len(pairs) * len(sh)} portées-mesures identiques) : "
              "seules les mesures vides ou jetées par Audiveris sont reprises de homr", file=sys.stderr)
    doubtful, changed, agreed, mixed, by_ear, by_usage, by_vote, by_heads = {}, 0, 0, 0, 0, 0, 0, 0
    by_range = 0
    changed += inserted + restructured
    counter = HeadCounter(voix) if voix and HEADS else None
    # troisième lecture (Audiveris sur l'autre version de l'image, deux portées) : même découpage que la première ?
    st_t = None
    if third and VOTE:
        try:
            tt = staves(converter.parse(third))
            if len(tt) == len(sa) and all(len(x) == count for x in tt[len(tt) - len(sh):]):
                st_t = tt[len(tt) - len(sh):]
        except Exception:  # noqa: BLE001 : sans troisième lecture, l'arbitrage à deux
            st_t = None
    for k in sorted(set(range(count)) - {i for i, _j in pairs}):
        doubtful[str(k + 1)] = 0.5  # une barre vue par un seul lecteur : mesure à vérifier
    for k, j in pairs:
        ma = [st[k] for st in sa_used]
        mh = [st[j] for st in sh]
        bar = float(ma[0].barDuration.quarterLength) if ma[0].timeSignature or ma[0].getContextByClass("TimeSignature") else 4.0
        ea, eh = [events(m) for m in ma], [events(m) for m in mh]
        if k == 0 and j == 0:
            eh = pickup(ea, eh, bar)
        # durée de la mesure : celle que donnent la plupart des lectures (levée, mesure coupée par une double barre)
        ends = [round(end_of(e), 3) for e in ea + eh if e]
        length = bar
        if ends:
            common = statistics.multimode(ends)
            if len(common) == 1 and ends.count(common[0]) >= 2 and common[0] <= bar + 1e-6:
                length = common[0]
        ends_a = {round(end_of(e), 3) for e in ea if e}
        if SPLIT_BAR and len(ends_a) == 1 and min(ends_a) < bar - 1e-6 and k + 1 < count:
            # fin de phrase (point d'orgue, double barre) : mesure courte d'Audiveris que la levée suivante complète ;
            # homr, qui ramène chaque mesure à sa durée pleine, y ajoutait une note fantôme
            nxt = {round(end_of(events(st[k + 1])), 3) for st in sa_used if events(st[k + 1])}
            if len(nxt) == 1 and abs(min(ends_a) + min(nxt) - bar) < 1e-6:
                length = min(ends_a)
        if SPLIT_BAR and k == 0 and len(ends_a) == 1 and min(ends_a) < bar - 1e-6:
            length = min(ends_a)  # levée : toutes les portées d'Audiveris s'accordent sur sa durée
        unsure = False
        for s, (m, x, y) in enumerate(zip(ma, ea, eh)):
            if signature(x) == signature(y):
                agreed += 1
                continue
            if rescue:
                if (getattr(m, "pupitre_vide", False) or not x) and y and faults(y, [], length, voices) == 0:
                    rebuild(m, y, voices, length)
                    changed += 1
                    unsure = True
                continue
            if st_t is not None and signature(events(st_t[s][k])) == signature(y):
                # vote : homr et l'autre lecture d'Audiveris s'accordent contre la première (deux sur trois)
                rebuild(m, y, voices, length)
                changed += 1
                by_vote += 1
                continue
            fa, fh = faults(x, y, length, voices), faults(y, x, length, voices)
            # à égalité, Audiveris (meilleur lecteur des pages nettes : bécarres, rythmes cohérents mais différents),
            # sauf si homr sonne nettement plus juste avec les autres portées et dans la tonalité
            take_h = fh < fa
            if split and TIE_HOMR and fa == fh and x and y and not only_accidentals(x, y):
                # voix séparées (photo lue sûrement par homr, copie usée) : à égalité, homr, qui lit une voix seule ;
                # Audiveris y confond des degrés (Kyrie réel : ténor mi4 pour ré4, homr juste). Altérations seules :
                # Audiveris et la relecture des signes, comme avant
                take_h = True
            usual = medians[s][0] if voices == 1 else None
            if usual is None and voices == 1 and layout == "satb" and len(sh) == 4:
                usual = (69, 64, 57, 50)[s]  # aucune mesure commune : tessiture de la voix à sa place
            if OCTAVE and usual is not None and x and y:
                mx = statistics.median(e[1] for e in x)
                my = statistics.median(e[1] for e in y)
                same_notes = sorted(round(e[1]) % 12 for e in x) == sorted(round(e[1]) % 12 for e in y)
                if same_notes and 10 <= abs(mx - my) <= 14:
                    # mêmes notes à l'octave près (clé de ténor suivie autrement d'une ligne à l'autre) : la lecture la
                    # plus proche de la tessiture habituelle de la portée
                    closer = abs(my - usual) < abs(mx - usual)
                    if closer != take_h:
                        take_h = closer
                        unsure = True
                elif take_h and abs(my - usual) > 9 and abs(mx - usual) <= 7:
                    # homr une octave à côté (clé de la ligne mal suivie : ténor lu en clé de sol sans 8) : sa
                    # mesure, plus cohérente en rythme, mettrait la voix hors de sa tessiture
                    take_h = False
                    unsure = True
                elif not take_h and abs(mx - usual) > (9 if medians[s][0] is not None else 12) and abs(my - usual) <= 7 \
                        and min(abs(abs(mx - my) - 12), abs(abs(mx - my) - 24)) > 1.5:
                    # (une octave pile : clé de ténor lue sans 8 sur toute la voix, que le rendu ramène en entier ;
                    # mêler des mesures des deux lectures fausserait cette correction)
                    # Audiveris hors de la tessiture (petite portée : têtes rapportées dix degrés trop bas), homr dedans
                    take_h = True
                    by_range += 1
                    if os.environ.get("PUPITRE_DEBUG_TESSITURE"):
                        print(f"tessiture : portée {s} mesure {k + 1} habituelle {usual} audiveris {mx} homr {my}", file=sys.stderr)
            if HEADS and fa == fh and counter is not None and not only_accidentals(x, y):
                seen = counter.count(s, j)
                if seen is not None and abs(filled(y) - seen) < abs(filled(x) - seen):
                    take_h = True  # homr a autant de têtes pleines que l'image, Audiveris non
                    by_heads += 1
            if REDONDANT and fa == fh and only_accidentals(x, y):
                mixed_acc, taken = mix_accidentals(x, y, _key_at(m))
                if taken:
                    rebuild(m, mixed_acc, voices, length)
                    changed += 1
                    by_usage += taken
                    unsure = True
                    continue
            if MUSICAL and fa == fh and not take_h:
                others = [e for t, ev_ in enumerate(ea) if t != s for e in ev_]
                ks = _key_at(m)
                if musical(y, others, ks) > musical(x, others, ks) + MUSIC_MARGIN:
                    take_h = True
                    by_ear += 1
            if voices > 1 and min(fa, fh) > 0:
                comp, split = composite(x, y, voices, length, medians[s])
                if signature(comp) not in (signature(x), signature(y)) and faults(comp, [], length, voices) < min(fa, fh):
                    rebuild(m, comp, voices, length, split)
                    changed += 1
                    mixed += 1
                    unsure = True
                    continue
            if take_h:
                rebuild(m, y, voices, length)
                changed += 1
            if min(fa, fh) > 0 or fa == fh:
                unsure = True
        if unsure or getattr(ma[0], "pupitre_insere", False):
            doubtful[str(k + 1)] = 0.5
    if rescue and not changed and not inserted and not restructured:
        raise SystemExit("Aucune mesure vide à reprendre : pas d'arbitrage")
    try:
        a.write("musicxml", fp=out)
    except Exception as e:  # noqa: BLE001 : ligatures refaites par music21 sur une mesure trop pleine (MeterException)
        print(f"Écriture sans ligatures refaites ({type(e).__name__})", file=sys.stderr)
        a.write("musicxml", fp=out, makeNotation=False)
    mean = 1 - 0.5 * len(doubtful) / max(1, count)
    pathlib.Path(out).with_name("fiabilite.json").write_text(json.dumps(
        {"passes": 2, "lecteurs": ["Audiveris", "homr"], "moyenne": round(mean, 3), "mesures": count,
         "arbitrees": changed, "a_verifier": doubtful, "secours": rescue}, ensure_ascii=False), encoding="utf-8")
    print(f"Double lecture : {agreed} portées-mesures identiques, {changed} reprises de homr (dont {mixed} voix par voix, {by_ear} à l'oreille, {by_usage} altérations vues par homr seul, {by_vote} par vote à trois lectures, {by_heads} par les têtes de l'image, {by_range} par la tessiture), "
          f"{len(doubtful)}/{count} mesures à vérifier", file=sys.stderr)


if __name__ == "__main__":
    args = sys.argv[1:]
    third = None
    if "--troisieme" in args:  # troisième lecture (Audiveris, autre version de l'image) : vote à trois
        k = args.index("--troisieme")
        third = args[k + 1]
        del args[k:k + 2]
    split = "--voix-separees" in args  # lecture de homr sur les pages des voix séparées (voix_separees.py)
    args = [x for x in args if x != "--voix-separees"]
    if len(args) not in (4, 5):  # 5e : dossier des lignes découpées (sens de l'armure lu sur l'image)
        sys.exit(__doc__)
    arbitrate(*args, third=third, split=split)
