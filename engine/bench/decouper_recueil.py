"""
Recueils scannés (« Chants notés ») découpés en chants. Un chant commence à son titre (ligne de texte nettement plus
grande que les paroles, entre deux systèmes ou au-dessus du premier : « Saint, le Seigneur », « Agneau de Dieu » au
milieu d'une page) et continue jusqu'au titre suivant, pages suivantes comprises. Chaque chant devient un dossier
source/ de morceaux de pages (01.png, 02.png…), que omr.py lit comme plusieurs photos d'une même partition.
Les recueils et leurs pages restent sur la machine (droits des éditeurs) : jamais dans le dépôt.

  <python du moteur> decouper_recueil.py <dossier des pages> <sortie> [--recueils tome1,tome3] [--pages 10-40]
      pages : <recueil>-pNNN.png (make_banc_reel.py pages) ; sortie : <recueil>/<NNN>-<titre>/source/NN.png,
      titre.txt, pages.txt ; index.json (chants dans l'ordre du recueil)
"""
import json, pathlib, re, statistics, sys, unicodedata

ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

TITLE_RATIO = 1.3    # hauteur d'un titre / hauteur médiane des lignes de texte (paroles)
_OCR = None


def ocr(gray):
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR()
    res, _ = _OCR(gray)
    out = []
    for box, text, conf in res or []:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        out.append(dict(text=text.strip(), y0=min(ys), y1=max(ys), x0=min(xs), x1=max(xs), h=max(ys) - min(ys), conf=conf))
    return out


def systems_of(gray):
    """Systèmes de la page, de haut en bas : [(haut, bas)] en points de la page, et l'interligne."""
    import preprocess
    import pupitres
    big = preprocess.to_gray(gray)
    scale = gray.shape[1] / big.shape[1]
    bw = preprocess.plain_page(big)
    try:
        staves = pupitres.find_staves(bw)
        groups = pupitres.systems_on(bw, staves, dashed=False) if staves else []
    except Exception:  # noqa: BLE001  (page de texte, couverture)
        return [], 0.0
    sp = float(np.median([(b - t) / 4 for t, b, _l, _r in staves])) * scale if staves else 0.0
    return sorted((min(s[0] for s in g) * scale, max(s[1] for s in g) * scale) for g in groups), sp


CREDITS = ("edition", "texte", "musique", "paroles", "harm", "disque", "copyright", "tous droits")


def titles_on(lines, systems, sp, height, width):
    """Lignes de titre : centrées, plus hautes que les paroles, sans syllabes coupées (« be-nis-sons » : paroles), ni
    mention d'auteur ou d'éditeur, hors des systèmes et du pied de page. (Les indications de mouvement, « Sans presser,
    bien balancé », sont aussi grandes mais au début du système, pas au milieu.)"""
    letters = [ln for ln in lines if sum(ch.isalpha() for ch in ln["text"]) >= 3]
    if not letters:
        return []
    usual = statistics.median(ln["h"] for ln in letters)
    out = []
    for ln in letters:
        cy = (ln["y0"] + ln["y1"]) / 2
        cx = (ln["x0"] + ln["x1"]) / 2 / width
        text = ln["text"].lower()
        if ln["h"] < TITLE_RATIO * usual or cy > 0.95 * height or abs(cx - 0.5) > 0.07 \
                or (ln["x1"] - ln["x0"]) > 0.6 * width or len(re.findall(r"\w-\s*\w", text)) >= 2 \
                or any(w in unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode() for w in CREDITS):
            continue
        if any(top - 0.5 * sp <= cy <= bottom + 0.5 * sp for top, bottom in systems):
            continue
        out.append(ln)
    return sorted(out, key=lambda ln: ln["y0"])


def slug(text):
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:50] or "sans-titre"


def split(pages_dir, out, books=None, span=None):
    pages_dir, out = pathlib.Path(pages_dir), pathlib.Path(out)
    files = sorted(pages_dir.glob("*-p[0-9][0-9][0-9].png"))
    chants, cur = [], None
    for f in files:
        book, num = f.stem.rsplit("-p", 1)
        num = int(num)
        if books and book not in books:
            continue
        if span and not (span[0] <= num <= span[1]):
            continue
        if cur and cur["book"] != book:
            cur = None
        gray = cv2.imread(str(f), cv2.IMREAD_GRAYSCALE)
        systems, sp = systems_of(gray)
        if not systems:
            cur = None  # page de texte (préface, table) : le chant en cours s'arrête
            continue
        titles = titles_on(ocr(gray), systems, sp, gray.shape[0], gray.shape[1])
        # morceaux de la page : avant le 1er titre (suite du chant en cours), puis un morceau par titre
        cuts = []
        prev_bottom = 0.0
        for top, bottom in systems:
            above = [t for t in titles if prev_bottom - 0.5 * sp <= (t["y0"] + t["y1"]) / 2 <= top]
            if above:
                cuts.append((min(t["y0"] for t in above), " — ".join(t["text"] for t in above)))
            prev_bottom = bottom
        starts = [0.0] + [c[0] for c in cuts] + [float(gray.shape[0])]
        names = [None] + [c[1] for c in cuts]
        for k in range(len(starts) - 1):
            y0, y1 = int(max(0, starts[k] - 0.5 * sp)), int(starts[k + 1] - 0.5 * sp) if k + 1 < len(starts) - 1 else gray.shape[0]
            inside = [s for s in systems if y0 <= (s[0] + s[1]) / 2 <= y1]
            if not inside:
                continue
            if names[k] is not None:
                cur = dict(book=book, title=names[k], parts=[])
                chants.append(cur)
            elif cur is None:
                continue  # musique sans titre au début d'un recueil
            cur["parts"].append(dict(page=num, y0=y0, y1=y1, systems=len(inside), file=str(f)))
        print(f"{f.stem} : {len(systems)} systèmes, titres {[c[1] for c in cuts]}", flush=True)
    index = []
    counters = {}
    for c in chants:
        counters[c["book"]] = counters.get(c["book"], 0) + 1
        name = f"{counters[c['book']]:03d}-{slug(c['title'])}"
        case = out / c["book"] / name
        (case / "source").mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(c["parts"]):
            gray = cv2.imread(p["file"], cv2.IMREAD_GRAYSCALE)
            cv2.imwrite(str(case / "source" / f"{i + 1:02d}.png"), gray[p["y0"]:p["y1"]])
        (case / "titre.txt").write_text(c["title"], encoding="utf-8")
        (case / "pages.txt").write_text(" ".join(str(p["page"]) for p in c["parts"]), encoding="utf-8")
        index.append(dict(recueil=c["book"], dossier=f"{c['book']}/{name}", titre=c["title"],
                          pages=[p["page"] for p in c["parts"]], systemes=sum(p["systems"] for p in c["parts"])))
    (out / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(index)} chants")


if __name__ == "__main__":
    args = sys.argv[1:]
    books = span = None
    if "--recueils" in args:
        i = args.index("--recueils")
        books = set(args[i + 1].split(","))
        args = args[:i] + args[i + 2:]
    if "--pages" in args:
        i = args.index("--pages")
        a, b = args[i + 1].split("-")
        span = (int(a), int(b))
        args = args[:i] + args[i + 2:]
    if len(args) != 2:
        sys.exit(__doc__)
    split(args[0], args[1], books, span)
