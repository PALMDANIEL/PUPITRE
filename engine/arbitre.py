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

from music21 import converter, key, note, chord, stream
from music21.common.numberTools import opFrac

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


def adopt_key(a, h):
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


def arbitrate(a_path, h_path, out, layout):
    a, h = converter.parse(a_path), converter.parse(h_path)
    before = sorted(set(_keys(a)))
    adopted = adopt_key(a, h)
    if adopted is not None:
        print(f"Armure lue par homr adoptée : {adopted:+d} (Audiveris : {before or 'aucune'})", file=sys.stderr)
    keyed = copy.deepcopy(a) if adopted is not None else None  # _arbitrate réunit des parties avant de renoncer
    try:
        _arbitrate(a, h, out, layout)
    except SystemExit as e:
        if keyed is None:
            raise
        keyed.write("musicxml", fp=out, makeNotation=False)  # pas d'arbitrage mesure par mesure, mais l'armure est rétablie
        print(f"{e} ; lecture d'Audiveris gardée, avec l'armure de homr", file=sys.stderr)


def _arbitrate(a, h, out, layout):
    sh = staves(h)
    voices = 2 if layout == "grand" else 1
    # mêmes portées des deux côtés ; seule exception : la portée d'instrument au-dessus du chœur (disposition « grand »),
    # que homr ne lit pas.
    if sh and len(a.parts) > len(sh) + (layout == "grand"):
        collapse(a, len(sh) + (layout == "grand"))
    sa = staves(a)
    if not sh or not (len(sa) == len(sh) or (layout == "grand" and len(sa) == len(sh) + 1)):
        raise SystemExit(f"Portées différentes ({len(sa)} contre {len(sh)}) : pas d'arbitrage")
    sa_used = sa[len(sa) - len(sh):]  # disposition « grand » : la portée d'instrument au-dessus n'est pas lue par homr
    count = len(sa_used[0])
    if any(len(x) != count for x in sa_used) or any(len(x) != len(sh[0]) for x in sh):
        raise SystemExit("Nombres de mesures différents d'une portée à l'autre : pas d'arbitrage")
    pairs = pair_measures(sa_used, sh)
    if len(pairs) < 0.6 * count:
        raise SystemExit(f"Mesures impossibles à apparier ({len(pairs)}/{count}) : pas d'arbitrage")
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
    if same < 0.4 * len(pairs) * len(sh):
        # lectures trop différentes pour être comparées mesure à mesure (mesures décalées, portées mal appariées)
        raise SystemExit(f"Lectures trop différentes ({same}/{len(pairs) * len(sh)} portées-mesures identiques) : pas d'arbitrage")
    doubtful, changed, agreed, mixed = {}, 0, 0, 0
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
        unsure = False
        for s, (m, x, y) in enumerate(zip(ma, ea, eh)):
            if signature(x) == signature(y):
                agreed += 1
                continue
            fa, fh = faults(x, y, length, voices), faults(y, x, length, voices)
            # à égalité, Audiveris : meilleur lecteur des pages nettes (bécarres, rythmes cohérents mais différents)
            take_h = fh < fa
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
        if unsure:
            doubtful[str(k + 1)] = 0.5
    a.write("musicxml", fp=out)
    mean = 1 - 0.5 * len(doubtful) / max(1, count)
    pathlib.Path(out).with_name("fiabilite.json").write_text(json.dumps(
        {"passes": 2, "lecteurs": ["Audiveris", "homr"], "moyenne": round(mean, 3), "mesures": count,
         "arbitrees": changed, "a_verifier": doubtful}, ensure_ascii=False), encoding="utf-8")
    print(f"Double lecture : {agreed} portées-mesures identiques, {changed} reprises de homr (dont {mixed} voix par voix), "
          f"{len(doubtful)}/{count} mesures à vérifier", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    arbitrate(*sys.argv[1:])
