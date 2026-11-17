"""
Banc réel privé : découpe des recueils scannés (PDF) en pages, classées d'après leurs portées, puis choix d'un
échantillon de copies à lire. Les recueils et les pages restent sur la machine (droits des éditeurs) : jamais dans le
dépôt ni sur le banc de GitHub, qui est public.

  python3 make_banc_reel.py pages <dossier> <recueil.pdf> [<recueil.pdf> …] [--dpi 170]
      pages/<recueil>-p<NNN>.png (dpi du scan, gris) et index.json : portées par système, interligne, disposition
  python3 make_banc_reel.py classer <dossier>
      classement refait sur les pages déjà découpées
  python3 make_banc_reel.py choisir <dossier> <nombre> [--graine 1]
      cas/<recueil>-p<NNN>/source.png : échantillon réparti entre recueils et dispositions (deux portées et plus
      d'abord : ce sont les copies des chorales), sans pages vides

La bonne réponse de chaque cas (truth.json, comme pour run_bench.py) s'écrit ensuite à part, vérifiée à la main.
Lancer avec le python du moteur (pypdfium2, OpenCV).
"""
import json, pathlib, random, re, sys, unicodedata

ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402


def label(pdf):
    """Nom court d'un recueil : « CHANTS NOTÉS Tome 3 (…).pdf » → « tome3 »."""
    name = unicodedata.normalize("NFKD", pathlib.Path(pdf).stem).encode("ascii", "ignore").decode().lower()
    m = re.search(r"tome\s*(\d+)", name)
    return f"tome{m.group(1)}" if m else re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:30]


def layout_of(sizes):
    if not sizes:
        return "vide"
    if set(sizes) == {1}:
        return "melodie"
    if max(sizes) == 4 and sizes.count(4) >= len(sizes) / 2:
        return "satb"
    if set(sizes) <= {1, 2, 3} and 2 in sizes:
        return "deux"
    return "mixte"


def classify(img):
    """Portées par système et interligne, sur la page passée par le début du nettoyage du moteur (page tournée remise
    droite, largeur de 2480 points comme dans omr.py : la recherche des portées est réglée pour elle)."""
    import preprocess
    import pupitres
    try:
        bw = preprocess.plain_page(preprocess.to_gray(preprocess.upright(img)))
        staves = pupitres.find_staves(bw)
        sizes = [len(g) for g in pupitres.systems_on(bw, staves, dashed=False)] if staves else []
        sp = float(np.median([(b - t) / 4 for t, b, _l, _r in staves])) * img.shape[1] / 2480 if staves else 0.0
    except Exception as e:  # page de texte, couverture : rien à lire
        print(f"classement impossible : {e}", file=sys.stderr)
        sizes, sp = [], 0.0
    return sizes, sp


def reclassify(out):
    out = pathlib.Path(out)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    for n, key in enumerate(sorted(index)):
        img = cv2.imread(str(out / "pages" / f"{key}.png"), cv2.IMREAD_GRAYSCALE)
        sizes, sp = classify(img)
        index[key].update(systemes=sizes, interligne=round(sp, 1), disposition=layout_of(sizes))
        print(f"{key} {index[key]['disposition']:8s} {sizes} interligne {sp:.1f}", flush=True)
        if n % 20 == 0:
            index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    summary(index)


def summary(index):
    counts = {}
    for v in index.values():
        counts[v["disposition"]] = counts.get(v["disposition"], 0) + 1
    print("Pages :", len(index), counts)


def pages(out, pdfs, dpi=170):
    import pypdfium2
    out = pathlib.Path(out)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    for pdf in pdfs:
        tag = label(pdf)
        doc = pypdfium2.PdfDocument(pdf)
        for i in range(len(doc)):
            key = f"{tag}-p{i + 1:03d}"
            if key in index:
                continue
            img = doc[i].render(scale=dpi / 72, grayscale=True).to_numpy()
            img = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            path = out / "pages" / f"{key}.png"
            cv2.imwrite(str(path), img)
            sizes, sp = classify(img)
            index[key] = dict(recueil=tag, page=i + 1, systemes=sizes, interligne=round(sp, 1),
                              disposition=layout_of(sizes))
            print(f"{key} {index[key]['disposition']:8s} {sizes} interligne {sp:.1f}", flush=True)
            if (i + 1) % 20 == 0:
                index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    summary(index)


def choose(out, number, seed=1):
    out = pathlib.Path(out)
    index = json.loads((out / "index.json").read_text(encoding="utf-8"))
    rng = random.Random(seed)
    # chœur (deux ou quatre portées) d'abord, puis mélodies ; réparti entre recueils
    order = {"satb": 0, "deux": 0, "mixte": 1, "melodie": 2}
    pools = {}
    for key, v in index.items():
        if v["disposition"] in order:
            pools.setdefault((order[v["disposition"]], v["recueil"]), []).append(key)
    for keys in pools.values():
        rng.shuffle(keys)
    want = {0: round(0.7 * number), 1: round(0.1 * number)}
    want[2] = number - want[0] - want[1]
    picked = []
    for rank in (0, 1, 2):
        groups = [k for (r, _t), k in sorted(pools.items()) if r == rank]
        take, i = [], 0
        while len(take) < want[rank] and any(groups):
            g = groups[i % len(groups)]
            if g:
                take.append(g.pop())
            i += 1
        picked += take
    if len(picked) < number:  # pas assez de chœur : on complète avec ce qui reste
        rest = [k for keys in pools.values() for k in keys]
        rng.shuffle(rest)
        picked += rest[:number - len(picked)]
    for key in picked:
        case = out / "cas" / key
        case.mkdir(parents=True, exist_ok=True)
        src = case / "source.png"
        if not src.exists():
            src.write_bytes((out / "pages" / f"{key}.png").read_bytes())
    print(f"{len(picked)} cas dans {out / 'cas'}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == "pages":
        dpi = 170
        if "--dpi" in args:
            k = args.index("--dpi")
            dpi = int(args[k + 1])
            args = args[:k] + args[k + 2:]
        pages(args[1], args[2:], dpi)
    elif len(args) == 2 and args[0] == "classer":
        reclassify(args[1])
    elif len(args) >= 3 and args[0] == "choisir":
        seed = 1
        if "--graine" in args:
            k = args.index("--graine")
            seed = int(args[k + 1])
            args = args[:k] + args[k + 2:]
        choose(args[1], int(args[2]), seed)
    else:
        sys.exit(__doc__)
