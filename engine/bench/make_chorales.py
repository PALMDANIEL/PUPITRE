"""
Banc des chorales : partitions numériques réelles (PDF gravés par MuseScore, Finale, LilyPond… : le répertoire des
chorales), lues nettes pour écrire la bonne réponse (lecture vérifiée sur l'épreuve, bench/epreuve.py), puis abîmées
comme les chorales photographient leurs copies (mêmes conditions que make_corpus, make_reels et make_usees).
Les partitions restent sur la machine (droits des compositeurs) : jamais dans le dépôt ni sur le banc public.

  <python du moteur> make_chorales.py pages <dossier> <partition.pdf> […]
      <dossier>/<nom>-net/source.pdf (le PDF tel quel) et <dossier>/_pages/<nom>/page-NN.png (2480 points de large) ;
      doublons (même contenu) et PDF sans portée écartés
  <python du banc (bench-venv)> make_chorales.py abimer <dossier> [conditions séparées par des virgules]
      <dossier>/<nom>-<condition>/source.jpg (ou .pdf), pour les partitions dont <nom>-net a une bonne réponse
      (truth.json, écrit par verite_pdf.py)
      conditions : photo, whatsapp, sombre, penchee, floue, copie, usee
"""
import hashlib, json, pathlib, re, shutil, sys, unicodedata

ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))

CONDITIONS = ["photo", "whatsapp", "sombre", "penchee", "floue", "copie", "usee"]


def slug(path):
    name = unicodedata.normalize("NFKD", pathlib.Path(path).stem).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"\(\d+\)", "", name)
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-")[:40]


def pages(out, pdfs):
    import cv2
    import pypdfium2
    import preprocess
    import pupitres
    out = pathlib.Path(out)
    seen = {}
    for pdf in pdfs:
        data = pathlib.Path(pdf).read_bytes()
        h = hashlib.md5(data).hexdigest()
        if h in seen:
            print(f"doublon : {pathlib.Path(pdf).name} (= {seen[h]})")
            continue
        name = slug(pdf)
        seen[h] = name
        doc = pypdfium2.PdfDocument(pdf)
        imgs, staves = [], 0
        for i in range(len(doc)):
            page = doc[i]
            w, _h = page.get_size()
            img = page.render(scale=2480 / w, grayscale=True).to_numpy()
            img = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            imgs.append(img)
            try:
                staves += len(pupitres.find_staves(preprocess.plain_page(img)))
            except Exception:  # noqa: BLE001 : page de texte
                pass
        if not staves:
            print(f"sans portée : {pathlib.Path(pdf).name}")
            continue
        case = out / f"{name}-net"
        case.mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf, case / "source.pdf")
        (case / "origine.txt").write_text(pathlib.Path(pdf).name, encoding="utf-8")
        dst = out / "_pages" / name
        dst.mkdir(parents=True, exist_ok=True)
        for k, img in enumerate(imgs, 1):
            cv2.imwrite(str(dst / f"page-{k:02d}.png"), img)
        print(f"{name} : {len(imgs)} page(s), {staves} portées")


def damage(out, wanted):
    import cv2
    import numpy as np
    import make_corpus as base
    import make_reels as reels
    import make_usees as usees
    out = pathlib.Path(out)
    for src in sorted((out / "_pages").iterdir()):
        name = src.name
        imgs = [cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) for p in sorted(src.glob("page-*.png"))]
        truth = out / f"{name}-net" / "truth.json"
        if not truth.exists():
            continue  # sans bonne réponse (verite_pdf.py) : rien à mesurer
        for cond in wanted:
            rng = np.random.default_rng(sum(map(ord, name + cond)))
            if cond == "photo":
                shots = [base.as_photo(img, int(rng.integers(1 << 30))) for img in imgs]
            elif cond in ("copie", "usee"):
                shots = [usees.as_photocopy(img, int(rng.integers(1 << 30)), cond) for img in imgs]
            else:
                shots = [reels.CONDITIONS[cond](img, rng) for img in imgs]
            case = out / f"{name}-{cond}"
            case.mkdir(parents=True, exist_ok=True)
            for old in case.glob("source.*"):
                old.unlink()
            if len(shots) == 1:
                cv2.imwrite(str(case / "source.jpg"), shots[0], [cv2.IMWRITE_JPEG_QUALITY, 95])
            else:
                base.save_pdf(shots, case / "source.pdf")
            if truth.exists():
                shutil.copy(truth, case / "truth.json")
            print(case.name, flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) >= 3 and args[0] == "pages":
        pages(args[1], args[2:])
    elif len(args) >= 2 and args[0] == "abimer":
        damage(args[1], args[2].split(",") if len(args) > 2 else CONDITIONS)
    else:
        sys.exit(__doc__)
