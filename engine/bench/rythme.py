"""
Rythme des voix rendues (render.extract_voices), comparé à la gravure : durée totale de la voix du haut contre celle
de la partition gravée (gravure.musicxml, ou gravure-1/-2 pour une page mêlée). Le banc ne compte que les hauteurs ;
une mesure complétée par un silence de trop (indication de mesure oubliée : 4 temps supposés pour un 3/4) ne s'y voit
pas, mais fausse l'écoute.
  <python du moteur> rythme.py <lectures (cas avec partition.*)> <copies (cas avec gravure*.musicxml)>
"""
import glob, json, pathlib, statistics, sys, warnings

warnings.filterwarnings("ignore")
ENGINE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE))
from music21 import converter, stream  # noqa: E402
import render  # noqa: E402


def engraved_length(case):
    files = sorted(case.glob("gravure*.musicxml"))
    total = 0.0
    for f in files:
        sc = converter.parse(str(f))
        total += float(sum(m.duration.quarterLength for m in sc.parts[0].getElementsByClass(stream.Measure)))
    return total


def main():
    reads, copies = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    errs, off = [], 0
    for d in sorted(p for p in reads.rglob("recueils-*") if p.is_dir()):
        part = next(iter(d.glob("partition.*")), None)
        name = d.name.replace("recueils-", "", 1)
        src = copies / name
        if part is None or not src.exists():
            continue
        voices = render.extract_voices(converter.parse(str(part)), trust_names=False)
        if not voices:
            continue
        got = float(sum(m.duration.quarterLength for m in voices[0].getElementsByClass(stream.Measure)))
        want = engraved_length(src)
        e = abs(got - want) / max(want, 1e-6)
        errs.append(e)
        off += e > 0.1
    print(f"{len(errs)} copies ; écart de durée médian {100 * statistics.median(errs):.1f} % ; moyen "
          f"{100 * statistics.mean(errs):.1f} % ; copies à plus de 10 % : {off}")


if __name__ == "__main__":
    main()
