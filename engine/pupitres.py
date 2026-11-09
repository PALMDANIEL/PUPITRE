"""
Disposition déclarée : chœur à quatre voix, une portée par voix (Soprano, Alto, Ténor, Basse, de haut en bas).

Photocopie usée : barres de mesure et accolades coupées entre les portées, clés à moitié effacées, dernière
portée pâlie. Audiveris prend alors chaque portée pour un système à elle seule et mélange les voix.
Quand on sait que chaque système compte quatre portées dans l'ordre S, A, T, B :
 1. on repère les portées de chaque page ; une portée trop pâle pour être vue est cherchée là où elle doit être
    (même écart que dans les autres systèmes), puis ses lignes sont retracées (copie nettoyée) ;
 2. on découpe chaque portée avec ses paroles et on refait une page par voix (toutes les lignes de soprano
    l'une sous l'autre…), barres de mesure ramenées à la hauteur de la portée : Audiveris la lit comme une
    partie seule et garde d'une ligne à l'autre la clé et la mesure de la première ;
 3. on remet les voix ensemble système par système, et mesure par mesure quand les barres sont lues (une erreur
    de rythme reste dans sa mesure au lieu de décaler la suite), avec la clé de chaque voix et son nom.

Usage (assemblage, après Audiveris) : python3 pupitres.py <sortie.musicxml> <disposition.json> <voix.mxl> …
  [--notes v1.musicxml v2.musicxml v3.musicxml v4.musicxml] : notes lues par homr (une page par voix),
  paroles prises dans la lecture d'Audiveris.
"""
import copy, json, pathlib, statistics, sys

import cv2
import numpy as np

import imgio

# (nom, clé) de chaque portée d'un système, de haut en bas
LAYOUTS = {
    # quatre portées par système, une par voix
    "satb": [("Soprano", "G"), ("Alto", "G"), ("Ténor", "G8"), ("Basse", "F")],
    # écriture serrée : soprano et alto sur la portée de sol, ténor et basse sur celle de fa (deux voix par portée,
    # lues en accords et séparées par render.py) ; une portée instrumentale au-dessus (contrechant) est laissée de côté
    "grand": [("", "G"), ("", "F")],
}


# ---------------------------------------------------------------------------------------------------------------
# 1. Portées de chaque page

def find_staves(bw):
    """Portées d'une page nettoyée, de haut en bas : [(haut, bas, gauche, droite)] (lignes 1 et 5)."""
    from preprocess import line_strokes, staff_chains
    _thin, chains = staff_chains(bw, thin=line_strokes(bw))
    staves = []
    for chain in chains:
        if len(chain) < 2:
            continue
        top = float(np.median([st[0][0] for _a, _b, st in chain]))
        bottom = float(np.median([st[4][0] for _a, _b, st in chain]))
        staves.append([top, bottom, chain[0][0], chain[-1][1]])
    staves.sort()
    out = []
    for s in staves:  # deux chaînes pour la même portée (coupée au milieu) : réunies
        if out and s[0] - out[-1][0] < (out[-1][1] - out[-1][0]) / 2:
            out[-1][2], out[-1][3] = min(out[-1][2], s[2]), max(out[-1][3], s[3])
        else:
            out.append(s)
    return [tuple(s) for s in out]


def _search(bw, y, height, x0, x1):
    """
    Portée très pâle attendue vers y : on y pose un gabarit de 5 lignes à l'écart connu et on garde la position où
    les 5 lignes ont le plus d'encre (chacune doit en avoir un peu : pas une simple ligne de paroles).
    """
    from preprocess import line_strokes
    sp = height / 4
    lo, hi = max(0, int(y - 3 * sp)), min(bw.shape[0], int(y + height + 3 * sp))
    prof = line_strokes(bw[lo:hi, x0:x1]).sum(1) / max(1, x1 - x0)
    prof = np.maximum(prof, np.maximum(np.roll(prof, 1), np.roll(prof, -1)))  # ligne à ±1 pixel près
    best, score = None, 0.0
    for top in range(0, len(prof) - int(height) - 1):
        lines = [prof[int(round(top + k * sp))] for k in range(5)]
        if min(lines) >= 0.01 and sum(lines) > score:
            best, score = top, sum(lines)
    if best is None or score < 0.08:
        return None
    return lo + best, lo + best + height


def complete(bw, staves, per_system):
    """
    Portées manquantes (trop pâles) : un trou dans la suite régulière des portées, ou un système incomplet en bas
    de page. Rend (haut, bas, gauche, droite, état) pour chaque portée ; état : « vue », « pâle » (retrouvée avec
    un seuil bas, à retracer) ou « absente » (place connue, lignes introuvables : la voix se tait sur ce système).
    """
    if len(staves) < 2:
        return [(*s, "vue") for s in staves]
    height = statistics.median(b - t for t, b, _l, _r in staves)
    step = statistics.median(b[0] - a[0] for a, b in zip(staves, staves[1:]))
    left = int(statistics.median(s[2] for s in staves))
    right = int(statistics.median(s[3] for s in staves))
    tops = []
    for k, s in enumerate(staves):
        if k:
            gap = s[0] - staves[k - 1][0]
            missing = int(round(gap / step)) - 1
            tops += [staves[k - 1][0] + gap * (j + 1) / (missing + 1) for j in range(missing)] if gap > 1.6 * step else []
        tops.append(s)
    while sum(1 for t in tops) % per_system:
        last = tops[-1][0] if isinstance(tops[-1], tuple) else tops[-1]
        first = tops[0][0] if isinstance(tops[0], tuple) else tops[0]
        if last + step + height < bw.shape[0] - height / 4:
            tops.append(last + step)
        elif first - step > 0:
            tops.insert(0, first - step)
        else:
            break
    out = []
    for t in tops:
        if isinstance(t, tuple):
            out.append((*t, "vue"))
            continue
        found = _search(bw, t, height, left, right)
        out.append((found[0], found[1], left, right, "pâle") if found else (t, t + height, left, right, "absente"))
    return out


def _follow(bw, staff, window=240):
    """
    Hauteur réelle de la portée, tronçon par tronçon : une photocopie est souvent gondolée (la portée descend
    de quelques pixels d'un bout à l'autre). Dans chaque tronçon, le gabarit de 5 lignes est recalé à moins
    d'une demi-interligne près. Rend [(x, haut)] (tronçons sans assez d'encre : omis).
    """
    from preprocess import line_strokes
    top, bottom, left, right = staff[:4]
    sp = (bottom - top) / 4
    reach = max(2, int(sp / 2))
    lo, hi = max(0, int(top) - reach - 2), min(bw.shape[0], int(bottom) + reach + 3)
    strokes = line_strokes(bw[lo:hi, int(left):int(right)])
    points = []
    for x in range(0, strokes.shape[1], window):
        prof = strokes[:, x:x + window].mean(1)
        prof = np.maximum(prof, np.maximum(np.roll(prof, 1), np.roll(prof, -1)))
        best, score = None, 0.0
        for d in range(-reach, reach + 1):
            lines = [prof[int(round(top - lo + d + k * sp))] for k in range(5)]
            if min(lines) >= 0.02 and sum(lines) > score:
                best, score = d, sum(lines)
        if best is not None:
            points.append((int(left) + x + min(window, strokes.shape[1] - x) // 2, top + best))
    return points


def redraw(bw, staff):
    """Lignes d'une portée retrouvée, retracées d'un trait continu qui suit la portée réelle (copie nettoyée)."""
    top, bottom, left, right, _state = staff
    sp = (bottom - top) / 4
    points = _follow(bw, staff) or [((left + right) / 2, top)]
    points = [(left, points[0][1])] + points + [(right, points[-1][1])]
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        for x in range(int(xa), int(xb), 8):  # petits segments : suit la pente
            y = ya + (yb - ya) * (x - xa) / max(1, xb - xa)
            for k in range(5):
                yk = int(round(y + k * sp))
                cv2.rectangle(bw, (x, yk - 1), (min(int(xb), x + 8) - 1, yk + 1), 0, -1)


def _redraw_bar(bw, staff, x):
    """Barre de mesure retracée sur toute la hauteur d'une portée, là où l'encre la montre déjà (±4 pixels)."""
    top, bottom = int(round(staff[0])), int(round(staff[1]))
    zone = (bw[top:bottom + 1, max(0, x - 12):x + 13] < 128).mean(0)
    if zone.size and zone.max() > 0.3:
        x = max(0, x - 12) + int(np.argmax(zone))  # sur le trait d'origine, pas à côté
    cv2.rectangle(bw, (x - 1, top), (x + 1, bottom), 0, -1)


# ---------------------------------------------------------------------------------------------------------------
# 2. Une page par voix

def cut_staff(bw, staff):
    """
    Portée découpée avec ses paroles ; barres de mesure (qui traversent tout le système) ramenées à sa hauteur.
    Rend (image, haut, bas) : place des lignes 1 et 5 dans l'image.
    """
    top, bottom = int(round(staff[0])), int(round(staff[1]))
    sp = (bottom - top) / 4
    up, down = max(0, int(top - 5.5 * sp)), min(bw.shape[0], int(bottom + 8 * sp))
    c = bw[up:down].copy()
    T, B = top - up, bottom - up
    ink = (c < 128).astype(np.uint8)
    vert = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 9)))
    vert = cv2.morphologyEx(vert, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(sp)))))
    # colonnes qui traversent toute la hauteur de la portée : barres de mesure
    cols = np.flatnonzero(cv2.dilate(vert[T:B + 1], np.ones((1, 3), np.uint8)).mean(0) >= 0.9)
    outside = np.zeros_like(ink)
    outside[:max(0, T - 3)] = vert[:max(0, T - 3)]
    outside[B + 4:] = vert[B + 4:]
    mask = np.zeros_like(ink)
    for x in cols:
        mask[:, max(0, x - 3):x + 4] = 1
    c[(outside & mask).astype(bool)] = 255
    return c, T, B


def blank_staff(width, staff):
    """Portée vide à la place d'une portée introuvable : la page de la voix garde un système par système."""
    top, bottom, left, right, _state = staff
    sp = (bottom - top) / 4
    h = int(13.5 * sp)
    img = np.full((h, width), 255, np.uint8)
    for k in range(5):
        y = int(round(5.5 * sp + k * sp))
        cv2.rectangle(img, (int(left), y - 1), (int(right), y + 1), 0, -1)
    return img, int(round(5.5 * sp)), int(round(9.5 * sp))


def voice_pages(page_files, layout, out_dir, pdf=True):
    """
    Repère les portées, complète la copie nettoyée (page_files réécrites), découpe chaque portée
    (out_dir/lignes/), écrit une page par voix (out_dir/voix.pdf), les premières lignes de chaque voix
    (out_dir/entetes.pdf : clé, armure et mesure y sont intactes) et la disposition (out_dir/disposition.json).
    Rend le nombre de systèmes, 0 si la page ne ressemble pas à la disposition annoncée.
    """
    from PIL import Image
    voices = LAYOUTS[layout]
    n = len(voices)
    rows = [[] for _ in range(n)]
    systems = []
    for pf in page_files:
        bw = imgio.imread(str(pf), cv2.IMREAD_GRAYSCALE)
        if layout == "satb":
            staves = complete(bw, find_staves(bw), n)
            groups = [list(range(k, k + n)) for k in range(0, len(staves) - len(staves) % n, n)]
        else:  # écriture serrée : les deux dernières portées de chaque système (une portée instrumentale peut les précéder)
            staves = [(*s, "vue") for s in find_staves(bw)]
            groups = [g[-n:] for g in system_indexes(bw, staves) if len(g) >= n]
        faint = [s for s in staves if s[4] == "pâle"]
        for s in faint:  # retracées : sur la copie nettoyée et pour la lecture
            redraw(bw, s)
        bars_drawn = False
        for idx in groups:
            group = [staves[i] for i in idx]
            bars = bar_lines(bw, group)
            lyrics = []
            for j, i in enumerate(idx):
                s = staves[i]
                nxt = staves[i + 1][0] if i + 1 < len(staves) else bw.shape[0]
                # écriture serrée : les paroles sont entre les deux portées du système (sous celle de sol) ; sous la portée
                # de fa il n'y a que les accords, les titres (« COUPLETS ») ou les couplets suivants imprimés en bas de page
                keep = s[4] != "absente" and (layout == "satb" or j == 0)
                lyrics.append(read_lyrics(bw, s, nxt) if keep else [])
            for s in group:  # barres retracées sur chaque portée (souvent presque effacées dans la portée)
                if s[4] != "absente":
                    for x in bars:
                        _redraw_bar(bw, s, x)
                        bars_drawn = True
            systems.append({"page": pf.name, "staves": [[round(s[0]), round(s[1]), s[4]] for s in group],
                            "mesures": len(bars), "barres": [int(x) for x in bars],
                            "paroles": [[[round(x), t, v] for x, t, v in ly] for ly in lyrics]})
            for v, s in enumerate(group):
                rows[v].append(blank_staff(bw.shape[1], s) if s[4] == "absente" else cut_staff(bw, s))
        if faint or bars_drawn:
            imgio.imwrite(str(pf), bw)  # copie nettoyée : portées pâles et barres retracées
    if not systems:
        return 0
    lines = out_dir / "lignes"
    lines.mkdir(parents=True, exist_ok=True)
    for v, vr in enumerate(rows):
        for k, (img, _T, _B) in enumerate(vr):
            imgio.imwrite(str(lines / f"v{v + 1}-{k + 1:02d}.png"), img)
    (out_dir / "disposition.json").write_text(json.dumps(
        {"layout": layout, "systems": systems, "lignes": [[[T, B] for _i, T, B in vr] for vr in rows]}, ensure_ascii=False), encoding="utf-8")
    if pdf:
        make_pdfs(out_dir, layout)
    return len(systems)


def make_pdfs(out_dir, layout):
    """entetes.pdf (première ligne de chaque voix) et voix.pdf (une page par voix) : pour la lecture par Audiveris."""
    info = json.loads((out_dir / "disposition.json").read_text(encoding="utf-8"))
    rows = [[imgio.imread(str(out_dir / "lignes" / f"v{v + 1}-{k + 1:02d}.png"), cv2.IMREAD_GRAYSCALE)
             for k in range(len(lines))] for v, lines in enumerate(info["lignes"])]
    _save([[vr[0]] for vr in rows], out_dir / "entetes.pdf")
    _save(rows, out_dir / "voix.pdf")


def _save(rows, pdf):
    """Une page par voix : ses lignes l'une sous l'autre."""
    from PIL import Image
    width = max(r.shape[1] for vr in rows for r in vr)
    pages = []
    for vr in rows:
        gap = np.full((60, width), 255, np.uint8)
        parts = []
        for r in vr:
            if r.shape[1] < width:
                r = np.hstack([r, np.full((r.shape[0], width - r.shape[1]), 255, np.uint8)])
            parts += [r, gap]
        pages.append(Image.fromarray(np.vstack(parts)))
    pages[0].save(pdf, save_all=True, append_images=pages[1:], resolution=300)


# ---------------------------------------------------------------------------------------------------------------
# 2 bis. Têtes de ligne redessinées

def _music_font():
    """Bravura (police musicale SMuFL, licence SIL OFL), prise dans Audiveris : rien de plus à installer."""
    import os, zipfile
    from omr import AUDIVERIS
    here = pathlib.Path(__file__).resolve().parent / "Bravura.otf"
    if here.exists():
        return here
    cache = pathlib.Path(os.environ.get("TMPDIR", "/tmp")) / "pupitre-Bravura.otf"
    if cache.exists():
        return cache
    base = pathlib.Path(AUDIVERIS).resolve().parent.parent
    for jar in list(base.rglob("audiveris*.jar")) + list(base.rglob("Audiveris*.jar")):
        try:
            with zipfile.ZipFile(jar) as z:
                cache.write_bytes(z.read("res/Bravura.otf"))
                return cache
        except (KeyError, OSError, zipfile.BadZipFile):
            continue
    return None


# place des altérations de l'armure, en lignes depuis le bas de la portée (clé de sol ; clé de fa : une ligne plus bas)
SHARPS = [5, 3.5, 5.5, 4, 2.5, 4.5, 3]
FLATS = [3, 4.5, 2.5, 4, 2, 3.5, 1.5]


def draw_header(height, T, B, clef_name, sharps, time_sig):
    """Tête de ligne nette : clé de la voix, armure et chiffres de mesure, aux hauteurs exactes de la portée."""
    from PIL import Image, ImageDraw, ImageFont
    font_file = _music_font()
    if font_file is None:
        return None
    sp = (B - T) / 4
    font = ImageFont.truetype(str(font_file), max(8, int(round(4 * sp))))  # 1 cadratin = 4 interlignes (SMuFL)
    num, den = time_sig.split("/")
    width = int((3.4 + 1.1 * abs(sharps) + 1.0 + 1.1 * max(len(num), len(den)) + 1.2) * sp)
    img = Image.new("L", (width, height), 255)
    d = ImageDraw.Draw(img)
    for k in range(5):
        y = int(round(T + k * sp))
        d.rectangle([0, y - 1, width, y + 1], fill=0)
    at = lambda line: B - (line - 1) * sp  # noqa: E731 : ligne 1 = ligne du bas
    glyph, line = {"G": ("\ue050", 2), "G8": ("\ue052", 2), "F": ("\ue062", 4)}[clef_name]
    d.text((0.5 * sp, at(line)), glyph, font=font, fill=0, anchor="ls")
    x = 3.4 * sp
    shift = -1 if clef_name == "F" else 0
    for pos in (SHARPS if sharps > 0 else FLATS)[:abs(sharps)]:
        d.text((x, at(pos + shift)), "\ue262" if sharps > 0 else "\ue260", font=font, fill=0, anchor="ls")
        x += 1.1 * sp
    x += 0.8 * sp
    for digits, line in ((num, 3), (den, 1)):
        d.text((x, at(line)), "".join(chr(0xE080 + int(c)) for c in digits if c.isdigit()), font=font, fill=0, anchor="ls")
    return np.array(img)


def _cut_point(c, T, B, sharps):
    """
    Fin de la tête de ligne d'origine (clé effacée, armure, accolade) : le plus grand blanc entre la tête et la
    première note, cherché un peu après la place de la clé et de l'armure.
    """
    from preprocess import line_strokes
    sp = (B - T) / 4
    strokes = line_strokes(c)
    rows = [strokes[max(0, int(round(T + k * sp)) - 2):int(round(T + k * sp)) + 3].any(0) for k in range(5)]
    starts = np.flatnonzero(np.sum(rows, axis=0) >= 3)
    left = int(starts[0]) if len(starts) else 0
    ink = (c[max(0, int(T - sp)):int(B + sp)] < 128).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 1)))
    empty = ((ink & (1 - lines)).sum(0) == 0)
    w0, w1 = int(left + 2.2 * sp), int(left + (6.0 + 1.3 * abs(sharps)) * sp)
    best, run, start = None, 0, None
    for x in range(w0, min(w1, len(empty))):
        if empty[x]:
            start = x if start is None else start
            if x - start + 1 > run:
                best, run = (start + x) // 2, x - start + 1
        else:
            start = None
    return best if best is not None and run >= 0.5 * sp else int(left + (3 + abs(sharps)) * sp)


def header_pages(out_dir, layout, sharps, time_sig, pdf=True):
    """
    voix.pdf refaite : chaque ligne après la première reçoit une tête nette (clé, armure, mesure) à la place de
    la sienne, souvent effacée. Sans clé reconnue, Audiveris lit la ligne en clé de sol et oublie la mesure
    (il ne sait plus où placer les barres). Rend False si rien n'a pu être dessiné.
    """
    info = json.loads((out_dir / "disposition.json").read_text(encoding="utf-8"))
    info.update({"armure": sharps, "mesure": time_sig})  # gardées pour l'assemblage
    (out_dir / "disposition.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    voices = LAYOUTS[layout]
    rows = []
    nettes = out_dir / "lignes-nettes"
    nettes.mkdir(exist_ok=True)
    for v, (_name, clef_name) in enumerate(voices):
        vr = []
        for k, (T, B) in enumerate(info["lignes"][v]):
            c = imgio.imread(str(out_dir / "lignes" / f"v{v + 1}-{k + 1:02d}.png"), cv2.IMREAD_GRAYSCALE)
            if k:
                head = draw_header(c.shape[0], T, B, clef_name, sharps, time_sig)
                if head is None:
                    return False
                c = np.hstack([head, c[:, _cut_point(c, T, B, sharps):]])
            imgio.imwrite(str(nettes / f"v{v + 1}-{k + 1:02d}.png"), c)
            vr.append(c)
        rows.append(vr)
    if pdf:
        _save(rows, out_dir / "voix.pdf")
    return True


def staff_spec(out_dir, layout, folder="lignes", first_only=False, passes=1):
    """
    portees.json pour pupitre-homr --portees : les lignes de chaque voix (dossier « lignes » ou « lignes-nettes »),
    la première seulement avec first_only (clé, armure et mesure d'origine).
    """
    info = json.loads((out_dir / "disposition.json").read_text(encoding="utf-8"))
    voix = [[{"image": f"{folder}/v{v + 1}-{k + 1:02d}.png", "T": T, "B": B} for k, (T, B) in enumerate(lines)][:1 if first_only else None]
            for v, lines in enumerate(info["lignes"])]
    (out_dir / "portees.json").write_text(json.dumps({"voix": voix, "passes": passes}), encoding="utf-8")
    return out_dir


TIMES = ["4/4", "3/4", "2/4", "6/8", "2/2", "3/8", "9/8", "12/8", "3/2"]


def key_and_time(sources):
    """
    Armure (dièses > 0, bémols < 0) et mesure lues par homr sur les premières lignes des voix ; None si rien de lu.
    Armure : la valeur sur laquelle s'accordent le plus de voix. Mesure : celle qui rend justes le plus de mesures
    lues (la mesure écrite en tête de ligne est parfois mal lue : 3/4 sur une voix, 4/4 sur la suivante).
    """
    from collections import Counter
    from music21 import converter, key, meter, stream
    ks, ts, durs = [], [], []
    for src in sources:
        sc = converter.parse(str(src))
        ks += [k.sharps for k in sc.recurse().getElementsByClass(key.KeySignature)][:1]  # la tête de la ligne
        ts += [t.ratioString for t in sc.recurse().getElementsByClass(meter.TimeSignature)][:1]
        for part in sc.parts:
            ms = list(part.getElementsByClass(stream.Measure))
            durs += [float(m.duration.quarterLength) for m in ms[1:-1]]  # sans la levée ni la fin de ligne
    if not ts:
        return None
    candidates = set(ts) | {"4/4", "3/4"}
    bar = lambda t: float(meter.TimeSignature(t).barDuration.quarterLength)  # noqa: E731
    exact = {t: sum(1 for d in durs if abs(d - bar(t)) < 1e-6) for t in candidates}
    best = max(exact.values())
    # à compte égal, la mesure lue le plus souvent, puis 4/4
    pick = max((t for t in candidates if exact[t] == best), key=lambda t: (ts.count(t), t == "4/4"))
    return (Counter(ks).most_common(1)[0][0] if ks else 0), pick


# ---------------------------------------------------------------------------------------------------------------
# 3. Les voix remises ensemble

def _lines(sources):
    """
    Lignes lues par Audiveris, dans l'ordre (chaque ligne en mesures). Il coupe parfois la lecture en plusieurs
    mouvements (clé non reconnue…) : un mouvement commence toujours une ligne. Rend aussi les débuts de page.
    """
    from music21 import converter, layout, stream
    lines, pages = [], []
    for src in sources:
        score = converter.parse(str(src))
        first = True
        for m in score.parts[0].getElementsByClass(stream.Measure):
            ls = list(m.getElementsByClass((layout.PageLayout, layout.SystemLayout)))
            page = any(isinstance(l, layout.PageLayout) and l.isNew for l in ls)
            if first or page or any(isinstance(l, layout.SystemLayout) and l.isNew for l in ls):
                if page:
                    pages.append(len(lines))
                lines.append([])
            first = False
            lines[-1].append(m)
    return lines, pages


def _staff_counts(sources):
    """Portées vues par Audiveris sur chaque page (journal : « [voix#2] … Systems: #1[1] #2[2] … »)."""
    import re
    counts = {}
    for src in sources:
        for log in pathlib.Path(src).parent.glob("*.log"):
            for line in log.read_text(errors="replace", encoding="utf-8").splitlines():
                m = re.search(r"\[[^\]#]*#(\d+)\].*Systems:(.*)", line)
                if m:
                    counts[int(m.group(1))] = len(re.findall(r"\[[^\]]*\]", m.group(2)))
    return [counts[k] for k in sorted(counts)]


def _place(lines, others, n_sys):
    """
    Voix dont Audiveris a manqué des lignes : à quel système va chacune ? Alignement dans l'ordre qui rapproche
    le plus la durée de chaque ligne de celle des autres voix au même système ; les systèmes sans ligne restent
    vides (la voix s'y tait au lieu de décaler la suite).
    """
    dur = [sum(float(m.duration.quarterLength) for m in ln) for ln in lines]
    m = len(lines)
    INF = float("inf")
    cost = [[INF] * (m + 1) for _ in range(n_sys + 1)]
    cost[0][0] = 0.0
    for i in range(1, n_sys + 1):
        for j in range(0, min(i, m) + 1):
            skip = cost[i - 1][j]
            take = cost[i - 1][j - 1] + abs(dur[j - 1] - others[i - 1]) if j else INF
            cost[i][j] = min(skip, take)
    out, j = [None] * n_sys, m
    for i in range(n_sys, 0, -1):
        if j and cost[i][j] == cost[i - 1][j - 1] + abs(dur[j - 1] - others[i - 1]):
            out[i - 1] = lines[j - 1]
            j -= 1
    return [ln if ln is not None else [] for ln in out]


def _sheets(sources, n_voices, n_sys):
    """
    Lignes réparties entre les pages des voix : n_sys lignes par voix ; sinon d'après le nombre de portées vues
    par Audiveris sur chaque page, les lignes manquantes d'une voix étant placées par _place.
    """
    lines, pages = _lines(sources)
    if len(lines) == n_voices * n_sys:
        return [lines[v * n_sys:(v + 1) * n_sys] for v in range(n_voices)]
    counts = _staff_counts(sources)
    if len(counts) != n_voices or sum(counts) != len(lines):
        starts = sorted(set([0] + pages))
        if len(starts) != n_voices:
            sys.exit(f"{len(lines)} lignes lues pour {n_voices} voix × {n_sys} systèmes")
        counts = [b - a for a, b in zip(starts, starts[1:] + [len(lines)])]
    sheets, at = [], 0
    for c in counts:
        sheets.append(lines[at:at + c])
        at += c
    full = [sh for sh in sheets if len(sh) == n_sys]
    for v, sh in enumerate(sheets):
        if len(sh) < n_sys:
            others = [statistics.median([sum(float(m.duration.quarterLength) for m in f[i]) for f in full]) if full else 0.0
                      for i in range(n_sys)]
            sheets[v] = _place(sh, others, n_sys)
        elif len(sh) > n_sys:
            sheets[v] = sh[:n_sys]
    return sheets


def _clef(name):
    from music21 import clef
    return {"G": clef.TrebleClef, "G8": clef.Treble8vbClef, "F": clef.BassClef}[name]()


def _moved(p, read, target, read_key, keysig):
    """
    Hauteur relue avec la bonne clé (même place sur la portée) et la bonne armure : une altération écrite
    devant la note reste, sinon c'est l'armure de la partition qui décide (Audiveris la perd souvent sur une
    ligne dont il n'a pas reconnu la clé).
    """
    from music21 import pitch
    written = read_key.accidentalByStep(p.step) if read_key else None
    explicit = p.accidental is not None and p.accidental.alter != (written.alter if written else 0)
    q = pitch.Pitch()
    q.diatonicNoteNum = p.diatonicNoteNum - read.lowestLine + target.lowestLine
    if explicit:
        q.accidental = pitch.Accidental(p.accidental.name)
    else:
        a = keysig.accidentalByStep(q.step)
        if a is not None:
            q.accidental = pitch.Accidental(a.name)
    return q


def _plausible_accidental(step, alter, sharps):
    """
    Une altération écrite en plus de l'armure est-elle vraisemblable dans un chant simple ? Dièses : sensible et
    notes voisines (fa, sol, do, ré) ; bémols : seulement dans une armure à bémols. Les autres (mi♭ ou si♭ sans bémol
    à l'armure, la♯, mi♯…) sont presque toujours une tache de la copie prise pour une altération.
    """
    if alter > 0:
        return step in "FGCD" or sharps < 0
    if alter < 0:
        return sharps < 0
    return True


def _clean_accidentals(lines, keysig):
    """
    Retire les altérations invraisemblables (voir _plausible_accidental) quand elles sont rares dans le chant
    (moins de 6 % des notes : un chant chromatique, comme un choral de Bach, en a bien plus et les garde toutes).
    Rend le nombre d'altérations retirées.
    """
    from music21 import pitch
    pitches = [p for row in lines for notes in row for n in notes if not n.isRest for p in n.pitches]
    explicit = [p for p in pitches if p.accidental is not None
                and p.accidental.alter != (keysig.accidentalByStep(p.step).alter if keysig.accidentalByStep(p.step) else 0)]
    if not pitches or len(explicit) / len(pitches) >= 0.06:
        return 0
    removed = 0
    for p in explicit:
        if not _plausible_accidental(p.step, p.accidental.alter, keysig.sharps):
            a = keysig.accidentalByStep(p.step)
            p.accidental = pitch.Accidental(a.name) if a else None
            removed += 1
    return removed


def _syllable(text):
    """
    Syllabe plausible ? Lettres seulement (accents compris, apostrophe, tiret), 1 à 8, avec une voyelle : sur une
    photocopie, la lecture du texte rend aussi des débris (« kLvmp », « «ry », « [l ») qu'il vaut mieux taire.
    """
    import re
    t = (text or "").strip(" -_.,;:!?")
    return bool(re.fullmatch(r"[A-Za-zÀ-ÖØ-öø-ÿƐɛƆɔŊŋ'’]{1,8}", t)) and bool(re.search(r"[aeiouyàâäéèêëìîïòôöùûüÿɛɔAEIOUYÀÂÄÉÈÊËÌÎÏÒÔÖÙÛÜƐƆ]", t))


def _line_notes(measures, target, keysig, state, drop_head_chords=True):
    """
    Notes et silences d'une ligne, mesure par mesure, à la clé et à l'armure de la voix.
    Clé et armure lues par Audiveris suivies d'une ligne à l'autre de la voix (state : il ne les réécrit que
    quand elles changent) ; on ne s'en remet pas au contexte de music21, que les copies de notes déplacent.
    """
    from music21 import clef, key, note
    read, read_key = state.get("clef") or clef.TrebleClef(), state.get("key")
    out = []
    for first, m in enumerate(measures):
        first = first == 0
        # plusieurs voix dans la mesure : la première (celle du haut en divisi) ; sauf si elle n'est qu'un silence et
        # qu'une autre chante au moins une demi-mesure (Audiveris range parfois toute la ligne à côté d'un silence)
        src = m.voices[0] if m.voices else m
        if m.voices and not list(src.notes):
            singing = [v for v in m.voices[1:] if sum(float(x.quarterLength) for x in v.notes) >= 0.5 * float(m.barDuration.quarterLength)]
            src = singing[0] if singing else src
        marks = sorted(list(m.getElementsByClass((clef.Clef, key.KeySignature)))
                       + (list(src.getElementsByClass((clef.Clef, key.KeySignature))) if src is not m else []),
                       key=lambda e: e.offset)
        notes = []
        for n in src.notesAndRests:
            while marks and marks[0].offset <= n.offset:
                mark = marks.pop(0)
                if isinstance(mark, clef.Clef):
                    read = mark
                else:
                    read_key = mark
            c = copy.deepcopy(n)
            if drop_head_chords and first and c.isChord and n.offset == 0:
                # accord au premier temps d'une ligne, là où était la tête d'origine : débris de clé ou de nom
                # de voix (« B ») pris pour des notes ; une voix seule ne chante qu'une note à la fois
                c = note.Rest(quarterLength=n.quarterLength)
            if c.lyrics:
                c.lyrics = [l for l in c.lyrics if _syllable(l.text)]
            if not c.isRest:
                if c.isChord:
                    for src_p, dst in zip(n.pitches, c.notes):
                        dst.pitch = _moved(src_p, read, target, read_key, keysig)
                else:
                    c.pitch = _moved(n.pitch, read, target, read_key, keysig)
            if isinstance(c, note.GeneralNote) and c.duration.quarterLength > 0:
                notes.append(c)
        for mark in marks:
            if isinstance(mark, clef.Clef):
                read = mark
            else:
                read_key = mark
        if notes:
            out.append(notes)
    state["clef"], state["key"] = read, read_key
    return out


def _signature(measure):
    """Ce qui fait la lecture d'une mesure : pour chaque note, ses hauteurs et sa durée (silence : aucune hauteur)."""
    return tuple((() if n.isRest else tuple(sorted(p.midi for p in n.pitches)), round(float(n.quarterLength), 3)) for n in measure)


def _vote(candidates, bar):
    """
    Plusieurs lectures de la même ligne (lire_homr, passes 1 à 3) : vote mesure par mesure. On ne garde que les lectures qui
    comptent le plus souvent le même nombre de mesures ; pour chaque mesure, on préfère celles qui font exactement la
    durée de la mesure, puis la lecture sur laquelle s'accordent le plus de passes (à égalité, la première passe).
    Rend (mesures choisies, confiance de chacune : part des passes qui lisent la même chose).
    """
    from collections import Counter
    if len(candidates) == 1:
        return candidates[0], [1.0] * len(candidates[0])
    counts = Counter(len(c) for c in candidates)
    top = max(counts.values())
    length = next(len(c) for c in candidates if counts[len(c)] == top)  # à égalité : la plus prioritaire
    kept = [c for c in candidates if len(c) == length]
    voted, conf = [], []
    for i in range(length):
        options = [c[i] for c in kept]
        sigs = [_signature(o) for o in options]
        valid = [k for k, o in enumerate(options) if abs(_length(o) - bar) < 1e-6]
        pool = valid or list(range(len(options)))
        best = max(pool, key=lambda k: (sum(sigs[k] == s for s in sigs), -k))
        voted.append(options[best])
        agree = sum(sigs[best] == s for s in sigs) / len(candidates)
        conf.append(agree if best in valid or not valid else min(agree, 0.5))
    return voted, conf


def _length(notes):
    return sum(float(n.duration.quarterLength) for n in notes)


def _fit(notes, length, entry=False):
    """
    Mesure ramenée à sa durée : silence ajouté si une note a été perdue, débordement coupé si une valeur a été
    mal lue (point ou crochet de trop) — l'erreur reste dans sa mesure au lieu de décaler toute la suite.
    entry : la voix entre après un silence ; ce qui manque est alors le silence d'avant l'entrée (levée).
    """
    from music21 import note
    out, t = [], 0.0
    for n in notes:
        d = float(n.duration.quarterLength)
        if t + d > length + 1e-6:
            rest = length - t
            if rest > 1e-6:
                n.duration.quarterLength = rest
                out.append(n)
            t = length
            break
        out.append(n)
        t += d
    if length - t > 1e-6:
        gap = note.Rest(quarterLength=length - t)
        out = [gap] + out if entry else out + [gap]
    return out


def _sings(notes):
    return any(not n.isRest for n in notes)


# voix qui chantent le plus souvent sur le même rythme (mêmes paroles) : soprano et alto, ténor et basse
PARTNERS = {0: [1, 2, 3], 1: [0, 2, 3], 2: [3, 1, 0], 3: [2, 1, 0]}


def _borrow_rhythms(row, sizes_of, bar, stats=None):  # noqa: C901
    """
    Écriture homorythmique (cantique, chœur à 4 voix) : une mesure dont les valeurs ne font toujours pas le compte prend
    le rythme d'une autre voix qui chante autant de notes dans la même mesure et dont le compte est juste
    (la voix sœur d'abord : soprano ↔ alto, ténor ↔ basse). Chaque voix garde ses hauteurs ; seules les durées
    mal lues (point, crochet, ligature effacés) sont reprises.
    """
    for v, sizes in sizes_of.items():  # d'abord : un point effacé ou en trop
        for i, k in enumerate(sizes):
            m = row[v][i]
            if stats is not None:
                stats["mesures"] = stats.get("mesures", 0) + 1
                stats["justes"] = stats.get("justes", 0) + (abs(_length(m) - k * bar) < 1e-6)
            if _one_mark(m, k * bar) and stats is not None:
                stats["marques"] = stats.get("marques", 0) + 1
    if len(row) != 4:  # reprise du rythme de la voix sœur : seulement avec quatre voix (soprano ↔ alto, ténor ↔ basse)
        return
    for v, sizes in sizes_of.items():
        for i, k in enumerate(sizes):
            m = row[v][i]
            if abs(_length(m) - k * bar) < 1e-6:
                continue
            for u in PARTNERS.get(v, []):
                if u not in sizes_of or sizes_of[u] != sizes:
                    continue
                donor = row[u][i]
                if len(donor) == len(m) and abs(_length(donor) - k * bar) < 1e-6 and _sings(donor):
                    for a, d in zip(m, donor):
                        a.duration.quarterLength = d.duration.quarterLength
                    if stats is not None:
                        stats["reprises"] = stats.get("reprises", 0) + 1
                    break


def _one_mark(m, length):
    """
    Mesure qui ne fait pas le compte à un point près : sur une photocopie, le point d'une note s'efface (ou une
    tache en fait un). On ne corrige que si une seule note peut l'expliquer ; sinon on laisse (mieux vaut une
    mesure complétée par un silence qu'un rythme inventé). Rend True si corrigé.
    """
    gap = length - _length(m)
    if abs(gap) < 1e-6:
        return False
    fixes = []
    for n in m:
        if n.isRest:
            continue
        d = float(n.duration.quarterLength)
        if n.duration.dots == 0 and abs(d * 0.5 - gap) < 1e-6:
            fixes.append((n, d * 1.5))  # point effacé
        elif n.duration.dots == 1 and abs(-d / 3 - gap) < 1e-6:
            fixes.append((n, d / 1.5))  # point en trop (tache)
    if len(fixes) != 1:
        return False
    fixes[0][0].duration.quarterLength = fixes[0][1]
    return True


def _system(row, bar, seen=0, silent=None, stats=None):
    """
    Les quatre voix d'un système, mises à la même longueur, mesure par mesure quand c'est possible.
    Nombre de mesures du système : celui de la majorité des voix (une « mesure » lue de 8 temps = 2 mesures dont la
    barre a échappé), relevé à celui compté sur l'image (seen) si une voix le confirme : mieux vaut une mesure de
    silence en trop qu'une note coupée.
    Chaque mesure lue est ramenée à sa durée pleine ; une voix qui ne s'accorde pas est complétée ou coupée
    en fin de ligne. silent[v] : la voix v se taisait à la fin du système d'avant (mis à jour ici).
    """
    silent = silent if silent is not None else [True] * len(row)
    spans = [[max(1, round(_length(m) / bar)) for m in ms] for ms in row]
    guesses = [sum(sp) for sp in spans if sp] + [len(sp) for sp in spans if sp]
    sums = [sum(sp) for sp in spans if sp]
    top = max(sums.count(x) for x in sums) if sums else 0
    count = max([x for x in sums if sums.count(x) == top], default=0)  # la majorité des voix (à égalité : la plus longue)
    if seen > count and seen in guesses:
        count = seen  # l'image en compte plus, et une voix le confirme : on ne coupe pas de notes
    sizes_of = {v: (sp if sum(sp) == count else [1] * len(ms))
                for v, (ms, sp) in enumerate(zip(row, spans)) if count and (sum(sp) == count or len(ms) == count)}
    _borrow_rhythms(row, sizes_of, bar, stats)
    if stats is not None:
        stats["count"] = count
    out = []
    for v, (ms, sp) in enumerate(zip(row, spans)):
        if v in sizes_of:
            sizes = sizes_of[v]
            notes = []
            for m, k in zip(ms, sizes):
                notes += _fit(m, k * bar, entry=silent[v] and _sings(m))
                silent[v] = not _sings(m)
        else:
            flat = [n for m in ms for n in m]
            notes = _fit(flat, count * bar, entry=silent[v] and _sings(flat)) if count else []
            silent[v] = not _sings(ms[-1]) if ms else silent[v]
        out.append(notes)
    return out


def _voice_lines(path, n_sys, others=None):
    """
    Lignes d'une voix lue à part : n_sys lignes. Si le lecteur a noté quelles lignes il a lues (v1.lignes.json,
    portées lues une à une), chacune retrouve sa place exacte ; sinon une ligne manquante est placée par _place.
    """
    lines, _pages = _lines([path])
    side = pathlib.Path(path).with_suffix(".lignes.json")
    if side.exists():
        kept = json.loads(side.read_text(encoding="utf-8"))
        if len(kept) == len(lines):
            out = [[] for _ in range(n_sys)]
            for i, ln in zip(kept, lines):
                if i < n_sys:
                    out[i] = ln
            return out
    if len(lines) == n_sys:
        return lines
    if len(lines) > n_sys:
        return lines[:n_sys]
    return _place(lines, others or [16.0] * n_sys, n_sys)


def _syllables(source):
    """Syllabes lues sur une ligne (Audiveris), mesure par mesure : [[[Lyric…] par note] par mesure]."""
    out = []
    for m in source or []:
        src = m.voices[0] if m.voices else m
        groups = []
        for n in src.notes:
            texts = [l for l in n.lyrics if _syllable(l.text)]
            if texts:
                groups.append(texts)
        out.append(groups)
    return out


def _put_lyrics(measures, syllables):
    """
    Paroles d'une autre lecture de la même ligne (Audiveris lit le texte, homr non) posées sur les notes :
    mesure par mesure quand les deux lectures ont autant de mesures (une erreur ne décale pas la suite),
    sinon dans l'ordre de la ligne ; une syllabe par note chantée (pas sur la suite d'une liaison).
    """
    sings = lambda ms: [n for n in ms if not n.isRest and (n.tie is None or n.tie.type == "start")]  # noqa: E731
    for ms in measures:
        for n in ms:
            n.lyrics = []
    pairs = (list(zip([sings(ms) for ms in measures], syllables)) if len(syllables) == len(measures)
             else [([n for ms in measures for n in sings(ms)], [g for gs in syllables for g in gs])])
    for targets, groups in pairs:
        for n, texts in zip(targets, groups):
            n.lyrics = [copy.deepcopy(l) for l in texts]


def _plain(text):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def _accents(lyric_sheets):
    """Formes accentuées lues par Audiveris (« bèè ») : RapidOCR rend les mêmes syllabes sans accent (« bee »)."""
    found = {}
    for sheet in lyric_sheets or []:
        for line in sheet:
            for m in line:
                for n in m.recurse().notes:
                    for l in n.lyrics:
                        t = (l.text or "").strip(" -_.,;:!?")
                        if _syllable(t) and t.lower() != _plain(t):
                            found.setdefault(_plain(t), t.lower())
    return found


def _put_read_lyrics(measures, entries, bars, accents):
    """
    Paroles lues sur l'image (x, syllabe, couplet) posées sur les notes : chaque syllabe va à la mesure où elle
    est écrite (entre deux barres), puis dans l'ordre sur les notes chantées de la mesure (pas sur la suite
    d'une liaison) ; sans barres concordantes, dans l'ordre de la ligne. Le 2e couplet va sur la 2e ligne.
    """
    from music21 import note
    sings = lambda ms: [n for n in ms if not n.isRest and (n.tie is None or n.tie.type == "start")]  # noqa: E731
    for ms in measures:
        for n in ms:
            n.lyrics = []
    for verse in sorted({e[2] for e in entries}):
        sylls = sorted((x, t) for x, t, v in entries if v == verse)
        if bars and len(bars) == len(measures):
            per = [[] for _ in measures]
            for x, t in sylls:
                per[min(len(measures) - 1, sum(1 for b in bars if b < x))].append(t)
            pairs = [(sings(ms), per[i]) for i, ms in enumerate(measures)]
        else:
            pairs = [([n for ms in measures for n in sings(ms)], [t for _x, t in sylls])]
        for targets, texts in pairs:
            for n, t in zip(targets, texts):
                n.addLyric(accents.get(_plain(t), t), lyricNumber=verse)


# voix qui chantent les mêmes paroles sur le même rythme : la meilleure lecture du texte sert aux deux
LYRIC_PAIRS = [(0, 1), (2, 3)]


def _best_syllables(lyric_sheets, s, v, row):
    """Syllabes de la voix v au système s, ou celles de sa voix sœur si sa lecture à elle est plus pauvre."""
    mine = _syllables(lyric_sheets[v][s]) if s < len(lyric_sheets[v]) else []
    count = lambda syl: sum(len(g) for g in syl)  # noqa: E731
    for a, b in LYRIC_PAIRS:
        if v in (a, b):
            u = b if v == a else a
            theirs = _syllables(lyric_sheets[u][s]) if s < len(lyric_sheets[u]) else []
            same_rhythm = [len([n for n in ms if not n.isRest]) for ms in row[v]] == \
                          [len([n for n in ms if not n.isRest]) for ms in row[u]]
            if same_rhythm and count(theirs) > count(mine):
                return theirs
    return mine


def assemble(out, disposition, sources, notes_by_voice=None, variants=None):
    """
    sources : lecture d'Audiveris (pages des voix). notes_by_voice : lecture des notes faite à part, une page
    par voix (homr, plus sûr sur une copie usée) ; les paroles viennent alors de la lecture d'Audiveris.
    variants : dossiers des passes supplémentaires de lire_homr (sortie-1, sortie-2) : vote mesure par mesure ; écrit
    fiabilite.json (confiance de chaque mesure) à côté de la partition.
    """
    from music21 import key, meter, note, stream
    info = json.loads(pathlib.Path(disposition).read_text(encoding="utf-8"))
    voices = LAYOUTS[info["layout"]]
    n_sys = len(info["systems"])
    lyric_sheets = None
    accents = {}
    if notes_by_voice:
        try:
            lyric_sheets = _sheets(sources, len(voices), n_sys) if sources else None
        except SystemExit:
            lyric_sheets = None
        sheets = [_voice_lines(f, n_sys) for f in notes_by_voice]
        vsheets = [[_voice_lines(pathlib.Path(d) / f"v{v + 1}.musicxml", n_sys) for v in range(len(voices))] for d in (variants or [])]
    else:
        vsheets = []
        sheets = _sheets(sources, len(voices), n_sys)
        lyric_sheets = None
    accents = _accents(lyric_sheets if lyric_sheets else sheets)
    # mesure et armure : les plus fréquentes parmi celles qu'Audiveris a lues
    ts = [t.ratioString for sh in sheets for ln in sh for m in ln for t in m.getElementsByClass(meter.TimeSignature)]
    ks = [k.sharps for sh in sheets for ln in sh for m in ln for k in m.getElementsByClass(key.KeySignature)]
    ts = meter.TimeSignature(info.get("mesure") or (statistics.mode(ts) if ts else "4/4"))
    # armure : celle lue sur l'image s'il y en a une, sinon la plus chargée lue au moins deux fois
    # (une armure n'est jamais inventée, souvent perdue)
    sure = [k for k in set(ks) if ks.count(k) >= 2] or ks
    ks = key.KeySignature(info["armure"] if info.get("armure") is not None else (max(sure, key=abs) if sure else 0))
    bar = float(ts.barDuration.quarterLength)
    lines = []  # [système][voix] -> notes, toutes les voix de même durée
    silent = [True] * len(voices)
    states = [{} for _ in voices]
    vstates = [[{} for _ in voices] for _ in vsheets]
    stats = {}
    confidence = {}  # numéro de mesure (1, 2, …) -> plus faible confiance des voix à cette mesure
    offset = 0
    for s in range(n_sys):
        row = [_line_notes(sheets[v][s], _clef(c), ks, states[v], info["layout"] == "satb") if s < len(sheets[v]) else []
               for v, (_n, c) in enumerate(voices)]
        conf_row = [[1.0] * len(m) for m in row]
        if vsheets:  # passes supplémentaires de homr : vote mesure par mesure
            for v, (_n, c) in enumerate(voices):
                cands = [row[v]] + [_line_notes(vs[v][s], _clef(c), ks, vstates[i][v], info["layout"] == "satb") if s < len(vs[v]) else []
                                    for i, vs in enumerate(vsheets)]
                row[v], conf_row[v] = _vote([c for c in cands if c] or [[]], bar)
        read = info["systems"][s].get("paroles")
        if lyric_sheets and not (read and any(read)):
            chosen = [_best_syllables(lyric_sheets, s, v, row) for v in range(len(voices))]
            for v in range(len(voices)):
                _put_lyrics(row[v], chosen[v])
        if read and any(read):  # paroles lues sur l'image : les plus fidèles
            for v in range(len(voices)):
                if v < len(read) and read[v]:
                    _put_read_lyrics(row[v], read[v], info["systems"][s].get("barres", []), accents)
        lines.append(_system(row, bar, info["systems"][s].get("mesures", 0), silent, stats))
        for v in range(len(voices)):  # confiance de chaque mesure -> numéros de mesure de la partition finale
            at = offset
            for m, c in zip(row[v], conf_row[v]):
                for b in range(at + 1, at + max(1, round(_length(m) / bar)) + 1):
                    confidence[b] = min(confidence.get(b, 1.0), c)
                at += max(1, round(_length(m) / bar))
        offset += stats.get("count", 0)
    cleaned = _clean_accidentals(lines, ks)
    if cleaned:
        print(f"Altérations invraisemblables retirées : {cleaned}", file=sys.stderr)
    parts = []
    for v, (name, clef_name) in enumerate(voices):
        flat = stream.Part()
        if name:
            flat.partName = name
        flat.id = f"P{v + 1}"
        flat.append(_clef(clef_name))
        flat.append(copy.deepcopy(ks))
        flat.append(copy.deepcopy(ts))
        for row in lines:
            for x in row[v]:
                flat.append(x)
        parts.append(flat)
    score = stream.Score()
    for v, flat in enumerate(parts):
        measured = flat.makeNotation()  # mesures, liaisons au passage de la barre, ligatures
        measured.partName, measured.id = (flat.partName if name else None), flat.id
        score.insert(0, measured)
    try:
        score.write("musicxml", fp=out)
    except Exception:  # durée « complexe » mal lue : ramenée à la durée simple la plus proche
        simple = [4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.375, 0.25, 0.125]
        for x in score.recurse().notesAndRests:
            if x.duration.type in ("complex", "inexpressible"):
                x.duration.quarterLength = min(simple, key=lambda q: abs(q - float(x.duration.quarterLength)))
        score.write("musicxml", fp=out, makeNotation=False)
    count = len(score.parts[0].getElementsByClass(stream.Measure)) if parts else 0
    if vsheets:
        doubtful = {str(b): round(c, 2) for b, c in sorted(confidence.items()) if c < 1.0 and b <= count}
        mean = sum(confidence.get(b, 1.0) for b in range(1, count + 1)) / max(1, count)
        pathlib.Path(out).with_name("fiabilite.json").write_text(json.dumps(
            {"passes": 1 + len(vsheets), "moyenne": round(mean, 3), "mesures": count, "a_verifier": doubtful},
            ensure_ascii=False), encoding="utf-8")
        print(f"Fiabilité : {mean:.0%} (passes : {1 + len(vsheets)}), mesures à vérifier : {len(doubtful)}/{count}", file=sys.stderr)
    print(f"Voix réunies : {', '.join(n or 'portée' for n, _c in voices)} ; {n_sys} systèmes, {count} mesures ; "
          f"mesures au compte juste : {stats.get('justes', 0)}/{stats.get('mesures', 0)}, "
          f"point rétabli : {stats.get('marques', 0)}, rythme repris d'une autre voix : {stats.get('reprises', 0)}")
    # part des mesures dont les valeurs lues font exactement la mesure : repère de fiabilité de la lecture (omr.py)
    print(f"exactitude:{stats.get('justes', 0) / max(1, stats.get('mesures', 0)):.2f}", flush=True)





def link(bw, upper, lower):
    """
    Les deux portées appartiennent-elles au même système ? Les barres de mesure et l'accolade de gauche
    traversent l'espace entre elles, même en pointillés sur une photocopie ; entre deux systèmes, rien ne le
    traverse (les paroles et les queues de notes n'en couvrent qu'une partie). Rend la plus grande part de
    l'espace couverte par un trait vertical (0 à 1).
    """
    top, bottom = int(upper[1]) + 4, int(lower[0]) - 4
    if bottom - top < 4:
        return 1.0
    x0 = max(0, int(min(upper[2], lower[2])) - 120)  # l'accolade est juste à gauche des portées
    x1 = int(max(upper[3], lower[3]))
    ink = (bw[top:bottom, x0:x1] < 128).astype(np.uint8)
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 15)))
    ink = cv2.dilate(ink, np.ones((1, 3), np.uint8))  # trait un peu penché
    score = float(ink.mean(0).max()) if ink.size else 0.0
    if score < 0.9:
        # copie usée : la ligne qui ouvre le système est trouée par endroits (plus de 15 pixels). Un trait vertical
        # mince, cassures d'une interligne comblées, qui va de la 1re portée à la 2e de bout en bout les relie.
        sp = max(6, int((upper[1] - upper[0]) / 4))
        y0, y1 = int(upper[0]), int(lower[1]) + 1
        # le bord gauche donné par find_staves peut venir une bande trop tard (clé, armure) : on regarde plus loin
        roi = (bw[y0:y1, max(0, x0 - 240):x1] < 128).astype(np.uint8)
        roi = cv2.morphologyEx(roi, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(5, sp // 2))))
        roi = cv2.morphologyEx(roi, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (3, sp)))
        _n, _lab, st, _ = cv2.connectedComponentsWithStats(roi, 8)
        if any(w <= max(7, sp // 3) and y <= sp / 2 and y + h >= (y1 - y0) - sp / 2 for _x, y, w, h, _a in st[1:]):
            return 1.0
    return score


def system_indexes(bw, staves, joined=0.75):
    """Portées d'une page regroupées en systèmes d'après leurs liaisons : [[indice, …], …]."""
    groups = []
    for k in range(len(staves)):
        if k and link(bw, staves[k - 1], staves[k]) >= joined:
            groups[-1].append(k)
        else:
            groups.append([k])
    return groups


def systems_on(bw, staves, joined=0.75):
    """Portées d'une page regroupées en systèmes d'après leurs liaisons : [[portée, …], …]."""
    return [[staves[k] for k in g] for g in system_indexes(bw, staves, joined)]


def detect(page_files, worn=False):
    """
    Disposition du chœur, d'après le nombre de portées de chaque système (liées par leurs barres de mesure) :
    « satb » : quatre portées, une par voix (sur une copie usée, les deux tiers suffisent : une portée trop pâle
    n'est pas vue) ; « grand » : deux portées (sol et fa), avec au plus une portée de plus au-dessus (instrument),
    et au moins un système à deux portées. Rend la disposition ou None.
    """
    sizes = []
    for pf in page_files:
        bw = imgio.imread(str(pf), cv2.IMREAD_GRAYSCALE)
        sizes += [len(g) for g in systems_on(bw, find_staves(bw))]
    if not sizes:
        return None
    need = 2 * len(sizes) / 3 if worn else len(sizes)
    if max(sizes) <= 4 and sizes.count(4) >= max(1, need):
        return "satb"
    if set(sizes) <= {2, 3} and 2 in sizes:
        return "grand"
    return None


def bar_count(bw, group):
    """Nombre de mesures d'un système, compté sur l'image (voir bar_lines)."""
    return len(bar_lines(bw, group))


def bar_lines(bw, group):
    """
    Barres de mesure d'un système, vues sur l'image : une barre traverse toute la hauteur de chacune de ses
    portées au même endroit (une queue de note, jamais). Les traits du tout début (accolade, barre initiale)
    ne comptent pas ; la barre finale, oui. Rend leurs positions [(x, pente)] (pente : décalage en x d'une
    portée à la suivante, la barre pouvant pencher).
    """
    left = int(max(s[2] for s in group))
    right = int(max(s[3] for s in group))
    sp = statistics.median((s[1] - s[0]) / 4 for s in group)
    staves = [s for s in group if len(s) < 5 or s[4] == "vue"] or group
    votes = 0
    for s in staves:
        top, bottom = int(round(s[0])), int(round(s[1]))
        ink = (bw[top:bottom + 1, :] < 128).astype(np.uint8)
        ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7)))
        full = ink.mean(0) >= 0.9  # toute la hauteur : une queue de note ou un chiffre de mesure, non
        votes = votes + cv2.dilate(full.astype(np.uint8)[None, :], np.ones((1, int(1.2 * sp)), np.uint8))[0]  # barre penchée
    # une barre peut manquer sur une portée de la copie : trois portées sur quatre suffisent
    hits = votes >= max(1, len(staves) - 1) if len(staves) > 1 else votes >= 1
    xs = np.flatnonzero(hits[:right + int(sp)])
    bars, last = [], -10**9
    for x in xs:
        if x - last > 1.5 * sp:  # barre double, de reprise : un seul trait de mesure
            bars.append(x + int(0.6 * sp))  # milieu de la zone élargie (pente tolérée)
        last = x
    return [x for x in bars if x > left + 2 * sp]


def _signs(c, T, B):
    """
    Signes d'une portée découpée, lignes de portée ôtées : sur chaque ligne, on efface l'encre qui n'a rien
    juste au-dessus ni juste au-dessous (ce qui traverse la ligne, tête de note ou dièse, reste entier).
    Rend [(x0, x1, y0, y1)] de gauche à droite.
    """
    ink = (c < 128).astype(np.uint8)
    sp = (B - T) / 4
    signs = ink.copy()
    for k in range(5):
        y = int(round(T + k * sp))
        lo, hi = max(0, y - 3), min(ink.shape[0], y + 4)
        above = ink[max(0, lo - 2):lo].any(0) if lo > 0 else np.zeros(ink.shape[1], bool)
        below = ink[hi:hi + 2].any(0) if hi < ink.shape[0] else np.zeros(ink.shape[1], bool)
        signs[lo:hi, ~(above & below)] = 0
    n, _lab, st, _ = cv2.connectedComponentsWithStats(signs, 8)
    out = []
    for k in range(1, n):
        x, y, w, h, area = st[k]
        if area >= sp and y + h > T - 3 * sp and y < B + 3 * sp:
            out.append((int(x), int(x + w), int(y), int(y + h)))
    return sorted(out)


def _time_signature(c, T, B):
    """
    Chiffres de la mesure (4/4, 6/8…) en tête de la première ligne : deux signes l'un sur l'autre, chacun dans
    une moitié de la portée, à moins de 16 interlignes du début. Rend (début, fin) en x, ou None.
    """
    sp = (B - T) / 4
    mid = (T + B) / 2
    signs = _signs(c, T, B)
    start = min((s[0] for s in signs), default=0)
    for a in signs:
        if a[0] > start + 16 * sp:
            break
        top_ok = a[2] >= T - sp / 2 and a[3] <= mid + sp / 2 and 1.2 * sp <= a[3] - a[2] <= 2.6 * sp
        if not top_ok:
            continue
        for b in signs:
            overlap = min(a[1], b[1]) - max(a[0], b[0])
            if overlap > 0.5 * min(a[1] - a[0], b[1] - b[0]) and b[2] >= mid - sp / 2 and b[3] <= B + sp / 2 \
                    and 1.2 * sp <= b[3] - b[2] <= 2.6 * sp:
                return min(a[0], b[0]), max(a[1], b[1])
    return None




def _glyph(char, sp):
    """Signe de la police musicale dessiné à l'échelle de la portée (encre = 1), rogné."""
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(str(_music_font()), max(8, int(round(4 * sp))))
    img = Image.new("L", (int(6 * sp), int(8 * sp)), 0)
    ImageDraw.Draw(img).text((int(sp), int(5 * sp)), char, font=font, fill=255, anchor="ls")
    a = (np.array(img) > 127).astype(np.uint8)
    ys, xs = np.nonzero(a)
    return a[ys.min():ys.max() + 1, xs.min():xs.max() + 1]


def key_from_image(out_dir, layout):
    """
    Armure lue sur l'image des premières lignes : juste après la clé, signes étroits de 2 à 3,5 interlignes de
    haut, serrés les uns contre les autres (la clé est bien plus haute, les chiffres de mesure plus larges).
    Dièse ou bémol : forme la plus proche du dessin de la police musicale. Rend le nombre (dièses > 0,
    bémols < 0) le plus fréquent entre les voix, ou None.
    """
    if _music_font() is None:
        return None
    from preprocess import line_strokes
    info = json.loads((out_dir / "disposition.json").read_text(encoding="utf-8"))
    found = []
    for v, _voice in enumerate(LAYOUTS[layout]):
        T, B = info["lignes"][v][0]
        c = imgio.imread(str(out_dir / "lignes" / f"v{v + 1}-01.png"), cv2.IMREAD_GRAYSCALE)
        sp = (B - T) / 4
        strokes = line_strokes(c)
        rows = [strokes[max(0, int(round(T + k * sp)) - 2):int(round(T + k * sp)) + 3].any(0) for k in range(5)]
        starts = np.flatnonzero(np.sum(rows, axis=0) >= 3)
        left = int(starts[0]) if len(starts) else 0
        tall = [g for g in _signs(c, T, B) if g[0] > left + 0.3 * sp and g[3] - g[2] >= 4.5 * sp]
        after_clef = tall[0][1] if tall else left + 3 * sp  # la clé : premier grand signe
        accs = [g for g in _signs(c, T, B)
                if after_clef - 0.3 * sp <= g[0] <= after_clef + 9 * sp
                and 2.0 * sp <= g[3] - g[2] <= 3.35 * sp and 0.4 * sp <= g[1] - g[0] <= 1.7 * sp]  # chiffres de mesure : plus hauts
        group = accs[:1]
        for g in accs[1:]:
            if g[0] - group[-1][1] <= 1.0 * sp:
                group.append(g)
        if not group or group[0][0] - after_clef > 2.5 * sp:
            found.append(0)
            continue
        votes = 0
        for g in group:
            part = (c[g[2]:g[3], g[0]:g[1]] < 128).astype(np.float32)
            scores = []
            for char in ("\ue262", "\ue260"):
                tpl = cv2.resize(_glyph(char, sp).astype(np.float32), (part.shape[1], part.shape[0]))
                scores.append(float(cv2.matchTemplate(part, tpl, cv2.TM_CCOEFF_NORMED).max()))
            votes += 1 if scores[0] >= scores[1] else -1
        found.append(len(group) if votes >= 0 else -len(group))
    return statistics.mode(found) if found else None


# place des altérations de l'armure, en interlignes sous la 1re ligne (clé de sol ; clé de fa : 1 de plus) :
# fa do sol ré la mi si pour les dièses, si mi la ré sol do fa pour les bémols
_SHARP_AT = [0.0, 1.5, -0.5, 1.0, 2.5, 0.5, 2.0]
_FLAT_AT = [2.0, 0.5, 2.5, 1.0, 3.0, 1.5, 3.5]


def _key_sign_line(c, T, B, count):
    """
    Dièses ou bémols, d'après la place des signes de l'armure (pas leur forme, effacée sur une photo floue) : les
    dièses commencent en haut et descendent (fa, do), les bémols commencent au milieu et montent (si, mi). Hauteur
    moyenne de l'encre colonne par colonne après la clé, découpée en `count` signes ; rend +1 (dièses), -1 (bémols)
    ou 0 si la forme ne ressemble nettement à aucune des deux.
    """
    from preprocess import line_strokes
    sp = (B - T) / 4
    strokes = line_strokes(c)
    rows = [strokes[max(0, int(round(T + k * sp)) - 2):int(round(T + k * sp)) + 3].any(0) for k in range(5)]
    starts = np.flatnonzero(np.sum(rows, axis=0) >= 3)
    if not len(starts):
        return 0
    left = int(starts[0])
    ink = (c < 128).astype(np.uint8)
    for k in range(5):  # lignes de portée ôtées
        y = int(round(T + k * sp))
        band = slice(max(0, y - 2), y + 3)
        ink[band] &= (1 - strokes[band]).astype(np.uint8)
    y0, y1 = max(0, int(T - 2.5 * sp)), min(c.shape[0], int(B + 1.5 * sp))
    xs = np.arange(left, min(c.shape[1], int(left + (count + 6) * sp)))
    weight = ink[y0:y1, xs].sum(0).astype(np.float64)
    centre = np.where(weight > 0, (ink[y0:y1, xs] * np.arange(y0, y1)[:, None]).sum(0) / np.maximum(weight, 1), np.nan)
    centre = (centre - T) / sp
    if count == 1:
        return 0  # un seul signe : sa place dépend de la clé, la forme seule ne départage pas sûrement
    best = (0.0, 0)
    sharp, flat = np.array(_SHARP_AT[:count]), np.array(_FLAT_AT[:count])
    for start in range(int(1.8 * sp), int(4.8 * sp)):
        for w in (0.9, 1.0, 1.1, 1.2):
            slots = []
            for i in range(count):
                a, b = int(start + i * w * sp), int(start + (i + 1) * w * sp)
                seg = centre[a:b]
                seg = seg[~np.isnan(seg)]
                if len(seg) < 0.3 * w * sp:
                    break
                slots.append(float(np.median(seg)))
            if len(slots) < count or np.std(slots) < 0.3:
                continue
            for pattern, sign in ((sharp, 1), (flat, -1)):
                r = float(np.corrcoef(slots, pattern)[0, 1])
                if r > best[0]:
                    best = (r, sign)
    return best[1] if best[0] >= 0.85 else 0


def key_sign_from_image(out_dir, layout, count):
    """
    Sens de l'armure (dièses +1, bémols -1, 0 inconnu) sur les premières lignes de chaque voix, `count` signes lus
    ailleurs (homr confond dièses et bémols sur photo floue : 4 bémols lus pour 4 dièses). Majorité nette des voix.
    """
    if count < 2:
        return 0
    try:
        info = json.loads((out_dir / "disposition.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    votes = []
    for v in range(len(LAYOUTS[layout])):
        f = out_dir / "lignes" / f"v{v + 1}-01.png"
        if not f.exists() or v >= len(info.get("lignes", [])):
            continue
        T, B = info["lignes"][v][0]
        c = imgio.imread(str(f), cv2.IMREAD_GRAYSCALE)
        if c is not None:
            votes.append(_key_sign_line(c, T, B, count))
    plus, minus = votes.count(1), votes.count(-1)
    return 1 if plus > minus else -1 if minus > plus else 0


# ---------------------------------------------------------------------------------------------------------------
# Paroles lues sur l'image (RapidOCR, qui accompagne homr) : bien plus fidèle que la lecture du texte d'Audiveris

_OCR = None


def _ocr():
    global _OCR
    if _OCR is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        except Exception:  # noqa: BLE001 : pas de lecteur de texte : paroles d'Audiveris
            _OCR = False
    return _OCR or None


def _tokens(text, x0, x1):
    """Syllabes d'un mot ou d'un groupe de mots lu (« dam-ba kata-nu »), chacune avec sa place en x (au prorata)."""
    import re
    out = []
    n = max(1, len(text))
    for m in re.finditer(r"[^\s\-_–—]+", text):
        word = m.group(0).strip(".,;:!?«»\"'()[]")
        if _syllable(word):
            out.append(((x0 + (x1 - x0) * (m.start() + m.end()) / 2 / n), word))
    return out


def read_lyrics(bw, staff, below):
    """
    Lignes de paroles sous une portée (jusqu'à la portée suivante) : [(x, syllabe, couplet)], couplet 1 = la
    ligne du haut. below : haut de la portée suivante (ou bas de page).
    """
    ocr = _ocr()
    if ocr is None:
        return []
    top, bottom = staff[0], staff[1]
    sp = (bottom - top) / 4
    y0 = int(bottom + 1.0 * sp)
    y1 = int(min(below - 2.5 * sp, bottom + 10 * sp))
    if y1 - y0 < 2 * sp:
        return []
    band = bw[y0:y1]
    res, _ = ocr(cv2.cvtColor(band, cv2.COLOR_GRAY2BGR))
    boxes = []
    for box, text, score in res or []:
        if float(score) < 0.5:
            continue
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        if max(ys) - min(ys) > 2.2 * sp:  # pas une ligne de texte (bout de portée, notes)
            continue
        boxes.append(((min(ys) + max(ys)) / 2, min(xs), max(xs), text, max(ys) - min(ys)))
    boxes.sort()
    lines = []  # lignes de texte (couplets), de haut en bas : une boîte va à la ligne dont le milieu est proche
    for yc, x0, x1, text, h in boxes:
        line = next((ln for ln in lines if abs(ln["y"] - yc) < 0.6 * h), None)
        if line is None:
            line = {"y": yc, "boxes": []}
            lines.append(line)
        line["boxes"].append((x0, x1, text))
    out = []
    for verse, line in enumerate(sorted(lines, key=lambda ln: ln["y"]), 1):
        for x0, x1, text in sorted(line["boxes"]):
            out += [(x, t, verse) for x, t in _tokens(text, x0, x1)]
    return sorted(out, key=lambda e: (e[2], e[0]))


if __name__ == "__main__":
    args = sys.argv[1:]
    groups = {"--notes": [], "--variantes": []}
    for flag in groups:  # chaque option prend les arguments qui la suivent jusqu'à la suivante
        if flag in args:
            k = args.index(flag)
            end = min([args.index(o) for o in groups if o != flag and o in args and args.index(o) > k] + [len(args)])
            groups[flag], args = args[k + 1:end], args[:k] + args[end:]
    notes = groups["--notes"] or None
    if len(args) < 2 or (len(args) < 3 and not notes):
        sys.exit(__doc__)
    assemble(args[0], args[1], args[2:], notes, groups["--variantes"] or None)
