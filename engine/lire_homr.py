"""
Lance homr (https://github.com/liebharc/homr, GNU AGPL v3), sans modification de homr : point d'entrée du
programme distinct pupitre-homr (engine/homr.spec), livré à côté de Pupitre comme Audiveris.

Deux usages :
  lire_homr <page.png>             → écrit <page>.musicxml à côté de l'image (lecture d'une page entière).
  lire_homr --portees <dossier>    → lit des portées déjà découpées (une image par ligne de chaque voix).
      <dossier>/portees.json : {"voix": [[{"image": "chemin.png", "T": haut, "B": bas}, …], …]}
      T et B : hauteur (pixels de l'image) de la 1re et de la 5e ligne de la portée.
      Écrit <dossier>/sortie/v1.musicxml … (une partie par voix) et v1.lignes.json (indices des lignes lues).
Les modèles doivent être présents (python -m homr.main --init, fait à la construction).

Lire les portées une à une évite la détection des portées de homr, lente et fragile sur une photocopie usée
(l'appelant sait déjà où elles sont) : chaque portée est ramenée à la taille attendue par le réseau, comme homr
le fait lui-même, et lue seule.
"""
import json
import os
import pathlib
import sys


def read_staves(folder: pathlib.Path) -> None:
    import cv2
    import numpy as np
    from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
    from homr.simple_logging import eprint
    from homr.staff_parsing import center_image_on_canvas, get_tr_omr_canvas_size
    from homr.transformer.configs import Config
    from homr.transformer.staff2score import Staff2Score
    from homr.transformer.vocabulary import EncodedSymbol, remove_duplicated_symbols

    spec = json.loads((folder / "portees.json").read_text(encoding="utf-8"))
    out = folder / "sortie"
    out.mkdir(exist_ok=True)
    config = Config()
    config.use_gpu_inference = False  # modèles « fp32 » pour processeur, ceux que --init télécharge
    model = Staff2Score(config)
    total = sum(len(v) for v in spec["voix"])
    done = 0
    for v, lines in enumerate(spec["voix"], 1):
        symbols: list = []
        kept: list[int] = []
        for k, line in enumerate(lines):
            img = cv2.imdecode(np.fromfile(str(folder / line["image"]), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)  # chemin Unicode (Windows)
            T, B = float(line["T"]), float(line["B"])
            sp = (B - T) / 4
            # étendue de la portée : colonnes où au moins 3 des 5 lignes ont de l'encre
            rows = [(img[max(0, int(round(T + j * sp)) - 2):int(round(T + j * sp)) + 3] < 128).any(0) for j in range(5)]
            xs = np.flatnonzero(np.sum(rows, axis=0) >= 3)
            left, right = (int(xs[0]), int(xs[-1])) if len(xs) else (0, img.shape[1] - 1)
            x0, x1 = max(0, int(left - 2 * sp)), min(img.shape[1], int(right + 2 * sp))
            y0, y1 = max(0, int(T - 4 * sp)), min(img.shape[0], int(B + 4 * sp))
            crop = img[y0:y1, x0:x1]
            size = get_tr_omr_canvas_size(crop.shape)
            # réduction lissée (INTER_AREA) : une portée binaire réduite sans lissage perd ses traits fins ; le réseau
            # a appris sur des images en niveaux de gris, comme celles que homr lui prépare à partir d'une photo
            mode = os.environ.get("HOMR_REDUCTION", "flou")
            if mode == "area":
                crop = cv2.resize(crop, (int(size[0]), int(size[1])), interpolation=cv2.INTER_AREA)
            elif mode == "flou":
                crop = cv2.resize(cv2.GaussianBlur(crop, (0, 0), 0.7), (int(size[0]), int(size[1])), interpolation=cv2.INTER_AREA)
            canvas = center_image_on_canvas(crop, size)
            eprint(f"Voix {v}, ligne {k + 1}/{len(lines)}")
            result = [s for s in model.predict(canvas) if s.position != "lower"]  # une seule portée, pas d'accolade
            done += 1
            print(f"portee:{done}/{total}", flush=True)
            if not result:
                continue
            result.append(EncodedSymbol("newline"))
            symbols.extend(result)
            kept.append(k)
        xml = generate_xml(XmlGeneratorArguments(), [remove_duplicated_symbols(symbols)], "")
        xml.write(str(out / f"v{v}.musicxml"))
        (out / f"v{v}.lignes.json").write_text(json.dumps(kept), encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--portees":
        read_staves(pathlib.Path(sys.argv[2]))
    elif len(sys.argv) == 2 and not sys.argv[1].startswith("--"):
        from homr.main import main
        sys.argv = ["homr", sys.argv[1]]
        main()
    else:
        sys.exit(__doc__)
