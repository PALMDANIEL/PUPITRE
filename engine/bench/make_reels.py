"""
Banc d'essai des conditions réelles : mêmes chorals de Bach que make_corpus.py (notes exactes connues), photographiés
comme le font vraiment les chorales, pour trouver les défaillances avant les utilisateurs :
  - « whatsapp » : photo envoyée comme image par WhatsApp (1280 px de haut au plus, JPEG très compressé) ;
  - « sombre »   : pièce mal éclairée, ombre du téléphone sur la page, contraste faible, bruit du capteur ;
  - « penchee »  : téléphone tenu de biais (perspective forte), page tournée de quelques degrés et bombée (livret) ;
  - « floue »    : mise au point manquée, léger bougé ;
  - « dense »    : recueil à petites portées (gravure serrée), photographié normalement.
Deux mises en page (ouverte = 4 portées, fermée = 2 portées), comme le banc de base.

Usage : bench-venv/bin/python make_reels.py <dossier> [nombre_de_chorals] [conditions séparées par des virgules]
Chaque cas : <dossier>/<choral>-<mise en page>-<condition>/source.jpg + truth.json.
"""
import json, pathlib, sys

import cv2
import numpy as np

import make_corpus as base


def lighting(img, rng, lo, hi, shadow=0.0):
    """Éclairage inégal (dégradé en diagonale), coins plus sombres, ombre douce posée sur la page."""
    h, w = img.shape
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = rng.uniform(0, 2 * np.pi)
    t = ((xx / w - 0.5) * np.cos(a) + (yy / h - 0.5) * np.sin(a)) + 0.5
    light = lo + (hi - lo) * np.clip(t, 0, 1)
    light *= 1 - 0.18 * (((xx / w - 0.5) ** 2 + (yy / h - 0.5) ** 2) * 2)
    if shadow:
        cx, cy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.3, 0.9) * h
        r = rng.uniform(0.25, 0.4) * w
        blob = np.exp(-(((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)))
        light *= 1 - shadow * blob
    return img.astype(np.float32) * light


def perspective(img, rng, amount, rot, bend=0.0, border=70):
    h, w = img.shape
    d = w * amount
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[rng.uniform(0, d), rng.uniform(0, d)], [w - rng.uniform(0, d), rng.uniform(0, d)],
                      [w - rng.uniform(0, d), h - rng.uniform(0, d)], [rng.uniform(0, d), h - rng.uniform(0, d)]])
    out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h), borderValue=border)
    M = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-rot, rot), 1.0)
    out = cv2.warpAffine(out, M, (w, h), borderValue=border)
    if bend:  # page bombée : les lignes se courbent, plus près de la reliure (à gauche)
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        dy = bend * h * np.sin(np.pi * xx / w) * (1 - xx / w) * (yy / h - 0.5) * 2
        out = cv2.remap(out, xx, yy + dy, cv2.INTER_LINEAR, borderValue=border)
    return out


def finish(img, rng, noise, long_side, quality):
    out = np.clip(img + rng.normal(0, noise, img.shape), 0, 255).astype(np.uint8)
    k = long_side / max(out.shape)
    out = cv2.resize(out, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])
    return cv2.imdecode(buf, cv2.IMREAD_GRAYSCALE)


def whatsapp(img, rng):
    page = perspective(lighting(img, rng, 0.8, 0.97) - 8, rng, 0.015, 1.5)
    return finish(cv2.GaussianBlur(page, (0, 0), 1.0), rng, 5, 1280, 55)


def sombre(img, rng):
    page = lighting(img, rng, 0.32, 0.85, shadow=0.45) * 0.85 + 18  # noir délavé : contraste faible
    page = perspective(page, rng, 0.02, 2.0, border=30)
    return finish(cv2.GaussianBlur(page, (0, 0), 1.2), rng, 10, 2000, 72)


def penchee(img, rng):
    page = perspective(lighting(img, rng, 0.75, 0.97) - 10, rng, 0.08, 4.0, bend=0.012)
    return finish(cv2.GaussianBlur(page, (0, 0), 1.0), rng, 6, 2000, 78)


def floue(img, rng):
    page = perspective(lighting(img, rng, 0.8, 0.97) - 8, rng, 0.02, 2.0)
    page = cv2.GaussianBlur(page, (0, 0), 3.0)
    k = np.zeros((9, 9), np.float32)
    k[4, :] = 1 / 9  # léger bougé horizontal
    page = cv2.filter2D(page, -1, cv2.warpAffine(k, cv2.getRotationMatrix2D((4, 4), rng.uniform(0, 180), 1.0), (9, 9)))
    return finish(page, rng, 6, 2000, 78)


def dense(img, rng):
    page = perspective(lighting(img, rng, 0.8, 0.97) - 8, rng, 0.02, 1.5)
    return finish(cv2.GaussianBlur(page, (0, 0), 1.0), rng, 6, 2000, 78)


CONDITIONS = {"whatsapp": whatsapp, "sombre": sombre, "penchee": penchee, "floue": floue, "dense": dense}
DENSE_SCALE = 30  # gravure serrée (le banc de base grave à 45)


def engrave(sc, base_path, scale):
    import cairosvg, verovio
    xml = base_path.with_suffix(".musicxml")
    sc.write("musicxml", fp=str(xml))
    tk = verovio.toolkit()
    grow = 45 / scale  # page agrandie d'autant : rendue à la même largeur, la musique y est plus petite
    tk.setOptions({"pageWidth": int(2100 * grow), "pageHeight": int(2970 * grow), "scale": scale, "adjustPageHeight": False,
                   "footer": "none", "header": "auto", "breaks": "auto"})
    tk.loadFile(str(xml))
    pages = []
    for i in range(1, tk.getPageCount() + 1):
        png = cairosvg.svg2png(bytestring=tk.renderToSVG(i).encode(), output_width=2480, background_color="white")
        pages.append(cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE))
    return pages


def main(out, count, wanted):
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
            normal = base.engrave(build(parts), tmp / f"{work}-{layout_name}")
            small = engrave(build(parts), tmp / f"{work}-{layout_name}-dense", DENSE_SCALE) if "dense" in wanted else None
            for name in wanted:
                pages = small if name == "dense" else normal
                rng = np.random.default_rng(sum(map(ord, work + layout_name + name)))
                case = out / f"{work}-{layout_name}-{name}"
                case.mkdir(parents=True, exist_ok=True)
                (case / "truth.json").write_text(json.dumps(t), encoding="utf-8")
                for old in case.glob("source.*"):
                    old.unlink()
                shots = [CONDITIONS[name](p, rng) for p in pages]
                if len(shots) == 1:
                    cv2.imwrite(str(case / "source.jpg"), shots[0], [cv2.IMWRITE_JPEG_QUALITY, 95])
                else:
                    base.save_pdf(shots, case / "source.pdf")
                print(case.name, "x".join(map(str, shots[0].shape[::-1])), flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    main(args[0], int(args[1]) if len(args) > 1 else 6, args[2].split(",") if len(args) > 2 else list(CONDITIONS))
