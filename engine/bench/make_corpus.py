"""
Banc d'essai : fabrique des partitions dont on connaît les notes exactes.
Chorals de Bach à 4 voix (corpus de music21), gravés avec Verovio en deux mises en page :
  - « ouverte » : 4 portées (S, A, T en clé de sol octaviée, B) ;
  - « fermée » : 2 portées (S+A en clé de sol, T+B en clé de fa), comme la plupart des chants de chorale ;
et en deux qualités : « net » (PDF numérique) et « photo » (inclinaison, ombre, flou, bruit, JPEG).

Usage : bench-venv/bin/python make_corpus.py <dossier> [nombre_de_chorals]
Chaque cas : <dossier>/<cas>/source.pdf|source.jpg + truth.json (hauteurs MIDI par voix).
"""
import copy, json, pathlib, sys
import cairosvg, cv2, numpy as np, verovio
from music21 import clef, corpus, layout, metadata, stream

CHORALES = ["bwv269", "bwv347", "bwv153.1", "bwv86.6", "bwv267", "bwv281", "bwv40.6", "bwv244.3", "bwv66.6", "bwv145.5"]
MEASURES = 10
NAMES = ["Soprano", "Alto", "Ténor", "Basse"]


def four_parts(work):
    sc = corpus.parse(work)
    parts = [p for p in sc.parts][:4]
    if len(parts) < 4:
        return None
    out = []
    for p in parts:
        q = p.measures(0, MEASURES)
        q = q.stripTies(inPlace=False)
        out.append(q)
    return out


def truth(parts):
    return {NAMES[i]: [int(n.pitch.midi) for n in p.recurse().notes if n.isNote] for i, p in enumerate(parts)}


def open_score(parts):
    sc = stream.Score()
    sc.insert(0, metadata.Metadata(title="Choral"))
    for i, p in enumerate(parts):
        q = copy.deepcopy(p)
        q.partName = NAMES[i]
        first = q.getElementsByClass(stream.Measure).first()
        for c in list(first.getElementsByClass(clef.Clef)):
            first.remove(c)
        first.insert(0, [clef.TrebleClef(), clef.TrebleClef(), clef.Treble8vbClef(), clef.BassClef()][i])
        sc.insert(0, q)
    return sc


def closed_score(parts):
    """Deux voix par portée, mesure par mesure (voix 1 hampes en haut, voix 2 hampes en bas)."""
    sc = stream.Score()
    sc.insert(0, metadata.Metadata(title="Choral"))
    for upper, lower, cl in ((parts[0], parts[1], clef.TrebleClef()), (parts[2], parts[3], clef.BassClef())):
        staff = stream.Part()
        staff.partName = "Chœur"
        for k, (mu, ml) in enumerate(zip(upper.getElementsByClass(stream.Measure), lower.getElementsByClass(stream.Measure))):
            m = stream.Measure(number=mu.number)
            if k == 0:
                m.insert(0, cl)
                for el in mu.getElementsByClass(("KeySignature", "TimeSignature")):
                    m.insert(0, copy.deepcopy(el))
            for vid, src, stem in (("1", mu, "up"), ("2", ml, "down")):
                v = stream.Voice(id=vid)
                for el in src.notesAndRests:
                    e = copy.deepcopy(el)
                    if e.isNote:
                        e.stemDirection = stem
                        if vid == "2":
                            e.lyrics = []
                    v.insert(el.offset, e)
                m.insert(0, v)
            staff.append(m)
        sc.insert(0, staff)
    return sc


def engrave(sc, base: pathlib.Path):
    xml = base.with_suffix(".musicxml")
    sc.write("musicxml", fp=str(xml))
    tk = verovio.toolkit()
    tk.setOptions({"pageWidth": 2100, "pageHeight": 2970, "scale": 45, "adjustPageHeight": False,
                   "footer": "none", "header": "auto", "breaks": "auto"})
    tk.loadFile(str(xml))
    pages = []
    for i in range(1, tk.getPageCount() + 1):
        png = cairosvg.svg2png(bytestring=tk.renderToSVG(i).encode(), output_width=2480, background_color="white")
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
        pages.append(img)
    return pages


def as_photo(img, seed):
    rng = np.random.default_rng(seed)
    h, w = img.shape
    # papier légèrement crème, éclairage inégal (ombre d'un côté)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    light = 0.78 + 0.2 * (xx / w) + 0.06 * np.sin(yy / h * np.pi)
    paper = img.astype(np.float32) * light - 12
    # perspective et inclinaison
    d = w * 0.025
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[rng.uniform(0, d), rng.uniform(0, d)], [w - rng.uniform(0, d), rng.uniform(0, d)],
                      [w - rng.uniform(0, d), h - rng.uniform(0, d)], [rng.uniform(0, d), h - rng.uniform(0, d)]])
    M = cv2.getPerspectiveTransform(src, dst)
    paper = cv2.warpPerspective(paper, M, (w, h), borderValue=60)
    rot = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-2, 2), 1.0)
    paper = cv2.warpAffine(paper, rot, (w, h), borderValue=60)
    paper = cv2.GaussianBlur(paper, (0, 0), 1.3)
    paper += rng.normal(0, 7, paper.shape)
    out = np.clip(paper, 0, 255).astype(np.uint8)
    out = cv2.resize(out, None, fx=0.65, fy=0.65, interpolation=cv2.INTER_AREA)  # téléphone ~ 1600 px de large
    return out


def save_pdf(pages, path):
    from PIL import Image
    pil = [Image.fromarray(p) for p in pages]
    pil[0].save(path, save_all=True, append_images=pil[1:], resolution=300)


def main(out, count):
    out = pathlib.Path(out)
    made = 0
    for work in CHORALES:
        if made >= count:
            break
        parts = four_parts(work)
        if not parts:
            continue
        made += 1
        t = truth(parts)
        for layout_name, build in (("ouverte", open_score), ("fermee", closed_score)):
            tmp = out / "_gravure"
            tmp.mkdir(parents=True, exist_ok=True)
            pages = engrave(build(parts), tmp / f"{work}-{layout_name}")
            for quality in ("net", "photo"):
                case = out / f"{work}-{layout_name}-{quality}"
                case.mkdir(parents=True, exist_ok=True)
                (case / "truth.json").write_text(json.dumps(t))
                if quality == "net":
                    save_pdf(pages, case / "source.pdf")
                elif len(pages) == 1:
                    cv2.imwrite(str(case / "source.jpg"), as_photo(pages[0], sum(map(ord, work))), [cv2.IMWRITE_JPEG_QUALITY, 80])
                else:
                    save_pdf([as_photo(p, sum(map(ord, work)) + i) for i, p in enumerate(pages)], case / "source.pdf")
                print(case.name, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 6)
