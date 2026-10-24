"""
Moteur de rendu : MusicXML -> une piste audio par voix.
Usage : python3 render.py <partition.mxl|.musicxml> <dossier_sortie> [--tempo 72] [--timbre choeur|piano]
"""
import argparse, copy, json, os, pathlib, re, shutil, statistics, subprocess, sys, zipfile
from music21 import converter, chord, clef, harmony, instrument, key, meter, note, stream, tempo as m21tempo

SF2 = os.environ.get("SOUNDFONT", "/usr/share/sounds/sf2/FluidR3_GM.sf2")
LABELS = {
    4: [("soprano", "Soprano"), ("alto", "Alto"), ("tenor", "Ténor"), ("basse", "Basse")],
    3: [("voix1", "Voix haute"), ("voix2", "Voix médiane"), ("voix3", "Voix basse")],
    2: [("voix1", "Voix haute"), ("voix2", "Voix basse")],
}
FR = {"C": "Do", "D": "Ré", "E": "Mi", "F": "Fa", "G": "Sol", "A": "La", "B": "Si"}
ACCOMP_WORDS = ("piano", "pno", "orgue", "organ", "org.", "accomp", "clavier", "keyboard", "guitare", "guitar")


def fr_name(p, octave=True):
    acc = {"#": "♯", "-": "♭", "##": "𝄪", "--": "𝄫"}.get(p.accidental.modifier if p.accidental else "", "")
    return FR[p.step] + acc + (str(p.octave) if octave and p.octave is not None else "")


def real_chords(part):
    return [c for c in part.recurse().getElementsByClass(chord.Chord) if not isinstance(c, harmony.ChordSymbol)]


def mean_pitch(obj):
    ps = [p.ps for n in obj.recurse().notes for p in n.pitches]
    return statistics.mean(ps) if ps else None


def needs_split(part):
    has_voices = any(len(m.voices) >= 2 for m in part.getElementsByClass(stream.Measure))
    n = len(part.recurse().notes)
    return has_voices or (n and len(real_chords(part)) > n * 0.3)


def keep_highest_or_lowest(line, pick):
    for c in real_chords(line):
        n = note.Note(pick(c.pitches, key=lambda p: p.ps))
        n.duration = copy.deepcopy(c.duration)
        if c.tie is not None:
            n.tie = copy.deepcopy(c.tie)
        for lyr in c.lyrics:
            n.lyrics.append(copy.deepcopy(lyr))
        c.activeSite.replace(c, n)


def split_staff(part):
    """Portée à deux voix (ex. S et A) -> deux parties, mesure par mesure."""
    top, bottom = stream.Part(), stream.Part()
    for m in part.getElementsByClass(stream.Measure):
        mt, mb = stream.Measure(number=m.number), stream.Measure(number=m.number)
        mt.paddingLeft = mb.paddingLeft = m.paddingLeft
        for el in m.getElementsByClass((clef.Clef, key.KeySignature, meter.TimeSignature)):
            mt.insert(el.offset, copy.deepcopy(el)); mb.insert(el.offset, copy.deepcopy(el))
        sung = [v for v in m.voices if v.notes]
        if len(sung) >= 2:
            sung.sort(key=mean_pitch, reverse=True)
            src_t, src_b = sung[0], sung[-1]
        else:
            src_t = src_b = sung[0] if sung else (m.voices[0] if m.voices else m)
        for src, dst in ((src_t, mt), (src_b, mb)):
            for el in src.notesAndRests:
                dst.insert(el.offset, copy.deepcopy(el))
        top.append(mt); bottom.append(mb)
    keep_highest_or_lowest(top, max)
    keep_highest_or_lowest(bottom, min)
    return [top, bottom]


def flatten_voices(part):
    p = copy.deepcopy(part)
    for m in p.getElementsByClass(stream.Measure):
        if m.voices:
            m.flattenUnnecessaryVoices(force=True, inPlace=True)
    keep_highest_or_lowest(p, max)
    return p


def is_accompaniment(part):
    """Portée d'instrument : nommée comme telle, ou remplie d'accords de 3 notes et plus."""
    name = f"{part.partName or ''} {part.partAbbreviation or ''}".lower()
    if any(w in name for w in ACCOMP_WORDS):
        return True
    notes = len(part.recurse().notes)
    big = sum(1 for c in real_chords(part) if len(c.pitches) >= 3)
    return notes > 0 and big > notes * 0.25


def extract_voices(score):
    sung = [p for p in score.parts if p.recurse().notes and not is_accompaniment(p)]
    if not sung:
        sung = [p for p in score.parts if p.recurse().notes]
    voices = []
    for part in sung:
        lines = split_staff(part) if needs_split(part) else [flatten_voices(part)]
        voices.extend(l for l in lines if l.recurse().notes)
    voices.sort(key=lambda v: mean_pitch(v) or 0, reverse=True)
    return voices


def detect_tempo(score):
    marks = list(score.recurse().getElementsByClass(m21tempo.MetronomeMark))
    if marks and marks[0].number:
        return int(round(marks[0].getQuarterBPM()))
    ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
    return 90 if ts and ts.numerator in (6, 9, 12) and ts.denominator == 8 else 72


def prepare(part, tempo_qpm, timbre, velocity=None):
    p = copy.deepcopy(part)
    for el in list(p.recurse().getElementsByClass((instrument.Instrument, m21tempo.MetronomeMark))):
        el.activeSite.remove(el)
    first = p.getElementsByClass(stream.Measure).first() or p
    first.insert(0, instrument.Piano() if timbre == "piano" else instrument.Choir())
    first.insert(0, m21tempo.MetronomeMark(number=tempo_qpm, referent="quarter"))
    if velocity is not None:
        for n in p.recurse().notes:
            n.volume.velocity = velocity
    return p


def to_mp3(sc, base: pathlib.Path):
    mid, wav, mp3 = base.with_suffix(".mid"), base.with_suffix(".wav"), base.with_suffix(".mp3")
    sc.write("midi", fp=str(mid))
    subprocess.run(["fluidsynth", "-ni", "-q", "-g", "0.8", "-F", str(wav), "-r", "44100", SF2, str(mid)],
                   check=True, stdout=subprocess.DEVNULL)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "160k", str(mp3)], check=True)
    wav.unlink(); mid.unlink()
    return mp3.name


def export_musicxml(src: pathlib.Path, dst: pathlib.Path):
    if zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as z:
            root = None
            if "META-INF/container.xml" in z.namelist():
                m = re.search(rb'full-path="([^"]+)"', z.read("META-INF/container.xml"))
                root = m.group(1).decode() if m else None
            root = root or next(n for n in z.namelist()
                                if n.endswith((".xml", ".musicxml")) and not n.startswith("META-INF"))
            dst.write_bytes(z.read(root))
    else:
        shutil.copy(src, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--tempo", type=int, default=0)
    ap.add_argument("--timbre", choices=["choeur", "piano"], default="choeur")
    a = ap.parse_args()

    if not pathlib.Path(SF2).exists():
        sys.exit(f"Banque de sons introuvable : {SF2}")
    out = pathlib.Path(a.out); out.mkdir(parents=True, exist_ok=True)
    score = converter.parse(a.src)
    tempo_qpm = a.tempo or detect_tempo(score)
    voices = extract_voices(score)
    if not voices:
        sys.exit("Aucune note n’a été reconnue dans la partition.")

    labels = LABELS.get(len(voices)) or [(f"voix{i+1}", f"Voix {i+1}") for i in range(len(voices))]
    entries = []
    for i, v in enumerate(voices):
        vid, vname = labels[i]
        stem = to_mp3(stream.Score([prepare(v, tempo_qpm, a.timbre)]), out / vid)
        practice = stream.Score()
        for j, other in enumerate(voices):
            practice.insert(0, prepare(other, tempo_qpm, a.timbre, 112 if i == j else 38))
        work = to_mp3(practice, out / f"{vid}_travail")
        pitches = [p for n in v.recurse().notes for p in n.pitches]
        lo, hi = min(pitches, key=lambda p: p.ps), max(pitches, key=lambda p: p.ps)
        entries.append({"id": vid, "name": vname, "stem": stem, "practice": work,
                        "notes": len(v.recurse().notes), "range": [fr_name(lo), fr_name(hi)]})
        print(f"Voix {i+1}/{len(voices)} : {vname} ({fr_name(lo)} à {fr_name(hi)})", flush=True)

    tutti = to_mp3(stream.Score([prepare(v, tempo_qpm, a.timbre) for v in voices]), out / "tutti")
    export_musicxml(pathlib.Path(a.src), out / "score.musicxml")
    ts = next(iter(score.recurse().getElementsByClass(meter.TimeSignature)), None)
    ks = score.analyze("key")
    manifest = {
        "tempo": tempo_qpm, "timbre": a.timbre, "tutti": tutti, "score": "score.musicxml",
        "measures": len(score.parts[0].getElementsByClass(stream.Measure)),
        "timeSignature": ts.ratioString if ts else None,
        "key": f"{fr_name(ks.tonic, octave=False)} {'majeur' if ks.mode == 'major' else 'mineur'}",
        "voices": entries,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"Terminé : {len(voices)} voix, tonalité {manifest['key']}, fichiers dans {out}")


if __name__ == "__main__":
    main()
