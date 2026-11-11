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
ORPHANS = os.environ.get("PUPITRE_TETES_ORPHELINES", "1") == "1"  # têtes non lues par Audiveris rangées par leur queue


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
        lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(2 * sp0), 1)))
        bars = bar_mask(img)
        for side, keep in KEEP.items():
            a = erase_other(img, mine, keep, lines)
            a = np.where(bars > 0, img, a).astype(np.uint8)  # barres de mesure rendues (une queue effacée les entamait)
            imgio.imwrite(str(out / side / "pages" / pathlib.Path(page).name), a)
    return True


def bar_mask(img):
    """Barres de mesure de la page (traits qui traversent une portée sans tête accolée), à rendre après l'effacement."""
    import pupitres
    mask = np.zeros(img.shape, np.uint8)
    for t, b, _l, _r in pupitres.find_staves(img):
        sp = (b - t) / 4
        for x0, x1 in pupitres._bar_runs(img, (t, b, _l, _r), sp):
            mask[int(round(t)) - 1:int(round(b)) + 2, max(0, x0 - 1):x1 + 2] = 1
    return mask


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
    return np.where(lines > 0, 0, a).astype(np.uint8)  # lignes de portée rendues


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
