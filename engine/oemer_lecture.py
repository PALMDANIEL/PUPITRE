"""
Troisième lecteur : oemer (MIT, https://github.com/BreezeWhite/oemer), lecture de la page entière par deux réseaux
(segmentation), autre famille que homr. Sert de troisième avis à l'arbitrage (arbitre.py --oemer) quand Audiveris et
homr diffèrent. oemer tourne dans son propre environnement Python (PUPITRE_OEMER_PYTHON) : sa version 0.1.5 demande les
alias numpy retirés (np.int…) et OpenCV 4.

Sa sortie MusicXML écrit les portées l'une après l'autre, système par système (sol du 1er système, fa du 1er, sol du
2e…), toutes sur « staff 1 », et <alter>0</alter> sur chaque note (l'armure s'en trouve effacée) : convert() en refait
une partition à deux portées (sol, fa), deux voix chacune, débuts recalculés voix par voix, armure réappliquée.

Usage : python3 oemer_lecture.py <page.png> <dossier> → <dossier>/oemer.musicxml
"""
import os
import pathlib
import subprocess
import xml.etree.ElementTree as ET
from music21 import chord, clef, key, meter, note, pitch, stream

SHARPS, FLATS = "FCGDAEB", "BEADGCF"


def convert(path, out):
    root = ET.parse(path).getroot()
    part = root.find("part")
    divisions, fifths, beats = 16, 0, "4/4"
    segments = []  # (signe de clé, [mesures])
    for m in part.findall("measure"):
        att = m.find("attributes")
        if att is not None:
            if att.findtext("divisions"):
                divisions = int(att.findtext("divisions"))
            if att.find("key/fifths") is not None:
                fifths = int(att.findtext("key/fifths"))
            if att.find("time/beats") is not None:
                beats = f"{att.findtext('time/beats')}/{att.findtext('time/beat-type')}"
            if att.find("clef/sign") is not None:
                segments.append((att.findtext("clef/sign"), []))
        if not segments:
            segments.append(("G", []))
        pos, last, events = {}, {}, []
        for n in m.findall("note"):
            v = n.findtext("voice") or "1"
            dur = int(n.findtext("duration") or 0) / divisions
            p = n.find("pitch")
            if n.find("chord") is not None and v in last:
                at = last[v]
            else:
                at = pos.get(v, 0.0)
                pos[v] = at + dur
                last[v] = at
            if p is None:
                continue
            step, octave = p.findtext("step"), int(p.findtext("octave"))
            alter = float(p.findtext("alter") or 0)
            if alter == 0 and n.find("accidental") is None:
                if fifths > 0 and step in SHARPS[:fifths]:
                    alter = 1
                elif fifths < 0 and step in FLATS[:-fifths]:
                    alter = -1
            events.append((v, at, dur, step, octave, alter))
        segments[-1][1].append(events)
    staves = {"G": [], "F": []}
    for sign, ms in segments:
        staves["F" if sign == "F" else "G"].extend(ms)
    n = max(len(staves["G"]), len(staves["F"]))
    score = stream.Score()
    for sign in ("G", "F"):
        p = stream.Part()
        for k in range(n):
            m = stream.Measure(number=k + 1)
            if k == 0:
                m.insert(0, clef.TrebleClef() if sign == "G" else clef.BassClef())
                m.insert(0, key.KeySignature(fifths))
                m.insert(0, meter.TimeSignature(beats))
            evs = staves[sign][k] if k < len(staves[sign]) else []
            for vid in sorted({e[0] for e in evs}):
                voice = stream.Voice(id=vid)
                groups = {}
                for e in evs:
                    if e[0] == vid:
                        groups.setdefault((e[1], e[2]), []).append(e)
                for (at, dur), g in sorted(groups.items()):
                    ps = [pitch.Pitch(step=s, octave=o, accidental=a if a else None) for _v, _a, _d, s, o, a in g]
                    el = chord.Chord(ps, quarterLength=dur) if len(ps) > 1 else note.Note(ps[0], quarterLength=dur)
                    voice.insert(at, el)
                m.insert(0, voice)
            if not evs:
                m.insert(0, note.Rest(quarterLength=4.0))
            p.append(m)
        score.insert(0, p)
    score.write("musicxml", fp=out, makeNotation=False)
    return n




LAUNCHER = """
import sys
import numpy as np
for name, val in (("int", int), ("float", float), ("object", object)):
    if name not in np.__dict__:
        setattr(np, name, val)
import warnings
warnings.filterwarnings("ignore")
sys.argv = ["oemer"] + sys.argv[1:]
from oemer.ete import main
main()
"""
PYTHON = os.environ.get("PUPITRE_OEMER_PYTHON", os.path.expanduser("~/pupitre/oemer-venv/bin/python3"))


def read(page, folder, timeout=1800):
    """oemer sur une page (prédictions gardées en cache : folder/page.pkl) ; rend le chemin de la lecture convertie ou None."""
    folder = pathlib.Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    img = folder / "page.png"
    if not img.exists():
        import shutil
        shutil.copy(page, img)
    out = folder / "oemer.musicxml"
    if out.exists():
        return out
    import sys
    if not pathlib.Path(PYTHON).exists():
        print(f"Lecture d'oemer impossible : {PYTHON} absent", file=sys.stderr)
        return None
    try:
        r = subprocess.run([PYTHON, "-c", LAUNCHER, str(img), "-o", str(folder) + "/", "--save-cache"], cwd=folder,
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print("Lecture d'oemer impossible : trop longue", file=sys.stderr)
        return None
    raw = folder / "page.musicxml"
    if not raw.exists():
        last = [l for l in (r.stdout + r.stderr).splitlines() if l.strip() and "Context leak" not in l][-5:]
        print(f"Lecture d'oemer impossible : {' | '.join(last)[:900]}", file=sys.stderr)
        return None
    try:
        convert(str(raw), str(out))
    except Exception as e:  # noqa: BLE001 : sans troisième avis
        print(f"Lecture d'oemer illisible : {e}", file=sys.stderr)
        return None
    return out


if __name__ == "__main__":
    import sys
    print(read(sys.argv[1], sys.argv[2]))
