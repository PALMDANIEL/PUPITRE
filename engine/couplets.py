"""
Couplets sur une portée seule (psaumes : refrain à quatre voix sur deux portées, couplets du soliste sur une portée,
souvent en tons de psaume : brève « ‖o‖ » de récitation puis quelques notes, dans une mesure plus longue que la
mesure écrite). Audiveris y écarte les notes qui débordent de la mesure (la brève, ou les notes qui la suivent : la
moitié du couplet perdue, même sur une copie nette). homr, qui lit une portée sans se soucier de la mesure, lit ces
lignes presque parfaitement : les mesures des couplets sont reprises de sa lecture, ligne par ligne, quand elle donne
autant de mesures qu'Audiveris pour cette ligne.

Étape 1 (prepare) : lignes des couplets découpées sur les pages, portees.json pour pupitre-homr --portees (une
« voix » par ligne, pour savoir quelles mesures viennent de quelle ligne).
Étape 2 (apply) : mesures de la partition remplacées par celles de homr ; paroles d'Audiveris reportées sur les notes
de même hauteur ; altérations invraisemblables retirées (les deux traits de la brève passent pour un bémol).
"""
import copy
import difflib
import json
import os
import pathlib
import sys

import cv2

import imgio
import pupitres

ENABLED = os.environ.get("PUPITRE_COUPLETS", "1") != "0"


def layout(pages_dir: pathlib.Path):
    """Systèmes des pages, dans l'ordre : [(fichier de la page, [portées (haut, bas, gauche, droite)]), …]."""
    out = []
    for pf in sorted(pages_dir.glob("page-*.png")):
        bw = imgio.imread(str(pf), cv2.IMREAD_GRAYSCALE)
        staves = [(*s, "vue") for s in pupitres.find_staves(bw)]
        for g in pupitres.system_indexes(bw, staves, dashed=pupitres._dashed()):
            out.append((pf, [staves[i][:4] for i in g]))
    return out


def prepare(pages_dir: pathlib.Path, folder: pathlib.Path):
    """
    Lignes des couplets : systèmes d'une seule portée qui suivent tous les systèmes de plusieurs portées (refrain
    puis couplets : la disposition des psaumes). Rend la liste des systèmes, ou None si la page n'est pas ainsi faite.
    """
    systems = layout(pages_dir)
    sizes = [len(s) for _pf, s in systems]
    if not sizes or max(sizes) < 2 or sizes[-1] != 1:
        return None
    tail = len(sizes)
    while tail and sizes[tail - 1] == 1:
        tail -= 1
    if any(n == 1 for n in sizes[:tail]):
        return None  # couplets entre deux systèmes du refrain : pas encore
    folder.mkdir(parents=True, exist_ok=True)
    voix = []
    for k, (pf, staff) in enumerate(systems[tail:]):
        bw = imgio.imread(str(pf), cv2.IMREAD_GRAYSCALE)
        t, b, _l, _r = staff[0]
        sp = (b - t) / 4
        y0, y1 = int(max(0, t - 4 * sp)), int(min(bw.shape[0], b + 4 * sp))
        name = f"couplet-{k + 1:02d}.png"
        imgio.imwrite(str(folder / name), bw[y0:y1])
        voix.append([{"image": name, "T": t - y0, "B": b - y0}])
    (folder / "portees.json").write_text(json.dumps({"voix": voix, "passes": 1}), encoding="utf-8")
    return systems[tail:]


def _sounding(m):
    return [n for n in m.recurse().notes if n.pitches and not n.duration.isGrace]


def _keysig(part, m):
    from music21 import key
    ks = m.getContextByClass(key.KeySignature)
    if ks is None:
        ks = next(iter(part.recurse().getElementsByClass(key.KeySignature)), None)
    return ks or key.KeySignature(0)


def _clean(p, ks):
    """Altération invraisemblable (bémol sans bémol à l'armure, la♯…) ramenée à l'armure."""
    from music21 import pitch
    a = ks.accidentalByStep(p.step)
    want = a.alter if a else 0
    alter = p.accidental.alter if p.accidental else 0
    if alter != want and not pupitres._plausible_accidental(p.step, alter, ks.sharps):
        p.accidental = pitch.Accidental(a.name) if a else None


def apply(partition, folder: pathlib.Path, out) -> int:
    """Mesures des couplets remplacées par la lecture de homr. Rend le nombre de lignes reprises."""
    from music21 import chord, converter, note, stream
    spec = json.loads((folder / "portees.json").read_text(encoding="utf-8"))
    lines = []
    for v in range(1, len(spec["voix"]) + 1):
        f = folder / "sortie" / f"v{v}.musicxml"
        if not f.exists():
            return 0
        sc = converter.parse(str(f))
        lines.append([m for p in sc.parts[:1] for m in p.getElementsByClass(stream.Measure)])
    score = converter.parse(str(partition))
    import arbitre
    arbitre.drop_chord_symbols(score)
    staves = list(score.parts)
    rows = [list(p.getElementsByClass(stream.Measure)) for p in staves]
    total = max(len(r) for r in rows)
    need = sum(len(l) for l in lines)
    if not need or need >= total:
        print(f"Couplets : {need} mesures lues par homr pour {total} dans la partition, pas de reprise", file=sys.stderr)
        return 0
    start = total - need
    # mesures des couplets : une seule portée y chante (ou aucune, si Audiveris a tout perdu)
    voices = {}
    for i in range(start, total):
        singing = [k for k, r in enumerate(rows) if i < len(r) and _sounding(r[i])]
        if len(singing) > 1:
            print(f"Couplets : mesure {i + 1} chantée par {len(singing)} portées, pas de reprise", file=sys.stderr)
            return 0
        if singing:
            voices[i] = singing[0]
    if not voices:
        return 0
    staff_of = max(set(voices.values()), key=list(voices.values()).count)
    taken = 0
    i = start
    for line in lines:
        for k, hm in enumerate(line):
            idx = i + k
            r = rows[voices.get(idx, staff_of)]
            if idx >= len(r):
                continue
            m = r[idx]
            ks = _keysig(staves[voices.get(idx, staff_of)], m)
            old = _sounding(m)
            new = []
            for el in hm.recurse().notesAndRests:
                # accords gardés : couplet de soprano et alto sur une portée (Psaumes 24, 70), écrit en accords
                if isinstance(el, chord.Chord):
                    n = chord.Chord(sorted({p.nameWithOctave: p for p in el.pitches}.values(), key=lambda p: p.ps),
                                    quarterLength=el.quarterLength)
                elif isinstance(el, note.Note):
                    n = note.Note(el.pitch, quarterLength=el.quarterLength)
                else:
                    n = note.Rest(quarterLength=el.quarterLength)
                if not n.isRest:
                    n.tie = el.tie
                    for p in n.pitches:
                        _clean(p, ks)
                new.append(n)
            # paroles d'Audiveris reportées sur la note de même hauteur (alignement des suites de hauteurs)
            top = lambda x: max(p.midi for p in x.pitches)  # noqa: E731
            a_seq = [top(o) for o in old]
            b_seq = [top(n) if not n.isRest else -1 for n in new]
            for tag, a1, a2, b1, b2 in difflib.SequenceMatcher(a=a_seq, b=b_seq, autojunk=False).get_opcodes():
                if tag in ("equal", "replace"):
                    for o, n in zip(old[a1:a2], new[b1:b2]):
                        if not n.isRest and o.lyrics:
                            n.lyrics = copy.deepcopy(o.lyrics)
            for el in list(m.recurse().notesAndRests):
                el.activeSite.remove(el)
            for v in list(m.voices):
                m.remove(v)
            at = 0.0
            for n in new:
                m.insert(at, n)
                at += float(n.quarterLength)
        i += len(line)
        taken += 1
    score.write("musicxml", fp=str(out))
    return taken


def main():
    if len(sys.argv) < 3:
        sys.exit("couplets.py prepare <pages> <dossier> | apply <partition> <dossier> <sortie>")
    if sys.argv[1] == "prepare":
        systems = prepare(pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3]))
        sys.exit(0 if systems else 3)
    n = apply(sys.argv[2], pathlib.Path(sys.argv[3]), sys.argv[4])
    print(f"Couplets relus par homr : {n} lignes", file=sys.stderr)
    sys.exit(0 if n else 3)


if __name__ == "__main__":
    main()
