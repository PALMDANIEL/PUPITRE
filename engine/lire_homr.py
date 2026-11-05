"""
Lance homr (https://github.com/liebharc/homr, GNU AGPL v3), sans modification de homr : point d'entrée du
programme distinct pupitre-homr (engine/homr.spec), livré à côté de Pupitre comme Audiveris.

Deux usages :
  lire_homr <page.png>             → écrit <page>.musicxml à côté de l'image (lecture d'une page entière).
  lire_homr --portees <dossier>    → lit des portées déjà découpées (une image par ligne de chaque voix).
      <dossier>/portees.json : {"voix": [[{"image": "chemin.png", "T": haut, "B": bas}, …], …]}
      T et B : hauteur (pixels de l'image) de la 1re et de la 5e ligne de la portée.
      Écrit <dossier>/sortie/v1.musicxml … (une partie par voix) et v1.lignes.json (indices des lignes lues).
      "passes": N (facultatif, 1 à 3) : chaque portée est lue N fois avec une préparation d'image un peu différente
      (flou, taille) ; les lectures supplémentaires sont écrites dans sortie-1/, sortie-2/. L'appelant vote entre elles
      mesure par mesure : un accord des lectures est un gage de fiabilité, un désaccord signale une mesure à vérifier.
Les modèles doivent être présents (python -m homr.main --init, fait à la construction).

Lire les portées une à une évite la détection des portées de homr, lente et fragile sur une photocopie usée
(l'appelant sait déjà où elles sont) : chaque portée est ramenée à la taille attendue par le réseau, comme homr
le fait lui-même, et lue seule.
"""
import json
import os
import pathlib
import sys


# préparations de l'image d'une portée, une par passe : (flou gaussien, facteur de largeur de la portée)
VARIANTS = [(0.7, 1.0), (0.0, 1.0), (1.2, 0.97)]


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
    passes = max(1, min(len(VARIANTS), int(spec.get("passes", 1))))
    outs = [folder / ("sortie" if k == 0 else f"sortie-{k}") for k in range(passes)]
    for o in outs:
        o.mkdir(exist_ok=True)
    config = Config()
    config.use_gpu_inference = False  # modèles « fp32 » pour processeur, ceux que --init télécharge
    model = Staff2Score(config)
    total = sum(len(v) for v in spec["voix"]) * passes
    done = 0
    for v, lines in enumerate(spec["voix"], 1):
        symbols = [[] for _ in range(passes)]
        kept: list[list[int]] = [[] for _ in range(passes)]
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
            crop0 = img[y0:y1, x0:x1]
            size = get_tr_omr_canvas_size(crop0.shape)
            eprint(f"Voix {v}, ligne {k + 1}/{len(lines)}")
            for p in range(passes):
                blur, width = VARIANTS[p]
                # réduction lissée (INTER_AREA) : une portée binaire réduite sans lissage perd ses traits fins ; le réseau
                # a appris sur des images en niveaux de gris, comme celles que homr lui prépare à partir d'une photo
                src = cv2.GaussianBlur(crop0, (0, 0), blur) if blur else crop0
                if width != 1.0:  # portée un peu plus étroite : le réseau voit une échelle légèrement différente
                    src = cv2.resize(src, (max(8, int(src.shape[1] * width)), src.shape[0]), interpolation=cv2.INTER_AREA)
                    size_p = get_tr_omr_canvas_size(src.shape)
                else:
                    size_p = size
                crop = cv2.resize(src, (int(size_p[0]), int(size_p[1])), interpolation=cv2.INTER_AREA)
                canvas = center_image_on_canvas(crop, size_p)
                result = [s for s in model.predict(canvas) if s.position != "lower"]  # une seule portée, pas d'accolade
                done += 1
                print(f"portee:{done}/{total}", flush=True)
                if result:
                    result.append(EncodedSymbol("newline"))
                    symbols[p].extend(result)
                    kept[p].append(k)
        for p in range(passes):
            xml = generate_xml(XmlGeneratorArguments(), [remove_duplicated_symbols(symbols[p])], "")
            xml.write(str(outs[p] / f"v{v}.musicxml"))
            (outs[p] / f"v{v}.lignes.json").write_text(json.dumps(kept[p]), encoding="utf-8")


def limit_threads() -> None:
    """
    PUPITRE_FILS=n : le réseau de neurones calcule sur n fils au lieu de tous les cœurs. Un ordinateur portable branché
    sur un chargeur trop faible (65 W pour un 15 pouces) bride son processeur à 20 % dès que tous les cœurs travaillent ;
    moins de fils, c'est moins de puissance demandée et une lecture plus rapide au total.
    """
    n = int(os.environ.get("PUPITRE_FILS", "0") or 0)
    if n <= 0:
        return
    import onnxruntime as ort
    base = ort.InferenceSession

    def session(*args, **kwargs):
        opts = kwargs.get("sess_options") or ort.SessionOptions()
        opts.intra_op_num_threads, opts.inter_op_num_threads = n, 1
        kwargs["sess_options"] = opts
        return base(*args, **kwargs)
    ort.InferenceSession = session
    import cv2
    cv2.setNumThreads(n)


if __name__ == "__main__":
    limit_threads()
    if len(sys.argv) == 3 and sys.argv[1] == "--portees":
        read_staves(pathlib.Path(sys.argv[2]))
    elif len(sys.argv) == 2 and not sys.argv[1].startswith("--"):
        from homr.main import main
        sys.argv = ["homr", sys.argv[1]]
        main()
    else:
        sys.exit(__doc__)
