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


def movements(folder: pathlib.Path):
    """Audiveris écrit clean.mxl, ou clean.mvt1.mxl, clean.mvt2.mxl… quand il coupe la partition."""
    order = lambda p: int(m.group(1)) if (m := re.search(r"\.mvt(\d+)\.", p.name)) else 0
    return sorted(folder.rglob("*.mxl"), key=order)


def audiveris(pdf: pathlib.Path, out: pathlib.Path, pages: int):
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    seen = set()
    try:
        proc = subprocess.Popen([AUDIVERIS, "-batch", "-export", "-output", str(out), "--", str(pdf)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
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
    prep = subprocess.run([sys.executable, str(HERE / "preprocess.py"), str(src), str(pre)], capture_output=True, text=True)
    if prep.returncode:
        last = (prep.stderr.strip().splitlines() or ["Le nettoyage de l’image a échoué."])[-1]
        sys.exit(last if "Error" not in last and "Traceback" not in last else "Le nettoyage de l’image a échoué.")
    shutil.rmtree(pages_dir, ignore_errors=True)
    pages_dir.mkdir(parents=True)
    pages = sorted(pre.glob("page-*.png"))
    for p in pages:
        shutil.copy(p, pages_dir / p.name)
    print(f"pages:{len(pages)}", flush=True)

    found = []
    for variant in ("clean.pdf", "alt.pdf"):
        found = audiveris(pre / variant, work / "omr", len(pages))
        if found:
            break
        print(f"Aucune portée lue avec {variant}, essai suivant", file=sys.stderr)
    if not found:
        sys.exit("Aucune portée n’a été reconnue. Essayez un scan plus net : page bien à plat, éclairage régulier, sans ombre.")

    for old in ("partition.mxl", "partition.musicxml"):
        (work / old).unlink(missing_ok=True)
    if len(found) == 1:
        target = work / "partition.mxl"
        shutil.copy(found[0], target)
    else:
        target = work / "partition.musicxml"
        subprocess.run([sys.executable, str(HERE / "merge.py"), str(target), *map(str, found)], check=True)
    shutil.rmtree(pre, ignore_errors=True)
    print(f"partition:{target.name}", flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
