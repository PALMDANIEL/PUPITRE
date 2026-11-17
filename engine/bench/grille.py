"""
Aide à la transcription : chaque système d'une page agrandi, avec un repère fin et le nom de la note sur chaque ligne
et chaque interligne de chaque portée (lignes supplémentaires comprises). Sert à écrire la bonne réponse d'une copie
du banc réel : on lit sur quel repère tombe chaque tête au lieu d'estimer sa hauteur.

  <python du moteur> grille.py <page.png> <dossier de sortie> [clés : sol,fa,sol,fa…] [--echelle 3]
      systeme-NN.png ; clés par défaut : portées alternées sol / fa (deux portées par système)
"""
import os, pathlib, sys

ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

STEPS = "CDEFGAB"
FR = {"C": "do", "D": "ré", "E": "mi", "F": "fa", "G": "sol", "A": "la", "B": "si"}
BOTTOM = {"sol": ("E", 4), "fa": ("G", 2), "sol8": ("E", 3)}


def name(clef, k):
    """Nom de la note k demi-interlignes au-dessus de la ligne du bas."""
    s, o = BOTTOM[clef]
    d = STEPS.index(s) + 7 * o + k
    return f"{FR[STEPS[d % 7]]}{d // 7}"


def main(page, out, clefs=None, scale=3):
    import preprocess, pupitres
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    img = cv2.imread(str(page), cv2.IMREAD_GRAYSCALE)
    k = img.shape[1] / 2480
    bw = preprocess.plain_page(preprocess.to_gray(img))
    staves = [(t * k, b * k, l * k, r * k) for t, b, l, r in pupitres.find_staves(bw)]
    groups = pupitres.systems_on(bw, pupitres.find_staves(bw), dashed=False)
    font = ImageFont.load_default()
    n = 0
    for gi, g in enumerate(groups):
        group = [(t * k, b * k, l * k, r * k) for t, b, l, r in g]
        top = min(t for t, *_ in group) - 5 * (group[0][1] - group[0][0]) / 4
        bot = max(b for _t, b, *_ in group) + 5 * (group[-1][1] - group[-1][0]) / 4
        left, right = max(0, min(l for *_x, l, _r in group) - 40), min(img.shape[1], max(r for *_x, r in group) + 10)
        y0, y1 = max(0, int(top)), min(img.shape[0], int(bot))
        crop = Image.fromarray(img[y0:y1, int(left):int(right)]).convert("RGB")
        crop = crop.resize((crop.width * scale, crop.height * scale), Image.LANCZOS)
        d = ImageDraw.Draw(crop)
        for si, (t, b, _l, _r) in enumerate(group):
            clef = (clefs[n + si] if clefs and n + si < len(clefs) else ("sol" if si % 2 == 0 else "fa"))
            half = (b - t) / 8
            for kk in range(-6, 15):
                y = (b - kk * half - y0) * scale
                if not 0 <= y < crop.height:
                    continue
                on_line = kk % 2 == 0
                colour = (60, 140, 255) if on_line else (255, 150, 60)
                for x in range(0, crop.width, 6 if on_line else 10):
                    d.line([(x, y), (x + 2, y)], fill=colour)
                d.text((2, y - 6), name(clef, kk), fill=colour, font=font)
                d.text((crop.width - 34, y - 6), name(clef, kk), fill=colour, font=font)
        n += len(group)
        dst = out / f"systeme-{gi + 1:02d}.png"
        crop.save(dst)
        print(dst, f"{len(group)} portées")


if __name__ == "__main__":
    args = sys.argv[1:]
    scale = 3
    if "--echelle" in args:
        i = args.index("--echelle")
        scale = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    if len(args) < 2:
        sys.exit(__doc__)
    main(args[0], args[1], args[2].split(",") if len(args) > 2 else None, scale)
