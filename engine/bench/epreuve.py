"""
Épreuve d'une lecture : la partition lue par le moteur regravée (Verovio), numéros sur chaque mesure, à côté de la
page d'origine, pour la relire comme un correcteur (les différences de dessin se voient mieux que des hauteurs
mesurées au pixel). Sert à écrire la bonne réponse des copies du banc réel.

  <python du banc (bench-venv)> epreuve.py <dossier du cas> [--largeur 1400]
      écrit epreuve-NN.png (lecture regravée, page par page) dans le dossier du cas
"""
import pathlib, sys, zipfile

import cairosvg
import verovio


def main(case, width=1400):
    case = pathlib.Path(case)
    src = next((p for p in (case / "partition.musicxml", case / "partition.mxl") if p.exists()), None)
    if src is None:
        sys.exit("pas de partition lue")
    data = src.read_bytes()
    if src.suffix == ".mxl":
        with zipfile.ZipFile(src) as z:
            name = next(n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META"))
            data = z.read(name)
    tk = verovio.toolkit()
    tk.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": 45, "adjustPageHeight": True,
                   "breaks": "auto", "mnumInterval": 1, "footer": "none", "header": "none",
                   "spacingSystem": 12, "lyricSize": 3.5})
    tk.loadData(data.decode("utf-8", errors="replace"))
    for k in range(1, tk.getPageCount() + 1):
        out = case / f"epreuve-{k:02d}.png"
        cairosvg.svg2png(bytestring=tk.renderToSVG(k).encode(), write_to=str(out), output_width=width,
                         background_color="white")
        print(out)


if __name__ == "__main__":
    args = sys.argv[1:]
    w = 1400
    if "--largeur" in args:
        k = args.index("--largeur")
        w = int(args[k + 1])
        args = args[:k] + args[k + 2:]
    if len(args) != 1:
        sys.exit(__doc__)
    main(args[0], w)
