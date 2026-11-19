"""
Bonne réponse du banc des chorales tirée de la lecture directe d'un PDF gravé (pdf_vectoriel.py, durées comprises) :
hauteurs par voix, sans les suites de liaison. Remplace verite_pdf.py (sans durées) depuis le 19/11/2026 : une tête
seule à une queue y était donnée aux deux voix même quand l'autre voix tenait encore sa note (croche de la basse
comptée au ténor, ré-mi de l'alto à la soprano pendant sa ronde) ; toutes les différences vérifiées sur la partition.
  python pdf_vectoriel.py source.pdf lu.musicxml && python bench/verite_directe.py lu.musicxml > truth.json
"""
import sys, json
from music21 import converter
sc = converter.parse(sys.argv[1])
out = {}
for p in sc.parts:
    seq = []
    for n in p.recurse().notes:
        if not n.pitches or (n.tie is not None and n.tie.type in ("stop", "continue")):
            continue
        seq.append(int(max(n.pitches, key=lambda q: q.ps).midi))
    if seq:
        out[p.partName] = seq
print(json.dumps(out))
