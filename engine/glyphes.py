"""
Symboles d'un PDF gravé reconnus par leur dessin, quand les codes de la police ne disent rien : LilyPond (Emmentaler,
codes propres à chaque fichier), Finale et Sibelius recodés (Maestro, Toccata : codes Latin-1 ou numéros de glyphes),
Encore (Anastasia : portées, queues et barres dessinées comme des caractères), polices TrueType renumérotées.

La page est rendue sans ses tracés (lignes, queues, ligatures, liaisons) : chaque caractère y est seul. On le découpe
à sa place (boîte du caractère donnée par le PDF) et on le reconnaît :
  - têtes : environ un interligne de haut, plus larges que hautes ; pleines (noires) ou creuses (blanches, rondes :
    la ronde se reconnaît ensuite à l'absence de queue) — même en parallélogramme (Toccata) ;
  - points : petits et ronds ;
  - traits : lignes de portée, lignes supplémentaires, queues et barres dessinées en caractères (Encore), recollés
    bout à bout et rendus comme des tracés ;
  - les autres (clés, altérations, crochets, silences, chiffres de la mesure) par comparaison au dessin de la police
    Bravura (SMuFL) ramené à la même taille, avec des dessins à écarter (nuances, points d'orgue, ornements).
Les caractères d'une même police, d'un même code et d'une même taille sont le même symbole : on vote entre eux (un
caractère touché par un voisin dans le rendu ne fausse pas la décision).
Une police est musicale si une bonne part de ses caractères sont des symboles reconnus (les paroles et les titres
ne le sont pas).
"""
import collections, ctypes, math

import cv2
import numpy as np
import pypdfium2.raw as raw
from PIL import Image, ImageDraw, ImageFont

SCALE = 6.0      # pixels par point au rendu de la page
GRID = 24        # taille du dessin comparé
TEXT_FONTS = ("Times", "Century", "Helvetica", "Arial", "Calibri", "Frutiger", "Castellar", "Centaur", "Tahoma",
              "Lucida", "Myriad", "Garamond", "Georgia", "Verdana", "Cambria", "Palatino", "Bookman", "Courier",
              "Futura", "Gill", "Optima", "Book", "Segoe", "Trebuchet", "Comic", "Impact", "Candara", "Corbel")

# dessins de référence (codes SMuFL de Bravura) ; None : symbole à écarter
REFERENCE = {
    0xE050: 0xE050, 0xE052: 0xE052, 0xE062: 0xE062, 0xE05C: 0xE05C,
    0xE262: 0xE262, 0xE260: 0xE260, 0xE261: 0xE261, 0xE263: 0xE263, 0xE264: 0xE264,
    0xE240: 0xE240, 0xE241: 0xE241, 0xE242: 0xE242, 0xE243: 0xE243, 0xE244: 0xE244, 0xE245: 0xE245,
    0xE4E5: 0xE4E5, 0xE4E6: 0xE4E6, 0xE4E7: 0xE4E7, 0xE4E8: 0xE4E8,
    **{0xE080 + k: 0xE080 + k for k in range(10)}, 0xE08A: 0xE08A, 0xE08B: 0xE08B,
    # à écarter : nuances, points d'orgue, ornements, signes de reprise, respirations
    0xE520: None, 0xE521: None, 0xE522: None, 0xE523: None, 0xE524: None, 0xE525: None, 0xE526: None,
    0xE4C0: None, 0xE4C1: None, 0xE566: None, 0xE567: None, 0xE56C: None, 0xE56D: None, 0xE047: None,
    0xE048: None, 0xE4CE: None, 0xE4A0: None, 0xE4AC: None, 0xE045: None, 0xE046: None, 0xE4D1: None,
}
RECT_REST = 0xE4E3
OUTLINES = __import__("os").environ.get("PUPITRE_PDF_CONTOURS", "1") != "0"  # pause ou demi-pause : décidée d'après sa place contre une ligne de la portée


def _bravura():
    try:
        from pupitres import _music_font
        path = _music_font()
    except Exception:  # noqa: BLE001
        path = None
    return ImageFont.truetype(str(path), 64) if path else None  # 64 px l'em : 16 px l'interligne


def _norm(mask):
    """Dessin ramené à GRID × GRID, centré, normalisé (corrélation)."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    m = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1].astype(np.float32)
    m = cv2.resize(m, (GRID, GRID), interpolation=cv2.INTER_AREA)
    m = cv2.GaussianBlur(m, (3, 3), 0)
    m = m - m.mean()
    n = np.linalg.norm(m)
    return m / n if n else None


_TEMPLATES = None


def templates():
    """(code de sortie, dessin, hauteur en interlignes, largeur / hauteur, ancre : place de la note sur le dessin,
    en part de la hauteur depuis le bas)."""
    global _TEMPLATES
    if _TEMPLATES is not None:
        return _TEMPLATES
    font = _bravura()
    out = []
    if font is not None:
        for code, label in REFERENCE.items():
            l, t, r, b = font.getbbox(chr(code), anchor="ls")
            if r - l < 2 or b - t < 2:
                continue
            im = Image.new("L", (r - l + 8, b - t + 8), 0)
            ImageDraw.Draw(im).text((4 - l, 4 - t), chr(code), font=font, fill=255, anchor="ls")
            mask = np.array(im) > 127
            d = _norm(mask)
            if d is not None:
                h = (b - t) / 16
                out.append((label, d, h, (r - l) / (b - t), b / (b - t)))
    _TEMPLATES = out
    return out


def _holes(mask):
    pad = np.pad(~mask, 1, constant_values=True).astype(np.uint8)
    n, lab = cv2.connectedComponents(pad, connectivity=4)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    sizes = collections.Counter(lab[lab > 0].ravel())
    return sum(1 for k, s in sizes.items() if k not in border and s >= 4)


def _runs(flags):
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            out.append((start, i - 1))
            start = None
    return out


def classify(mask, h, w):
    """Classe d'un caractère découpé (mask : encre), h et w en interlignes. Renvoie (classe, détail)."""
    if mask.sum() == 0:
        return ("vide", None)
    ink = mask.mean()
    H, W = mask.shape
    rows = mask.mean(axis=1)
    cols = mask.mean(axis=0)
    # portée dessinée en caractère : cinq lignes pleines, à égale distance
    full = _runs(rows >= 0.85)
    if len(full) == 5 and h > 2.5 and w >= 0.8:
        mids = [(a + b) / 2 for a, b in full]
        gaps = np.diff(mids)
        if gaps.min() > 0.8 * gaps.mean():
            return ("portee", [((a + b) / 2 / H) for a, b in full])
    # traits seuls : horizontal (ligne supplémentaire, morceau de ligne) ou vertical (queue, barre)
    if h <= 0.4 and w >= 0.6 and ink >= 0.6:
        return ("hbar", None)
    vcols = _runs(cols >= 0.9)
    if w <= 0.45 and h >= 0.6 and ink >= 0.6 and vcols:
        return ("vbar", [((a + b) / 2 / W) for a, b in vcols])
    if h >= 2.5 and vcols and sum(mask[:, a:b + 1].sum() for a, b in vcols) >= 0.85 * mask.sum():
        return ("vbar", [((a + b) / 2 / W) for a, b in vcols])  # double barre, barre épaisse (pas un dièse)
    holes = _holes(mask)
    # têtes de note
    if 0.65 <= h <= 1.5 and 0.85 <= w <= 2.4 and 0.85 <= w / h <= 2.6:
        if holes == 0 and ink >= 0.3:  # 0,3 : tête en parallélogramme (Toccata, 0,36)
            return ("noire", None)
        if holes == 1 and ink < 0.8:  # deux trous : le « 8 » d'une clé de ténor
            return ("creuse", None)
    # point (durée, staccato)
    if 0.2 <= h <= 0.7 and 0.2 <= w <= 0.7 and 0.65 <= w / h <= 1.5 and holes == 0 and ink >= 0.5:
        return ("point", None)
    # pause, demi-pause : rectangle plein
    if 0.3 <= h <= 0.8 and 0.8 <= w <= 1.8 and ink >= 0.85:
        return ("rect", None)
    d = _norm(mask)
    if d is None:
        return ("vide", None)
    best, score = None, -9
    for label, td, th, ta, anchor in templates():
        corr = float((d * td).sum())
        s = corr - 0.35 * abs(math.log((w / h) / ta)) - 0.3 * max(0.0, abs(math.log(h / th)) - math.log(1.4))
        if s > score:
            best, score = (label, anchor, corr), s
    if best is None or score < 0.5 or best[2] < 0.6:
        return ("inconnu", None)
    if best[0] is None:
        return ("ecarte", None)
    return ("signe", (best[0], best[1]))


def _hide_paths(handles):
    for obj in handles:
        t = raw.FPDFPageObj_GetType(obj)
        if t == raw.FPDF_PAGEOBJ_FORM:
            _hide_paths([raw.FPDFFormObj_GetObject(obj, k) for k in range(raw.FPDFFormObj_CountObjects(obj))])
        elif t != raw.FPDF_PAGEOBJ_TEXT:
            raw.FPDFPageObj_SetFillColor(obj, 255, 255, 255, 0)
            raw.FPDFPageObj_SetStrokeColor(obj, 255, 255, 255, 0)


def _font(tp, i, buf=ctypes.create_string_buffer(256), flags=ctypes.c_int()):
    raw.FPDFText_GetFontInfo(tp, i, buf, 256, ctypes.byref(flags))
    return buf.value.decode("latin1", "ignore").split("+")[-1]


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


def _doubles(page, tp):
    """Caractères identiques au précédent qui le chevauchent, écartés par la page de texte de pdfium (« faux gras ») :
    la seconde tête d'un accord (Toccata, MuseScore 1 et 2). On les reprend des objets du PDF : objet de texte vide,
    juste après un objet d'un seul caractère, au même x, de même taille, de la même police."""
    out, recent = [], []
    for k in range(raw.FPDFPage_CountObjects(page.raw)):
        obj = raw.FPDFPage_GetObject(page.raw, k)
        if raw.FPDFPageObj_GetType(obj) != raw.FPDF_PAGEOBJ_TEXT:
            continue
        txt = _obj_text(obj, tp).strip()
        l, b, r, t = (ctypes.c_float(), ctypes.c_float(), ctypes.c_float(), ctypes.c_float())
        raw.FPDFPageObj_GetBounds(obj, ctypes.byref(l), ctypes.byref(b), ctypes.byref(r), ctypes.byref(t))
        box = (l.value, b.value, r.value, t.value)
        font = _obj_font(obj)
        if txt:
            if len(txt) == 1:
                recent = (recent + [(txt, box, font)])[-6:]  # un point peut s'intercaler entre les deux têtes
            continue
        for ch, p, f in reversed(recent):
            if f == font and abs(box[0] - p[0]) < 0.5 and abs((box[2] - box[0]) - (p[2] - p[0])) < 0.1 \
                    and abs((box[3] - box[1]) - (p[3] - p[1])) < 0.1 and 0 < abs(box[1] - p[1]) < 2 * (p[3] - p[1]):
                out.append(dict(i=-1, u=ord(ch), font=font, l=box[0], b=box[1], r=box[2], t=box[3]))
                break
    return out


def _outline(font, u):
    """Contours d'un caractère d'après sa police (courbes aplaties), en unités du caractère ; [] si inconnu."""
    gp = raw.FPDFFont_GetGlyphPath(font, u, ctypes.c_float(100.0))
    if not gp:
        return []
    x, y = ctypes.c_float(), ctypes.c_float()
    contours, cur, pend = [], [], []
    for k in range(raw.FPDFGlyphPath_CountGlyphSegments(gp)):
        seg = raw.FPDFGlyphPath_GetGlyphPathSegment(gp, k)
        raw.FPDFPathSegment_GetPoint(seg, ctypes.byref(x), ctypes.byref(y))
        t, p = raw.FPDFPathSegment_GetType(seg), (x.value, y.value)
        if t == raw.FPDF_SEGMENT_MOVETO:
            if len(cur) > 2:
                contours.append(cur)
            cur, pend = [p], []
        elif t == raw.FPDF_SEGMENT_BEZIERTO:
            pend.append(p)
            if len(pend) == 3 and cur:
                p0, (c1, c2, p3) = cur[-1], pend
                for k2 in range(1, 7):
                    s_ = k2 / 6
                    a, b_, c, d = (1 - s_) ** 3, 3 * s_ * (1 - s_) ** 2, 3 * s_ ** 2 * (1 - s_), s_ ** 3
                    cur.append((a * p0[0] + b_ * c1[0] + c * c2[0] + d * p3[0], a * p0[1] + b_ * c1[1] + c * c2[1] + d * p3[1]))
                pend = []
        else:
            cur.append(p)
        if raw.FPDFPathSegment_GetClose(seg) and len(cur) > 2:
            contours.append(cur)
            cur = []
    if len(cur) > 2:
        contours.append(cur)
    return contours


def _raster(contours, width, height):
    """Contours dessinés dans un cadre width × height pixels (règle pair-impair)."""
    xs = [p[0] for c in contours for p in c]
    ys = [p[1] for c in contours for p in c]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    if x1 - x0 <= 0 or y1 - y0 <= 0:
        return None
    sx, sy = (width - 1) / (x1 - x0), (height - 1) / (y1 - y0)
    acc = np.zeros((height, width), bool)
    for c in contours:
        im = Image.new("1", (width, height), 0)
        ImageDraw.Draw(im).polygon([((q[0] - x0) * sx, (y1 - q[1]) * sy) for q in c], fill=1)
        acc ^= np.array(im, bool)
    return acc


def _merge(segs, horizontal):
    """Morceaux de traits (caractères mis bout à bout) recollés."""
    if horizontal:
        segs = sorted(segs, key=lambda s: (round(s[1] * 4), s[0]))
        out = []
        for s in segs:
            if out and abs(out[-1][1] - s[1]) < 0.3 and s[0] <= out[-1][2] + 1.0:
                p = out[-1]
                out[-1] = (p[0], p[1], max(p[2], s[2]), p[3])
            else:
                out.append(s)
        return out
    segs = sorted(segs, key=lambda s: (round(s[0] * 4), s[1]))
    out = []
    for s in segs:
        if out and abs(out[-1][0] - s[0]) < 0.35 and s[1] <= out[-1][3] + 1.0:
            p = out[-1]
            out[-1] = (p[0], p[1], p[2], max(p[3], s[3]))
        else:
            out.append(s)
    return out


def read_page(page, sp=None):
    """Symboles de la page reconnus par leur dessin : (signes au format de pdf_vectoriel.glyphs, traits horizontaux,
    traits verticaux, morceaux de ligature). sp : interligne en points, s'il est connu par les tracés. La page est
    modifiée en mémoire (tracés rendus invisibles) : en donner une copie."""
    tp = page.get_textpage()
    n = tp.count_chars()
    chars = []
    for i in range(n):
        u = raw.FPDFText_GetUnicode(tp, i)
        if u in (9, 10, 13, 32, 0xA0, 0xFFFE):
            continue
        l, b, r, t = tp.get_charbox(i)
        if r - l <= 0.05 or t - b <= 0.05:
            continue
        chars.append(dict(i=i, u=u, font=_font(tp, i), l=l, b=b, r=r, t=t))
    chars += _doubles(page, tp)
    if not chars:
        return [], [], [], []
    _hide_paths([raw.FPDFPage_GetObject(page.raw, k) for k in range(raw.FPDFPage_CountObjects(page.raw))])
    W, H = page.get_size()
    img = np.array(page.render(scale=SCALE, may_draw_forms=False).to_pil().convert("L")) < 140
    shapes = {}
    for c in chars:
        x0, x1 = int(math.floor(c["l"] * SCALE)), int(math.ceil(c["r"] * SCALE))
        y0, y1 = int(math.floor((H - c["t"]) * SCALE)), int(math.ceil((H - c["b"]) * SCALE))
        crop = img[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
        c["mask"] = crop
        # dessin du caractère seul, d'après sa police : la découpe de la page peut ramasser un voisin (tête collée
        # à un crochet). Gardé si ses proportions sont celles de la boîte du caractère (sinon le code ne désigne
        # pas le bon dessin : polices dont plusieurs caractères ont le même code)
        if OUTLINES and c["i"] >= 0 and crop.size:
            key = (c["font"], c["u"])
            if key not in shapes:
                obj = raw.FPDFText_GetTextObject(tp, c["i"])
                shapes[key] = _outline(raw.FPDFTextObj_GetFont(obj), c["u"]) if obj else []
            cs = shapes[key]
            if cs:
                xs = [q[0] for cc in cs for q in cc]
                ys = [q[1] for cc in cs for q in cc]
                ow, oh = max(xs) - min(xs), max(ys) - min(ys)
                bw, bh = c["r"] - c["l"], c["t"] - c["b"]
                if ow > 0 and oh > 0 and abs(math.log((ow / oh) / (bw / bh))) < 0.15:
                    m = _raster(cs, crop.shape[1], crop.shape[0])
                    if m is not None and m.any():
                        c["mask"] = m
    music = [c for c in chars if not c["font"].startswith(TEXT_FONTS)]
    if sp is None:
        sp = _guess_sp(music)
    if not sp:
        return [], [], [], []
    for c in music:
        c["cls"] = classify(c["mask"], (c["t"] - c["b"]) / sp, (c["r"] - c["l"]) / sp)
    # seconde découpe des caractères non reconnus : têtes, points et signes voisins déjà reconnus effacés (la boîte
    # d'un crochet de queue descendante couvre la tête de sa note)
    done = [c for c in music if c["cls"][0] in ("noire", "creuse", "point", "signe")]
    for c in music:
        if c["cls"][0] != "inconnu" or not c["mask"].size:
            continue
        m = c["mask"].copy()
        hh, ww = m.shape
        for o in done:
            if o is c or o["r"] <= c["l"] or o["l"] >= c["r"] or o["t"] <= c["b"] or o["b"] >= c["t"]:
                continue
            ox0 = max(0, int(math.floor((o["l"] - c["l"]) * SCALE)) - 1)
            ox1 = min(ww, int(math.ceil((o["r"] - c["l"]) * SCALE)) + 1)
            oy0 = max(0, int(math.floor((c["t"] - o["t"]) * SCALE)) - 1)
            oy1 = min(hh, int(math.ceil((c["t"] - o["b"]) * SCALE)) + 1)
            m[oy0:oy1, ox0:ox1] = False
        if m.any() and not np.array_equal(m, c["mask"]):
            ys, xs = np.nonzero(m)
            m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            cls = classify(m, m.shape[0] / SCALE / sp, m.shape[1] / SCALE / sp)
            if cls[0] == "signe":
                c["cls"] = cls
    # vote par police, code et taille
    groups = collections.defaultdict(list)
    for c in music:
        groups[(c["font"], c["u"], round((c["r"] - c["l"]) * 4), round((c["t"] - c["b"]) * 4))].append(c)
    for g in groups.values():
        votes = collections.Counter((c["cls"][0], c["cls"][1][0] if c["cls"][0] == "signe" else None) for c in g)
        (kind, code), k = votes.most_common(1)[0]
        if k >= 0.5 * len(g) and kind not in ("portee", "vbar", "hbar"):
            model = next(c["cls"] for c in g if (c["cls"][0], c["cls"][1][0] if c["cls"][0] == "signe" else None) == (kind, code))
            for c in g:
                c["cls"] = model
    # polices musicales : une bonne part de symboles reconnus, ou une clé
    useful = ("portee", "hbar", "vbar", "noire", "creuse", "point", "rect", "signe", "ecarte")
    by_font = collections.defaultdict(list)
    for c in music:
        by_font[c["font"]].append(c)
    keep = []
    for font, cs in by_font.items():
        rec = sum(1 for c in cs if c["cls"][0] in useful)
        clef = any(c["cls"][0] == "signe" and c["cls"][1][0] in (0xE050, 0xE062, 0xE05C, 0xE052) for c in cs)
        heads = sum(1 for c in cs if c["cls"][0] in ("noire", "creuse"))
        # une police musicale a deux ou trois dessins de têtes ; des lettres grasses (noms des auteurs) en donnent
        # une dizaine (« Songo Soalla » : « Davy Hermann TAPSOBA » lu en notes)
        if len({c["u"] for c in cs if c["cls"][0] in ("noire", "creuse")}) > 4:
            continue
        if (rec >= 0.6 * len(cs) and heads) or (clef and rec >= 0.4 * len(cs)):
            keep += cs
    glyphs, hor, ver, beams = [], [], [], []
    for c in keep:
        kind, detail = c["cls"]
        l, b, r, t = c["l"], c["b"], c["r"], c["t"]
        base = dict(left=l, right=r, bottom=b, top=t, size=t - b, x=l, y=(b + t) / 2)
        if kind == "portee":
            for f in detail:
                hor.append((l, t - f * (t - b), r, t - f * (t - b)))
        elif kind == "hbar":
            hor.append((l, (b + t) / 2, r, (b + t) / 2))
        elif kind == "vbar":
            for f in detail:
                x = l + f * (r - l)
                ver.append((x, b, x, t))
        elif kind == "noire":
            glyphs.append(dict(base, code=0xE0A4))
        elif kind == "creuse":
            glyphs.append(dict(base, code=0xE0A3, hollow=True))
        elif kind == "point":
            glyphs.append(dict(base, code=0xE1E7))
        elif kind == "rect":
            glyphs.append(dict(base, code=RECT_REST, rect=True))
        elif kind == "signe":
            code, anchor = detail
            glyphs.append(dict(base, code=code, y=b + anchor * (t - b)))
        elif kind == "inconnu" and c["font"] in by_font and (t - b) / sp <= 1.6 and (r - l) / sp >= 0.8:
            beams.append((l, b, r, t, False))  # morceau de ligature dessiné en caractère (Encore)
    # même signe deux fois au même endroit (caractère repris des objets et aussi lu par la page de texte) : un seul
    uniq = []
    for g in sorted(glyphs, key=lambda g: (g["code"], round(g["x"]), round(g["y"]))):
        if not any(u["code"] == g["code"] and abs(u["x"] - g["x"]) < 0.3 and abs(u["y"] - g["y"]) < 0.3 for u in uniq[-4:]):
            uniq.append(g)
    return uniq, _merge(hor, True), _merge(ver, False), beams


def _guess_sp(chars):
    """Interligne d'après les caractères : portées dessinées en caractères, sinon hauteur des têtes les plus
    fréquentes (environ un interligne)."""
    for c in chars:
        m = c["mask"]
        if m.size and m.shape[0] > 10:
            full = _runs(m.mean(axis=1) >= 0.85)
            if len(full) == 5:
                mids = [(a + b) / 2 for a, b in full]
                gap = float(np.mean(np.diff(mids))) / SCALE
                if gap > 2:
                    return gap
    sizes = collections.Counter()
    for c in chars:
        h, w = c["t"] - c["b"], c["r"] - c["l"]
        m = c["mask"]
        if h > 2 and 1.0 <= w / h <= 2.2 and m.size and m.mean() >= 0.5 and _holes(m) == 0:
            sizes[round(h * 2) / 2] += 1
    if not sizes:
        return None
    return sizes.most_common(1)[0][0]
