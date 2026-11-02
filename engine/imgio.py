"""
Lecture et écriture d'images par Python (numpy) et non par OpenCV : cv2.imread / cv2.imwrite ne savent pas ouvrir un
chemin contenant certains caractères (accents hors page de code, lettres africaines…) sous Windows, et le dossier
« Documents » d'un utilisateur en contient souvent. Ils renvoient alors None / False sans erreur.
"""
import pathlib

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_GRAYSCALE):
    data = np.fromfile(str(path), dtype=np.uint8)
    img = cv2.imdecode(data, flags) if data.size else None
    if img is None:
        raise FileNotFoundError(f"Image illisible : {path}")
    return img


def imwrite(path, img):
    ok, buf = cv2.imencode(pathlib.Path(path).suffix or ".png", img)
    if not ok:
        raise OSError(f"Image non écrite : {path}")
    buf.tofile(str(path))
