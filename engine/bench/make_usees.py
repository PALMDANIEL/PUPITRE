"""
Banc d'essai des copies abîmées : mêmes chorals de Bach que make_corpus.py (notes exactes connues), mais passés dans une
simulation de photocopie ou de vieux scan en noir et blanc :
  - « copie » : lignes de portée en tirets, quelques queues et barres de mesure cassées, petites taches ;
  - « usee »  : tout cela en plus fort (comme « Fa damba ka ta nu » : portées en pointillés, barres coupées, trous
    dans les notes, centaines de taches), légère rotation.
Deux mises en page (ouverte = 4 portées, fermée = 2 portées), comme le banc de base.

Usage : bench-venv/bin/python make_usees.py <dossier> [nombre_de_chorals]
Chaque cas : <dossier>/<choral>-<mise en page>-<niveau>/source.pdf + truth.json.
"""
import json, pathlib, sys

import cv2
import numpy as np

import make_corpus as base

LEVELS = {
    # lignes en tirets, trous (pixels), queues cassées, taches par mégapixel, rotation maximale, flou
    "copie": dict(dash=0.30, holes=0.025, breaks=0.010, specks=160, rot=0.6, blur=0.9),
    "usee": dict(dash=0.60, holes=0.070, breaks=0.035, specks=520, rot=1.2, blur=1.1),
}


def blocks(rng, shape, cell, p):
    """Masque de blocs aléatoires (cell = (haut, large) d'un bloc), vrai avec la probabilité p."""
    h, w = shape
    ch, cw = cell
    small = rng.random((h // ch + 1, w // cw + 1)) < p
    return np.kron(small, np.ones((ch, cw), bool))[:h, :w]


def as_photocopy(img, seed, level):
    rng = np.random.default_rng(seed)
    cfg = LEVELS[level]
    h, w = img.shape
    ink = img < 128
    # 1) lignes de portée : longs traits horizontaux, coupés par morceaux (tirets de 8 à 60 px)
    lines = cv2.morphologyEx(ink.astype(np.uint8), cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (w // 12, 1))) > 0
    for _ in range(1):
        dash = blocks(rng, (h, w), (3, int(rng.integers(8, 20))), cfg["dash"]) | blocks(rng, (h, w), (3, int(rng.integers(30, 60))), cfg["dash"] / 3)
        ink &= ~(lines & dash)
    # 2) trous dans les notes, les queues, les ligatures (petits blocs 3 × 3)
    ink &= ~blocks(rng, (h, w), (3, 3), cfg["holes"])
    # 3) queues et barres de mesure cassées (blocs hauts et fins)
    ink &= ~blocks(rng, (h, w), (14, 2), cfg["breaks"])
    # 4) taches
    page = np.where(ink, 0, 255).astype(np.uint8)
    for _ in range(int(cfg["specks"] * h * w / 1e6)):
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        cv2.circle(page, (x, y), int(rng.integers(1, 4)), 0, -1)
    # 5) rotation, flou, bruit, puis noir et blanc (copie)
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), float(rng.uniform(-cfg["rot"], cfg["rot"])), 1.0)
    page = cv2.warpAffine(page, rot, (w, h), borderValue=255).astype(np.float32)
    page = cv2.GaussianBlur(page, (0, 0), cfg["blur"]) + rng.normal(0, 6, page.shape)
    return np.where(page < 170, 0, 255).astype(np.uint8)


def main(out, count):
    out = pathlib.Path(out)
    made = 0
    for work in base.CHORALES:
        if made >= count:
            break
        parts = base.four_parts(work)
        if not parts:
            continue
        made += 1
        t = base.truth(parts)
        for layout_name, build in (("ouverte", base.open_score), ("fermee", base.closed_score)):
            tmp = out / "_gravure"
            tmp.mkdir(parents=True, exist_ok=True)
            pages = base.engrave(build(parts), tmp / f"{work}-{layout_name}")
            for level in LEVELS:
                case = out / f"{work}-{layout_name}-{level}"
                case.mkdir(parents=True, exist_ok=True)
                (case / "truth.json").write_text(json.dumps(t), encoding="utf-8")
                base.save_pdf([as_photocopy(p, sum(map(ord, work)) + i, level) for i, p in enumerate(pages)], case / "source.pdf")
                print(case.name, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 6)
