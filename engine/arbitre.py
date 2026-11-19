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


class Events(list):
    """Notes d'une mesure, avec les silences écrits dans la lecture (rests : [(début, fin)])."""
    rests = ()



def drop_chord_symbols(*scores):
    """Accords chiffrés pour la guitare (G, Em, Am7) lus par Audiveris : des accords sans durée que music21 compte
    parmi les notes (instants chantés par trop de notes, hauteurs, notes à apparier). Ils ne se chantent pas."""
    if os.environ.get("PUPITRE_ACCORDS_CHIFFRES") == "garder":
        return scores[0] if len(scores) == 1 else scores
    from music21 import harmony
    for sc in scores:
        for h in list(sc.recurse().getElementsByClass(harmony.Harmony)):
            h.activeSite.remove(h)
    return scores[0] if len(scores) == 1 else scores

def events(m):
    """Notes d'une mesure : (début, hauteur en demi-tons, durée, Pitch), têtes en double fusionnées ; les silences
    écrits sont gardés à part (une note seule pendant le silence d'une autre voix n'est pas un unisson)."""
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
    ev = Events(sorted(out, key=lambda e: (e[0], -e[1])))
    ev.rests = [(round(float(r.getOffsetInHierarchy(m)), 4), round(float(r.getOffsetInHierarchy(m) + r.quarterLength), 4))
                for r in m.recurse().getElementsByClass(note.Rest) if r.quarterLength]
    return ev


# note seule à un instant où les deux voix sont libres : unisson (chantée par les deux), sauf si la lecture écrit un
# silence à cet instant (Kyrie réel, m. 4 : soupir du ténor, fa de la basse ; l'unisson donnait le fa au ténor, puis
# faisait paraître fautive la lecture juste de homr) ; elle va alors à la voix dont elle est la plus proche
REST_UNISON = os.environ.get("PUPITRE_UNISSON_SILENCE", "1") == "1"


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
SPLIT_PREV = os.environ.get("PUPITRE_LEVEE_APRES", "1") == "1"  # levée qui complète la mesure courte d'avant
SPLIT_BAR = os.environ.get("PUPITRE_MESURE_COUPEE", "1") == "1"  # mesure courte + levée d'Audiveris : durée gardée  # lectures trop différentes : homr ne remplit que ces mesures
# à égalité : le nombre de têtes pleines de l'image. Désactivé par défaut (PUPITRE_TETES=1 pour l'essayer) : banc
# complet du 10/11, bwv153.1 ouverte nette A 98 → 100 mais bwv269 ouverte photo et sombre A 100 → 88 (homr pris à tort)
HEADS = os.environ.get("PUPITRE_TETES", "0") == "1"
# égalité de fautes : la lecture qui colle à l'image (PlaceJudge). Banc complet 96,3 → 96,4 % (photos, floues,
# penchées, petites portées +0,1 à +0,3) ; pas sur copie usée (bwv347 fermée usée −2,8 : omr.arbitrate ne donne pas
# les pages). PUPITRE_JUGE_IMAGE=0 : jamais.
JUDGE = os.environ.get("PUPITRE_JUGE_IMAGE", "1") == "1"
JUDGE_GAP = float(os.environ.get("PUPITRE_JUGE_ECART", "0"))
# le juge aussi en secours (lectures trop différentes) : homr pris si l'image lui donne nettement raison (deux têtes au
# moins) et qu'il n'a pas plus de fautes ; banc 96,4 → 96,5 % (bwv153.1 fermée dense +2,6, bwv267 fermée floue +2,6), 0 recul
JUDGE_RESCUE = os.environ.get("PUPITRE_JUGE_SECOURS", "1") == "1"
JUDGE_STRONG = float(os.environ.get("PUPITRE_JUGE_FORT", "0"))  # (essai) écart de têtes qui l'emporte sur les fautes  # (essai) écart de fautes jusqu'auquel le juge tranche
# voix séparées (deux portées) : mesures appariées par leur place sur l'image quand celle d'Audiveris y correspond une à
# une ; arbitrage complet même si les lectures diffèrent beaucoup (homr y lit une voix seule, pas des accords)
GEO = os.environ.get("PUPITRE_APPARIEMENT_IMAGE", "1") == "1"
PLACE_PAIRS = os.environ.get("PUPITRE_APPARIEMENT_PLACE", "0") == "1"  # toutes copies (essai)
RESCUE_PITCHES = os.environ.get("PUPITRE_SECOURS_HAUTEURS", "0") == "1"  # (essai) voir rescue
# signe vu par homr seul (Audiveris sans signe) repris à égalité ; (essai) =0 : seulement les signes inutiles d'Audiveris
# (les altérations d'Audiveris sont relues sur l'image par le reconnaisseur appris de signes.py depuis le 11/11)
HOMR_SIGN = os.environ.get("PUPITRE_SIGNE_HOMR_SEUL", "1") == "1"
TIE_MORE = os.environ.get("PUPITRE_EGALITE_PLUS", "0") == "1"  # égalité, homr a plus de notes → homr (essai)
# (essai) mesure d'Audiveris qui en couvre plusieurs sur l'image (barres manquées, photo floue) et que homr ne remplace
# pas : coupée aux barres de l'image d'après la place de ses notes, puis arbitrée mesure par mesure comme les autres.
# Désactivé (banc des copies fermées : seules bwv86.6 fermée petites portées 93 → 86 et floue 75 → 72 touchées : le
# rythme d'Audiveris y est brouillé, l'arbitrage aboutit en secours et empêche le repli sur homr)
CUT = os.environ.get("PUPITRE_COUPE_BARRES", "0") == "1"
COLUMN = 9.0  # dixièmes d'interligne : têtes d'une même colonne (même instant)
TIE_HOMR = os.environ.get("PUPITRE_EGALITE_HOMR", "0") == "1"  # voix séparées : égalité → homr (banc 96,0 → 95,9 ; Kyrie réel 95,5 → 97,3)


# photo floue : les altérations de homr (et du reconnaisseur relu sur ses lignes) y sont peu sûres (dièses inventés,
# bécarres lus comme dièses : bwv153.1 et bwv347 ouvertes floues) ; une mesure reprise de homr garde, pour chaque note
# qu'Audiveris lit au même instant sur le même degré, l'altération d'Audiveris (relue par signes.py).
# Désactivé (essai local sur 4 photos floues : 23 → 27 erreurs ; Audiveris y perd aussi des dièses que homr voit)
BLUR_SIGNS = os.environ.get("PUPITRE_PHOTO_FLOUE") == "1" and os.environ.get("PUPITRE_FLOU_ALTERATIONS", "0") == "1"


def keep_signs(x, y):
    """Lecture y (homr) dont les notes qu'Audiveris (x) lit au même instant et sur le même degré prennent son
    altération. Rend (lecture, nombre de notes changées)."""
    if not BLUR_SIGNS:
        return y, 0
    by = {}
    for e in x:
        by.setdefault((round(e[0], 3), e[3].step, e[3].octave), e)
    out, n = [], 0
    for e in y:
        a = by.get((round(e[0], 3), e[3].step, e[3].octave))
        if a is not None and _alter(a[3]) != _alter(e[3]):
            out.append((e[0], a[1], e[2], a[3]))
            n += 1
        else:
            out.append(e)
    return out, n


# troisième lecteur (oemer, MIT : lecture de la page entière, autre réseau que homr) : quand Audiveris et homr diffèrent
# sur une portée-mesure, la lecture dont oemer confirme le plus de notes (même suite de hauteurs) l'emporte si l'écart
# est net (OEMER_GAP notes) et qu'elle n'a pas plus de fautes de cohérence
OEMER_GAP = float(os.environ.get("PUPITRE_OEMER_ECART", "2"))
OEMER_NOTES = os.environ.get("PUPITRE_OEMER_NOTES", "1") == "1"  # vote note par note (deux contre un)


def _lcs(a, b):
    if not a or not b:
        return 0
    prev = [0] * (len(b) + 1)
    for u in a:
        cur = [0]
        for j, v in enumerate(b):
            cur.append(prev[j] + 1 if u == v else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def confirmed(z, x):
    """Notes de la lecture x que confirme la lecture z (suite des hauteurs, rythme mis à part), moins la moitié de celles
    qu'elle ne confirme pas."""
    sx, sz = [int(round(e[1])) for e in x], [int(round(e[1])) for e in z]
    common = _lcs(sz, sx)
    return common - 0.5 * (len(sx) - common)


def vote_notes(base, other, z):
    """
    Vote note par note, deux contre un : la lecture retenue (base) reçoit les notes que l'autre lecteur et oemer (z)
    voient tous deux au même instant et à la même hauteur (durée : celle sur laquelle ils s'accordent, sinon celle de
    l'autre lecteur), et perd celles qu'aucun des deux ne voit quand tous deux lisent à cet instant une même autre note
    qu'elle n'a pas. Les têtes en double (même instant, même hauteur, deux durées) n'en font qu'une.
    """
    def key_(e):
        return round(e[0], 3), int(round(e[1]))
    kb, ko, kz = {}, {}, {}
    durs_o = {}
    for d, ev in ((kb, base), (ko, other), (kz, z)):
        for e in ev:
            d.setdefault(key_(e), e)
    for e in other:
        durs_o.setdefault(key_(e), []).append(e)
    out = dict(kb)
    added = set()
    for k_, e in ko.items():
        if k_ in kz and k_ not in out:
            same = next((v for v in durs_o[k_] if abs(v[2] - kz[k_][2]) < 1e-6), e)
            out[k_] = same
            added.add(k_)
    for k_ in list(out):
        # retirée seulement si une note ajoutée au même instant la remplace (un ou deux demi-tons : degré ou altération
        # mal lus) ; sur une portée à deux voix, une note ajoutée à la basse ne dit rien du ténor
        if k_ in kb and k_ not in ko and k_ not in kz and any(a[0] == k_[0] and 0 < abs(a[1] - k_[1]) <= 2 for a in added):
            del out[k_]
    return sorted(out.values(), key=lambda e: (e[0], -e[1]))


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
        if _alter(a[3]) != _alter(b[3]) and (k in odd or (HOMR_SIGN and _shown(b[3]) and not _shown(a[3]) and k not in odd_h)):
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


def lines(ev, voices, length, dropped=None, medians=None):
    """
    Répartit les notes en voix (la plus aiguë d'abord) ; unisson (une seule tête pour deux voix libres) : dans les deux,
    sauf pendant un silence écrit (voir REST_UNISON) : la voix dont la note est la plus proche (sa note précédente dans
    la mesure, sinon sa hauteur habituelle, medians).
    dropped : liste où ranger les notes qu'aucune voix ne peut prendre (accord de trop, durée qui déborde).
    """
    out = [[] for _ in range(voices)]
    free = [0.0] * voices
    by_onset = {}
    for e in ev:
        by_onset.setdefault(e[0], []).append(e)
    rests = getattr(ev, "rests", ()) if REST_UNISON else ()
    for off in sorted(by_onset):
        group = sorted(by_onset[off], key=lambda e: -e[1])
        ready = [v for v in range(voices) if free[v] <= off + 1e-6]
        if not ready:
            ready = [min(range(voices), key=lambda v: free[v])]
        if voices == 2 and len(group) == 1 and len(ready) == 2:
            pairs = [(0, group[0]), (1, group[0])]
            if any(a - 1e-6 <= off < b - 1e-6 for a, b in rests):
                ref = [out[v][-1][1] if out[v] else (medians[v] if medians else None) for v in range(2)]
                if all(r is not None for r in ref) and ref[0] != ref[1]:
                    pairs = [(min(range(2), key=lambda v: abs(group[0][1] - ref[v])), group[0])]
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
    lx, ly = lines(x, voices, length, drop_x, medians), lines(y, voices, length, drop_y, medians)

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


def rebuild(m, ev, voices, length, split=None, medians=None):
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
        parts = [[(off, dur, [p]) for off, _ps, dur, p in line] for line in (split or lines(ev, voices, length, medians=medians))]
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


class PlaceJudge:
    """
    Juge d'après l'image (essai, PUPITRE_JUGE_IMAGE=1) : têtes de notes vues sur la page entre les barres de la mesure
    (têtes blanches remplies, deux têtes collées coupées en deux), avec leur place sur la portée ; chaque lecture est
    comparée colonne par colonne à ces têtes (places en trop ou en moins). À égalité de fautes, la lecture qui colle le
    mieux à l'image l'emporte (Audiveris fond deux croches en une noire, homr place une tête un degré à côté…).
    """
    BOTTOM = {"G": 31, "G8": 24, "F": 19}  # place 0 = ligne du bas : mi4, mi3, sol2 (diatonicNoteNum)

    def __init__(self, voix, pages, layout):
        self.ok = False
        try:
            import cv2
            import pupitres
            self.cv2 = cv2
            d = json.loads((pathlib.Path(voix) / "disposition.json").read_text(encoding="utf-8"))
            self.systems = d["systems"]
            self.pages = pathlib.Path(pages)
            self.clefs = [c for _n, c in pupitres.LAYOUTS[layout]]
            self.cache = {}
            self.ok = bool(self.systems) and all("barres" in s_ for s_ in self.systems) and self.pages.exists()
        except Exception:  # noqa: BLE001
            self.ok = False

    def _heads(self, page, sp):
        if page not in self.cache:
            import numpy as np
            cv2 = self.cv2
            img = cv2.imread(str(self.pages / page), cv2.IMREAD_GRAYSCALE)
            ink = (img < 128).astype(np.uint8)
            lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(1.6 * sp)), 1)))
            body = ink & (1 - lines)
            body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(0.4 * sp)))))
            n, lab, st, _c = cv2.connectedComponentsWithStats((1 - body).astype(np.uint8), 4)
            H, W = body.shape
            small = (st[:, cv2.CC_STAT_AREA] < 0.9 * sp * sp) & (st[:, 0] > 0) & (st[:, 1] > 0) & \
                    (st[:, 0] + st[:, 2] < W) & (st[:, 1] + st[:, 3] < H)
            small[0] = False
            body = np.where(small[lab], 1, body).astype(np.uint8)
            k = max(3, int(0.6 * sp)) | 1
            blobs = cv2.morphologyEx(body, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
            _n, _l, st, _c = cv2.connectedComponentsWithStats(blobs, 8)
            out = []
            for x, y, w, h, _a in st[1:]:
                if not (0.8 * sp <= w <= 2.0 * sp) or not (0.55 * sp <= h <= 2.7 * sp):
                    continue
                cx = x + w / 2
                if h <= 1.5 * sp:
                    out.append((cx, y + h / 2))
                else:
                    out += [(cx, y + h / 4), (cx, y + 3 * h / 4)]
            self.cache[page] = out
        return self.cache[page]

    def _columns(self, staff, j):
        k = j
        for s_ in self.systems:
            n = len(s_["barres"])
            if k < n:
                if not k or staff >= len(s_["staves"]):
                    return None  # 1re mesure de la ligne : la tête de ligne s'y mêle
                t, b = s_["staves"][staff][0], s_["staves"][staff][1]
                sp = (b - t) / 4
                x0, x1 = s_["barres"][k - 1], s_["barres"][k]
                pts = sorted((x, round((b - y) / (sp / 2))) for x, y in self._heads(s_["page"], sp)
                             if x0 + 0.3 * sp < x < x1 - 0.3 * sp and t - 1.7 * sp <= y <= b + 1.7 * sp)  # pas les paroles
                cols = []
                for x, pl in pts:
                    if cols and x - cols[-1][0] <= 1.0 * sp:
                        cols[-1][1].append(pl)
                    else:
                        cols.append([x, [pl]])
                return [sorted(c[1]) for c in cols]
            k -= n
        return None

    def cost(self, staff, j, ev):
        """Écart entre une lecture (événements de la portée) et les têtes vues ; None si on ne sait pas."""
        if not self.ok or staff >= len(self.clefs):
            return None
        cols = self._columns(staff, j)
        if cols is None:
            return None
        base = self.BOTTOM[self.clefs[staff]]
        by_onset = {}
        for o, _ps, _d, p in ev:
            by_onset.setdefault(o, []).append(p.diatonicNoteNum - base)
        want = [sorted(v) for _o, v in sorted(by_onset.items())]
        n, m = len(want), len(cols)
        D = [[0.0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            D[i][0] = D[i - 1][0] + len(want[i - 1])
        for c in range(1, m + 1):
            D[0][c] = D[0][c - 1] + len(cols[c - 1])
        for i in range(1, n + 1):
            for c in range(1, m + 1):
                a, b_ = want[i - 1], cols[c - 1]
                miss = sum(1 for pl in a if pl not in b_) + sum(1 for pl in b_ if pl not in a)
                D[i][c] = min(D[i - 1][c] + len(a), D[i][c - 1] + len(b_), D[i - 1][c - 1] + miss)
        return D[n][m]


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


def image_map(score, voix, cuts=None):
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
        if cuts is not None:
            # barres de l'image à l'intérieur de la mesure, en dixièmes depuis son début (comme la place des notes)
            base = left + (ends[mi - 1] if mi else 0.0)
            cuts.append([bars[q - starts[si]] / scale - base for q in covered[:-1]])
    flat = [q for c in out for q in c]
    if flat != sorted(set(flat)) or sum(len(c) == 1 for c in out) < 0.7 * len(out):
        return None  # image couverte deux fois, dans le désordre : découpages incompatibles
    return out


def cut_measure(m, cuts, voices):
    """
    Mesure d'Audiveris coupée aux barres de l'image (cuts : abscisses en dixièmes depuis le début de la mesure) : chaque
    note va à la mesure où tombe sa tête ; dans chaque morceau, débuts recalculés colonne par colonne (la plus courte
    des durées d'une colonne mène à la suivante : Audiveris, quand il manque une barre, embrouille ses voix). Rend
    [(notes, durée)] par morceau, ou None si une note n'a pas de place.
    """
    import bisect
    items = []
    for n in m.recurse().notesAndRests:
        if n.duration.isGrace or not n.quarterLength:
            continue
        x = getattr(n.style, "absoluteX", None)
        if x is None and n.isChord:  # accord : place de ses têtes
            xs = [getattr(c.style, "absoluteX", None) for c in n.notes]
            x = min(xs) if xs and None not in xs else None
        if x is None:
            return None
        items.append((float(x), n))
    pieces = [[] for _ in range(len(cuts) + 1)]
    for x, n in items:
        pieces[bisect.bisect(cuts, x)].append((x, n))
    out = []
    for piece in pieces:
        piece.sort(key=lambda t: t[0])
        cols = []
        for x, n in piece:
            if cols and x - cols[-1][0] <= COLUMN:
                cols[-1][1].append(n)
            else:
                cols.append([x, [n]])
        at, evs, lyr = 0.0, [], {}
        for _x, ns in cols:
            for n in ns:
                if n.isRest:
                    continue
                if n.lyrics and at not in lyr:
                    lyr[at] = [copy.deepcopy(l) for l in n.lyrics]
                for p in n.pitches:
                    evs.append((round(at, 4), p.ps, round(float(n.quarterLength), 4), p))
            at += min(float(n.quarterLength) for n in ns)
        out.append((sorted(evs, key=lambda e: (e[0], -e[1])), lyr))
    return out


def restructure(a, sh, voices, mapping, total, cuts=None):
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
        elif len(cov) > 1 and CUT and cuts is not None and i < len(cuts) and len(cuts[i]) == len(cov) - 1 and \
                all(cut_measure(st[i], cuts[i], voices) is not None for st in sa):
            plan.extend(("c", (i, k)) for k in range(len(cov)))
        else:
            plan.append(("a", i))
        taken.update(cov)
    for q in range(max(taken, default=-1) + 1, total):
        plan.append(("h", q))
    redone = sum(1 for kind, _ in plan if kind != "a")
    if not redone:
        return 0
    cut_cache = {}
    parts = list(a.parts)
    offset_parts = len(parts) - len(sh)
    for pi, part in enumerate(parts):
        ms = list(part.getElementsByClass(stream.Measure))
        out = []
        for kind, idx in plan:
            if kind == "a":
                out.append(ms[idx])
                continue
            if kind == "c":
                i, k = idx
                if (pi, i) not in cut_cache:
                    cut_cache[(pi, i)] = cut_measure(ms[i], cuts[i], voices)
                evs, lyr = cut_cache[(pi, i)][k]
                q = mapping[i][k]
                bar = float(sh[0][q].duration.quarterLength) or 4.0
                new = stream.Measure()
                for off, ls in lyr.items():  # paroles gardées : rebuild les reprend d'après leur début
                    holder = note.Note(quarterLength=0.25)
                    holder.lyrics = ls
                    new.insert(_q(off), holder)
                new.pupitre_coupee = True
                rebuild(new, evs, voices if pi >= offset_parts else 1, bar)
                out.append(new)
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


def arbitrate(a_path, h_path, out, layout, voix=None, third=None, split=False, oemer=None):
    a, h = drop_chord_symbols(converter.parse(a_path), converter.parse(h_path))
    before = sorted(set(_keys(a)))
    adopted = adopt_key(a, h, voix, layout)
    if adopted is not None:
        print(f"Armure lue par homr adoptée : {adopted:+d} (Audiveris : {before or 'aucune'})", file=sys.stderr)
    keyed = copy.deepcopy(a) if adopted is not None else None  # _arbitrate réunit des parties avant de renoncer
    try:
        _arbitrate(a, h, out, layout, third, voix, split, oemer)
    except SystemExit as e:
        if keyed is None:
            raise
        keyed.write("musicxml", fp=out, makeNotation=False)  # pas d'arbitrage mesure par mesure, mais l'armure est rétablie
        print(f"{e} ; lecture d'Audiveris gardée, avec l'armure de homr", file=sys.stderr)


def _arbitrate(a, h, out, layout, third=None, voix=None, split=False, oemer=None):
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
        cuts = []
        mapping = image_map(a, voix, cuts) if total and len(sh[0]) == total else None
        if mapping is not None:
            restructured = restructure(a, sh, voices, mapping, total, cuts)
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
    place_ok = mapping is not None and not restructured and len(mapping) == count and \
        all(len(c) == 1 for c in mapping) and len(sh[0]) == image_measures(voix)
    geo = split and GEO and place_ok
    if geo:
        if len(pairs) < count:
            print(f"Mesures appariées par leur place sur l'image : {count} (par les notes : {len(pairs)})", file=sys.stderr)
        pairs = [(i, c[0]) for i, c in enumerate(mapping)]
    elif PLACE_PAIRS and place_ok:
        # (essai) toutes copies : quand les mesures d'Audiveris tombent une à une sur celles de l'image, la place fait foi
        # (l'appariement par les notes se décale d'une mesure sur des motifs répétés : alto m. 11 contre m. 10)
        placed = [(i, c[0]) for i, c in enumerate(mapping)]
        if placed != pairs:
            print(f"Mesures appariées par leur place sur l'image plutôt que par leurs notes", file=sys.stderr)
            pairs = placed
    cut_here = sum(1 for m in sa_used[0] if getattr(m, "pupitre_coupee", False))
    if len(pairs) < 0.6 * count and CUT and cut_here and count == len(sh[0]) == image_measures(voix):
        # mesures d'Audiveris coupées aux barres de l'image : les deux lectures ont les mesures de l'image
        print(f"Mesures appariées par leur place sur l'image après la coupe : {count} (par les notes : {len(pairs)})",
              file=sys.stderr)
        pairs = [(i, i) for i in range(count)]
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
    if rescue and split and RESCUE_PITCHES:
        # (essai) voix séparées : homr lit chaque voix seule, ses rythmes diffèrent souvent d'Audiveris sans que ses
        # notes soient fausses ; mesures aux mêmes hauteurs (dans l'ordre, rythme mis à part) comptées comme semblables
        alike = sum(sorted(e[1] for e in events(st_a[i])) == sorted(e[1] for e in events(st_h[j]))
                    for st_a, st_h in zip(sa_used, sh) for i, j in pairs)
        if alike >= 0.4 * len(pairs) * len(sh):
            print(f"Lectures semblables par leurs hauteurs ({alike}/{len(pairs) * len(sh)}) : arbitrage complet",
                  file=sys.stderr)
            rescue = False
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
    pages_dir = os.environ.get("PUPITRE_PAGES")
    judge = PlaceJudge(voix, pages_dir, layout) if voix and JUDGE and pages_dir else None
    by_image = 0
    # troisième lecture (Audiveris sur l'autre version de l'image, deux portées) : même découpage que la première ?
    st_t = None
    if third and VOTE:
        try:
            tt = staves(drop_chord_symbols(converter.parse(third)))
            if len(tt) == len(sa) and all(len(x) == count for x in tt[len(tt) - len(sh):]):
                st_t = tt[len(tt) - len(sh):]
        except Exception:  # noqa: BLE001 : sans troisième lecture, l'arbitrage à deux
            st_t = None
    st_o, o_of, by_oemer = None, {}, 0
    if oemer:
        try:
            oo = staves(drop_chord_symbols(converter.parse(oemer)))
            if len(oo) >= len(sh):
                st_o = oo[len(oo) - len(sh):]
                # mesures d'oemer appariées à celles de homr d'après leurs notes, portée par portée (ses barres ne sont
                # pas les mêmes, ni toujours les mêmes d'une portée à l'autre d'un système)
                o_of = [{jh: io for io, jh in pair_measures([so_], [sh_])} for so_, sh_ in zip(st_o, sh)]
                print(f"Lecture d'oemer : {[len(d) for d in o_of]}/{len(sh[0])} mesures appariées", file=sys.stderr)
        except Exception as e:  # noqa: BLE001 : sans troisième lecteur, l'arbitrage à deux
            print(f"Lecture d'oemer illisible : {e}", file=sys.stderr)
    for k in sorted(set(range(count)) - {i for i, _j in pairs}):
        doubtful[str(k + 1)] = 0.5  # une barre vue par un seul lecteur : mesure à vérifier
    pair_set = set(pairs)
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
        if SPLIT_BAR and SPLIT_PREV and len(ends_a) == 1 and min(ends_a) < bar - 1e-6 and k > 0 and \
                (k - 1, j - 1) in pair_set and all(e for e in ea) and \
                all(events(st[k - 1]) and not getattr(st[k - 1], "pupitre_vide", False) for st in sa_used):
            # (toutes les portées d'Audiveris lues dans les deux mesures : une portée jetée, laissée vide, et une
            # durée lue sur l'autre seule faisaient écarter la mesure entière de homr, bwv267 fermée petites portées)
            # levée après une double barre : elle complète la mesure courte d'avant (3 temps + 1) ; homr, qui ramène
            # chaque mesure à sa durée pleine, y inventait des notes tenues (bwv267 fermée photocopie, m. 11)
            prv = {round(end_of(events(st[k - 1])), 3) for st in sa_used if events(st[k - 1])}
            if len(prv) == 1 and abs(min(ends_a) + min(prv) - bar) < 1e-6:
                length = min(ends_a)
                if os.environ.get("PUPITRE_DEBUG_LEVEE"):
                    print(f"levée : mesure {k + 1} (homr {j + 1}) durée {length}", file=sys.stderr)
        unsure = False
        for s, (m, x, y) in enumerate(zip(ma, ea, eh)):
            if signature(x) == signature(y):
                agreed += 1
                continue
            if rescue:
                z = events(st_o[s][o_of[s][j]]) if st_o is not None and j in o_of[s] else None
                if (getattr(m, "pupitre_vide", False) or not x) and y and faults(y, [], length, voices) == 0:
                    rebuild(m, y, voices, length, medians=medians[s])
                    changed += 1
                    unsure = True
                elif z and x and y and confirmed(z, y) - confirmed(z, x) >= OEMER_GAP + 1 and \
                        faults(y, x, length, voices) <= faults(x, y, length, voices):
                    # secours : homr pris quand oemer lui donne nettement raison
                    rebuild(m, y, voices, length, medians=medians[s])
                    changed += 1
                    by_oemer += 1
                    unsure = True
                elif CUT and getattr(m, "pupitre_coupee", False) and y and \
                        faults(y, x, length, voices) < faults(x, y, length, voices):
                    # mesure coupée aux barres de l'image : le rythme d'Audiveris y est souvent brouillé
                    rebuild(m, y, voices, length, medians=medians[s])
                    changed += 1
                    unsure = True
                elif JUDGE_RESCUE and judge is not None and x and y and not only_accidentals(x, y) and \
                        (mapping[k] == [j] if (mapping is not None and not restructured and k < len(mapping))
                         else (k == j and count == len(sh[0]))):
                    # (essai) secours : homr pris aussi quand l'image lui donne nettement raison (deux têtes au moins)
                    # et qu'il n'a pas plus de fautes
                    ca, ch = judge.cost(s, j, x), judge.cost(s, j, y)
                    if ca is not None and ch is not None and ch + 2 <= ca and \
                            faults(y, x, length, voices) <= faults(x, y, length, voices):
                        rebuild(m, keep_signs(x, y)[0], voices, length, medians=medians[s])
                        changed += 1
                        by_image += 1
                        unsure = True
                continue
            if st_t is not None and signature(events(st_t[s][k])) == signature(y):
                # vote : homr et l'autre lecture d'Audiveris s'accordent contre la première (deux sur trois)
                rebuild(m, y, voices, length, medians=medians[s])
                changed += 1
                by_vote += 1
                continue
            fa, fh = faults(x, y, length, voices), faults(y, x, length, voices)
            if os.environ.get("PUPITRE_DEBUG_MESURE") == str(k + 1):
                print(f"mesure {k + 1} portée {s} : fautes Audiveris {fa}, homr {fh}\n  A {signature(x)}\n  H {signature(y)}",
                      file=sys.stderr)
            # à égalité, Audiveris (meilleur lecteur des pages nettes : bécarres, rythmes cohérents mais différents),
            # sauf si homr sonne nettement plus juste avec les autres portées et dans la tonalité
            take_h = fh < fa
            if TIE_MORE and fa == fh and x and y and len(y) > len(x) and not only_accidentals(x, y) \
                    and sorted(round(e[1]) for e in x) != sorted(round(e[1]) for e in y):
                # égalité, homr a plus de notes : Audiveris en a perdu une (deux croches lues en une noire, do4 sur
                # ligne supplémentaire oublié : bwv153.1 ouverte nette)
                take_h = True
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
            same_place = (mapping[k] == [j] if (mapping is not None and not restructured and k < len(mapping))
                          else (k == j and count == len(sh[0])))
            near_tie = fa == fh or (JUDGE_GAP and abs(fa - fh) <= JUDGE_GAP) or JUDGE_STRONG > 0
            if judge is not None and same_place and near_tie and x and y and signature(x) != signature(y) \
                    and not only_accidentals(x, y):
                # (seulement si les deux mesures tombent sur la même mesure de l'image : une paire décalée d'une mesure
                # aurait l'image de l'une pour juge — bwv269 ouverte photo, alto m. 11 contre m. 10 de homr)
                ca, ch = judge.cost(s, j, x), judge.cost(s, j, y)
                need = 1 if fa == fh else (2 if JUDGE_GAP and abs(fa - fh) <= JUDGE_GAP else JUDGE_STRONG or 99)
                if ca is not None and ch is not None and abs(ca - ch) >= need:
                    if (ch < ca) != take_h:
                        by_image += 1
                    take_h = ch < ca
            if HEADS and fa == fh and counter is not None and not only_accidentals(x, y):
                seen = counter.count(s, j)
                if seen is not None and abs(filled(y) - seen) < abs(filled(x) - seen):
                    take_h = True  # homr a autant de têtes pleines que l'image, Audiveris non
                    by_heads += 1
            if REDONDANT and fa == fh and only_accidentals(x, y) and not BLUR_SIGNS:
                mixed_acc, taken = mix_accidentals(x, y, _key_at(m))
                if taken:
                    rebuild(m, mixed_acc, voices, length, medians=medians[s])
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
                    if BLUR_SIGNS:
                        split = [keep_signs(x, line)[0] for line in split]
                        comp = keep_signs(x, comp)[0]
                    rebuild(m, comp, voices, length, split)
                    changed += 1
                    mixed += 1
                    unsure = True
                    continue
            if st_o is not None and x and y and j in o_of[s] and OEMER_NOTES:
                z = events(st_o[s][o_of[s][j]])
                base, other = (y, x) if take_h else (x, y)
                voted = vote_notes(base, other, z) if z else base
                if signature(voted) != signature(base) and \
                        faults(voted, other, length, voices) <= faults(base, other, length, voices):
                    rebuild(m, voted, voices, length, medians=medians[s])
                    changed += 1
                    by_oemer += 1
                    unsure = True
                    continue
            if take_h:
                rebuild(m, keep_signs(x, y)[0], voices, length, medians=medians[s])
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
    print(f"Double lecture : {agreed} portées-mesures identiques, {changed} reprises de homr (dont {mixed} voix par voix, {by_ear} à l'oreille, {by_usage} altérations vues par homr seul, {by_vote} par vote à trois lectures, {by_heads} par les têtes de l'image, {by_range} par la tessiture, {by_image} par le juge d'après l'image, {by_oemer} par oemer), "
          f"{len(doubtful)}/{count} mesures à vérifier", file=sys.stderr)


def homr_vote(h_path, a_path, o_path, out):
    """
    Copie très usée (lecture de homr prise telle quelle) : chaque portée-mesure de homr reçoit les notes qu'Audiveris
    et oemer voient tous deux, et perd celles qu'aucun ne voit quand tous deux s'accordent sur une autre (vote_notes),
    si elle n'en devient pas moins cohérente. Écrit out ; rend le nombre de portées-mesures corrigées.
    """
    h, a, o = drop_chord_symbols(converter.parse(h_path), converter.parse(a_path), converter.parse(o_path))
    sh, sa, so = staves(h), staves(a), staves(o)
    sa, so = sa[len(sa) - len(sh):], so[len(so) - len(sh):]
    if len(sa) != len(sh) or len(so) != len(sh) or len({len(x) for x in sa}) != 1:
        raise SystemExit("Portées différentes : pas de vote")
    pa = {jh: ia for ia, jh in pair_measures(sa, sh)}
    pos = [{jh: io for io, jh in pair_measures([so_], [sh_])} for so_, sh_ in zip(so, sh)]
    po = pos[0]
    voices, changed = 2, 0
    for j in range(len(sh[0])):
        if j not in pa:
            continue
        for s in range(len(sh)):
            if j not in pos[s]:
                continue
            m = sh[s][j]
            y, x, z = events(m), events(sa[s][pa[j]]), events(so[s][pos[s][j]])
            if not (x and y and z):
                continue
            length = float(m.duration.quarterLength) or 4.0
            voted = vote_notes(y, x, z)
            if signature(voted) != signature(y) and faults(voted, x, length, voices) <= faults(y, x, length, voices):
                rebuild(m, voted, voices, length)
                changed += 1
    try:
        h.write("musicxml", fp=out)
    except Exception:  # noqa: BLE001
        h.write("musicxml", fp=out, makeNotation=False)
    print(f"Copie très usée : {changed} portées-mesures corrigées où Audiveris et oemer s'accordent "
          f"({len(pa)} et {len(po)} mesures appariées sur {len(sh[0])})", file=sys.stderr)
    return changed


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "--homr-base":  # copie très usée : homr corrigé par Audiveris et oemer d'accord
        homr_vote(*args[1:5])
        sys.exit(0)
    third = None
    if "--troisieme" in args:  # troisième lecture (Audiveris, autre version de l'image) : vote à trois
        k = args.index("--troisieme")
        third = args[k + 1]
        del args[k:k + 2]
    oemer = None
    if "--oemer" in args:  # lecture d'oemer convertie (deux portées) : troisième avis
        k = args.index("--oemer")
        oemer = args[k + 1]
        del args[k:k + 2]
    split = "--voix-separees" in args  # lecture de homr sur les pages des voix séparées (voix_separees.py)
    args = [x for x in args if x != "--voix-separees"]
    if len(args) not in (4, 5):  # 5e : dossier des lignes découpées (sens de l'armure lu sur l'image)
        sys.exit(__doc__)
    arbitrate(*args, third=third, split=split, oemer=oemer)
