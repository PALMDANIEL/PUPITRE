"""
Assemblage : Audiveris coupe la partition en plusieurs mouvements (clean.mvt1.mxl, clean.mvt2.mxl…)
dès que le nombre de portées change (couplet en solo, par exemple). On les remet bout à bout.
Usage : python3 merge.py <sortie.musicxml> <mvt1.mxl> <mvt2.mxl> ...
"""
import copy, sys
from music21 import converter, note, stream


def rest_measure(model: stream.Measure) -> stream.Measure:
    m = stream.Measure()
    r = note.Rest(quarterLength=model.barDuration.quarterLength if model.timeSignature else model.highestTime or 4)
    m.append(r)
    return m


def main(out, sources):
    movements = [converter.parse(s) for s in sources]
    width = max(len(mv.parts) for mv in movements)
    merged = [stream.Part() for _ in range(width)]
    for i, part in enumerate(movements[0].parts):
        merged[i].partName = part.partName
        merged[i].id = part.id
    number = 0
    for mv in movements:
        parts = list(mv.parts)
        model = parts[0].getElementsByClass(stream.Measure)
        count = max(len(p.getElementsByClass(stream.Measure)) for p in parts)
        for i in range(width):
            measures = list(parts[i].getElementsByClass(stream.Measure)) if i < len(parts) else []
            for k in range(count):
                m = copy.deepcopy(measures[k]) if k < len(measures) else rest_measure(model[min(k, len(model) - 1)])
                m.number = number + k + 1
                merged[i].append(m)
        number += count
    score = stream.Score(merged)
    score.write("musicxml", fp=out, makeNotation=False)
    print(f"Mouvements assemblés : {len(movements)}, {number} mesures")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
