"""
Diagnostic de chaque copie lue par le banc (banc.yml) : chemin de lecture, portées de la partition, voix séparées.
Usage (dans l'image du moteur) : python diag_cas.py <dossier des copies>
"""
import io, contextlib, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "engine"))  # moteur du dépôt (dans l'image : /app/engine)
import render  # noqa: E402
from music21 import converter, stream  # noqa: E402

KEEP = ("Disposition", "disposition:", "Double lecture", "Seconde lecture", "Portées", "Lecture", "lecture", "Mesures",
        "Lectures", "Voix réunies", "exactitude", "Mouvements", "clé", "partition:", "Aucune", "PUPITRE-ERREUR", "Traceback")

for case in sorted(p for p in pathlib.Path(sys.argv[1]).iterdir() if p.is_dir()):
    print(f"=== {case.name}")
    journal = case / "journal.txt"
    if journal.exists():
        lines = [l.strip() for l in journal.read_text(encoding="utf-8").splitlines() if any(k in l for k in KEEP)]
        for l in lines[-12:]:
            print("  |", l[:180])
    fid = case / "fiabilite.json"
    if fid.exists():
        f = json.loads(fid.read_text(encoding="utf-8"))
        print("  fiabilité :", {k: f[k] for k in ("passes", "lecteurs", "moyenne", "mesures", "arbitrees") if k in f})
    part = next(case.glob("partition.*"), None)
    if not part:
        print("  pas de partition")
        continue
    sc = converter.parse(str(part))
    print("  portées :", [(p.partName, len(p.getElementsByClass(stream.Measure)), len(p.recurse().notes)) for p in sc.parts])
    with contextlib.redirect_stderr(io.StringIO()) as err:
        voices = render.extract_voices(converter.parse(str(part)), trust_names=False)
    for l in err.getvalue().splitlines()[-4:]:
        print("  render |", l[:180])
    print("  voix :", [(v.partName, len(v.recurse().notes), round(render.mean_pitch(v) or 0)) for v in voices])
