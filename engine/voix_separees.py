"""
Deux voix par portée (S/A sur la portée de sol, T/B sur celle de fa) : homr lit mal ces accords à deux voix (il n'écrit
qu'un rythme par portée), alors qu'il lit très bien une voix seule. La page est donc séparée en deux pages : la voix du
haut (queues en haut) et la voix du bas (queues en bas), d'après la lecture d'Audiveris replacée sur l'image (signes.place) :
chaque tête de l'autre voix est effacée avec sa queue (et son altération si rien de la voix gardée n'est à côté), les
lignes de portée sont rendues. homr lit ensuite chaque page portée par portée, et les deux lectures sont réunies en une
partition à deux voix par portée, arbitrée mesure par mesure avec celle d'Audiveris (arbitre.py).

Banc local (PDF nets à deux portées) : homr sur voix séparées retrouve les notes qu'Audiveris perd (alto de bwv269
fermée 88 → 97 %), Audiveris reste meilleur sur les altérations : les deux lectures se complètent.
"""
import copy
import os
import pathlib

import cv2
import numpy as np

import imgio
import signes

KEEP = {"haut": "up", "bas": "down"}
ORPHANS = os.environ.get("PUPITRE_TETES_ORPHELINES", "1") == "1"
STRUCTURES = os.environ.get("PUPITRE_LIGATURES", "1") == "1"  # ligatures et crochets de l'autre voix effacés  # têtes non lues par Audiveris rangées par leur queue


def split_pages(mxl, pages, out: pathlib.Path) -> bool:
    """Écrit out/haut/pages/page-NN.png et out/bas/pages/page-NN.png. Rend False si une page n'a pas pu être séparée
    (moins de 80 % des notes d'Audiveris replacées sur l'image)."""
    root, _ = signes._read(mxl)
    notes, pw = signes.notes_of(root)
    for side in KEEP:
        (out / side / "pages").mkdir(parents=True, exist_ok=True)
    for k, page in enumerate(pages):
        img = imgio.imread(str(page), cv2.IMREAD_GRAYSCALE)
        if img is None:
            return False
        total = sum(1 for n in notes if n["page"] == k)
        mine = signes.place(notes, pw, img, k)
        if not total or len(mine) < 0.8 * total:
            return False
        ink = (img < 128).astype(np.uint8)
        sp0 = float(np.median([n["sp"] for n in mine]))
        lines = staff_lines(img, ink, sp0)
        bars = bar_mask(img)
        for side, keep in KEEP.items():
            a = erase_other(img, mine, keep, lines)
            a = np.where(bars > 0, img, a).astype(np.uint8)  # barres de mesure rendues (une queue effacée les entamait)
            imgio.imwrite(str(out / side / "pages" / pathlib.Path(page).name), a)
    return True


def staff_lines(img, ink, sp0):
    """Lignes des portées seulement (traits horizontaux longs sur les cinq lignes de chaque portée) : une ligature est
    aussi un long trait, elle ne doit pas être protégée comme une ligne."""
    import pupitres
    long_ = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(2 * sp0), 1)))
    rows = np.zeros(img.shape, np.uint8)
    for t, b, _l, _r in pupitres.find_staves(img):
        sp = (b - t) / 4
        for k in range(5):
            y = t + k * sp
            rows[max(0, int(y - 0.3 * sp)):int(y + 0.3 * sp) + 1, :] = 1
    return long_ & rows


def bar_mask(img):
    """Barres de mesure de la page (traits qui traversent une portée sans tête accolée), à rendre après l'effacement."""
    import pupitres
    mask = np.zeros(img.shape, np.uint8)
    for t, b, _l, _r in pupitres.find_staves(img):
        sp = (b - t) / 4
        for x0, x1 in pupitres._bar_runs(img, (t, b, _l, _r), sp):
            mask[int(round(t)) - 1:int(round(b)) + 2, max(0, x0 - 1):x1 + 2] = 1
    return mask


def mend_lines(a, lines, n, xa, xb):
    """Lignes de portée redessinées sous une tête effacée (photo : retrouvées de part et d'autre de la tête, à leur
    hauteur et leur épaisseur locales ; sinon les lignes restaient trouées et homr lisait mal la page)."""
    t, b = n["staff_tb"]
    sp = (b - t) / 4
    H, W = a.shape
    w = max(4, int(2 * sp))
    for k in range(5):
        yk = t + k * sp
        lo, hi = max(0, int(yk - 0.35 * sp)), min(H, int(yk + 0.35 * sp) + 1)
        left = lines[lo:hi, max(0, xa - w):max(0, xa)]
        right = lines[lo:hi, min(W, xb):min(W, xb + w)]
        rows = (left.sum(1) if left.size else 0) + (right.sum(1) if right.size else 0)
        if np.ndim(rows) == 0 or rows.max() < 0.3 * w:
            continue
        on = np.flatnonzero(rows >= 0.5 * rows.max())
        a[lo + on[0]:lo + on[-1] + 1, max(0, xa):min(W, xb)] = 0


def erase_other(img, mine, keep, lines):
    """Image où ne restent que les notes dont la queue va dans le sens keep."""
    a = img.copy()
    kept = [m for m in mine if (m["el"].findtext("stem") or "") == keep]
    H, W = a.shape
    for n in mine:
        stem = n["el"].findtext("stem") or ""
        if stem == keep or stem not in ("up", "down"):
            continue
        x, y = n["xy"]
        sp = n["sp"]
        hx = n.get("head") if n.get("head") is not None else x - 0.65 * sp
        x0, x1 = int(hx - 0.1 * sp), int(hx + 1.45 * sp)
        # unisson (une tête, deux queues) : la tête reste pour la voix gardée
        twin = any(abs(m["xy"][0] - x) < 0.6 * sp and abs(m["xy"][1] - y) < 0.3 * sp for m in kept)
        if not twin:
            cv2.ellipse(a, (int((x0 + x1) / 2), int(y)), (int(0.78 * sp), int(0.62 * sp)), -20, 0, 360, 255, -1)
            mend_lines(a, lines, n, x0 - int(0.3 * sp), x1 + int(0.3 * sp))
            if n["acc"]:
                near = any(abs(m["xy"][0] - (hx - 1.2 * sp)) < 1.4 * sp and abs(m["xy"][1] - y) < 1.5 * sp for m in kept)
                if not near:
                    a[max(0, int(y - 1.6 * sp)):min(H, int(y + 1.6 * sp)), max(0, int(hx - 2.4 * sp)):max(0, int(hx - 0.15 * sp))] = 255
        # queue (et crochets, ligatures qui s'y accrochent) : à gauche vers le bas, à droite vers le haut
        if stem == "down":
            a[int(y + 0.3 * sp):min(H, int(y + 4.3 * sp)), max(0, x0 - 3):max(0, x0 + int(0.35 * sp))] = 255
        else:
            a[max(0, int(y - 4.3 * sp)):max(0, int(y - 0.3 * sp)), max(0, x1 - int(0.35 * sp)):min(W, x1 + 3)] = 255
    if ORPHANS:
        a = erase_orphans(img, a, mine, keep, lines)
    if STRUCTURES:
        a = erase_structures(img, a, mine, kept, keep, lines)
    return np.where(lines > 0, 0, a).astype(np.uint8)  # lignes de portée rendues


def erase_structures(img, a, mine, kept, keep, lines):
    """Queues, ligatures et crochets de l'autre voix effacés d'un seul tenant : l'encre (lignes ôtées) qui touche la
    queue d'une tête effacée et ne touche aucune tête gardée (une ligature restée seule passait pour un rythme)."""
    H, W = a.shape
    ink = ((a < 128) & (lines == 0)).astype(np.uint8)
    n_c, lab, st, _c = cv2.connectedComponentsWithStats(ink, connectivity=8)
    if n_c <= 1:
        return a
    sp0 = float(np.median([n["sp"] for n in mine]))
    w_, h_ = st[:, cv2.CC_STAT_WIDTH], st[:, cv2.CC_STAT_HEIGHT]
    # forme d'une queue (haute et mince), d'une ligature ou d'un crochet (long et plat) ; pas d'une lettre des paroles
    shaped = ((h_ >= 2.0 * sp0) & (w_ <= 1.0 * sp0)) | ((w_ >= 1.3 * sp0) & (h_ <= 1.6 * sp0)) | \
             ((w_ >= 1.3 * sp0) & (h_ >= 2.0 * sp0))
    hit, safe = np.zeros(n_c, bool), np.zeros(n_c, bool)
    for n in mine:
        stem = n["el"].findtext("stem") or ""
        if stem not in ("up", "down"):
            continue
        x, y = n["xy"]
        sp = n["sp"]
        hx = n.get("head") if n.get("head") is not None else x - 0.65 * sp
        x0, x1 = int(hx - 0.1 * sp), int(hx + 1.45 * sp)
        if stem == keep:  # tête gardée et sa queue : leur encre est à garder
            zone = lab[max(0, int(y - 0.6 * sp)):min(H, int(y + 0.6 * sp)), max(0, x0):min(W, x1)]
            safe[np.unique(zone)] = True
            continue
        # bout de la queue effacée (au-delà de la zone déjà blanchie) : la ligature ou le crochet s'y accroche
        if stem == "down":
            zone = lab[min(H - 1, int(y + 2.3 * sp)):min(H, int(y + 4.6 * sp)),
                       max(0, x0 - int(0.6 * sp)):min(W, x0 + int(0.8 * sp))]
        else:
            zone = lab[max(0, int(y - 4.6 * sp)):max(1, int(y - 2.3 * sp)),
                       max(0, x1 - int(0.8 * sp)):min(W, x1 + int(0.6 * sp))]
        hit[np.unique(zone)] = True
    hit[0] = safe[0] = False
    drop = hit & ~safe & shaped
    if drop.any():
        a = a.copy()
        a[drop[lab]] = 255
    return a


def erase_orphans(img, a, mine, keep, lines):
    """
    Têtes pleines qu'Audiveris n'a pas lues (elles resteraient sur les deux pages, lues dans les deux voix) : rangées
    d'après le sens de leur queue sur l'image (vers le bas depuis le bord gauche : voix du bas ; vers le haut depuis le bord
    droit : voix du haut), effacées de la page de l'autre voix. Deux queues (unisson) ou aucune : la tête reste.
    """
    ink = (img < 128).astype(np.uint8)
    body = ink & (1 - lines)
    sp0 = float(np.median([n["sp"] for n in mine]))
    k = max(3, int(0.55 * sp0)) | 1
    heads = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    _nb, _lab, st, cen = cv2.connectedComponentsWithStats(heads, 8)
    H, W = a.shape
    known = np.array([n["xy"] for n in mine], float) if mine else np.zeros((0, 2))
    for s_, (cx, cy) in zip(st[1:], cen[1:]):
        x, y, w, h = s_[:4]
        if not (0.6 * sp0 <= h <= 1.6 * sp0 and 0.8 * sp0 <= w <= 2.2 * sp0) or w > 1.7 * sp0:
            continue  # pas une tête seule (deux têtes collées : on ne devine pas)
        if len(known) and (np.hypot(known[:, 0] - cx, (known[:, 1] - cy) * 2) < 0.9 * sp0).any():
            continue  # tête lue par Audiveris : déjà traitée
        reach = int(2.5 * sp0)
        up = body[max(0, y - reach):y, max(0, x + w - 4):min(W, x + w + 2)].any(1).mean() if y > reach else 0.0
        down = body[y + h:min(H, y + h + reach), max(0, x - 2):min(W, x + 4)].any(1).mean() if y + h + reach < H else 0.0
        stem = "up" if up >= 0.9 and down < 0.5 else "down" if down >= 0.9 and up < 0.5 else None
        if stem is None or stem == keep:
            continue
        cv2.ellipse(a, (int(cx), int(cy)), (int(0.78 * sp0), int(0.62 * sp0)), -20, 0, 360, 255, -1)
        if stem == "down":
            a[y + h // 2:min(H, y + h + reach + int(1.5 * sp0)), max(0, x - 3):min(W, x + 5)] = 255
        else:
            a[max(0, y - reach - int(1.5 * sp0)):y + h // 2, max(0, x + w - 5):min(W, x + w + 3)] = 255
    return a


def combine(up_path, down_path, out) -> bool:
    """Lectures de homr des deux pages (une voix par portée) réunies : chaque portée porte la voix 1 (haut) et la voix 2
    (bas). Rend False si les découpages ne se correspondent pas."""
    from music21 import converter, stream
    a, b = converter.parse(str(up_path)), converter.parse(str(down_path))
    if len(a.parts) != len(b.parts) or not a.parts:
        return False
    score = stream.Score()
    for pa, pb in zip(a.parts, b.parts):
        ma, mb = list(pa.getElementsByClass(stream.Measure)), list(pb.getElementsByClass(stream.Measure))
        if len(ma) != len(mb) or not ma:
            return False
        part = stream.Part()
        part.partName = pa.partName or ""
        at = 0.0
        for x, y in zip(ma, mb):
            m = stream.Measure(number=x.number)
            for el in x.getElementsByClass(("Clef", "KeySignature", "TimeSignature")):
                m.insert(0, copy.deepcopy(el))
            for i, src in enumerate((x, y), 1):
                v = stream.Voice(id=str(i))
                for n in src.recurse().notesAndRests:
                    v.insert(float(n.getOffsetInHierarchy(src)), copy.deepcopy(n))
                m.insert(0, v)
            part.insert(at, m)
            at += float(max(x.duration.quarterLength, y.duration.quarterLength))
        score.insert(0, part)
    score.write("musicxml", fp=str(out))
    return True
