"""
Contrôles musicaux de la partition lue, comme les ferait un chef de chœur à la première lecture.

Portée décalée : sur une photo peu nette, la lecture optique peut placer toutes les notes d'une portée un ou deux degrés
trop haut ou trop bas pendant un système (lignes mal repérées). Chaque voix reste mélodieuse, mais l'harmonie avec les
autres portées devient fausse : secondes et septièmes partout au lieu de tierces, quintes, sixtes. On cherche, pour chaque
portée, le décalage qui rend ses accords avec les autres portées consonants ; une portée n'est recalée que si le gain est
net sur au moins deux mesures et que l'orthographe le confirme (un ré dièse lu un degré trop haut devient un « mi dièse »,
qu'aucun compositeur n'écrit dans ces tonalités). Entre deux portées seulement (S+A / T+B), on ne sait pas laquelle a
glissé : l'orthographe départage, sinon la tessiture ; à défaut, on ne touche à rien.
"""


from music21 import key, stream

# un degré seulement : décalée d'une tierce (deux degrés), une voix reste consonante (tierces parallèles), et l'harmonie
# ne permet plus de savoir si elle a glissé (essayé sur le banc : des dizaines de fausses alertes sur des lectures justes)
SHIFTS = (-1, 1)
# consonance de deux sons (demi-tons modulo 12) : unisson, tierces, quinte, sixtes ; quarte à moitié (consonante entre
# voix hautes) ; triton peu ; secondes et septièmes dissonantes
CONSONANCE = {0: 1.0, 3: 1.0, 4: 1.0, 7: 1.0, 8: 1.0, 9: 1.0, 5: 0.5, 6: 0.2, 1: 0.0, 2: 0.0, 10: 0.0, 11: 0.0}
MIN_GAIN = 0.25      # consonance gagnée (de 0 à 1) sur la portion recalée
MIN_AFTER = 0.7      # consonance après recalage
MIN_MEASURES = 2
# Orthographes invraisemblables corrigées par le recalage : sans elles, une harmonie fausse vient le plus souvent de
# mesures décalées entre les voix (mesure perdue sur une portée), qu'un recalage de hauteur ne répare pas.
MIN_ODD = 2
SWITCH = 1.5         # coût d'un changement de décalage dans le chemin optimal (en « durée consonante »)
STEPS = "CDEFGAB"


def _key_alters(m):
    ks = m.getContextByClass(key.KeySignature)
    sharps = ks.sharps if ks is not None else 0
    k = key.KeySignature(sharps)
    return sharps, {s: (k.accidentalByStep(s).alter if k.accidentalByStep(s) else 0) for s in STEPS}


def _notes(m):
    """(début, fin, [(degré absolu, altération, altération écrite ?)]) des notes de la mesure, toutes voix confondues."""
    out = []
    for n in m.recurse().notes:
        start = float(n.getOffsetInHierarchy(m))
        end = start + float(n.quarterLength)
        if end <= start:
            continue
        ps = []
        for p in n.pitches:
            printed = p.accidental is not None and bool(p.accidental.displayStatus)
            ps.append((STEPS.index(p.step) + 7 * p.octave, p.accidental.alter if p.accidental is not None else 0, printed))
        out.append((start, end, ps))
    return out


_SEMI = [0, 2, 4, 5, 7, 9, 11]


def _midi(degree, alter):
    return 12 * (degree // 7) + _SEMI[degree % 7] + alter


def _shift(notes, s, alters):
    """Notes décalées de s degrés : altération écrite gardée (elle est collée à la tête), sinon celle de l'armure."""
    out = []
    for a, b, ps in notes:
        out.append((a, b, [(d + s, al if pr else alters[STEPS[(d + s) % 7]], pr) for d, al, pr in ps]))
    return out


def _consonance(mine, others):
    """Durée consonante et durée totale des recouvrements entre mes notes et celles des autres portées."""
    good = total = 0.0
    for a, b, ps in mine:
        for c, d, qs in others:
            w = min(b, d) - max(a, c)
            if w <= 1e-6:
                continue
            for x in ps:
                for y in qs:
                    good += w * CONSONANCE[abs(_midi(x[0], x[1]) - _midi(y[0], y[1])) % 12]
                    total += w
    return good, total


def _odd(notes, sharps):
    """Orthographes invraisemblables dans cette armure : mi dièse, si dièse, fa bémol, do bémol, doubles altérations."""
    n = 0
    for _a, _b, ps in notes:
        for d, al, _pr in ps:
            step = STEPS[d % 7]
            if abs(al) >= 2:
                n += 1
            elif al == 1 and step in "EB" and sharps < 5:
                n += 1
            elif al == -1 and step in "FC" and sharps > -5:
                n += 1
            elif al == 1 and sharps < -2 or al == -1 and sharps > 2:
                n += 1  # dièse dans une armure très bémolisée, ou l'inverse
    return n


# tessiture de chaque portée selon sa position : voix hautes (sol) ou basses (fa)
CENTER_HIGH, CENTER_LOW = 67, 54


def analyse(parts):
    """
    Pour chaque portée et chaque mesure : consonance avec les autres portées sans décalage et avec chaque décalage.
    Rend (mesures, table) ; table[i][k] = {décalage: (bon, total)}.
    """
    rows = [list(p.getElementsByClass(stream.Measure)) for p in parts]
    count = min((len(r) for r in rows), default=0)
    notes = [[_notes(r[k]) for k in range(count)] for r in rows]
    table = []
    for i, r in enumerate(rows):
        line = []
        for k in range(count):
            sharps, alters = _key_alters(r[k])
            others = [ev for j in range(len(rows)) if j != i for ev in notes[j][k]]
            cell = {0: _consonance(notes[i][k], others)}
            for s in SHIFTS:
                cell[s] = _consonance(_shift(notes[i][k], s, alters), others)
            line.append(cell)
        table.append(line)
    return rows, notes, table


def _path(line):
    """Décalage de chaque mesure : chemin qui maximise la durée consonante, chaque changement coûtant SWITCH."""
    states = (0,) + SHIFTS
    best = {s: (line[0][s][0] if line else 0.0, [s]) for s in states}
    for cell in line[1:]:
        nxt = {}
        for s in states:
            prev = max(states, key=lambda t: best[t][0] - (SWITCH if t != s else 0))
            score = best[prev][0] - (SWITCH if prev != s else 0) + cell[s][0]
            nxt[s] = (score, best[prev][1] + [s])
        best = nxt
    return max(best.values(), key=lambda x: x[0])[1] if line else []


def candidates(parts):
    """Portions de portée (i, début, fin, décalage, gain, consonance après, orthographe gagnée, tessiture gagnée)."""
    rows, notes, table = analyse(parts)
    out = []
    for i, line in enumerate(table):
        path = _path(line)
        k = 0
        while k < len(path):
            s = path[k]
            j = k
            while j + 1 < len(path) and path[j + 1] == s:
                j += 1
            if s:
                g0 = sum(line[x][0][0] for x in range(k, j + 1))
                gs = sum(line[x][s][0] for x in range(k, j + 1))
                tot = sum(line[x][0][1] for x in range(k, j + 1))
                if tot > 0:
                    sharps = _key_alters(rows[i][k])[0]
                    seg = [ev for x in range(k, j + 1) for ev in notes[i][x]]
                    moved = [ev for x in range(k, j + 1) for ev in _shift(notes[i][x], s, _key_alters(rows[i][x])[1])]
                    odd = _odd(seg, sharps) - _odd(moved, sharps)
                    out.append(dict(part=i, start=k, end=j, shift=s, gain=(gs - g0) / tot, after=gs / tot,
                                    before=g0 / tot, odd=odd, measures=j - k + 1))
            k = j + 1
    return out


def _convincing(c):
    return (c["measures"] >= MIN_MEASURES and c["gain"] >= MIN_GAIN and c["after"] >= MIN_AFTER
            and (c["odd"] >= MIN_ODD or (c["odd"] >= 1 and c["gain"] >= 0.35)))


def fix_staff_shifts(parts):
    """
    Recale les portions de portée lues un degré trop haut ou trop bas (voir en tête). Modifie les portées en place ;
    rend la liste des recalages faits : (portée, première mesure, dernière mesure, décalage), mesures comptées depuis 0.
    """
    import merge  # décalage d'une mesure avec ses altérations (partagé avec la clé de fa rétablie)
    done = []
    for _round in range(8):
        found = [c for c in candidates(parts) if _convincing(c)]
        if not found:
            break
        best = max(found, key=lambda c: (c["odd"], c["gain"] * c["measures"]))
        measures = list(parts[best["part"]].getElementsByClass(stream.Measure))
        for m in measures[best["start"]:best["end"] + 1]:
            merge.shift_measure(m, best["shift"])
        done.append((best["part"], best["start"], best["end"], best["shift"]))
    return done
