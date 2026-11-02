"""
Lecture d'une partition (PDF ou image) : nettoyage -> Audiveris -> partition MusicXML unique.
Usage : python3 omr.py <source> <dossier_travail> [--disposition satb|ordinaire] [--etape1]
        python3 omr.py --reprise <etat.zip> <dossier_travail>     (suite d'une lecture commencée avec --etape1)
  Sans --disposition, la disposition est reconnue sur l'image : si les systèmes comptent quatre portées
  (chœur S, A, T, B, une portée par voix) et que la copie est usée, ou que la lecture ordinaire mélange les
  portées, chaque voix est relue à part. Affiche alors « disposition:satb ».
  --disposition satb : lecture voix par voix imposée ; ordinaire : jamais.
Écrit <dossier_travail>/pages/page-NN.png et <dossier_travail>/partition.mxl|.musicxml,
affiche « progress:omr:<0-100> » pendant la lecture et « partition:<fichier> » à la fin.
"""
import os, pathlib, re, shutil, subprocess, sys, threading, time

HERE = pathlib.Path(__file__).resolve().parent
AUDIVERIS = os.environ.get("AUDIVERIS_BIN") or next(
    (p for p in ("/Applications/Audiveris.app/Contents/MacOS/Audiveris", "/opt/audiveris/bin/Audiveris") if os.path.exists(p)),
    "audiveris")
TIMEOUT = int(os.environ.get("OMR_TIMEOUT_S", 15 * 60))
# Hébergement à durée limitée (Vercel : 5 min par requête) : temps total accordé à la lecture des notes.
# La seconde lecture (autre version de l'image) n'est tentée que s'il reste le temps d'en faire une autre.
BUDGET = int(os.environ.get("OMR_BUDGET_S", 0)) or None


# Temps accordé à Audiveris pour chaque étape d'une page : au-delà, il abandonne la page et n'exporte plus rien
# du tout. Une photocopie dense, sur un ordinateur occupé, dépasse sa valeur par défaut.
STEP_TIMEOUT = int(os.environ.get("OMR_ETAPE_S", 600))


# Windows : pas de fenêtre de console pour chaque programme lancé (Audiveris, étapes du moteur)
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def step(name, *args):
    """Commande d'une autre étape du moteur : exécutable autonome (version installée) ou script Python (développement)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, name, *map(str, args)]
    return [sys.executable, str(HERE / f"{name}.py"), *map(str, args)]


def movements(folder: pathlib.Path):
    """Audiveris écrit clean.mxl, ou clean.mvt1.mxl, clean.mvt2.mxl… quand il coupe la partition.
    Lecture faite par morceaux (page en échec relue à part) : sous-dossiers « part-01 », « part-02 »… dans l'ordre des pages."""
    order = lambda p: (str(p.parent.relative_to(folder)), int(m.group(1)) if (m := re.search(r"\.mvt(\d+)\.", p.name)) else 0)
    return sorted(folder.rglob("*.mxl"), key=order)


def systems(folder: pathlib.Path):
    """Nombre de portées de chaque système, page par page, d'après le journal d'Audiveris
    (« Systems: #1[1, 2] #2[3] #3[4] » : le 2e système de deux portées a été coupé en deux)."""
    sheets = []
    for log in sorted(folder.rglob("*.log")):
        for line in log.read_text(errors="replace", encoding="utf-8").splitlines():
            if "Systems:" in line:
                sheets.append([len(g.split(",")) for g in re.findall(r"\[([^\]]*)\]", line.split("Systems:")[1])])
    return sheets


def broken(sheets):
    """Systèmes plus courts que le plus grand de leur page : soit un couplet en solo, soit des portées mal regroupées."""
    return sum(1 for sheet in sheets for n in sheet if n < max(sheet))


def tessdata() -> pathlib.Path | None:
    """Langues de lecture du texte (Tesseract) : sans elles, Audiveris ne lit ni les paroles ni les noms des voix."""
    base = pathlib.Path(getattr(sys, "_MEIPASS", pathlib.Path(__file__).parent))
    d = pathlib.Path(os.environ.get("TESSDATA_DIR") or base / "tessdata")
    return d if (d / "fra.traineddata").exists() else None


def ocr_env() -> dict:
    env = dict(os.environ)
    d = tessdata()
    if d:
        env["TESSDATA_PREFIX"] = str(d)
    return env


def ocr_options() -> list[str]:
    """Paroles et noms de voix lus en français (le latin et l’anglais s’écrivent avec les mêmes lettres)."""
    if not tessdata():
        return []
    return ["-option", f"org.audiveris.omr.text.Language.defaultSpecification={os.environ.get('OMR_LANGUES', 'fra')}"]


def failed_sheets(folder: pathlib.Path) -> set[int]:
    """Pages sur lesquelles Audiveris a planté (une seule suffit à ce qu'il n'exporte rien du tout)."""
    bad = set()
    for log in folder.rglob("*.log"):
        for line in log.read_text(errors="replace", encoding="utf-8").splitlines():
            if "Error processing stub" in line and (m := re.search(r"\[[^\]#]*#(\d+)\]", line)):
                bad.add(int(m.group(1)))
    return bad


def read_book(pdf: pathlib.Path, alt_pdf: pathlib.Path, out: pathlib.Path, pages: int):
    """
    Lecture de toutes les pages ; si Audiveris plante sur une page (photocopie très abîmée), il n'exporte rien :
    on relit alors les autres pages par morceaux, et la page en échec avec l'autre version de l'image.
    Une page illisible est sautée plutôt que de perdre toute la partition.
    """
    found = audiveris(pdf, out, pages)
    bad = failed_sheets(out) if not found else set()
    if found or not bad or len(bad) >= pages:
        return found
    print(f"Pages relues à part après une erreur d'Audiveris : {sorted(bad)}", file=sys.stderr)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    chunks, run = [], []
    for page in range(1, pages + 1):
        if page in bad:
            if run:
                chunks.append((pdf, run)); run = []
            chunks.append((alt_pdf, [page]))
        else:
            run.append(page)
    if run:
        chunks.append((pdf, run))
    for k, (source, sheets) in enumerate(chunks, 1):
        audiveris(source, out / f"part-{k:02d}", len(sheets), sheets)
    return movements(out)


def audiveris(pdf: pathlib.Path, out: pathlib.Path, pages: int, sheets: list[int] | None = None):
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    select = ["-sheets", *map(str, sheets)] if sheets else []
    seen = set()
    tail = []  # dernières lignes d'Audiveris, affichées s'il ne produit rien (diagnostic sur un serveur)
    proc = None
    try:
        proc = subprocess.Popen([AUDIVERIS, "-batch", "-export", "-output", str(out), *select, *ocr_options(),
                                 "-option", f"org.audiveris.omr.Main.sheetStepTimeOut={STEP_TIMEOUT}", "--", str(pdf)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                                env=ocr_env(), **QUIET)
        last_sign = time.time()
        for line in proc.stdout:
            tail = (tail + [line.rstrip()])[-25:]
            if time.time() - last_sign > 20:  # signe de vie : une page dense peut prendre plusieurs minutes
                print("actif:omr", flush=True)
                last_sign = time.time()
            m = re.search(r"Sheet#(\d+)", line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                print(f"progress:omr:{min(95, int(100 * len(seen) / max(pages, 1)))}", flush=True)
        proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        if proc: proc.kill()
        print("Audiveris a dépassé le temps imparti", file=sys.stderr)
    except OSError as e:
        print(f"Audiveris introuvable ou impossible à lancer ({AUDIVERIS}) : {e}", file=sys.stderr)
    found = movements(out)
    if not found:
        print(f"Audiveris n'a rien produit pour {pdf.name} (code {getattr(proc, 'returncode', '?')}). Dernières lignes :", file=sys.stderr)
        print("\n".join(tail), file=sys.stderr)
    return found


# homr (reconnaissance par réseau de neurones, entraîné sur des photos de partitions, GNU AGPL v3) : lit les notes
# d'une copie usée bien mieux qu'Audiveris (rythmes : points, crochets, ligatures). Programme distinct, comme
# Audiveris : HOMR_BIN (version installable : pupitre-homr), sinon homr installé à côté (développement).


def homr_base():
    """Commande de pupitre-homr (sans argument), ou None s'il n'est pas là."""
    exe = os.environ.get("HOMR_BIN")
    if not exe and getattr(sys, "frozen", False):  # à côté du moteur : …/engine/pupitre-engine → …/homr/pupitre-homr
        exe = str(pathlib.Path(sys.executable).resolve().parent.parent / "homr" /
                  ("pupitre-homr.exe" if os.name == "nt" else "pupitre-homr"))
    if exe and os.path.exists(exe):
        return [exe]
    if not getattr(sys, "frozen", False):
        import importlib.util
        if importlib.util.find_spec("homr") is not None:
            return [sys.executable, str(HERE / "lire_homr.py")]
    return None


def homr_staves(folder: pathlib.Path) -> bool:
    """
    Fait lire par homr les portées décrites dans <folder>/portees.json (une image par ligne de chaque voix) ;
    écrit <folder>/sortie/. Signe de vie à chaque portée lue (un petit PC met plusieurs secondes par portée).
    """
    base = homr_base()
    if base is None:
        return False
    shutil.rmtree(folder / "sortie", ignore_errors=True)
    try:
        proc = subprocess.Popen([*base, "--portees", str(folder)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, encoding="utf-8", errors="replace", **QUIET)
        # pas de limite de durée ici : une mise en veille de l'ordinateur ferait « dépasser » une limite horaire ;
        # un homr bloqué est arrêté par la surveillance du serveur (aucun signe de vie pendant 5 minutes)
        for line in proc.stdout:
            if line.startswith("portee:"):
                print("actif:omr", flush=True)
        proc.wait()
    except OSError as e:
        print(f"homr indisponible : {e}", file=sys.stderr)
        return False
    return proc.returncode == 0 and (folder / "sortie" / "v1.musicxml").exists()


_T0 = time.monotonic()


def chrono(label: str) -> None:
    """Durée écrite dans le journal du moteur (aide à repérer l'étape lente sur un petit ordinateur)."""
    print(f"[{time.monotonic() - _T0:6.1f} s] {label}", file=sys.stderr, flush=True)


def prepare_voices(pages_dir: pathlib.Path, work: pathlib.Path, layout: str):
    """
    Étape 1 de la lecture voix par voix : portées repérées, lignes découpées, paroles lues sur l'image, puis première
    ligne de chaque voix lue par homr (sa clé, son armure et sa mesure y sont intactes). Rend (voix, armure, mesure),
    ou None (pas de système à quatre portées, homr absent) : on lit alors par Audiveris ou en lecture ordinaire.
    """
    import pupitres
    voix = work / "voix"
    shutil.rmtree(voix, ignore_errors=True)
    try:
        n_sys = pupitres.voice_pages(sorted(pages_dir.glob("page-*.png")), layout, voix, pdf=False)
    except Exception as e:  # noqa: BLE001 : on garde la lecture ordinaire
        print(f"Découpage par voix impossible : {e}", file=sys.stderr)
        return None
    if not n_sys:
        print("Aucun système complet trouvé pour la disposition annoncée", file=sys.stderr)
        return None
    print(f"Lecture voix par voix : {n_sys} systèmes", file=sys.stderr)
    chrono("portées repérées, lignes découpées, paroles lues")
    if homr_base() is None:
        return voix, None, None
    pupitres.staff_spec(voix, layout, "lignes", first_only=True)
    time_sig, key = None, None
    try:
        if homr_staves(voix):
            read = pupitres.key_and_time(sorted((voix / "sortie").glob("v*.musicxml")))
            if read:
                key, time_sig = read
    except Exception as e:  # noqa: BLE001 : armure et mesure par défaut
        print(f"Armure et mesure non lues : {e}", file=sys.stderr)
    shutil.rmtree(voix / "sortie-entetes", ignore_errors=True)
    if (voix / "sortie").exists():
        (voix / "sortie").rename(voix / "sortie-entetes")
    if key is None:  # homr n'a rien lu en tête : l'image (signes après la clé)
        key = pupitres.key_from_image(voix, layout)
    chrono("premières lignes lues (armure, mesure)")
    return voix, (0 if key is None else key), (time_sig or "4/4")


def read_voices(work: pathlib.Path, voix: pathlib.Path, layout: str, key: int, time_sig: str):
    """
    Étape 2 : toutes les lignes, chacune avec une tête nette (clé, armure, mesure) à la place de la sienne, lues une
    à une par homr, puis voix réunies. Rend le chemin de la partition, ou None.
    """
    import pupitres
    n = len(pupitres.LAYOUTS[layout])
    target = work / "partition.musicxml"
    try:
        if pupitres.header_pages(voix, layout, key, time_sig, pdf=False):
            print(f"Têtes de ligne redessinées : armure {key:+d}, mesure {time_sig}", file=sys.stderr)
            pupitres.staff_spec(voix, layout, "lignes-nettes")
        else:
            pupitres.staff_spec(voix, layout, "lignes")
        ok = homr_staves(voix)
        chrono("toutes les portées lues par homr")
        notes = [voix / "sortie" / f"v{v + 1}.musicxml" for v in range(n)]
        if ok and all(f.exists() for f in notes):
            print("Portées lues une à une par homr, paroles lues sur l'image", file=sys.stderr)
            print("lecture:homr", flush=True)  # repère sans accent (test de fumée, journaux Windows)
            r = subprocess.run(step("pupitres", target, voix / "disposition.json", "--notes", *notes), **QUIET)
            chrono("voix réunies")
            if r.returncode == 0 and target.exists():
                return target
            target.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 : Audiveris prend le relais
        print(f"Lecture par portées impossible : {e}", file=sys.stderr)
    return None


def read_voices_audiveris(work: pathlib.Path, voix: pathlib.Path, layout: str):
    """Repli (homr absent ou en échec) : une page par voix, lue par Audiveris, puis voix réunies."""
    import pupitres
    n = len(pupitres.LAYOUTS[layout])
    target = work / "partition.musicxml"
    print("Lecture des voix par Audiveris", file=sys.stderr)
    pupitres.make_pdfs(voix, layout)
    heads = audiveris(voix / "entetes.pdf", voix / "omr-entetes", n)
    try:
        read = pupitres.key_and_time(heads) if heads else None
        seen = pupitres.key_from_image(voix, layout)
        known = (seen if seen is not None else read[0], read[1]) if read else None
        if known and pupitres.header_pages(voix, layout, *known):
            print(f"Têtes de ligne redessinées : armure {known[0]:+d}, mesure {known[1]}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001 : on lit alors les lignes telles quelles
        print(f"Têtes de ligne non redessinées : {e}", file=sys.stderr)
    found = audiveris(voix / "voix.pdf", voix / "omr", n)
    if not found or subprocess.run(step("pupitres", target, voix / "disposition.json", *found), **QUIET).returncode:
        target.unlink(missing_ok=True)
        return None
    return target


def read_by_voice(pages_dir: pathlib.Path, work: pathlib.Path, layout: str, stage1_only: bool = False):
    """
    Disposition reconnue ou déclarée : chaque voix lue à part, puis voix réunies (pupitres.py). Chemin principal :
    portées découpées lues une à une par homr (sans Audiveris) ; sinon une page par voix lue par Audiveris.
    stage1_only : s'arrête après l'étape 1 et écrit work/etat.zip (hébergement limité à 5 minutes par requête :
    la suite se fait dans une autre requête, voir resume_by_voice). Rend le chemin de la partition ou de l'état.
    """
    prepared = prepare_voices(pages_dir, work, layout)
    if prepared is None:
        return None
    voix, key, time_sig = prepared
    keep = bool(os.environ.get("PUPITRE_GARDER"))  # PUPITRE_GARDER=1 : dossier des voix gardé (banc d'essai)
    if stage1_only and key is not None:
        return save_state(work, voix, key, time_sig)
    target = read_voices(work, voix, layout, key, time_sig) if key is not None else None
    if target is None:
        target = read_voices_audiveris(work, voix, layout)
    if target is not None and not keep:
        shutil.rmtree(voix, ignore_errors=True)
    return target


def save_state(work: pathlib.Path, voix: pathlib.Path, key: int, time_sig: str) -> pathlib.Path:
    """État de l'étape 1 (lignes découpées, disposition, armure, mesure) : de quoi reprendre dans une autre requête."""
    import json, zipfile
    out = work / "etat.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as z:  # les PNG sont déjà compressés
        z.writestr("etat.json", json.dumps({"armure": key, "mesure": time_sig}))
        z.write(voix / "disposition.json", "disposition.json")
        for f in sorted((voix / "lignes").glob("*.png")):
            z.write(f, f"lignes/{f.name}")
    shutil.rmtree(voix, ignore_errors=True)
    return out


def resume_by_voice(state: pathlib.Path, work: pathlib.Path, layout: str):
    """Étape 2 depuis l'état de l'étape 1 : lecture des portées par homr et assemblage. Rend la partition ou None."""
    import json, zipfile
    voix = work / "voix"
    shutil.rmtree(voix, ignore_errors=True)
    voix.mkdir(parents=True)
    with zipfile.ZipFile(state) as z:
        for name in z.namelist():
            if name.startswith("/") or ".." in name:
                sys.exit("PUPITRE-ERREUR: État de lecture invalide.")
        z.extractall(voix)
    info = json.loads((voix / "etat.json").read_text(encoding="utf-8"))
    target = read_voices(work, voix, layout, int(info["armure"]), str(info["mesure"]))
    if target is not None:
        shutil.rmtree(voix, ignore_errors=True)
    return target


def main(src, work, layout=None, stage1=False):
    src, work = pathlib.Path(src), pathlib.Path(work)
    pre, pages_dir = work / "pre", work / "pages"
    shutil.rmtree(pre, ignore_errors=True)
    proc = subprocess.Popen(step("preprocess", src, pre), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace", **QUIET)
    errors = []
    threading.Thread(target=lambda: errors.extend(proc.stderr), daemon=True).start()
    for line in proc.stdout:  # une ligne par page nettoyée : signe de vie pour la surveillance du serveur
        if line.startswith("actif:"):
            print("actif:omr", flush=True)
    proc.wait()
    if proc.returncode:
        last = (("".join(errors)).strip().splitlines() or ["Le nettoyage de l’image a échoué."])[-1]
        sys.exit(last if "Error" not in last and "Traceback" not in last else "Le nettoyage de l’image a échoué.")
    shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True)
    pages = sorted(pre.glob("page-*.png"))
    for p in pages:
        shutil.copy(p, pages_dir / p.name)
    print(f"pages:{len(pages)}", flush=True)
    chrono("pages nettoyées")

    for old in ("partition.mxl", "partition.musicxml"):
        (work / old).unlink(missing_ok=True)
    guess = None
    if layout is None:
        worn = (pre / "usee").exists()
        try:
            import pupitres
            guess = pupitres.detect(sorted(pages_dir.glob("page-*.png")), worn)
        except Exception as e:  # noqa: BLE001 : la lecture ordinaire reste possible
            print(f"Disposition non reconnue : {e}", file=sys.stderr)
        if guess:
            print(f"Disposition reconnue : {guess}{' (copie usée)' if worn else ''}", file=sys.stderr)
        if guess and worn:
            layout = guess  # photocopie usée : barres et accolades coupées, la lecture ordinaire mêle les voix

    def by_voice(chosen):
        target = read_by_voice(pages_dir, work, chosen, stage1_only=stage1)
        if target:
            shutil.rmtree(pre, ignore_errors=True)
            print(f"disposition:{chosen}", flush=True)
            # état de l'étape 1 (hébergement limité à 5 minutes par requête) ou partition terminée
            print(f"etat:{target.name}" if target.suffix == ".zip" else f"partition:{target.name}", flush=True)
        return target

    if layout and layout != "ordinaire":
        if by_voice(layout):
            return
        print("Lecture voix par voix impossible : lecture ordinaire", file=sys.stderr)
        guess = None

    omr, alt = work / "omr", work / "omr-alt"
    started = time.monotonic()
    found = read_book(pre / "clean.pdf", pre / "alt.pdf", omr, len(pages))
    first_took = time.monotonic() - started
    first = systems(omr)
    in_budget = BUDGET is None or 2 * first_took < BUDGET
    if not in_budget and found:
        print("Seconde lecture écartée faute de temps", file=sys.stderr)
    if (not found or broken(first)) and (in_budget or not found):
        # Seconde lecture avec l'autre version de l'image ; on garde celle qui regroupe le mieux les portées
        # (un vrai couplet en solo donne le même découpage dans les deux cas : on garde alors la première).
        print("Seconde lecture avec l’autre version de l’image", file=sys.stderr)
        other = read_book(pre / "alt.pdf", pre / "clean.pdf", alt, len(pages))
        if other and (not found or broken(systems(alt)) < broken(first)):
            shutil.rmtree(omr, ignore_errors=True)
            alt.rename(omr)
            found = movements(omr)
        shutil.rmtree(alt, ignore_errors=True)
    if guess and (not found or broken(systems(omr))) and (BUDGET is None or 2 * (time.monotonic() - started) < BUDGET):
        # les portées n'ont pas été regroupées comme sur l'image (quatre par système) : voix relues à part
        print("Portées mal regroupées : lecture voix par voix", file=sys.stderr)
        if by_voice(guess):
            shutil.rmtree(omr, ignore_errors=True)
            return
    if not found:
        sys.exit("Aucune portée n’a été reconnue. Essayez un scan plus net : page bien à plat, éclairage régulier, sans ombre.")

    for old in ("partition.mxl", "partition.musicxml"):
        (work / old).unlink(missing_ok=True)
    target = work / "partition.musicxml"
    if len(found) == 1:
        # un seul mouvement : copié tel quel, sauf s'il faut remettre des portées dans leur système (photocopie abîmée)
        r = subprocess.run(step("merge", "--si-utile", target, found[0]), **QUIET)
        if r.returncode:
            target.unlink(missing_ok=True)
            target = work / "partition.mxl"
            shutil.copy(found[0], target)
    else:
        subprocess.run(step("merge", target, *found), check=True, **QUIET)
    shutil.rmtree(pre, ignore_errors=True)
    print(f"partition:{target.name}", flush=True)


def _fail(e: BaseException) -> None:
    """Cause lisible sur la dernière ligne (affichée à l'utilisateur) ; la trace complète va dans le journal."""
    import traceback
    traceback.print_exc()
    short = " ".join(str(e).split())[:160] or type(e).__name__
    sys.exit(f"PUPITRE-ERREUR: La lecture a été interrompue ({type(e).__name__} : {short}). "
             "Réessayez ; si cela se répète, envoyez le journal des erreurs à AIT.")


def resume(state, work, layout="satb"):
    """Seconde requête de la lecture voix par voix : reprend l'état de l'étape 1 (etat.zip)."""
    work = pathlib.Path(work)
    for old in ("partition.mxl", "partition.musicxml"):
        (work / old).unlink(missing_ok=True)
    target = resume_by_voice(pathlib.Path(state), work, layout)
    if target is None:
        sys.exit("PUPITRE-ERREUR: La lecture des voix n'a pas abouti. Reprenez la photo : page bien à plat, en pleine lumière.")
    print(f"disposition:{layout}", flush=True)
    print(f"partition:{target.name}", flush=True)


if __name__ == "__main__":
    args = sys.argv[1:]
    layout = None
    state = None
    stage1 = "--etape1" in args  # lecture en deux requêtes : la première s'arrête après l'étape 1 (voir read_by_voice)
    args = [a for a in args if a != "--etape1"]
    if "--reprise" in args:  # seconde requête : omr.py --reprise <etat.zip> <dossier_travail>
        k = args.index("--reprise")
        state = args[k + 1]
        del args[k:k + 2]
    if "--disposition" in args:
        k = args.index("--disposition")
        layout = args[k + 1] if k + 1 < len(args) else None
        del args[k:k + 2]
    if len(args) != (1 if state else 2) or (layout and layout not in ("satb", "ordinaire")):
        sys.exit(__doc__)
    try:
        if state:
            resume(state, args[0], layout or "satb")
        else:
            main(args[0], args[1], layout, stage1)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        _fail(e)
