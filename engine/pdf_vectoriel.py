"""
Lecture directe d'un PDF gravé par un logiciel (MuseScore 3 et 4 : symboles de la police SMuFL — Leland, Bravura,
MScore —, chacun placé exactement) : aucune reconnaissance d'image, chaque note est lue telle qu'elle a été gravée.
Hauteur : place de la tête sur sa portée, clé, armure, altérations reportées dans la mesure. Durée : tête (ronde,
blanche, noire), crochets ou ligatures au bout de la queue, points, triolets. Mesures : barres. Voix : la portée
(4 portées : S, A, T, B ; 2 portées : S/A et T/B séparées par le sens des queues ; une portée seule : la voix haute,
ou soprano et alto en accords), les portées masquées d'un système reconnues à leur nom écrit à gauche.

  python3 pdf_vectoriel.py <partition.pdf> <sortie.musicxml>
      code de sortie 2 : PDF sans symboles SMuFL (scan, autre logiciel) : la lecture d'image prend le relais
"""
import ctypes, io, os, statistics, sys
from fractions import Fraction

import pypdfium2 as pdfium
import pypdfium2.raw as raw

HEADS = {0xE0A0: 8, 0xE0A2: 4, 0xE0A3: 2, 0xE0A4: 1}
CLEFS = {0xE050: ("G", 0), 0xE052: ("G", -1), 0xE053: ("G", 1), 0xE062: ("F", 0), 0xE05C: ("C", 0),
         0xE07A: ("G", 0), 0xE07C: ("F", 0), 0xE07B: ("C", 0)}
ACC = {0xE260: -1, 0xE261: 0, 0xE262: 1, 0xE263: 2, 0xE264: -2}
FLAGS = {0xE240: 1, 0xE241: 1, 0xE242: 2, 0xE243: 2, 0xE244: 3, 0xE245: 3, 0xE246: 4, 0xE247: 4}
RESTS = {0xE4E2: 8, 0xE4E3: 4, 0xE4E4: 2, 0xE4E5: 1, 0xE4E6: 0.5, 0xE4E7: 0.25, 0xE4E8: 0.125}
DOT = 0xE1E7
TIME = {0xE080 + k: k for k in range(10)}
COMMON, CUT = 0xE08A, 0xE08B
TUPLET = {0xE880 + k: k for k in range(10)}
BOTTOM = {"G": 2 + 7 * 4, "F": 4 + 7 * 2, "C": 3 + 7 * 3}
STEP_PC = [0, 2, 4, 5, 7, 9, 11]
# Polices d'avant SMuFL, ramenées aux codes SMuFL ci-dessus.
# MuseScore 1 et 2 (police « MScore 20 », « MScore Regular » : codes de la police feta de LilyPond)
OLD_MSCORE = {0xE12B: 0xE0A2, 0xE12C: 0xE0A3, 0xE12D: 0xE0A4,
              0xE19E: 0xE050, 0xE1D7: 0xE052, 0xE19C: 0xE062, 0xE19A: 0xE05C,
              0xE10E: 0xE262, 0xE113: 0xE261, 0xE114: 0xE260,
              0xE190: 0xE240, 0xE194: 0xE241,
              0xE100: 0xE4E3, 0xE101: 0xE4E4, 0xE107: 0xE4E5, 0xE109: 0xE4E6, 0xE10A: 0xE4E7, 0xE10B: 0xE4E8,
              0xE127: 0xE1E7, 0xE09A: 0xE08A, 0xE09B: 0xE08B}
# Sibelius (Opus, Helsinki), Finale (Maestro, Petrucci, Engraver), Toccata : codes de la police Sonata, lus selon
# le codage Mac (« œ » = 0xCF, tête noire) ou décalés de 0xF000 (police « symbole »)
SONATA = {0xCF: 0xE0A4, 0xFA: 0xE0A3, 0x77: 0xE0A2,
          0x26: 0xE050, 0x3F: 0xE062, 0x42: 0xE05C,
          0x23: 0xE262, 0x6E: 0xE261, 0x62: 0xE260,
          0x6A: 0xE240, 0x4A: 0xE241,
          0xB7: 0xE4E3, 0xEE: 0xE4E4, 0xCE: 0xE4E5, 0xE4: 0xE4E6, 0xC5: 0xE4E7,
          0x2E: 0xE1E7, 0x63: 0xE08A, 0x43: 0xE08B}
SONATA_SPECIAL = {0xAA: 0xE1E7}  # Opus Special, Helsinki Special : point de durée
SONATA_FONTS = ("Opus", "Helsinki", "Maestro", "Petrucci", "Engraver", "SToccata", "Toccata", "Sonata", "Inkpen",
                "Reprise", "Jazz", "Norfolk", "Pori", "Tamburo")
NOT_MUSIC = ("Chord", "Text", "Times", "Figured", "Percussion", "Ornaments", "Metronome")
NAMES = ["Soprano", "Alto", "Ténor", "Basse"]
LABELS = [("soprano", "Soprano"), ("alto", "Alto"), ("tenor", "Ténor"), ("ténor", "Ténor"), ("basse", "Basse"),
          ("bass", "Basse"), ("sop", "Soprano"), ("ten", "Ténor"), ("bar", "Basse")]


# ------------------------------------------------------------------------------------------------ éléments de la page

def _font(tp, i, buf=ctypes.create_string_buffer(256), flags=ctypes.c_int()):
    raw.FPDFText_GetFontInfo(tp, i, buf, 256, ctypes.byref(flags))
    return buf.value.decode("latin1", "ignore").split("+")[-1]


def _sonata_byte(ch):
    if 0xF000 <= ch <= 0xF0FF:
        return ch - 0xF000
    if ch < 0x80:
        return ch
    try:
        return chr(ch).encode("mac_roman")[0]
    except (UnicodeEncodeError, ValueError):
        return None


def kind_of(font, codes):
    """Codage d'une police : « smufl », « mscore » (MuseScore 1 et 2), « sonata », « sonata-special » ou None."""
    if font.startswith(SONATA_FONTS):
        if any(w in font for w in NOT_MUSIC):
            return None
        return "sonata-special" if "Special" in font else "sonata"
    if codes & {0xE12B, 0xE12C, 0xE12D} and not codes & {0xE0A2, 0xE0A3, 0xE0A4}:
        return "mscore"
    if any(0xE000 <= c <= 0xF8FF for c in codes):
        return "smufl"
    return None


def translate(kind, ch):
    """Code SMuFL d'un caractère d'une police musicale (None : pas un symbole lu ici)."""
    if kind == "smufl":
        return ch if 0xE000 <= ch <= 0xF8FF else None
    if kind == "mscore":
        if 0x30 <= ch <= 0x39:
            return 0xE080 + ch - 0x30  # chiffres de la mesure
        return OLD_MSCORE.get(ch)
    if kind in ("sonata", "sonata-special"):
        b = _sonata_byte(ch)
        if kind == "sonata" and b is not None and 0x30 <= b <= 0x39:
            return 0xE080 + b - 0x30
        return (SONATA if kind == "sonata" else SONATA_SPECIAL).get(b)
    return None


def _obj_text(obj, tp):
    n = raw.FPDFTextObj_GetText(obj, tp.raw, None, 0)
    if n <= 2:
        return ""
    buf = (ctypes.c_ubyte * n)()
    raw.FPDFTextObj_GetText(obj, tp.raw, ctypes.cast(buf, ctypes.POINTER(ctypes.c_ushort)), n)
    return bytes(buf).decode("utf-16-le", "ignore").rstrip("\x00")


def _obj_font(obj, buf=ctypes.create_string_buffer(256)):
    raw.FPDFFont_GetBaseFontName(raw.FPDFTextObj_GetFont(obj), buf, 256)
    return buf.value.decode("latin1", "ignore").split("+")[-1]


def glyphs(page):
    tp = page.get_textpage()
    n = tp.count_chars()
    fonts = [_font(tp, i) for i in range(n)]
    codes = [raw.FPDFText_GetUnicode(tp, i) for i in range(n)]
    by_font = {}
    for f, c in zip(fonts, codes):
        by_font.setdefault(f, set()).add(c)
    kinds = {f: kind_of(f, cs) for f, cs in by_font.items()}
    out = []
    x, y = ctypes.c_double(), ctypes.c_double()
    for i in range(n):
        ch = translate(kinds[fonts[i]], codes[i])
        if ch is None:
            continue
        raw.FPDFText_GetCharOrigin(tp, i, ctypes.byref(x), ctypes.byref(y))
        l, b_, r, t = tp.get_charbox(i)
        out.append(dict(code=ch, x=x.value, y=y.value, left=l, right=r, bottom=b_, top=t, size=t - b_))
    # La page de texte de pdfium écarte un caractère identique au précédent qui le chevauche (faux gras) : la tête
    # de note du haut d'un accord serré (MuseScore 1 et 2, une tête par objet). On la reprend des objets du PDF :
    # objet de texte vide, juste après un objet au même x, de même taille, d'une police musicale.
    prev = None
    for k in range(raw.FPDFPage_CountObjects(page.raw)):
        obj = raw.FPDFPage_GetObject(page.raw, k)
        if raw.FPDFPageObj_GetType(obj) != raw.FPDF_PAGEOBJ_TEXT:
            continue
        txt = _obj_text(obj, tp).strip()
        l, b_, r, t = (ctypes.c_float(), ctypes.c_float(), ctypes.c_float(), ctypes.c_float())
        raw.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b_), ctypes.byref(r), ctypes.byref(t))
        box = (l.value, b_.value, r.value, t.value)
        if txt:
            prev = (txt, box, _obj_font(obj)) if len(txt) == 1 else None
            continue
        if prev is None or prev[2] != _obj_font(obj) or kinds.get(prev[2]) is None:
            continue
        pbox = prev[1]
        if abs(box[0] - pbox[0]) < 0.5 and abs((box[2] - box[0]) - (pbox[2] - pbox[0])) < 0.1 \
                and abs((box[3] - box[1]) - (pbox[3] - pbox[1])) < 0.1 and 0 < abs(box[1] - pbox[1]) < 2 * (pbox[3] - pbox[1]):
            ch = translate(kinds[prev[2]], ord(prev[0]))
            if ch is not None:
                m = _matrix(obj)
                out.append(dict(code=ch, x=m[4], y=m[5], left=box[0], right=box[2], bottom=box[1], top=box[3],
                                size=box[3] - box[1]))
    return out


def words(page):
    """Mots de la page : (texte, gauche, droite, milieu en hauteur). Les lettres d'un mot sont réunies d'après leur
    ligne de base (« o » et « T » n'ont pas le même milieu)."""
    tp = page.get_textpage()
    chars = []
    x, y = ctypes.c_double(), ctypes.c_double()
    for i in range(tp.count_chars()):
        ch = raw.FPDFText_GetUnicode(tp, i)
        if 32 < ch < 0x2000:
            l, b, r, t = tp.get_charbox(i)
            raw.FPDFText_GetCharOrigin(tp, i, ctypes.byref(x), ctypes.byref(y))
            chars.append((chr(ch), l, r, (b + t) / 2, y.value))
    lines = []
    for c in sorted(chars, key=lambda c: c[4]):
        if lines and abs(c[4] - lines[-1][0][4]) < 1.0:
            lines[-1].append(c)
        else:
            lines.append([c])
    out = []
    for line in lines:
        cur = None
        for c in sorted(line, key=lambda c: c[1]):
            if cur is not None and 0 <= c[1] - cur[2] < 4:
                cur = (cur[0] + c[0], cur[1], c[2], cur[3], cur[4])
            else:
                if cur is not None:
                    out.append(cur)
                cur = c
        if cur is not None:
            out.append(cur)
    return [(w[0], w[1], w[2], w[3]) for w in out]


def _mul(m, n):
    a, b, c, d, e, f = m
    a2, b2, c2, d2, e2, f2 = n
    return (a * a2 + b * c2, a * b2 + b * d2, c * a2 + d * c2, c * b2 + d * d2, e * a2 + f * c2 + e2, e * b2 + f * d2 + f2)


def _matrix(obj):
    m = raw.FS_MATRIX()
    raw.FPDFPageObj_GetMatrix(obj, ctypes.byref(m))
    return (m.a, m.b, m.c, m.d, m.e, m.f)


def segment_lines(page):
    """Traits droits horizontaux de tous les tracés, un par segment, en coordonnées de la page (Sibelius, Finale,
    MuseScore 2 tracent parfois les cinq lignes d'une portée en un seul chemin, ou un trait épais)."""
    out, vert = [], []
    px, py = ctypes.c_float(), ctypes.c_float()

    def walk(handles, parent):
        for obj in handles:
            kind = raw.FPDFPageObj_GetType(obj)
            m = _mul(_matrix(obj), parent)
            if kind == raw.FPDF_PAGEOBJ_FORM:
                n = raw.FPDFFormObj_CountObjects(obj)
                walk([raw.FPDFFormObj_GetObject(obj, k) for k in range(n)], m)
                continue
            if kind != raw.FPDF_PAGEOBJ_PATH:
                continue
            n = raw.FPDFPath_CountSegments(obj)
            if n > 400:
                continue
            prev = None
            for k in range(n):
                seg = raw.FPDFPath_GetPathSegment(obj, k)
                raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(px), ctypes.byref(py))
                a, b, c, d, e, f = m
                x, y = a * px.value + c * py.value + e, b * px.value + d * py.value + f
                if raw.FPDFPathSegment_GetType(seg) == raw.FPDF_SEGMENT_LINETO and prev is not None:
                    if abs(y - prev[1]) < 0.15 and abs(x - prev[0]) > 30:
                        out.append((min(x, prev[0]), y, max(x, prev[0]), y))
                    elif abs(x - prev[0]) < 0.15 and abs(y - prev[1]) > 5:
                        vert.append((x, min(y, prev[1]), x, max(y, prev[1])))
                prev = (x, y)

    walk([raw.FPDFPage_GetObject(page.raw, k) for k in range(raw.FPDFPage_CountObjects(page.raw))], (1, 0, 0, 1, 0, 0))
    # un rectangle plein trace deux fois chaque ligne (haut et bas du trait) : on garde le milieu
    out.sort(key=lambda s: (round(s[0]), s[1]))
    merged = []
    for s in out:
        if merged and abs(merged[-1][0] - s[0]) < 1 and abs(merged[-1][2] - s[2]) < 1 and 0 <= s[1] - merged[-1][1] < 1.5:
            p = merged[-1]
            merged[-1] = (p[0], (p[1] + s[1]) / 2, p[2], (p[1] + s[1]) / 2)
        else:
            merged.append(s)
    return merged, vert


def paths(page):
    hor, ver, shapes, blocks = [], [], [], []
    for o in page.get_objects():
        if o.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        l, b, r, t = o.get_bounds()
        w, h = r - l, t - b
        if h < 1.2 and w > 30:
            hor.append((l, b, r, t))
        elif (w < 2.5 and h > 5) or (THICK_BARS and w < 4.5 and h > 5 * w):
            ver.append((l, b, r, t))  # 4,5 : barre épaisse de fin de partie (Toccata : 3 points)
        elif w > 2 and h < 14:
            # liaisons (courbes), ligatures, crochets de triolet ; une liaison n'est jamais une ligature
            # (une ligature est un quadrilatère ; une liaison, une courbe, ou une ligne brisée de nombreux points)
            nseg = raw.FPDFPath_CountSegments(o.raw)
            curved = nseg > 8 or any(raw.FPDFPathSegment_GetType(raw.FPDFPath_GetPathSegment(o.raw, k)) == raw.FPDF_SEGMENT_BEZIERTO
                                     for k in range(min(nseg, 200)))
            # même tracé deux fois (remplissage puis contour) : une seule ligature
            # (LilyPond : surface et contour arrondi, cadres décalés de 0,4 point)
            if not (SAME_SHAPE and any(abs(q[0] - l) < 0.6 and abs(q[1] - b) < 0.6 and abs(q[2] - r) < 0.6 and abs(q[3] - t) < 0.6
                                       for q in shapes[-6:])):
                shapes.append((l, b, r, t, curved))
        if w > 30 and 8 < h < 60:
            blocks.append((l, b, r, t))
    if len(hor) < 5 and blocks:
        common = statistics.mode(round(t - b) for _l, b, _r, t in blocks)
        bands = {}
        for l, b, r, t in blocks:
            if abs((t - b) - common) <= 1:
                bands.setdefault((round(b * 2) / 2, round(t * 2) / 2), []).append((l, r))
        hor = []
        for (b, t), xs in bands.items():
            for k in range(5):
                y = b + k * (t - b) / 4
                hor.append((min(x[0] for x in xs), y, max(x[1] for x in xs), y))
    return hor, ver, shapes


def staves_of(hor):
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
                staves.append([ys[0], ys[-1], statistics.mean(gaps), s0[0], s0[2]])
    staves.sort(key=lambda s: (round(s[0]), s[3]))
    merged = []
    for s_ in staves:
        m = next((o for o in merged if abs(o[0] - s_[0]) < 0.6 and abs(o[1] - s_[1]) < 0.6
                  and s_[3] <= o[4] + 3 and s_[4] >= o[3] - 3), None)
        if m is None:
            merged.append(list(s_))
        else:
            m[3], m[4] = min(m[3], s_[3]), max(m[4], s_[4])
    # lignes supplémentaires empilées sous une portée (cinq petits traits réguliers, « Toussaint » : 8 interlignes de
    # large) : pas une portée ; gardée, elle prenait les crochets des notes voisines (croches lues noires)
    if merged:
        widest = max(m[4] - m[3] for m in merged)
        merged = [m for m in merged if m[4] - m[3] >= max(12 * m[2], 0.25 * widest)]
    return sorted((tuple(m) for m in merged), key=lambda s: -s[1])


def systems_of(staves, ver):
    if staves and FRAME:
        # cadre de la page, traits de coupe : hors de la largeur des portées, ils reliaient tous les systèmes en un
        sp = statistics.median(s[2] for s in staves)
        x0, x1 = min(s[3] for s in staves) - sp, max(s[4] for s in staves) + sp
        top, bottom = max(s[1] for s in staves) + 6 * sp, min(s[0] for s in staves) - 6 * sp
        ver = [v for v in ver if x0 <= v[0] <= x1 and not (v[3] > top and v[1] < bottom)]
    groups = [[s] for s in staves]
    merged = True
    while merged:
        merged = False
        for a in range(len(groups) - 1):
            lo, hi = groups[a][-1], groups[a + 1][0]
            if any(v[1] <= hi[1] + 0.5 and v[3] >= lo[0] - 0.5 for v in ver):
                groups[a] += groups.pop(a + 1)
                merged = True
                break
    return groups


def names_of(label):
    out = []
    for w in label.lower().replace(".", " ").replace("&", " ").replace("/", " ").split():
        hit = next((n for k, n in LABELS if w.startswith(k)), None)
        if hit is None and len(w) == 1:
            hit = {"s": "Soprano", "a": "Alto", "t": "Ténor", "b": "Basse"}.get(w)
        if hit and hit not in out:
            out.append(hit)
    return out


# --------------------------------------------------------------------------------------------- lecture d'une portée

def read_staff(st, mine, ver, shapes, texts, all_staves, size, page_flags=None):
    y0, y1, sp, xl, xr = st
    mine.sort(key=lambda g: g["x"])
    heads = [g for g in mine if g["code"] in HEADS and g["size"] >= 0.8 * size]
    clefs = []
    for g in mine:
        if g["code"] in CLEFS:
            kind = CLEFS[g["code"]]
            # clé de sol avec un petit « 8 » écrit dessous (MuseScore 1 et 2, Sibelius) : octave plus bas
            if kind == ("G", 0) and any(w[0] == "8" and g["left"] - 0.5 * sp <= (w[1] + w[2]) / 2 <= g["right"] + 0.5 * sp
                                        and g["bottom"] - 1.5 * sp <= w[3] <= g["bottom"] + 0.5 * sp for w in texts):
                kind = ("G", -1)
            clefs.append((g["x"], kind))
    accs = [g for g in mine if g["code"] in ACC]
    first_head = heads[0]["x"] if heads else xr
    key = {}
    for a in accs:
        if a["x"] < first_head - 0.5 * sp and not any(0 < h["x"] - a["x"] < 2.2 * sp and abs(h["y"] - a["y"]) < 0.3 * sp for h in heads):
            cl = max((c for c in clefs if c[0] < a["x"]), default=(0, ("G", 0)))[1]
            d = BOTTOM[cl[0]] + 7 * cl[1] + round((a["y"] - y0) / (sp / 2))
            key["CDEFGAB"[d % 7]] = ACC[a["code"]]
    fifths = sum(1 for v in key.values() if v == 1) - sum(1 for v in key.values() if v == -1)
    # barres de mesure : traits qui couvrent la portée (ou le système), pas les queues
    def stem_of_head(v):
        # queue d'une note du 1er ou du 4e interligne : elle couvre la portée comme une barre (Finale, Sibelius)
        return any((abs(v[0] - h["right"]) < 0.3 * sp and abs(v[1] - h["y"]) < 0.6 * sp)
                   or (abs(v[2] - h["left"]) < 0.3 * sp and abs(v[3] - h["y"]) < 0.6 * sp) for h in heads)

    bars = sorted(v[0] for v in ver if ((abs(v[1] - y0) < 0.35 * sp + 1 and abs(v[3] - y1) < 0.35 * sp + 1)
                  or (v[1] <= y0 + 0.3 * sp and v[3] >= y1 - 0.3 * sp and v[3] - v[1] > 5 * sp)) and not stem_of_head(v))
    cuts = []
    for b in bars:
        if b <= xl + 0.5 * sp:
            continue  # ligne d'ouverture du système
        if cuts and b - cuts[-1] < 1.2 * sp:
            cuts[-1] = b  # double barre, barre de reprise : un seul trait de mesure
        else:
            cuts.append(b)
    # chiffres de la mesure : deux chiffres l'un sur l'autre (haut : numérateur)
    time_sig = None
    tdig = [g for g in mine if g["code"] in TIME and y0 - 0.5 * sp <= g["y"] <= y1 + 0.5 * sp]
    if any(g["code"] == COMMON for g in mine):
        time_sig = (4, 4)
    elif any(g["code"] == CUT for g in mine):
        time_sig = (2, 2)
    elif tdig:
        mid = (y0 + y1) / 2
        top = "".join(str(TIME[g["code"]]) for g in sorted((g for g in tdig if g["y"] > mid), key=lambda g: g["x"]))
        bot = "".join(str(TIME[g["code"]]) for g in sorted((g for g in tdig if g["y"] <= mid), key=lambda g: g["x"]))
        if top and bot:
            time_sig = (int(top), int(bot))
    # notes : tête, queue, crochets ou ligatures, points
    notes = []
    measure_acc, last_cut = {}, -1e9
    stems = [v for v in ver if v[3] - v[1] < 11 * sp]  # accord du ténor et de la basse : queue longue
    for h in heads:
        passed = [c for c in cuts if last_cut < c < h["x"]]
        if passed:
            measure_acc, last_cut = {}, passed[-1]
        cl = max((c for c in clefs if c[0] < h["x"]), default=(0, ("G", 0)))[1]
        d = BOTTOM[cl[0]] + 7 * cl[1] + round((h["y"] - y0) / (sp / 2))
        step = "CDEFGAB"[d % 7]
        sign = next((a for a in accs if 0 < h["left"] - a["right"] < 1.6 * sp and abs(a["y"] - h["y"]) < 0.3 * sp), None)
        if sign is not None:
            alter = ACC[sign["code"]]
            measure_acc[d] = alter
        else:
            alter = measure_acc.get(d, key.get(step, 0))
        midi = 12 * (d // 7 + 1) + STEP_PC[d % 7] + alter
        up = [v for v in stems if abs(v[0] - h["right"]) < 0.3 * sp and abs(v[1] - h["y"]) < 0.6 * sp and v[3] > h["y"] + sp]
        down = [v for v in stems if abs(v[0] - h["left"]) < 0.3 * sp and abs(v[3] - h["y"]) < 0.6 * sp and v[1] < h["y"] - sp]
        notes.append(dict(x=h["x"], y=h["y"], left=h["left"], right=h["right"], midi=midi, step=step, octave=d // 7,
                          alter=alter, base=HEADS[h["code"]], hollow=h.get("hollow", False), up=bool(up), down=bool(down),
                          stem=(up or down or [None])[0], stem_down=down[0] if up and down else None, tie=False))
    # accord de seconde : une tête est déportée de l'autre côté de la queue, juste à côté de sa voisine ; c'est le
    # même temps (« Rendons gloire à Dieu » : mi bémol et ré de la dernière noire lus l'un après l'autre)
    if SECONDS:
        for n in sorted(notes, key=lambda n: n["x"]):
            w = n["right"] - n["left"]
            for m in notes:
                # une seconde (pas un unisson : récitation des psaumes, brèves côte à côte), sur une seule queue
                # (deux voix à queues opposées gardent chacune son temps : Psaume 70)
                if m is not n and 0.75 * w < m["x"] - n["x"] < 1.15 * w and 0.35 * sp <= abs(m["y"] - n["y"]) <= 0.65 * sp \
                        and (n["stem"] is None or m["stem"] is None or n["stem"] == m["stem"]):
                    m["x"] = n["x"]
    # queue partagée par un accord : la tête du bout la porte, les autres au même x et sous la même queue aussi
    for n in notes:
        if n["stem"] is None:
            for m in notes:
                if m is not n and m["stem"] is not None and abs(m["x"] - n["x"]) < 1.0:
                    s_ = m["stem"]
                    if s_[1] - 0.6 * sp <= n["y"] <= s_[3] + 0.6 * sp:
                        n["stem"], n["up"], n["down"] = s_, m["up"], m["down"]
                        break
    # tête creuse reconnue par son dessin (glyphes.py) : blanche si elle a une queue, ronde sinon
    for n in notes:
        if n.get("hollow") and n["stem"] is None:
            n["base"] = 4

    def stem_dur(n, s_, up):
        dur = Fraction(n["base"])
        if n["base"] == 1 and s_ is not None:
            tip = s_[3] if up else s_[1]
            sx = (s_[0] + s_[2]) / 2
            # crochet : son origine au bout de la queue (SMuFL) ou à la tête (polices Sonata), son bord au bout
            # crochets de toute la page : celui d'une queue qui descend loin sous la portée est plus près de la
            # portée du dessous (« Devant toi » : croche de l'alto lue noire)
            flags = [g for g in (page_flags if page_flags is not None else mine) if g["code"] in FLAGS and abs(g["x"] - sx) < 0.6 * sp
                     and min(abs(g["y"] - tip), abs(g["top"] - tip), abs(g["bottom"] - tip)) < 1.8 * sp]
            if flags:
                dur = Fraction(1, 2 ** FLAGS[flags[0]["code"]])
            else:
                # ligatures : au bout de la queue, les suivantes empilées vers la tête (3/4 d'interligne chacune)
                toward = 1 if not up else -1  # queue descendante : les ligatures suivantes sont au-dessus
                beams = [b for b in shapes if not b[4] and b[0] - 0.4 <= sx <= b[2] + 0.4 and 0.35 * sp <= (b[3] - b[1]) < 3 * sp and (b[2] - b[0]) > 0.6 * sp
                         and b[1] - 0.6 * sp <= tip + (2.6 * sp if toward > 0 else 0) and b[3] + 0.6 * sp >= tip - (2.6 * sp if toward < 0 else 0)
                         and not (b[1] > n["y"] - 0.3 * sp and b[3] < n["y"] + 0.3 * sp)
                         # une ligature ne couvre pas sa propre tête (Finale : queue et ligne supplémentaire d'un tracé)
                         and not (OWN_HEAD and b[0] <= (n["left"] + n["right"]) / 2 <= b[2] and b[1] <= n["y"] <= b[3])]
                if beams and BEAM_PIECES:
                    # ligature tracée en morceaux d'une queue à l'autre (Toccata) : à une queue du milieu, le morceau
                    # de gauche et celui de droite sont la même ligature
                    beams = [b for b in beams if not any(c is not b and abs(c[2] - b[0]) < 1.0 and abs(b[0] - sx) < 1.0
                                                         and min(b[3], c[3]) - max(b[1], c[1]) > 0.5 * min(b[3] - b[1], c[3] - c[1])
                                                         for c in beams)]
                if beams:
                    # une ligature par niveau, chacune son tracé (penchée : son cadre est plus haut qu'elle, on ne
                    # mesure pas sa hauteur, on compte les tracés qui passent au bout de la queue)
                    dur = Fraction(1, 2 ** min(4, len(beams)))
        return dur

    # chaque point de durée à une seule tête : la plus proche en hauteur parmi celles juste à sa gauche (deux voix
    # pointées sur une portée : le point de l'alto comptait aussi pour la soprano, blanche lue doublement pointée)
    owner = {}
    for g in mine:
        if g["code"] == DOT:
            near = [n for n in notes if 0 < g["x"] - n["right"] < 1.6 * sp and abs(g["y"] - n["y"]) < 0.6 * sp]
            if near:
                # à égale distance de deux têtes (tierce : point dans l'interligne entre elles), il est à celle qu'il
                # surmonte (note sur une ligne : point dans l'interligne au-dessus ; « Songo Soalla »)
                owner[id(g)] = id(min(near, key=lambda n: (round(abs(g["y"] - n["y"]) / sp * 4), g["y"] < n["y"] - 0.1 * sp,
                                                           g["x"] - n["right"])))
    for n in notes:
        dur = stem_dur(n, n["stem"], n["up"])
        # unisson à deux queues : chaque voix sa durée (noire du ténor, croche ligaturée de la basse : Psaume 118)
        dur_down = stem_dur(n, n["stem_down"], False) if n["stem_down"] is not None else None
        dots = [g for g in mine if g["code"] == DOT and 0 < g["x"] - n["right"] < 1.6 * sp and abs(g["y"] - n["y"]) < 0.6 * sp
                and (not DOT_OWNER or owner.get(id(g)) == id(n) or any(abs(m["x"] - n["x"]) < 0.5 and abs(m["y"] - n["y"]) < 0.05
                                                                        and owner.get(id(g)) == id(m) for m in notes))]
        if dots:
            dur = dur * (Fraction(3, 2) if len(dots) == 1 else Fraction(7, 4))
            dur_down = dur_down and dur_down * (Fraction(3, 2) if len(dots) == 1 else Fraction(7, 4))
        n["dur"] = dur
        if dur_down is not None and dur_down != dur:
            n["dur_down"] = dur_down
    # triolets : chiffre « 3 » au-dessus d'un groupe ligaturé ou d'un crochet
    for g in mine:
        if g["code"] in TUPLET and TUPLET[g["code"]] in (3, 5, 6):
            k = TUPLET[g["code"]]
            close = sorted((n for n in notes if abs(n["x"] - g["x"]) < 3.5 * sp), key=lambda n: abs(n["x"] - g["x"]))
            group = sorted({id(n): n for n in close[:k * 2]}.values(), key=lambda n: n["x"])
            xs = sorted({round(n["x"]) for n in group})[:k]
            for n in group:
                if round(n["x"]) in xs:
                    n["dur"] = n["dur"] * Fraction(2 if k == 3 else 4, k)
                    if "dur_down" in n:
                        n["dur_down"] = n["dur_down"] * Fraction(2 if k == 3 else 4, k)
    # liaisons de prolongation
    for k, n in enumerate(notes):
        for m in notes[k + 1:]:
            if abs(m["y"] - n["y"]) < 0.2 * sp and m["midi"] == n["midi"]:
                if any(n["left"] - 0.3 * sp < s[0] < n["right"] + 0.8 * sp and m["left"] - 0.8 * sp < s[2] < m["right"] + 0.3 * sp
                       and abs((s[1] + s[3]) / 2 - n["y"]) < 1.5 * sp for s in shapes):
                    if not any(n["x"] < q["x"] < m["x"] and abs(q["y"] - n["y"]) < 0.2 * sp for q in notes):
                        m["tie"] = True
                break
    rests = []
    for g in mine:
        if g["code"] in RESTS:
            code = g["code"]
            if g.get("rect"):
                # rectangle plein (glyphes.py) : la pause pend sous une ligne, la demi-pause est posée dessus
                lines = [y0 + k * sp for k in range(5)]
                code = 0xE4E3 if min(abs(g["top"] - y) for y in lines) < min(abs(g["bottom"] - y) for y in lines) else 0xE4E4
            dur = Fraction(RESTS[code]).limit_denominator(32)
            if any(d["code"] == DOT and 0 < d["x"] - g["right"] < 1.6 * sp and abs(d["y"] - g["y"]) < 1.2 * sp for d in mine):
                dur *= Fraction(3, 2)
            rests.append(dict(x=g["x"], y=g["y"], dur=dur, whole=code == 0xE4E3))
    label = " ".join(w[0] for w in sorted(texts, key=lambda w: (-w[3], w[1]))
                     if w[2] < xl + 2 and y0 - 1.5 * sp <= w[3] <= y1 + 1.5 * sp)
    return dict(staff=st, sp=sp, notes=notes, rests=rests, cuts=cuts, clefs=clefs, fifths=fifths, time=time_sig,
                names=names_of(label), mid=(y0 + y1) / 2)


def upright(path):
    """Document dont les pages tournées (« A4 paysage » : /Rotate 90) sont remises droites, contenu compris : les
    lignes de portée y redeviennent horizontales."""
    doc = pdfium.PdfDocument(str(path))
    if all(p.get_rotation() % 360 == 0 for p in doc):
        return doc
    for page in doc:
        r = page.get_rotation() % 360
        if not r:
            continue
        x0, y0, x1, y1 = page.get_mediabox()
        W, H = x1 - x0, y1 - y0
        m = {90: (0, -1, 1, 0, -y0, W + x0), 180: (-1, 0, 0, -1, W + x0, H + y0), 270: (0, 1, -1, 0, H + y0, -x0)}[r]
        for k in range(raw.FPDFPage_CountObjects(page.raw)):
            raw.FPDFPageObj_Transform(raw.FPDFPage_GetObject(page.raw, k), *m)
        nw, nh = (H, W) if r in (90, 270) else (W, H)
        raw.FPDFPage_SetMediaBox(page.raw, 0, 0, nw, nh)
        raw.FPDFPage_SetCropBox(page.raw, 0, 0, nw, nh)
        page.set_rotation(0)
        raw.FPDFPage_GenerateContent(page.raw)
    buf = io.BytesIO()
    doc.save(buf)
    return pdfium.PdfDocument(buf.getvalue())


SHAPES = os.environ.get("PUPITRE_PDF_DESSINS", "1") != "0"


def read_pdf(path):
    doc = upright(path)
    copy = None
    systems = []
    for i in range(len(doc)):
        page = doc[i]
        gl = glyphs(page)
        hor, ver, shapes = paths(page)
        # portée : au moins 12 % de la largeur de la page (des traits courts parallèles, ligatures empilées, soulignés
        # des paroles, faisaient de fausses portées : « Songo Soalla », portées dessinées en caractères)
        wide = (lambda sts: [st for st in sts if st[4] - st[3] >= 0.12 * page.get_size()[0]]) if SHORT_STAVES else (lambda sts: sts)
        staves = wide(staves_of(hor))
        seg_hor, seg_ver = segment_lines(page)
        alt = wide(staves_of(seg_hor))
        if len(alt) > len(staves):
            # portées tracées autrement (Sibelius, Finale, MuseScore 2) : barres de mesure peut-être aussi dans un
            # seul chemin avec d'autres traits
            staves = alt
            ver = ver + seg_ver
            hor = seg_hor
        if SHAPES and sum(1 for g in gl if g["code"] in HEADS) < 4:
            # codes de la police inconnus ou recodés : symboles reconnus par leur dessin (glyphes.py)
            import glyphes
            if copy is None:
                buf = io.BytesIO()
                doc.save(buf)
                copy = pdfium.PdfDocument(buf.getvalue())
            sp0 = statistics.median(s[2] for s in staves) if staves else None
            g2, h2, v2, b2 = glyphes.read_page(copy[i], sp0)
            if sum(1 for g in g2 if g["code"] in HEADS) >= 4:
                gl, ver, shapes = g2, ver + v2, shapes + b2
                if h2:
                    more = wide(staves_of(hor + h2))
                    if len(more) > len(staves):
                        staves = more
        if not any(g["code"] in HEADS for g in gl):
            continue
        if PATH_DOTS and staves:
            # points de durée tracés (petits disques) et non écrits avec la police (« JEM 677 »)
            spm = statistics.median(s[2] for s in staves)
            for o in page.get_objects():
                if o.type != raw.FPDF_PAGEOBJ_PATH:
                    continue
                l, b, r, t = o.get_bounds()
                if 0.25 * spm <= r - l <= 0.7 * spm and 0.25 * spm <= t - b <= 0.7 * spm and abs((r - l) - (t - b)) < 0.25 * spm \
                        and not any(g["code"] == DOT and abs(g["x"] - l) < 0.3 * spm and abs(g["y"] - (b + t) / 2) < 0.3 * spm for g in gl):
                    gl.append(dict(code=DOT, x=l, y=(b + t) / 2, left=l, right=r, bottom=b, top=t, size=t - b))
        texts = words(page)
        size = statistics.median([g["size"] for g in gl if g["code"] in HEADS])
        for group in systems_of(staves, ver):
            content = []
            for st in group:
                y0, y1, sp, xl, xr = st
                # 6,5 interlignes : crochet d'une note à deux lignes supplémentaires (ténor au-dessus de la clé de fa,
                # « Toussaint » : croches lues noires à 4 interlignes) ; chaque signe va à la portée la plus proche
                mine = [g for g in gl if y0 - 6.5 * sp <= g["y"] <= y1 + 6.5 * sp and xl - 2 * sp <= g["x"] <= xr + sp
                        and min(staves, key=lambda s: abs((s[0] + s[1]) / 2 - g["y"])) is st]
                content.append(read_staff(st, mine, ver, shapes, texts, staves, size,
                                          [g for g in gl if g["code"] in FLAGS] if FLAGS_PAGE else None))
            # cinq traits parallèles sans clé, sans note ni silence (cadre, traits décoratifs) : pas une portée ; gardée,
            # elle prenait la place de la portée de fa (« Toussaint » : soprano lue sur la portée de fa, ténor et basse perdus)
            content = [c for c in content if c["notes"] or c["rests"] or c["clefs"]]
            if content:
                systems.append(content)
    return systems


# ----------------------------------------------------------------------------------------------- voix et partition

PARTNER = {"Soprano": "Alto", "Ténor": "Basse"}


def chordal(s):
    return sum(1 for n in s["notes"] if any(m is not n and abs(m["x"] - n["x"]) < 1.0 for m in s["notes"])) >= 0.3 * max(1, len(s["notes"]))


def two_voiced(s):
    """Portée à deux voix : au moins un dixième de ses attaques sont des accords (ténor et basse souvent à l'unisson :
    moins d'accords que la règle de chordal, mais jamais une mélodie seule)."""
    xs = sorted(n["x"] for n in s["notes"])
    onsets, chords, prev, size = 0, 0, None, 0
    for x in xs + [None]:
        if x is not None and prev is not None and abs(x - prev) < 1.0:
            size += 1
            continue
        if prev is not None:
            onsets += 1
            chords += size >= 2
        prev, size = x, 1
    return chords >= max(2, 0.1 * onsets)


VOICE_COUNT = os.environ.get("PUPITRE_VOIX_COMPTEES", "1") != "0"
TENOR_8 = os.environ.get("PUPITRE_TENOR_SOL", "1") != "0"
CHOIR_BELOW = os.environ.get("PUPITRE_CHOEUR_BAS", "1") != "0"
VOICE_CLEFS = os.environ.get("PUPITRE_VOIX_CLES", "1") != "0"
SATB_STAVES = os.environ.get("PUPITRE_QUATRE_PORTEES", "1") != "0"
DOT_OWNER = os.environ.get("PUPITRE_POINT_UNIQUE", "1") != "0"
FLAGS_PAGE = os.environ.get("PUPITRE_CROCHETS_PAGE", "1") != "0"
THICK_BARS = os.environ.get("PUPITRE_BARRES_EPAISSES", "1") != "0"
FRAME = os.environ.get("PUPITRE_CADRE", "1") != "0"
OWN_HEAD = os.environ.get("PUPITRE_LIGATURE_TETE", "1") != "0"
PATH_DOTS = os.environ.get("PUPITRE_POINTS_TRACES", "1") != "0"
SAME_SHAPE = os.environ.get("PUPITRE_TRACES_DOUBLES", "1") != "0"
BEAM_PIECES = os.environ.get("PUPITRE_LIGATURES_MORCEAUX", "1") != "0"
SECONDS = os.environ.get("PUPITRE_SECONDES", "1") != "0"
BAR_REST = os.environ.get("PUPITRE_PAUSE_MESURE", "1") != "0"
SHORT_STAVES = os.environ.get("PUPITRE_PORTEES_COURTES", "1") != "0"


def plan_of(system):
    k = len(system)
    if all(s["names"] for s in system) and len({n for s in system for n in s["names"]}) == sum(len(s["names"]) for s in system):
        used = {n for s in system for n in s["names"]}
        plan = []
        for s in system:
            names = list(s["names"])
            # « S » écrit devant une portée en accords, sans portée « A » : soprano et alto sur la même portée
            if len(names) == 1 and PARTNER.get(names[0]) not in used | {None} and chordal(s):
                names.append(PARTNER[names[0]])
            plan.append((s, names))
        return plan
    if k >= 4:
        if SATB_STAVES and k > 4:
            # quatre portées à une voix, clés d'un chœur (sol, sol, sol ou sol 8, fa), au-dessus d'un accompagnement
            # (« Donne-moi seulement de t'aimer », refrain) : ce sont elles, pas la réduction pour piano
            cl = [s["clefs"][0][1] if s["clefs"] else ("G", 0) for s in system]
            for i in range(k - 3):
                four = system[i:i + 4]
                if not any(two_voiced(s) for s in four) and cl[i][0] == "G" and cl[i + 1][0] == "G" \
                        and cl[i + 2][0] == "G" and cl[i + 3][0] == "F" and any(two_voiced(s) for s in system[i + 4:]):
                    return [(s, [NAMES[j]]) for j, s in enumerate(four)]
        if CHOIR_BELOW and chordal(system[-2]) and chordal(system[-1]) and not any(chordal(s) for s in system[:-2]):
            # mélodies (couplets, soliste) au-dessus d'un chœur écrit sur deux portées à deux voix
            # (« Donne-moi seulement de t'aimer » : trois portées de couplets, puis S+A et T+B)
            return [(system[-2], ["Soprano", "Alto"]), (system[-1], ["Ténor", "Basse"])]
        return [(s, [NAMES[i]]) for i, s in enumerate(system[-4:])]
    if k == 3 and VOICE_COUNT:
        # trois portées sans noms : voix comptées sur chaque portée (deux si elle porte des accords) ; quatre en tout
        # → soprano, alto, ténor, basse dans l'ordre (« Devant toi » : S+A, ténor seul en clé de sol, basse)
        counts = [2 if two_voiced(s) else 1 for s in system]
        if sum(counts) == 4:
            plan, names = [], list(NAMES)
            for s, c in zip(system, counts):
                plan.append((s, names[:c]))
                names = names[c:]
            return plan
    if k in (2, 3) and VOICE_CLEFS:
        counts = [2 if two_voiced(s) else 1 for s in system]
        clefs_ = [s["clefs"][0][1] if s["clefs"] else ("G", 0) for s in system]
        if k == 2 and counts == [2, 1] and clefs_[0][0] == "G" and clefs_[1][0] == "F":
            # soprano et alto sur la portée de sol, basse seule sur la portée de fa : pas de ténor recopié
            return [(system[0], ["Soprano", "Alto"]), (system[1], ["Basse"])]
        if all(c == 1 for c in counts):
            # une voix par portée : chaque portée reçoit un seul nom, d'après sa clé (une portée sans
            # accords recopiée en soprano et alto, puis en ténor et basse : « Marie, tendresse dans nos vies »)
            plan, high, low = [], ["Soprano", "Alto"], ["Ténor", "Basse"]
            bass_left = sum(1 for s in system if s["clefs"] and s["clefs"][0][1][0] == "F")
            for s, c in zip(system, counts):
                cl = s["clefs"][0][1] if s["clefs"] else ("G", 0)
                if cl[0] == "F":
                    bass_left -= 1
                    names = low[:] if c == 2 else (["Ténor"] if bass_left > 0 else ["Basse"])
                    low = [n for n in low if n not in names]
                elif cl == ("G", -1):
                    names = ["Ténor"]
                else:
                    names = high[:c] if high else []
                    high = high[c:]
                names = [n for n in names if not any(n in q for _s, q in plan)]
                if names:
                    plan.append((s, names))
            return plan
    if k in (2, 3):
        return [(system[-2], ["Soprano", "Alto"]), (system[-1], ["Ténor", "Basse"])]
    s = system[0]
    return [(s, ["Soprano", "Alto"] if chordal(s) else ["Soprano"])]


HOLD = os.environ.get("PUPITRE_UNISSON_TENUE", "1") != "0"
STEMLESS = os.environ.get("PUPITRE_RONDES_VOIX", "1") != "0"  # ronde seule : à quelle voix ?


def split_voices(staff, names, cuts=()):
    """Événements de chaque voix de la portée, triés par x : (x, durée, [notes] ou None pour un silence).
    cuts : barres de mesure du système (abscisses), pour suivre le temps de chaque voix dans la mesure."""
    notes = sorted(staff["notes"], key=lambda n: (round(n["x"], 1), -n["midi"]))
    if STEMLESS and len(names) == 2:
        # unisson de deux voix en rondes (ou brèves) : le graveur dessine les deux têtes côte à côte ; une seule note
        # chantée par les deux voix (« Avec toi Seigneur » m. 28, Psaume 84 m. 13 : ténor et basse comptés 8 temps
        # au lieu de 4, 18 au lieu de 10)
        kept = []
        for n in notes:
            twin = next((k for k in kept if k["midi"] == n["midi"] and k["dur"] == n["dur"]
                         and not (k["up"] or k["down"] or n["up"] or n["down"])
                         and 0 < n["x"] - k["x"] < 2.5 * staff["sp"]
                         and not any(k["x"] < c < n["x"] for c in cuts)), None)
            if twin is None:
                kept.append(n)
        notes = kept
    onsets = []
    for n in notes:
        if onsets and abs(onsets[-1][0]["x"] - n["x"]) < 1.0:
            onsets[-1].append(n)
        else:
            onsets.append([n])
    out = {name: [] for name in names}
    if len(names) == 1:
        for g in onsets:
            out[names[0]].append((g[0]["x"], min(n["dur"] for n in g), g))
        for r in staff["rests"]:
            out[names[0]].append((r["x"], r["dur"], None))
        return out
    two_stems = any(any(n["up"] and not n["down"] for n in g) and any(n["down"] and not n["up"] for n in g) for g in onsets)
    sp = staff["sp"]

    def rest_target(r):
        # silence au-dessus du milieu : voix du haut ; au-dessous : voix du bas
        return names[0] if r["y"] > staff["mid"] + 0.3 * sp else names[1] if r["y"] < staff["mid"] - 0.3 * sp else None

    # temps de chaque voix depuis la dernière barre : une tête seule n'est un unisson que si l'autre voix ne tient pas
    # encore sa note (« Avec toi Seigneur » : note de l'alto pendant la ronde de la soprano ; Psaume 118 : croche de la
    # basse pendant la noire du ténor)
    items = [(g[0]["x"], 0, g) for g in onsets] + [(r["x"], 1, r) for r in staff["rests"]]
    items.sort(key=lambda t: (t[0], t[1]))
    clock = {name: Fraction(0) for name in names}
    rests = {name: [] for name in names}
    bar_i = 0
    for x, kind, it in items:
        while bar_i < len(cuts) and x >= cuts[bar_i]:
            bar_i += 1
            clock = {name: Fraction(0) for name in names}
        if kind == 1:
            target = rest_target(it)
            busy = target is None and any(abs(g[0]["x"] - it["x"]) < 0.8 * sp for g in onsets)
            for name in ([target] if target else names):
                rests[name].append(it)
                if not busy:
                    clock[name] += it["dur"]
            continue
        g = it
        ups = [n for n in g if n["up"] and not n["down"]]
        downs = [n for n in g if n["down"] and not n["up"]]
        if not two_stems or (len(g) >= 2 and (not ups or not downs)) or (not ups and not downs):
            srt = sorted(g, key=lambda n: -n["midi"])
            hi, lo = [srt[0]], [srt[-1]]
            if STEMLESS and two_stems and len(g) == 1 and not ups and not downs:
                # tête sans queue (ronde) seule à sa place, sur une portée à deux voix : elle n'est à l'unisson que si
                # l'autre voix n'a ni silence écrit ni note à elle au même endroit (« Seigneur, c'est vers toi » : ronde
                # de la basse sous le soupir du ténor, donnée aux deux voix, le ténor décalé de 4 temps ; ronde du ténor
                # à côté de la noire de la basse : la basse recopiait toute la ligne du ténor)
                h0 = g[0]
                near = [r for r in staff["rests"] if abs(r["x"] - h0["x"]) < 1.5 * sp and rest_target(r)]
                partner = [m for m in staff["notes"] if m is not h0 and abs(m["x"] - h0["x"]) < 1.5 * sp
                           and m["up"] != m["down"]]
                if near:
                    if rest_target(near[0]) == names[0]:
                        hi = None
                    else:
                        lo = None
                elif partner:
                    p0 = min(partner, key=lambda m: abs(m["x"] - h0["x"]))
                    if p0["down"] and h0["midi"] >= p0["midi"]:
                        lo = None
                    elif p0["up"] and h0["midi"] <= p0["midi"]:
                        hi = None
        else:
            hi, lo = ups or None, downs or None
            if len(g) == 1:
                h0 = g[0]
                other = [m for m in staff["notes"] if m is not h0 and abs(m["x"] - h0["x"]) < 3 * sp
                         and ((m["down"] if h0["up"] else m["up"])
                              or (STEMLESS and not m["up"] and not m["down"] and abs(m["x"] - h0["x"]) < 1.5 * sp))]
                mine, theirs = (names[0], names[1]) if h0["up"] else (names[1], names[0])
                holding = HOLD and clock[theirs] > clock[mine]
                if not other and not holding and not any(abs(r["x"] - h0["x"]) < 1.5 * sp for r in staff["rests"]):
                    hi = lo = [h0]
        for name, grp in ((names[0], hi), (names[1], lo)):
            if grp:
                d = min(n.get("dur_down", n["dur"]) if name == names[1] else n["dur"] for n in grp)
                out[name].append((g[0]["x"], d, grp))
                clock[name] += d
    for name in names:  # silence écrit là où la voix a déjà une note : l'autre voix
        sounding = [e[0] for e in out[name]]
        out[name] += [(r["x"], r["dur"], None) for r in rests[name] if not any(abs(x - r["x"]) < 0.8 * sp for x in sounding)]
    return out


def build(systems):
    from music21 import clef as m21clef, key as m21key, meter, note, chord, stream, tie, metadata
    time_sig = next((s["time"] for sy in systems for s in sy if s["time"]), (4, 4))
    fifths = next((s["fifths"] for sy in systems for s in sy), 0)
    bar = Fraction(4 * time_sig[0], time_sig[1])
    voices = {n: [] for n in NAMES}  # mesures de chaque voix : [[événements]]
    clefs = {}
    for system in systems:
        # barres vues sur au moins la moitié des portées du système (une queue qui couvre une portée n'en est pas une)
        sp0 = system[0]["sp"]
        cand = sorted(c for s in system for c in s["cuts"])
        cuts = []
        for c in cand:
            if cuts and c - cuts[-1] < 1.5 * sp0:
                continue
            votes = sum(1 for s in system if any(abs(c - d) < 1.5 * sp0 for d in s["cuts"]))
            if votes >= max(1, (len(system) + 1) // 2):
                cuts.append(c)
        xs = [e["x"] for s in system for e in s["notes"] + s["rests"]]
        kept, prev = [], -1e9
        for c in cuts:
            if any(prev < x < c for x in xs):
                kept.append(c)
                prev = c
        cuts = kept
        n_meas = max(1, len(cuts))
        seen = set()
        for staff, names in plan_of(system):
            ev = split_voices(staff, names, cuts)
            for name in names:
                seen.add(name)
                cl = staff["clefs"][0][1] if staff["clefs"] else ("G", 0)
                # ténor seul sur une portée en clé de sol sans « 8 » : écrit une octave plus haut qu'il ne sonne
                low = TENOR_8 and name == "Ténor" and len(names) == 1 and cl == ("G", 0)
                clefs.setdefault(name, ("G", -1) if low else cl)
                meas = [[] for _ in range(n_meas)]
                for e in sorted(ev[name], key=lambda e: e[0]):
                    if low and e[2]:
                        e = (e[0], e[1], [dict(n_, midi=n_["midi"] - 12) for n_ in e[2]])
                    k = next((i for i, c in enumerate(cuts) if e[0] < c), n_meas - 1)
                    meas[min(k, n_meas - 1)].append(e)
                if BAR_REST:
                    # pause seule dans sa mesure : elle vaut la mesure, quelle que soit la mesure (2/4, 6/8…)
                    meas = [[(m[0][0], bar, None)] if len(m) == 1 and m[0][2] is None and m[0][1] == 4 and bar != 4 else m
                            for m in meas]
                voices[name] += meas
        for name in NAMES:
            if name not in seen:
                voices[name] += [[] for _ in range(n_meas)]  # portée masquée : la voix se tait
    score = stream.Score()
    score.insert(0, metadata.Metadata(title=""))
    total = max(len(m) for m in voices.values())
    for name in NAMES:
        if not any(voices[name]):
            continue
        part = stream.Part()
        part.partName = name
        cl = clefs.get(name, ("G", 0))
        for i in range(total):
            m = stream.Measure(number=i + 1)
            if i == 0:
                m.append({"G": m21clef.Treble8vbClef() if cl[1] < 0 else m21clef.TrebleClef(), "F": m21clef.BassClef(),
                          "C": m21clef.AltoClef()}[cl[0]])
                m.append(m21key.KeySignature(fifths))
                m.append(meter.TimeSignature(f"{time_sig[0]}/{time_sig[1]}"))
            evs = voices[name][i] if i < len(voices[name]) else []
            at = Fraction(0)
            for _x, dur, group in evs:
                q = float(dur)
                if group is None:
                    el = note.Rest(quarterLength=q)
                elif len(group) == 1:
                    el = note.Note(midi=group[0]["midi"], quarterLength=q)
                else:
                    el = chord.Chord([n_["midi"] for n_ in group], quarterLength=q)
                if group is not None and all(n_["tie"] for n_ in group):
                    el.tie = tie.Tie("stop")
                m.insert(float(at), el)
                at += dur
            if not evs:
                m.insert(0, note.Rest(quarterLength=float(bar)))
            part.append(m)
        # liaisons : la note qui précède une note liée commence la liaison
        prev = None
        for el in part.recurse().notes:
            if el.tie is not None and el.tie.type == "stop" and prev is not None:
                prev.tie = tie.Tie("start" if prev.tie is None else "continue")
            prev = el
        score.append(part)
    return score


def main(src, out):
    systems = read_pdf(src)
    n = sum(len(s["notes"]) for sy in systems for s in sy)
    if not systems or n < 8:
        sys.exit(2)
    score = build(systems)
    score.write("musicxml", fp=str(out), makeNotation=False)
    print(f"PDF gravé lu directement : {len(systems)} systèmes, {n} notes", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
