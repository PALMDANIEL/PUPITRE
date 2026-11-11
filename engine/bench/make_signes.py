"""
Exemples pour apprendre à reconnaître les altérations (♯ ♮ ♭) à gauche d'une tête de note : chorals de Bach du corpus de
music21 (jamais ceux du banc d'essai), gravés par Verovio (positions exactes de chaque tête et de chaque signe dans le SVG),
à plusieurs tailles de portée, dégradés comme des photos (flou, bruit, JPEG, taille réduite, traits épaissis ou amincis,
taches), noircis comme les pages du moteur, puis découpés exactement comme signes.read_signs : de 2,8 interlignes à gauche
du bord gauche de la tête jusqu'à elle, 2,2 interlignes au-dessus et au-dessous.

Usage : bench-venv/bin/python make_signes.py <sortie.npz> [nombre_de_chorals]
"""
import copy, pathlib, re, sys, tempfile
import xml.etree.ElementTree as ET

import cairosvg, cv2, numpy as np, verovio
from music21 import corpus

import make_corpus as mc

BENCH = {"bwv269", "bwv347", "bwv153.1", "bwv86.6", "bwv267", "bwv281", "bwv40.6", "bwv244.3", "bwv66.6", "bwv145.5"}
LABELS = {"E262": 1, "E261": 2, "E260": 3}  # dièse, bécarre, bémol ; 0 : rien
PATCH_W, PATCH_H = 16, 26
WORN = "--usees" in sys.argv  # seulement des copies usées (complément du jeu d'exemples)
SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"


def patch(img, x_left, y, sp):
    """Encre (0 à 1) à gauche de la tête, ramenée à PATCH_H × PATCH_W."""
    x0, x1 = int(round(x_left - 2.8 * sp)), int(round(x_left - 0.05 * sp))
    y0, y1 = int(round(y - 2.2 * sp)), int(round(y + 2.2 * sp))
    H, W = img.shape
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H or x1 - x0 < 4:
        return None
    reg = (img[y0:y1, x0:x1] < 128).astype(np.float32)
    return cv2.resize(reg, (PATCH_W, PATCH_H), interpolation=cv2.INTER_AREA)


def notes_of(svg_text, width_px):
    root = ET.fromstring(svg_text)
    inner = next(e for e in root.iter(SVG + "svg") if e.get("viewBox"))
    vb_w = float(inner.get("viewBox").split()[2])
    k = width_px / vb_w
    margin = next((e for e in root.iter(SVG + "g") if e.get("class") == "page-margin"), None)
    mx, my = (float(v) for v in re.findall(r"[-\d.]+", margin.get("transform"))[:2]) if margin is not None else (0, 0)
    staff_sp = None
    out = []
    for g in root.iter(SVG + "g"):
        if g.get("class") != "note":
            continue
        head = next((u for h in g.iter(SVG + "g") if h.get("class") == "notehead" for u in h.iter(SVG + "use")), None)
        if head is None:
            continue
        tx, ty = (float(v) for v in re.findall(r"translate\(([-\d.]+),\s*([-\d.]+)\)", head.get("transform"))[0])
        label = 0
        for a in g.iter(SVG + "g"):
            if a.get("class") == "accid":
                for u in a.iter(SVG + "use"):
                    code = u.get(XLINK, "")[1:5]
                    label = LABELS.get(code, label)
        out.append(((tx + mx) * k, (ty + my) * k, label))
    return out, k


def wear(img, rng):
    """Vieille photocopie : lignes de portée en pointillés (60 % effacés), traits rongés, taches."""
    bw = np.where(img < 128, 0, 255).astype(np.uint8)
    ink = (bw < 128).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1)))
    ys, xs = np.nonzero(lines)
    gaps = np.zeros_like(lines)
    for _ in range(int(rng.integers(1500, 4000))):
        if not len(ys):
            break
        i = int(rng.integers(0, len(ys)))
        gaps[max(0, ys[i] - 2):ys[i] + 3, xs[i]:xs[i] + int(rng.integers(6, 30))] = 1
    bw[(gaps > 0) & (lines > 0)] = 255
    if rng.random() < 0.6:  # traits rongés
        noise = rng.random(bw.shape) < float(rng.uniform(0.02, 0.08))
        bw[noise & (bw == 0)] = 255
    n = int(rng.integers(800, 3000))  # taches
    for y, x in zip(rng.integers(0, bw.shape[0], n), rng.integers(0, bw.shape[1], n)):
        cv2.circle(bw, (int(x), int(y)), int(rng.integers(1, 3)), 0, -1)
    if rng.random() < 0.4:
        bw = cv2.erode(bw, np.ones((2, 2), np.uint8))  # photocopie plus noire
    return bw


def degrade(img, rng, worn=False):
    """Une version dégradée de la page (puis noircie comme les pages du moteur)."""
    if worn:
        return wear(img, rng)
    a = img.astype(np.float32)
    kind = rng.integers(0, 6)
    if kind >= 1:
        a = cv2.GaussianBlur(a, (0, 0), float(rng.uniform(0.6, 2.8)))
    if kind >= 2:
        a = a + rng.normal(0, rng.uniform(4, 22), a.shape)
    a = np.clip(a, 0, 255).astype(np.uint8)
    if kind in (3, 5):  # WhatsApp : page réduite puis JPEG puis remise à la taille
        h, w = a.shape
        f = float(rng.uniform(0.4, 0.65))
        small = cv2.resize(a, (int(w * f), int(h * f)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(30, 70))])
        a = cv2.resize(cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE), (w, h), interpolation=cv2.INTER_CUBIC)
    if kind >= 1 and rng.random() < 0.7:
        bw = cv2.adaptiveThreshold(a, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, int(rng.integers(8, 20)))
    else:
        bw = np.where(a < 128, 0, 255).astype(np.uint8)
    if rng.random() < 0.25:
        k = np.ones((2, 2), np.uint8)
        bw = cv2.erode(bw, k) if rng.random() < 0.5 else cv2.dilate(bw, k)  # traits épaissis / amincis
    if rng.random() < 0.3:  # taches
        n = int(rng.integers(200, 1500))
        ys, xs = rng.integers(0, bw.shape[0], n), rng.integers(0, bw.shape[1], n)
        for y, x in zip(ys, xs):
            cv2.circle(bw, (int(x), int(y)), int(rng.integers(1, 3)), 0, -1)
    return bw


def main(out, count):
    rng = np.random.default_rng(7)
    works = [w for w in corpus.chorales.Iterator(returnType="filename")][:400]
    works = [w for w in works if not any(b in str(w) for b in BENCH)]
    rng.shuffle(works)
    if WORN:  # d'autres chorals que le premier jeu
        works = works[200:] + works[:200]
        rng = np.random.default_rng(11)
    X, Y, G = [], [], []  # G : numéro du choral (pour séparer apprentissage et contrôle)
    done = 0
    for wi, w in enumerate(works):
        if done >= count:
            break
        try:
            parts = mc.four_parts(w)
        except Exception:  # noqa: BLE001
            continue
        if not parts:
            continue
        for layout in ("ouverte", "fermee"):
            sc = mc.open_score(parts) if layout == "ouverte" else mc.closed_score(parts)
            with tempfile.TemporaryDirectory() as t:
                xml = pathlib.Path(t) / "c.musicxml"
                try:
                    sc.write("musicxml", fp=str(xml))
                except Exception:  # noqa: BLE001
                    continue
                for scale in (36, 45, 54):
                    tk = verovio.toolkit()
                    tk.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": scale, "adjustPageHeight": False,
                                   "footer": "none", "header": "auto", "breaks": "auto"})
                    if not tk.loadFile(str(xml)):
                        continue
                    svg = tk.renderToSVG(1)
                    png = cairosvg.svg2png(bytestring=svg.encode(), output_width=2480, background_color="white")
                    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
                    notes, k = notes_of(svg, 2480)
                    sp = 180 * k  # interligne : 180 unités de Verovio
                    starts = staff_starts(img, sp)
                    for rep in range(3):
                        page = degrade(img, rng, WORN) if rep or WORN else np.where(img < 128, 0, 255).astype(np.uint8)
                        for x, y, label in notes:
                            if any(abs(y - ys) < 4 * sp and x - xs < 9 * sp for ys, xs in starts):
                                continue  # tête de ligne : l'armure est à gauche (le moteur ne lit pas de signe ici)
                            if label == 0 and rng.random() > 0.35:
                                continue  # assez de négatifs
                            jx, jy = rng.uniform(-0.3, 0.3) * sp, rng.uniform(-0.15, 0.15) * sp
                            p = patch(page, x + jx, y + jy, sp)
                            if p is not None:
                                X.append(p); Y.append(label); G.append(wi)
        done += 1
        print(f"{done}/{count} {pathlib.Path(str(w)).name} : {len(X)} exemples, signes {sum(1 for v in Y if v)}", flush=True)
    np.savez_compressed(out, X=np.array(X, np.float32), Y=np.array(Y, np.int8), G=np.array(G, np.int16))


def staff_starts(img, sp):
    """(hauteur du milieu, bord gauche) des portées de la page."""
    ink = (img < 128).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(6 * sp), 1)))
    rows = np.flatnonzero(lines.sum(1) > 0)
    out = []
    if not rows.size:
        return out
    groups = np.split(rows, np.flatnonzero(np.diff(rows) > 1.5 * sp) + 1)
    for g in groups:
        cols = np.flatnonzero(lines[g[0]:g[-1] + 1].any(0))
        if cols.size:
            out.append(((g[0] + g[-1]) / 2, int(cols[0])))
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--usees"]
    main(args[0], int(args[1]) if len(args) > 1 else 60)
