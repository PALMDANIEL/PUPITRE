"""
Répertoire vérifié : versions exactes des chants déjà connus (PDF gravés lus directement, partitions corrigées à la
main). Une copie photographiée ou scannée d'un chant du répertoire est reconnue d'après ses notes lues, même fautives,
et la version exacte remplace la lecture. Un chant inconnu n'est jamais remplacé par un autre : il faut une ressemblance
forte ET nettement meilleure que celle de tous les autres chants (sinon la lecture de l'image reste).

  python repertoire.py chercher <partition lue> <dossier du répertoire>     → JSON sur la sortie
  python repertoire.py remplacer <partition lue> <sortie> <dossiers…>      → version exacte (paroles reprises de la
                                                                             lecture) ; code 3 si rien n'est reconnu
  python repertoire.py ajouter <partition exacte> <dossier du répertoire> [nom] [titre] [--pdf <PDF gravé>]
  (remplacer … --page <image de la 1re page> : reconnaissance aussi par le titre imprimé ; lecture « - » si les notes
   n'ont pas pu être lues)
Le dossier contient <nom>.musicxml (version exacte) et <nom>.json (empreinte, refaite si absente ou plus ancienne).
"""
import contextlib
import io
import json
import os
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# mesuré sur le banc des chorales (104 copies, 32 chants) : une copie ressemble en médiane à 0,84 à sa version
# exacte, jamais à plus de 0,48 à un autre chant ; 0,55 et 0,15 : 97 copies reconnues, aucune confondue
ACCEPT = float(os.environ.get("PUPITRE_REPERTOIRE_SEUIL", "0.55"))  # ressemblance minimale (0 à 1)
MARGIN = float(os.environ.get("PUPITRE_REPERTOIRE_ECART", "0.15"))  # avance minimale sur le 2e chant le plus proche
MIN_NOTES = 24                                                        # trop peu de notes lues : on ne décide pas


def _voice_parts(path, exact=False):
    """Voix séparées comme le moteur le fait (exact : partition exacte, voix nommées S, A, T, B prises telles quelles)."""
    import render
    from music21 import converter
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        sc = converter.parse(str(path))
        return render.extract_voices(sc, trust_names=exact)


def _held(n):
    return n.tie is not None and n.tie.type in ("stop", "continue")


def voices_of(path, exact=False):
    """Hauteurs (MIDI) de chaque voix, dans l'ordre S, A, T, B, comme la séparation des voix du moteur les donne."""
    voices = _voice_parts(path, exact)
    out = []
    for v in voices:
        seq = [int(max(n.pitches, key=lambda q: q.ps).midi) for n in v.recurse().notes
               if n.pitches and not (n.tie is not None and n.tie.type in ("stop", "continue"))]
        if seq:
            out.append(seq)
    return out


def fingerprint(path, title=None, page_title=None):
    """Empreinte d'un chant exact : ses voix, son titre (nom du fichier, ou titre donné à l'ajout) et le titre imprimé
    sur la 1re page du PDF gravé, s'il est connu."""
    fp = {"voices": voices_of(path, exact=True), "titre": title or pathlib.Path(path).stem}
    if page_title:
        fp["titre_page"] = page_title
    return fp


# --- Titre imprimé en haut de la page (OCR) : il résiste souvent mieux que les notes (copie usée, photo floue) ---

TITLE_ACCEPT = float(os.environ.get("PUPITRE_REPERTOIRE_TITRE", "0.8"))  # part des mots du titre retrouvés
TITLE_MARGIN = 0.3                                                         # avance sur le 2e titre le plus proche
TITLE_MIN_WORDS = 3  # mots du titre retrouvés : « Kyrie », « Ave Maria » ne désignent pas un chant (tant de versions)
TITLE_MIN_KEYS = 2   # mots clés (hors mots courants, GENERIC) dans le titre
TITLE_MELODY_SLACK = 0.05  # les notes lues ne doivent pas ressembler nettement mieux à un autre chant…
MELODY_INFORMATIVE = 0.45  # …quand elles sont assez lisibles pour être un indice (copie usée : presque toutes fausses)
SAME_PIECE = 0.9           # deux entrées aussi proches sont le même chant (PDF en double dans le dossier)
DUPLICATE = 0.97           # à l'ajout : version exacte d'un chant déjà présent
_OCR = None


def _words(text):
    import unicodedata
    t = unicodedata.normalize("NFD", text.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    import re
    return [w for w in re.findall(r"[a-z]+|\d+", t) if len(w) >= 3 or w.isdigit()]


def _mixed(text):
    """Nombres mal lus par l'OCR, gardés d'un tenant (« (1f9) » pour « (119) ») : lettres et chiffres mêlés."""
    import re
    return [t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) >= 3 and any(c.isdigit() for c in t)
            and any(c.isalpha() for c in t)]


def _near(w, words):
    """Mot du titre retrouvé dans le texte lu : à l'identique, ou à une ou deux lettres près (OCR : « Psaunie »).
    Nombre de trois chiffres au moins : un seul caractère mal lu toléré (« 1f9 » pour 119) ; les petits nombres non
    (« 17e dimanche », dates : trop de faux)."""
    if w in words:
        return True
    if w.isdigit():
        return len(w) >= 3 and any(len(x) == len(w) and sum(a != b for a, b in zip(w, x)) <= 1 and
                                   sum(c.isdigit() for c in x) >= len(w) - 1 for x in words)
    if len(w) < 4:
        return False
    tol = 1 if len(w) < 6 else 2
    return any(abs(len(x) - len(w)) <= tol and _lev(w, x) <= tol for x in words if not x.isdigit())


# Mots trop courants pour désigner un chant : titres liturgiques, en-têtes de recueil ou de chorale (« Répertoire de la
# maîtrise Notre-Dame… », « Psaume », « Messe »), mots-outils. Le titre est jugé sur ses autres mots (les mots clés) :
# une copie d'un autre chant du même recueil n'a que l'en-tête en commun.
GENERIC = set("""
psaume psaumes cantique cantiques chant chants messe messes kyrie gloria sanctus agnus dei alleluia alleluya amen credo
seigneur dieu jesus christ marie notre dame pere esprit saint sainte saints vierge ave maria
repertoire chorale choeur maitrise paroisse cathedrale basilique eglise diocese communaute recueil partition partitions
refrain couplet couplets strophe dimanche ordinaire temps careme avent noel paques annee
les des une nous vous toi moi est mon ton son mes tes ses nos vos leur pour dans avec qui que par sur sous vers
""".split())


def _key_words(title):
    return [w for w in _words(title) if w not in GENERIC]


def title_score(title, text_words, count=False):
    """Part des mots clés du titre retrouvés dans le texte lu (count : nombre de mots du titre retrouvés, tous compris)."""
    if count:
        return sum(1 for w in _words(title) if _near(w, text_words))
    keys = _key_words(title)
    if len(keys) < TITLE_MIN_KEYS:
        return 0.0  # « Kyrie », « O Seigneur nous tes enfants » : pas assez de mots propres à ce chant
    return sum(1 for w in keys if _near(w, text_words)) / len(keys)


def pdf_title(pdf):
    """Titre imprimé sur la 1re page d'un PDF gravé : la plus grande ligne de texte du haut de la page (polices de texte
    seulement : les symboles des polices musicales, SMuFL ou Sonata, sont écartés). None si rien n'est lisible."""
    try:
        import pypdfium2 as pdfium
        import pypdfium2.raw as raw
        import pdf_vectoriel as pv
        page = pdfium.PdfDocument(str(pdf))[0]
        height = page.get_height()
        tp = page.get_textpage()
        chars, codes = [], {}
        for i in range(tp.count_chars()):
            ch = raw.FPDFText_GetUnicode(tp, i)
            font = pv._font(tp, i)
            codes.setdefault(font, set()).add(ch)
            if not 32 < ch < 0x2000:
                if ch == 32 and chars:
                    chars[-1]["space"] = True
                continue
            left, bottom, right, top = tp.get_charbox(i, loose=True)
            if bottom < 0.65 * height:  # haut de la page seulement (compté depuis le bas)
                continue
            chars.append({"c": chr(ch), "font": font, "size": top - bottom, "left": left, "right": right, "base": bottom})
        music = {f for f, cs in codes.items() if pv.kind_of(f, cs)}
        chars = [c for c in chars if c["font"] not in music and (c["c"].isalnum() or c["c"] in "'’-")]
        if not chars:
            return None
        big = max(c["size"] for c in chars)
        title = sorted((c for c in chars if c["size"] >= 0.85 * big), key=lambda c: (-round(c["base"] / (0.5 * big)), c["left"]))
        out, last = "", None
        for c in title:
            if last is not None and (abs(c["base"] - last["base"]) > 0.5 * big or last.get("space")
                                     or c["left"] - last["right"] > 0.18 * c["size"]):
                out += " "
            out += c["c"]
            last = c
        return out.strip() or None
    except Exception as e:  # noqa: BLE001
        print(f"Répertoire : titre du PDF non lu ({type(e).__name__})", file=sys.stderr)
        return None


def ocr_title(page):
    """Texte du haut de la 1re page (titre, sous-titre), lu par RapidOCR ; None s'il n'est pas installé."""
    global _OCR
    try:
        import cv2
        import imgio
        if _OCR is None:
            from rapidocr_onnxruntime import RapidOCR
            _OCR = RapidOCR()
        img = imgio.imread(str(page), cv2.IMREAD_GRAYSCALE)
        res, _ = _OCR(img[: int(0.22 * img.shape[0])])
        return " ".join(r[1] for r in (res or []))
    except Exception as e:  # noqa: BLE001
        print(f"Répertoire : titre non lu ({type(e).__name__})", file=sys.stderr)
        return None


def _titles(x, f):
    return [t for t in (f.get("titre") or x.stem, f.get("titre_page")) if t]


def _title_match(x, f, words):
    """Meilleur des titres d'un chant (nom du fichier, titre imprimé) : (part des mots retrouvés, nombre de mots)."""
    return max(((title_score(t, words), title_score(t, words, count=True)) for t in _titles(x, f)), default=(0.0, 0))


def search_title(text, items, read=None):
    """Chant dont le titre est lu en haut de la page, ou None ; les notes lues, s'il y en a, ne doivent pas le démentir."""
    words = set(_words(text or "")) | set(_mixed(text))
    if not words:
        return None
    ranked = sorted(((_title_match(x, f, words), x, f) for x, f in items), key=lambda t: (-t[0][0], -t[0][1]))
    if not ranked:
        return None
    (best, found), x, f = ranked[0]
    second = next((sc for (sc, _n), y, g in ranked[1:] if not _same(f, g)), 0.0)
    if best < TITLE_ACCEPT or best - second < TITLE_MARGIN or found < TITLE_MIN_WORDS:
        return short_title(words, items, read)
    if read and sum(len(v) for v in read) >= MIN_NOTES:
        mine = similarity(read, f["voices"])
        others = max((similarity(read, g["voices"]) for y, g in items if y != x and not _same(f, g)), default=0.0)
        # les notes ne démentent le titre que si elles sont lisibles (sinon une copie usée ne serait jamais reconnue)
        if max(mine, others) >= MELODY_INFORMATIVE and mine < others - TITLE_MELODY_SLACK:
            return None
    return {"nom": x.stem, "chemin": str(x), "titre": round(best, 3), "ecart_titre": round(best - second, 3)}


SHORT_TITLE = os.environ.get("PUPITRE_TITRE_COURT", "1") != "0"
SHORT_MIN, SHORT_GAP = 0.3, 0.03


def short_title(words, items, read):
    """Titre court (« Devant toi » : un seul mot propre au chant) retrouvé en entier dans l'en-tête, et notes lues qui
    ressemblent d'abord à ce même chant, même de peu (copie WhatsApp mal lue : 0,39 contre 0,34) : deux indices faibles
    qui s'accordent. Un titre plus long de la même tournure (« Voici ce que nous portons devant toi ») est reconnu avant,
    par la règle ordinaire."""
    if not SHORT_TITLE or not read or sum(len(v) for v in read) < MIN_NOTES:
        return None
    sims = sorted(((similarity(read, g["voices"]), y, g) for y, g in items if g["voices"]), key=lambda t: -t[0])
    if not sims:
        return None
    top, y, g = sims[0]
    second = next((sc for sc, z, h in sims[1:] if not _same(g, h)), 0.0)
    full = any(len(_words(t)) >= 2 and all(_near(w, words) for w in _words(t)) for t in _titles(y, g))
    if full and top >= SHORT_MIN and top - second >= SHORT_GAP:
        return {"nom": y.stem, "chemin": str(y), "titre": 1.0, "ecart_titre": round(top - second, 3)}
    return None


def _lev(a, b):
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _grams(seq, n=4):
    pc = [p % 12 for p in seq]
    return {tuple(pc[i:i + n]) for i in range(len(pc) - n + 1)}


def similarity(read, ref):
    """
    Ressemblance (0 à 1) d'une lecture et d'un chant du répertoire, voix par voix, sur les classes de hauteur (do, ré…
    sans l'octave : les fautes d'octave de la lecture ne comptent pas), pondérée par la longueur des voix du chant.
    Nombre de voix différent : la voix du haut et la voix du bas seulement.
    """
    if not read or not ref:
        return 0.0
    pairs = list(zip(read, ref)) if len(read) == len(ref) else [(read[0], ref[0]), (read[-1], ref[-1])]
    num = den = 0.0
    for r, e in pairs:
        a, b = [p % 12 for p in r], [p % 12 for p in e]
        sim = max(0.0, 1 - _lev(a, b) / max(len(a), len(b), 1))
        num += sim * len(e)
        den += len(e)
    return num / den if den else 0.0


def load(folder: pathlib.Path):
    """Chants du répertoire et leurs empreintes (refaites si la partition est plus récente)."""
    items = []
    for xml in sorted(folder.glob("*.musicxml")):
        fp = xml.with_suffix(".json")
        try:
            if not fp.exists() or fp.stat().st_mtime < xml.stat().st_mtime:
                old = json.loads(fp.read_text(encoding="utf-8")) if fp.exists() else {}  # titres donnés à l'ajout gardés
                fp.write_text(json.dumps(fingerprint(xml, old.get("titre"), old.get("titre_page"))), encoding="utf-8")
            items.append((xml, json.loads(fp.read_text(encoding="utf-8"))))
        except Exception as e:  # noqa: BLE001 : un chant illisible n'empêche pas les autres
            print(f"Répertoire : {xml.name} illisible ({type(e).__name__})", file=sys.stderr)
    return items


def _same(f, g):
    """Deux entrées du répertoire qui sont le même chant (PDF en double) : pas des concurrentes."""
    return f is g or (bool(f["voices"]) and bool(g["voices"]) and similarity(f["voices"], g["voices"]) >= SAME_PIECE)


def search(read_path, folder, exclude=None):
    """Chant du répertoire reconnu dans la lecture, ou None : {nom, chemin, ressemblance, ecart}.
    folder : un dossier ou une liste de dossiers (répertoire commun d'AIT, répertoire propre à la chorale…)."""
    read = voices_of(read_path)
    if sum(len(v) for v in read) < MIN_NOTES:
        return None, read, []
    folders = folder if isinstance(folder, (list, tuple)) else [folder]
    items = [(x, f) for d in folders if pathlib.Path(d).is_dir() for x, f in load(pathlib.Path(d))
             if exclude is None or x.stem != exclude]
    top = _grams(read[0]) if read else set()
    # présélection : les chants qui partagent le plus de motifs de quatre notes avec la voix du haut
    scored = []
    for x, f in items:
        if not f["voices"]:
            continue
        g = _grams(f["voices"][0])
        jac = len(top & g) / max(1, len(top | g))
        scored.append((jac, x, f))
    scored.sort(key=lambda t: -t[0])
    ranked = sorted(((similarity(read, f["voices"]), x, f) for _j, x, f in scored[:8]), key=lambda t: -t[0])
    if not ranked:
        return None, read, []
    best = ranked[0][0]
    second = next((sc for sc, _y, g in ranked[1:] if not _same(ranked[0][2], g)), 0.0)
    ranked = [(sc, y) for sc, y, _g in ranked]
    found = {"nom": ranked[0][1].stem, "chemin": str(ranked[0][1]), "ressemblance": round(best, 3), "ecart": round(best - second, 3)}
    return (found if best >= ACCEPT and best - second >= MARGIN else None), read, ranked


def transfer_lyrics(read_path, exact_path, out):
    """
    Version exacte écrite dans out, avec les paroles lues sur la copie (la version exacte d'un PDF n'en a pas toujours) :
    chaque voix de la lecture est alignée sur la voix de même rang de la version exacte, note à note (classes de
    hauteur), et les syllabes passent sur les notes appariées. Rend le nombre de syllabes reprises.
    """
    import copy
    import difflib
    from music21 import converter
    read = _voice_parts(read_path)
    exact = converter.parse(str(exact_path))
    parts = list(exact.parts)
    moved = 0
    for k, part in enumerate(parts):
        if k >= len(read):
            break
        src = [n for n in read[k].recurse().notes if n.pitches and not _held(n)]
        dst = [n for n in part.recurse().notes if n.pitches and not _held(n)]
        if not any(n.lyrics for n in src) or any(n.lyrics for n in dst):
            continue
        a = [max(n.pitches, key=lambda q: q.ps).midi % 12 for n in src]
        b = [max(n.pitches, key=lambda q: q.ps).midi % 12 for n in dst]
        for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
            if tag != "equal":
                continue
            for s_, d_ in zip(src[a1:a2], dst[b1:b2]):
                if s_.lyrics:
                    d_.lyrics = copy.deepcopy(s_.lyrics)
                    moved += 1
    exact.write("musicxml", fp=str(out), makeNotation=False)
    return moved


def replace(read_path, out, folders, page=None):
    """
    Copie reconnue dans le répertoire : version exacte (avec les paroles de la lecture) écrite dans out.
    D'abord par les notes lues ; sinon par le titre imprimé en haut de la page (page : image de la 1re page), même si
    la lecture des notes a échoué (read_path None).
    """
    import shutil
    folders = [pathlib.Path(f) for f in folders]
    found, read = None, []
    if read_path is not None:
        found, read, _ranked = search(read_path, folders)
    if not found and page is not None and pathlib.Path(page).exists():
        items = [(x, f) for d in folders if d.is_dir() for x, f in load(d)]
        found = search_title(ocr_title(page), items, read)
        if found:
            found["par"] = "titre"
    if not found:
        return None
    if read_path is None:
        shutil.copy(found["chemin"], out)
        found["paroles"] = 0
        return found
    try:
        found["paroles"] = transfer_lyrics(read_path, found["chemin"], out)
    except Exception as e:  # noqa: BLE001 : sans les paroles, la version exacte reste bonne
        print(f"Répertoire : paroles non reprises ({type(e).__name__})", file=sys.stderr)
        shutil.copy(found["chemin"], out)
        found["paroles"] = 0
    return found


INCOHERENT = float(os.environ.get("PUPITRE_REPERTOIRE_INCOHERENCE", "0.3"))


def incoherence(path):
    """Part des mesures où toutes les voix chantent mais ne durent pas le même temps (première et dernière mesures mises
    à part : levée, fin) : signe sûr d'une note ou d'un rythme mal lu. Les mesures libres des psaumes (récitation)
    durent le même temps dans toutes les voix et ne comptent pas."""
    from music21 import converter
    sc = converter.parse(str(path))
    parts = [list(p.getElementsByClass("Measure")) for p in sc.parts]
    if not parts:
        return 1.0
    n = max(len(p) for p in parts)
    bad = tot = 0
    for k in range(1, n - 1):
        durs = set()
        if not all(k < len(p) and p[k].notes for p in parts):
            continue
        for p in parts:
            durs.add(round(float(sum(e.duration.quarterLength for e in p[k].notesAndRests)), 3))
        tot += 1
        bad += len(durs) > 1
    return bad / tot if tot and bad >= 3 else 0.0  # une ou deux mesures (petite pièce) : pas un signe


def main():
    if len(sys.argv) < 4:
        sys.exit(__doc__)
    cmd, src, folder = sys.argv[1], pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    if cmd == "chercher":
        found, _read, ranked = search(src, folder)
        print(json.dumps({"trouve": found, "proches": [{"nom": x.stem, "ressemblance": round(s, 3)} for s, x in ranked[:3]]},
                         ensure_ascii=False))
    elif cmd == "remplacer":
        rest = sys.argv[4:]
        page = rest[rest.index("--page") + 1] if "--page" in rest else None
        if "--page" in rest:
            i = rest.index("--page")
            rest = rest[:i] + rest[i + 2:]
        found = replace(None if str(src) == "-" else src, sys.argv[3], [f for f in rest if f], page)
        print(json.dumps(found or {}, ensure_ascii=False))
        sys.exit(0 if found else 3)
    elif cmd == "ajouter":
        import shutil
        folder.mkdir(parents=True, exist_ok=True)
        rest = sys.argv[4:]
        pdf = None
        if "--pdf" in rest:
            i = rest.index("--pdf")
            pdf, rest = rest[i + 1], rest[:i] + rest[i + 2:]
        name = rest[0] if rest else src.stem
        title = rest[1] if len(rest) > 1 else None
        # lecture d'un PDF gravé peu cohérente (mise en page que la lecture directe ne comprend pas encore) : pas une
        # version exacte, elle ne doit pas remplacer la lecture des copies de ce chant
        bad = incoherence(src)
        if bad > INCOHERENT:
            print(f"Partition incohérente ({bad:.0%} des mesures) : pas ajoutée au répertoire", file=sys.stderr)
            return
        fp = fingerprint(src, title, pdf_title(pdf) if pdf else None)
        # même chant déjà présent sous un autre nom (PDF en double, chorale qui renvoie sa partition) : pas de doublon,
        # sinon les deux entrées se feraient concurrence et aucune ne serait reconnue
        for x, f in load(folder):
            if x.stem != name and f["voices"] and fp["voices"] and \
                    min(similarity(fp["voices"], f["voices"]), similarity(f["voices"], fp["voices"])) >= DUPLICATE:
                print(f"Déjà dans le répertoire : {x.stem}", file=sys.stderr)
                return
        dst = folder / f"{name}.musicxml"
        if src.suffix.lower() == ".mxl":  # partition corrigée compressée (MuseScore) : rangée décompressée
            from music21 import converter
            converter.parse(str(src)).write("musicxml", fp=str(dst))
        else:
            shutil.copy(src, dst)
        (folder / f"{name}.json").write_text(json.dumps(fp), encoding="utf-8")
        print(f"Ajouté au répertoire : {name}", file=sys.stderr)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
