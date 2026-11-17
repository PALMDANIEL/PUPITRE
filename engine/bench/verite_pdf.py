"""
Bonne réponse calculée depuis un PDF gravé (MuseScore 3 et 4 : symboles de la police SMuFL, Leland, Bravura, MScore),
sans lire l'image : chaque tête de note y est un caractère placé exactement. Hauteur : place de la tête sur sa portée
(lignes de portée = traits horizontaux du PDF), clé, armure, altérations reportées dans la mesure ; voix : la portée
(4 portées : S, A, T, B ; 2 portées : S/A et T/B, séparées par le sens des queues ; 1 portée : couplet du soliste,
versé dans la voix haute comme le fait render.py) ; une note liée compte une fois (comme run_bench).

  <python du moteur> verite_pdf.py <source.pdf> [truth.json] [--detail]
      écrit truth.json (voix → hauteurs MIDI) ; --detail : notes de chaque voix, système par système
"""
import ctypes, json, pathlib, statistics, sys

import pypdfium2 as pdfium
import pypdfium2.raw as raw

HEADS = {0xE0A0, 0xE0A2, 0xE0A3, 0xE0A4}
CLEFS = {0xE050: ("G", 0), 0xE052: ("G", -1), 0xE053: ("G", 1), 0xE062: ("F", 0), 0xE05C: ("C", 0),
         0xE07A: ("G", 0), 0xE07C: ("F", 0), 0xE07B: ("C", 0)}  # (+ clés de changement, plus petites)
ACC = {0xE260: -1, 0xE261: 0, 0xE262: 1, 0xE263: 2, 0xE264: -2}
BOTTOM = {"G": 2 + 7 * 4, "F": 4 + 7 * 2, "C": 3 + 7 * 3}  # ligne du bas : mi4, sol2 ; ut 3e ligne : fa3
STEP_PC = [0, 2, 4, 5, 7, 9, 11]
SHARPS, FLATS = "FCGDAEB", "BEADGCF"
NAMES = ["Soprano", "Alto", "Ténor", "Basse"]


def glyphs(page):
    """Caractères des polices musicales : (code, x, y du point d'origine, gauche, droite, taille)."""
    tp = page.get_textpage()
    out = []
    x, y = ctypes.c_double(), ctypes.c_double()
    for i in range(tp.count_chars()):
        ch = raw.FPDFText_GetUnicode(tp, i)
        if not 0xE000 <= ch <= 0xF8FF:
            continue
        raw.FPDFText_GetCharOrigin(tp, i, ctypes.byref(x), ctypes.byref(y))
        l, b, r, t = tp.get_charbox(i)
        out.append(dict(code=ch, x=x.value, y=y.value, left=l, right=r, size=t - b))
    return out


def lines_and_bars(page):
    """Traits horizontaux (lignes de portée) et verticaux (barres, queues) : [(gauche, bas, droite, haut)]."""
    hor, ver, shapes, blocks = [], [], [], []
    for o in page.get_objects():
        if o.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        l, b, r, t = o.get_bounds()
        w, h = r - l, t - b
        if h < 1.2 and w > 30:
            hor.append((l, b, r, t))
        elif w < 2.5 and h > 5:
            ver.append((l, b, r, t))
        elif w > 3 and h < 12:
            shapes.append((l, b, r, t))  # liaisons, ligatures, crochets
        if w > 30 and 8 < h < 60:
            blocks.append((l, b, r, t))  # portée tracée d'un seul chemin (MuseScore : les 5 lignes, mesure par mesure)
    if len(hor) < 5 and blocks:
        # lignes de portée en un seul tracé : bandes de même haut et même bas réunies ; hauteur la plus courante
        common = statistics.mode(round(t - b) for _l, b, _r, t in blocks)
        bands = {}
        for l, b, r, t in blocks:
            if abs((t - b) - common) <= 1:
                key = (round(b * 2) / 2, round(t * 2) / 2)
                bands.setdefault(key, []).append((l, r))
        hor = []
        for (b, t), xs in bands.items():
            l, r = min(x[0] for x in xs), max(x[1] for x in xs)
            for k in range(5):
                y = b + k * (t - b) / 4
                hor.append((l, y, r, y))
    return hor, ver, shapes


def staves_of(hor):
    """Portées : 5 lignes équidistantes de même étendue → [(y bas, y haut, interligne, x gauche, x droite)]."""
    rows = sorted(hor, key=lambda s: ((s[1] + s[3]) / 2, s[0]))
    used, staves = set(), []
    centres = [((s[1] + s[3]) / 2, s) for s in rows]
    for i, (y0, s0) in enumerate(centres):
        if i in used:
            continue
        group = [i]
        for j in range(i + 1, len(centres)):
            if j in used:
                continue
            yj, sj = centres[j]
            if abs(sj[0] - s0[0]) < 8 and abs(sj[2] - s0[2]) < 8:
                if len(group) == 1 or abs((yj - centres[group[-1]][0]) - (centres[group[1]][0] - y0)) < 0.6:
                    if yj - centres[group[-1]][0] > 2:
                        group.append(j)
                if len(group) == 5:
                    break
        if len(group) == 5:
            ys = [centres[k][0] for k in group]
            gaps = [b - a for a, b in zip(ys, ys[1:])]
            if max(gaps) - min(gaps) < 0.6:
                used.update(group)
                staves.append((ys[0], ys[-1], statistics.mean(gaps), s0[0], s0[2]))
    # portée tracée mesure par mesure : morceaux à la même hauteur, bout à bout, réunis
    staves.sort(key=lambda s: (round(s[0]), s[3]))
    merged = []
    for s_ in staves:
        m = next((k for k, o in enumerate(merged) if abs(o[0] - s_[0]) < 0.6 and abs(o[1] - s_[1]) < 0.6
                  and s_[3] <= o[4] + 3 and s_[4] >= o[3] - 3), None)
        if m is None:
            merged.append(list(s_))
        else:
            merged[m][3], merged[m][4] = min(merged[m][3], s_[3]), max(merged[m][4], s_[4])
    return sorted((tuple(m) for m in merged), key=lambda s: -s[1])  # de haut en bas (PDF : y vers le haut)


def systems_of(staves, ver):
    """Portées liées par une barre de mesure qui les traverse toutes : systèmes, de haut en bas."""
    groups = [[s] for s in staves]
    merged = True
    while merged:
        merged = False
        for a in range(len(groups) - 1):
            lo, hi = groups[a][-1], groups[a + 1][0]  # bas du système a, haut du suivant (y vers le haut)
            if any(v[1] <= hi[1] + 0.5 and v[3] >= lo[0] - 0.5 for v in ver):
                groups[a] += groups.pop(a + 1)
                merged = True
                break
    return groups


def pitch(clef, octave_shift, place, alter):
    d = BOTTOM[clef] + 7 * octave_shift + place
    step, octave = d % 7, d // 7
    return 12 * (octave + 1) + STEP_PC[step] + alter


LABELS = [("soprano", ["Soprano"]), ("alto", ["Alto"]), ("tenor", ["Ténor"]), ("ténor", ["Ténor"]), ("basse", ["Basse"]),
          ("bass", ["Basse"]), ("sop", ["Soprano"]), ("ten", ["Ténor"]), ("bar", ["Basse"])]


def words(page):
    """Texte ordinaire de la page : [(texte, gauche, droite, y)] (mots d'une même ligne, lettres voisines)."""
    tp = page.get_textpage()
    chars = []
    for i in range(tp.count_chars()):
        ch = raw.FPDFText_GetUnicode(tp, i)
        if 32 < ch < 0x2000:
            l, b, r, t = tp.get_charbox(i)
            chars.append((chr(ch), l, r, (b + t) / 2))
    out = []
    for c in sorted(chars, key=lambda c: (round(c[3] / 3), c[1])):
        if out and abs(out[-1][3] - c[3]) < 3 and 0 <= c[1] - out[-1][2] < 4:
            w = out[-1]
            out[-1] = (w[0] + c[0], w[1], c[2], w[3])
        else:
            out.append(c)
    return out


def names_of(label):
    """« S. », « Soprano », « S.A. », « Ténor Basse » → voix."""
    t = label.lower().replace(".", " ").replace("&", " ").replace("/", " ").split()
    out = []
    for w in t:
        hit = next((n for k, n in LABELS if w.startswith(k)), None)
        if hit is None and len(w) == 1:
            hit = {"s": ["Soprano"], "a": ["Alto"], "t": ["Ténor"], "b": ["Basse"]}.get(w)
        if hit and hit[0] not in out:
            out += hit
    return out


def read_page(page):
    gl = glyphs(page)
    texts = words(page)
    hor, ver, shapes = lines_and_bars(page)
    staves = staves_of(hor)
    if not staves:
        return []
    size = statistics.median([g["size"] for g in gl if g["code"] in HEADS] or [0])
    systems = systems_of(staves, ver)
    out = []
    for system in systems:
        content = []
        for st in system:
            y0, y1, sp, xl, xr = st
            mine = [g for g in gl if y0 - 4 * sp <= g["y"] <= y1 + 4 * sp and xl - 2 * sp <= g["x"] <= xr + sp
                    and min(staves, key=lambda s: abs((s[0] + s[1]) / 2 - g["y"])) is st]
            mine.sort(key=lambda g: g["x"])
            bars = sorted(v[0] for v in ver if abs(v[1] - y0) < 0.3 * sp + 1 and abs(v[3] - y1) < 0.3 * sp + 1
                          or (v[1] <= y0 + 0.3 * sp and v[3] >= y1 - 0.3 * sp and v[3] - v[1] > 5 * sp))
            heads = [g for g in mine if g["code"] in HEADS and g["size"] >= 0.8 * size]
            first_head = heads[0]["x"] if heads else xr
            clefs = [(g["x"], CLEFS[g["code"]]) for g in mine if g["code"] in CLEFS]
            accs = [g for g in mine if g["code"] in ACC]
            # armure : altérations avant la 1re tête, loin de toute tête (pas un signe de note)
            key = {}
            for a in accs:
                if a["x"] < first_head - 0.5 * sp and not any(0 < h["x"] - a["x"] < 2.2 * sp and abs(h["y"] - a["y"]) < 0.3 * sp for h in heads):
                    st_ = round((a["y"] - y0) / (sp / 2))
                    cl = max((c for c in clefs if c[0] < a["x"]), default=(0, ("G", 0)))[1]
                    d = BOTTOM[cl[0]] + 7 * cl[1] + st_
                    key["CDEFGAB"[d % 7]] = ACC[a["code"]]
            notes = []
            measure_acc = {}
            last_bar = -1e9
            for h in heads:
                passed = [b for b in bars if last_bar < b < h["x"]]
                if passed:
                    measure_acc, last_bar = {}, passed[-1]
                cl = max((c for c in clefs if c[0] < h["x"]), default=(0, ("G", 0)))[1]
                place = round((h["y"] - y0) / (sp / 2))
                d = BOTTOM[cl[0]] + 7 * cl[1] + place
                step = "CDEFGAB"[d % 7]
                sign = next((a for a in accs if 0 < h["left"] - a["right"] < 1.6 * sp and abs(a["y"] - h["y"]) < 0.3 * sp), None)
                if sign is not None:
                    alter = ACC[sign["code"]]
                    measure_acc[d] = alter
                else:
                    alter = measure_acc.get(d, key.get(step, 0))
                # sens de la queue : trait vertical au bord droit montant (voix du haut), au bord gauche descendant
                # (la queue part de cette tête : une queue montante voisine passe aussi à côté de la tête de l'autre voix)
                up = any(abs(v[0] - h["right"]) < 0.3 * sp and abs(v[1] - h["y"]) < 0.6 * sp and v[3] > h["y"] + sp for v in ver)
                down = any(abs(v[0] - h["left"]) < 0.3 * sp and abs(v[3] - h["y"]) < 0.6 * sp and v[1] < h["y"] - sp for v in ver)
                notes.append(dict(x=h["x"], y=h["y"], right=h["right"], left=h["left"], midi=pitch(cl[0], cl[1], place, alter),
                                  up=up, down=down))
            # liaisons de prolongation : forme mince entre deux têtes de même hauteur qui se suivent sur la portée
            for n in notes:
                n["held"] = False
            for k, n in enumerate(notes):
                for m in notes[k + 1:]:
                    if abs(m["y"] - n["y"]) < 0.2 * sp and m["midi"] == n["midi"]:
                        if any(n["left"] - 0.3 * sp < s[0] < n["right"] + 0.8 * sp
                               and m["left"] - 0.8 * sp < s[2] < m["right"] + 0.3 * sp
                               and abs((s[1] + s[3]) / 2 - n["y"]) < 1.5 * sp for s in shapes):
                            if not any(n["x"] < q["x"] < m["x"] and abs(q["y"] - n["y"]) < 0.2 * sp for q in notes):
                                m["held"] = True
                        break
            label = " ".join(w[0] for w in sorted(texts, key=lambda w: (-w[3], w[1]))
                             if w[2] < xl + 2 and y0 - 1.5 * sp <= w[3] <= y1 + 1.5 * sp)
            content.append(dict(staff=st, notes=notes, names=names_of(label)))
        out.append(content)
    return out


def voices_of(systems):
    """Hauteurs par voix, dans l'ordre de la page, selon la disposition de chaque système."""
    v = {n: [] for n in NAMES}
    for system in systems:
        k = len(system)
        if all(s_["names"] for s_ in system) and len({n for s_ in system for n in s_["names"]}) == sum(len(s_["names"]) for s_ in system):
            plan = [(s_, s_["names"]) for s_ in system]  # portées nommées (portées vides masquées par MuseScore)
        elif k >= 4:
            plan = [(s, [NAMES[i]]) for i, s in enumerate(system[-4:])]
        elif k in (2, 3):
            plan = [(system[-2], ["Soprano", "Alto"]), (system[-1], ["Ténor", "Basse"])]
        else:
            # portée seule : couplet du soliste (voix haute), ou soprano et alto en accords
            chords = sum(1 for n in system[0]["notes"] if any(m is not n and abs(m["x"] - n["x"]) < 1.0 for m in system[0]["notes"]))
            plan = [(system[0], ["Soprano", "Alto"] if chords >= 0.3 * len(system[0]["notes"]) else ["Soprano"])]
        for staff, names in plan:
            notes = sorted(staff["notes"], key=lambda n: (round(n["x"], 1), -n["midi"]))
            onsets = []
            for n in notes:
                if onsets and abs(onsets[-1][0]["x"] - n["x"]) < 1.0:
                    onsets[-1].append(n)
                else:
                    onsets.append([n])
            # écriture à deux queues (une par voix) ou en accords (une queue pour les deux voix)
            two_stems = any(any(n["up"] and not n["down"] for n in g) and any(n["down"] and not n["up"] for n in g) for g in onsets)
            for group in onsets:
                if len(names) == 1:
                    top = max(group, key=lambda n: n["midi"])
                    if not top["held"]:
                        v[names[0]].append(top["midi"])
                    continue
                ups = [n for n in group if n["up"] and not n["down"]]
                downs = [n for n in group if n["down"] and not n["up"]]
                both = [n for n in group if n not in ups and n not in downs]
                if not two_stems or (len(group) >= 2 and (not ups or not downs)):
                    # accords : la plus haute à la voix du haut, la plus basse à celle du bas ; tête seule : unisson
                    srt = sorted(group, key=lambda n: -n["midi"])
                    hi, lo = srt[0], srt[-1]
                else:
                    hi = max(ups, key=lambda n: n["midi"]) if ups else None
                    lo = min(downs, key=lambda n: n["midi"]) if downs else None
                    if both:  # unisson (deux queues) ou ronde : les deux voix, la plus haute en haut
                        b = sorted(both, key=lambda n: -n["midi"])
                        hi = hi or b[0]
                        lo = lo or b[-1]
                for name, n in ((names[0], hi), (names[1], lo)):
                    if n is not None and not n["held"]:
                        v[name].append(n["midi"])
    return {k: x for k, x in v.items() if x}


def main(pdf, out=None, detail=False):
    doc = pdfium.PdfDocument(str(pdf))
    systems = []
    for i in range(len(doc)):
        systems += read_page(doc[i])
    voices = voices_of(systems)
    if not voices or not systems:
        sys.exit("aucune note en police SMuFL dans ce PDF")
    if detail:
        for si, system in enumerate(systems):
            print(f"système {si + 1} : {len(system)} portée(s), notes {[len(s['notes']) for s in system]}")
    for k, x in voices.items():
        print(f"{k:8s} {len(x):3d} notes  {x[:24]}")
    if out:
        pathlib.Path(out).write_text(json.dumps(voices, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--detail"]
    if not args:
        sys.exit(__doc__)
    main(args[0], args[1] if len(args) > 1 else None, "--detail" in sys.argv)
