"""
Lecture d'une partition (PDF ou image) : nettoyage -> Audiveris -> partition MusicXML unique.
Usage : python3 omr.py <source> <dossier_travail>
Écrit <dossier_travail>/pages/page-NN.png et <dossier_travail>/partition.mxl|.musicxml,
affiche « progress:omr:<0-100> » pendant la lecture et « partition:<fichier> » à la fin.
"""
import os, pathlib, re, shutil, subprocess, sys

HERE = pathlib.Path(__file__).resolve().parent
AUDIVERIS = os.environ.get("AUDIVERIS_BIN") or next(
    (p for p in ("/Applications/Audiveris.app/Contents/MacOS/Audiveris", "/opt/audiveris/bin/Audiveris") if os.path.exists(p)),
    "audiveris")
TIMEOUT = int(os.environ.get("OMR_TIMEOUT_S", 15 * 60))


# Windows : pas de fenêtre de console pour chaque programme lancé (Audiveris, étapes du moteur)
QUIET = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def step(name, *args):
    """Commande d'une autre étape du moteur : exécutable autonome (version installée) ou script Python (développement)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, name, *map(str, args)]
    return [sys.executable, str(HERE / f"{name}.py"), *map(str, args)]


def movements(folder: pathlib.Path):
    """Audiveris écrit clean.mxl, ou clean.mvt1.mxl, clean.mvt2.mxl… quand il coupe la partition."""
    order = lambda p: int(m.group(1)) if (m := re.search(r"\.mvt(\d+)\.", p.name)) else 0
    return sorted(folder.rglob("*.mxl"), key=order)


def systems(folder: pathlib.Path):
    """Nombre de portées de chaque système, page par page, d'après le journal d'Audiveris
    (« Systems: #1[1, 2] #2[3] #3[4] » : le 2e système de deux portées a été coupé en deux)."""
    sheets = []
    for log in folder.glob("*.log"):
        for line in log.read_text(errors="replace").splitlines():
            if "Systems:" in line:
                sheets.append([len(g.split(",")) for g in re.findall(r"\[([^\]]*)\]", line.split("Systems:")[1])])
    return sheets


def broken(sheets):
    """Systèmes plus courts que le plus grand de leur page : soit un couplet en solo, soit des portées mal regroupées."""
    return sum(1 for sheet in sheets for n in sheet if n < max(sheet))


def audiveris(pdf: pathlib.Path, out: pathlib.Path, pages: int):
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    seen = set()
    try:
        proc = subprocess.Popen([AUDIVERIS, "-batch", "-export", "-output", str(out), "--", str(pdf)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", **QUIET)
        for line in proc.stdout:
            m = re.search(r"Sheet#(\d+)", line)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                print(f"progress:omr:{min(95, int(100 * len(seen) / max(pages, 1)))}", flush=True)
        proc.wait(timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        print("Audiveris a dépassé le temps imparti", file=sys.stderr)
    return movements(out)


def main(src, work):
    src, work = pathlib.Path(src), pathlib.Path(work)
    pre, pages_dir = work / "pre", work / "pages"
    shutil.rmtree(pre, ignore_errors=True)
    prep = subprocess.run(step("preprocess", src, pre), capture_output=True, text=True, **QUIET)
    if prep.returncode:
        last = (prep.stderr.strip().splitlines() or ["Le nettoyage de l’image a échoué."])[-1]
        sys.exit(last if "Error" not in last and "Traceback" not in last else "Le nettoyage de l’image a échoué.")
    shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True)
    pages = sorted(pre.glob("page-*.png"))
    for p in pages:
        shutil.copy(p, pages_dir / p.name)
    print(f"pages:{len(pages)}", flush=True)

    omr, alt = work / "omr", work / "omr-alt"
    found = audiveris(pre / "clean.pdf", omr, len(pages))
    first = systems(omr)
    if not found or broken(first):
        # Seconde lecture avec l'autre version de l'image ; on garde celle qui regroupe le mieux les portées
        # (un vrai couplet en solo donne le même découpage dans les deux cas : on garde alors la première).
        print("Seconde lecture avec l’autre version de l’image", file=sys.stderr)
        other = audiveris(pre / "alt.pdf", alt, len(pages))
        if other and (not found or broken(systems(alt)) < broken(first)):
            shutil.rmtree(omr, ignore_errors=True)
            alt.rename(omr)
            found = movements(omr)
        shutil.rmtree(alt, ignore_errors=True)
    if not found:
        sys.exit("Aucune portée n’a été reconnue. Essayez un scan plus net : page bien à plat, éclairage régulier, sans ombre.")

    for old in ("partition.mxl", "partition.musicxml"):
        (work / old).unlink(missing_ok=True)
    if len(found) == 1:
        target = work / "partition.mxl"
        shutil.copy(found[0], target)
    else:
        target = work / "partition.musicxml"
        subprocess.run(step("merge", target, *found), check=True, **QUIET)
    shutil.rmtree(pre, ignore_errors=True)
    print(f"partition:{target.name}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
