"""
Lecture directe d'un PDF gravé par un logiciel (MuseScore 3 et 4 : symboles de la police SMuFL — Leland, Bravura,
MScore —, chacun placé exactement) : aucune reconnaissance d'image, chaque note est lue telle qu'elle a été gravée.
Hauteur : place de la tête sur sa portée, clé, armure, altérations reportées dans la mesure. Durée : tête (ronde,
blanche, noire), crochets ou ligatures au bout de la queue, points, triolets. Mesures : barres. Voix : la portée
(4 portées : S, A, T, B ; 2 portées : S/A et T/B séparées par le sens des queues ; une portée seule : la voix haute,
ou soprano et alto en accords), les portées masquées d'un système reconnues à leur nom écrit à gauche.

  python3 pdf_vectoriel.py <partition.pdf> <sortie.musicxml>
      code de sortie 2 : PDF sans symboles SMuFL (scan, autre logiciel) : la lecture d'image prend le relais
"""
import ctypes, statistics, sys
from fractions import Fraction

import pypdfium2 as pdfium
import pypdfium2.raw as raw

HEADS = {0xE0A0: 8, 0xE0A2: 4, 0xE0A3: 2, 0xE0A4: 1}
CLEFS = {0xE050: ("G", 0), 0xE052: ("G", -1), 0xE053: ("G", 1), 0xE062: ("F", 0), 0xE05C: ("C", 0),
         0xE07A: ("G", 0), 0xE07C: ("F", 0), 0xE07B: ("C", 0)}
ACC = {0xE260: -1, 0xE261: 0, 0xE262: 1, 0xE263: 2, 0xE264: -2}
FLAGS = {0xE240: 1, 0xE241: 1, 0xE242: 2, 0xE243: 2, 0xE244: 3, 0xE245: 3, 0xE246: 4, 0xE247: 4}
RESTS = {0xE4E2: 8, 0xE4E3: 4, 0xE4E4: 2, 0xE4E5: 1, 0xE4E6: 0.5, 0xE4E7: 0.25, 0xE4E8: 0.125}
DOT = 0xE1E7
TIME = {0xE080 + k: k for k in range(10)}
COMMON, CUT = 0xE08A, 0xE08B
TUPLET = {0xE880 + k: k for k in range(10)}
BOTTOM = {"G": 2 + 7 * 4, "F": 4 + 7 * 2, "C": 3 + 7 * 3}
STEP_PC = [0, 2, 4, 5, 7, 9, 11]
NAMES = ["Soprano", "Alto", "Ténor", "Basse"]
LABELS = [("soprano", "Soprano"), ("alto", "Alto"), ("tenor", "Ténor"), ("ténor", "Ténor"), ("basse", "Basse"),
          ("bass", "Basse"), ("sop", "Soprano"), ("ten", "Ténor"), ("bar", "Basse")]


# ------------------------------------------------------------------------------------------------ éléments de la page

def glyphs(page):
    tp = page.get_textpage()
    out = []
    x, y = ctypes.c_double(), ctypes.c_double()
    for i in range(tp.count_chars()):
        ch = raw.FPDFText_GetUnicode(tp, i)
        if not 0xE000 <= ch <= 0xF8FF:
            continue
        raw.FPDFText_GetCharOrigin(tp, i, ctypes.byref(x), ctypes.byref(y))
        l, b, r, t = tp.get_charbox(i)
        out.append(dict(code=ch, x=x.value, y=y.value, left=l, right=r, bottom=b, top=t, size=t - b))
    return out


def words(page):
    tp = page.get_textpage()
    chars = []
    for i in range(tp.count_chars()):
        ch = raw.FPDFText_GetUnicode(tp, i)
        if 32 < ch < 0x2000:
            l, b, r, t = tp.get_charbox(i)
            chars.append((chr(ch), l, r, (b + t) / 2))
    out = []
    for c in sorted(chars, key=lambda c: (round(c[3] / 3), c[1])):
        if out and abs(out[-1][3] - c[3]) < 3 and 0 <= c[1] - out[-1][2] < 4:
            w = out[-1]
            out[-1] = (w[0] + c[0], w[1], c[2], w[3])
        else:
            out.append(c)
    return out


def paths(page):
    hor, ver, shapes, blocks = [], [], [], []
    for o in page.get_objects():
        if o.type != raw.FPDF_PAGEOBJ_PATH:
            continue
        l, b, r, t = o.get_bounds()
        w, h = r - l, t - b
        if h < 1.2 and w > 30:
            hor.append((l, b, r, t))
        elif w < 2.5 and h > 5:
            ver.append((l, b, r, t))
        elif w > 2 and h < 14:
            shapes.append((l, b, r, t))  # liaisons, ligatures, crochets de triolet
        if w > 30 and 8 < h < 60:
            blocks.append((l, b, r, t))
    if len(hor) < 5 and blocks:
        common = statistics.mode(round(t - b) for _l, b, _r, t in blocks)
        bands = {}
        for l, b, r, t in blocks:
            if abs((t - b) - common) <= 1:
                bands.setdefault((round(b * 2) / 2, round(t * 2) / 2), []).append((l, r))
        hor = []
        for (b, t), xs in bands.items():
            for k in range(5):
                y = b + k * (t - b) / 4
                hor.append((min(x[0] for x in xs), y, max(x[1] for x in xs), y))
    return hor, ver, shapes


def staves_of(hor):
    rows = sorted(hor, key=lambda s: ((s[1] + s[3]) / 2, s[0]))
    used, staves = set(), []
    centres = [((s[1] + s[3]) / 2, s) for s in rows]
    for i, (y0, s0) in enumerate(centres):
        if i in used:
            continue
        group = [i]
        for j in range(i + 1, len(centres)):
            if j in used:
                continue
            yj, sj = centres[j]
            if abs(sj[0] - s0[0]) < 8 and abs(sj[2] - s0[2]) < 8:
                if len(group) == 1 or abs((yj - centres[group[-1]][0]) - (centres[group[1]][0] - y0)) < 0.6:
                    if yj - centres[group[-1]][0] > 2:
                        group.append(j)
                if len(group) == 5:
                    break
        if len(group) == 5:
            ys = [centres[k][0] for k in group]
            gaps = [b - a for a, b in zip(ys, ys[1:])]
            if max(gaps) - min(gaps) < 0.6:
                used.update(group)
                staves.append([ys[0], ys[-1], statistics.mean(gaps), s0[0], s0[2]])
    staves.sort(key=lambda s: (round(s[0]), s[3]))
    merged = []
    for s_ in staves:
        m = next((o for o in merged if abs(o[0] - s_[0]) < 0.6 and abs(o[1] - s_[1]) < 0.6
                  and s_[3] <= o[4] + 3 and s_[4] >= o[3] - 3), None)
        if m is None:
            merged.append(list(s_))
        else:
            m[3], m[4] = min(m[3], s_[3]), max(m[4], s_[4])
    return sorted((tuple(m) for m in merged), key=lambda s: -s[1])


def systems_of(staves, ver):
    groups = [[s] for s in staves]
    merged = True
    while merged:
        merged = False
        for a in range(len(groups) - 1):
            lo, hi = groups[a][-1], groups[a + 1][0]
            if any(v[1] <= hi[1] + 0.5 and v[3] >= lo[0] - 0.5 for v in ver):
                groups[a] += groups.pop(a + 1)
                merged = True
                break
    return groups


def names_of(label):
    out = []
    for w in label.lower().replace(".", " ").replace("&", " ").replace("/", " ").split():
        hit = next((n for k, n in LABELS if w.startswith(k)), None)
        if hit is None and len(w) == 1:
            hit = {"s": "Soprano", "a": "Alto", "t": "Ténor", "b": "Basse"}.get(w)
        if hit and hit not in out:
            out.append(hit)
    return out


# --------------------------------------------------------------------------------------------- lecture d'une portée

def read_staff(st, mine, ver, shapes, texts, all_staves, size):
    y0, y1, sp, xl, xr = st
    mine.sort(key=lambda g: g["x"])
    heads = [g for g in mine if g["code"] in HEADS and g["size"] >= 0.8 * size]
    clefs = [(g["x"], CLEFS[g["code"]]) for g in mine if g["code"] in CLEFS]
    accs = [g for g in mine if g["code"] in ACC]
    first_head = heads[0]["x"] if heads else xr
    key = {}
    for a in accs:
        if a["x"] < first_head - 0.5 * sp and not any(0 < h["x"] - a["x"] < 2.2 * sp and abs(h["y"] - a["y"]) < 0.3 * sp for h in heads):
            cl = max((c for c in clefs if c[0] < a["x"]), default=(0, ("G", 0)))[1]
            d = BOTTOM[cl[0]] + 7 * cl[1] + round((a["y"] - y0) / (sp / 2))
            key["CDEFGAB"[d % 7]] = ACC[a["code"]]
    fifths = sum(1 for v in key.values() if v == 1) - sum(1 for v in key.values() if v == -1)
    # barres de mesure : traits qui couvrent la portée (ou le système), pas les queues
    bars = sorted(v[0] for v in ver if (abs(v[1] - y0) < 0.35 * sp + 1 and abs(v[3] - y1) < 0.35 * sp + 1)
                  or (v[1] <= y0 + 0.3 * sp and v[3] >= y1 - 0.3 * sp and v[3] - v[1] > 5 * sp))
    cuts = []
    for b in bars:
        if b <= xl + 0.5 * sp:
            continue  # ligne d'ouverture du système
        if cuts and b - cuts[-1] < 1.2 * sp:
            cuts[-1] = b  # double barre, barre de reprise : un seul trait de mesure
        else:
            cuts.append(b)
    # chiffres de la mesure : deux chiffres l'un sur l'autre (haut : numérateur)
    time_sig = None
    tdig = [g for g in mine if g["code"] in TIME]
    if any(g["code"] == COMMON for g in mine):
        time_sig = (4, 4)
    elif any(g["code"] == CUT for g in mine):
        time_sig = (2, 2)
    elif tdig:
        mid = (y0 + y1) / 2
        top = "".join(str(TIME[g["code"]]) for g in sorted((g for g in tdig if g["y"] > mid), key=lambda g: g["x"]))
        bot = "".join(str(TIME[g["code"]]) for g in sorted((g for g in tdig if g["y"] <= mid), key=lambda g: g["x"]))
        if top and bot:
            time_sig = (int(top), int(bot))
    # notes : tête, queue, crochets ou ligatures, points
    notes = []
    measure_acc, last_cut = {}, -1e9
    stems = [v for v in ver if v[3] - v[1] < 7 * sp]
    for h in heads:
        passed = [c for c in cuts if last_cut < c < h["x"]]
        if passed:
            measure_acc, last_cut = {}, passed[-1]
        cl = max((c for c in clefs if c[0] < h["x"]), default=(0, ("G", 0)))[1]
        d = BOTTOM[cl[0]] + 7 * cl[1] + round((h["y"] - y0) / (sp / 2))
        step = "CDEFGAB"[d % 7]
        sign = next((a for a in accs if 0 < h["left"] - a["right"] < 1.6 * sp and abs(a["y"] - h["y"]) < 0.3 * sp), None)
        if sign is not None:
            alter = ACC[sign["code"]]
            measure_acc[d] = alter
        else:
            alter = measure_acc.get(d, key.get(step, 0))
        midi = 12 * (d // 7 + 1) + STEP_PC[d % 7] + alter
        up = [v for v in stems if abs(v[0] - h["right"]) < 0.3 * sp and abs(v[1] - h["y"]) < 0.6 * sp and v[3] > h["y"] + sp]
        down = [v for v in stems if abs(v[0] - h["left"]) < 0.3 * sp and abs(v[3] - h["y"]) < 0.6 * sp and v[1] < h["y"] - sp]
        notes.append(dict(x=h["x"], y=h["y"], left=h["left"], right=h["right"], midi=midi, step=step, octave=d // 7,
                          alter=alter, base=HEADS[h["code"]], up=bool(up), down=bool(down),
                          stem=(up or down or [None])[0], tie=False))
    # queue partagée par un accord : la tête du bout la porte, les autres au même x et sous la même queue aussi
    for n in notes:
        if n["stem"] is None:
            for m in notes:
                if m is not n and m["stem"] is not None and abs(m["x"] - n["x"]) < 1.0:
                    s_ = m["stem"]
                    if s_[1] - 0.6 * sp <= n["y"] <= s_[3] + 0.6 * sp:
                        n["stem"], n["up"], n["down"] = s_, m["up"], m["down"]
                        break
    for n in notes:
        dur = Fraction(n["base"])
        if n["base"] == 1 and n["stem"] is not None:
            s_ = n["stem"]
            tip = s_[3] if n["up"] else s_[1]
            sx = (s_[0] + s_[2]) / 2
            flags = [g for g in mine if g["code"] in FLAGS and abs(g["x"] - sx) < 0.6 * sp and abs(g["y"] - tip) < 1.8 * sp]
            if flags:
                dur = Fraction(1, 2 ** FLAGS[flags[0]["code"]])
            else:
                # ligatures : au bout de la queue, les suivantes empilées vers la tête (3/4 d'interligne chacune)
                toward = 1 if not n["up"] else -1  # queue descendante : les ligatures suivantes sont au-dessus
                beams = [b for b in shapes if b[0] - 0.4 <= sx <= b[2] + 0.4 and (b[3] - b[1]) < 3 * sp and (b[2] - b[0]) > 0.6 * sp
                         and b[1] - 0.6 * sp <= tip + (2.6 * sp if toward > 0 else 0) and b[3] + 0.6 * sp >= tip - (2.6 * sp if toward < 0 else 0)
                         and not (b[1] > n["y"] - 0.3 * sp and b[3] < n["y"] + 0.3 * sp)]
                if beams:
                    # une ligature par niveau, chacune son tracé (penchée : son cadre est plus haut qu'elle, on ne
                    # mesure pas sa hauteur, on compte les tracés qui passent au bout de la queue)
                    dur = Fraction(1, 2 ** min(4, len(beams)))
        dots = [g for g in mine if g["code"] == DOT and 0 < g["x"] - n["right"] < 1.6 * sp and abs(g["y"] - n["y"]) < 0.6 * sp]
        if dots:
            dur = dur * (Fraction(3, 2) if len(dots) == 1 else Fraction(7, 4))
        n["dur"] = dur
    # triolets : chiffre « 3 » au-dessus d'un groupe ligaturé ou d'un crochet
    for g in mine:
        if g["code"] in TUPLET and TUPLET[g["code"]] in (3, 5, 6):
            k = TUPLET[g["code"]]
            close = sorted((n for n in notes if abs(n["x"] - g["x"]) < 3.5 * sp), key=lambda n: abs(n["x"] - g["x"]))
            group = sorted({id(n): n for n in close[:k * 2]}.values(), key=lambda n: n["x"])
            xs = sorted({round(n["x"]) for n in group})[:k]
            for n in group:
                if round(n["x"]) in xs:
                    n["dur"] = n["dur"] * Fraction(2 if k == 3 else 4, k)
    # liaisons de prolongation
    for k, n in enumerate(notes):
        for m in notes[k + 1:]:
            if abs(m["y"] - n["y"]) < 0.2 * sp and m["midi"] == n["midi"]:
                if any(n["left"] - 0.3 * sp < s[0] < n["right"] + 0.8 * sp and m["left"] - 0.8 * sp < s[2] < m["right"] + 0.3 * sp
                       and abs((s[1] + s[3]) / 2 - n["y"]) < 1.5 * sp for s in shapes):
                    if not any(n["x"] < q["x"] < m["x"] and abs(q["y"] - n["y"]) < 0.2 * sp for q in notes):
                        m["tie"] = True
                break
    rests = []
    for g in mine:
        if g["code"] in RESTS:
            dur = Fraction(RESTS[g["code"]]).limit_denominator(32)
            if any(d["code"] == DOT and 0 < d["x"] - g["right"] < 1.6 * sp and abs(d["y"] - g["y"]) < 1.2 * sp for d in mine):
                dur *= Fraction(3, 2)
            rests.append(dict(x=g["x"], y=g["y"], dur=dur, whole=g["code"] == 0xE4E3))
    label = " ".join(w[0] for w in sorted(texts, key=lambda w: (-w[3], w[1]))
                     if w[2] < xl + 2 and y0 - 1.5 * sp <= w[3] <= y1 + 1.5 * sp)
    return dict(staff=st, sp=sp, notes=notes, rests=rests, cuts=cuts, clefs=clefs, fifths=fifths, time=time_sig,
                names=names_of(label), mid=(y0 + y1) / 2)


def read_pdf(path):
    doc = pdfium.PdfDocument(str(path))
    systems = []
    for i in range(len(doc)):
        page = doc[i]
        gl = glyphs(page)
        if not any(g["code"] in HEADS for g in gl):
            continue
        hor, ver, shapes = paths(page)
        staves = staves_of(hor)
        texts = words(page)
        size = statistics.median([g["size"] for g in gl if g["code"] in HEADS])
        for group in systems_of(staves, ver):
            content = []
            for st in group:
                y0, y1, sp, xl, xr = st
                mine = [g for g in gl if y0 - 4 * sp <= g["y"] <= y1 + 4 * sp and xl - 2 * sp <= g["x"] <= xr + sp
                        and min(staves, key=lambda s: abs((s[0] + s[1]) / 2 - g["y"])) is st]
                content.append(read_staff(st, mine, ver, shapes, texts, staves, size))
            systems.append(content)
    return systems


# ----------------------------------------------------------------------------------------------- voix et partition

def plan_of(system):
    k = len(system)
    if all(s["names"] for s in system) and len({n for s in system for n in s["names"]}) == sum(len(s["names"]) for s in system):
        return [(s, s["names"]) for s in system]
    if k >= 4:
        return [(s, [NAMES[i]]) for i, s in enumerate(system[-4:])]
    if k in (2, 3):
        return [(system[-2], ["Soprano", "Alto"]), (system[-1], ["Ténor", "Basse"])]
    s = system[0]
    chords = sum(1 for n in s["notes"] if any(m is not n and abs(m["x"] - n["x"]) < 1.0 for m in s["notes"]))
    return [(s, ["Soprano", "Alto"] if chords >= 0.3 * max(1, len(s["notes"])) else ["Soprano"])]


def split_voices(staff, names):
    """Événements de chaque voix de la portée, triés par x : (x, durée, [notes] ou None pour un silence)."""
    notes = sorted(staff["notes"], key=lambda n: (round(n["x"], 1), -n["midi"]))
    onsets = []
    for n in notes:
        if onsets and abs(onsets[-1][0]["x"] - n["x"]) < 1.0:
            onsets[-1].append(n)
        else:
            onsets.append([n])
    out = {name: [] for name in names}
    if len(names) == 1:
        for g in onsets:
            out[names[0]].append((g[0]["x"], min(n["dur"] for n in g), g))
        for r in staff["rests"]:
            out[names[0]].append((r["x"], r["dur"], None))
        return out
    two_stems = any(any(n["up"] and not n["down"] for n in g) and any(n["down"] and not n["up"] for n in g) for g in onsets)
    sp = staff["sp"]
    for g in onsets:
        ups = [n for n in g if n["up"] and not n["down"]]
        downs = [n for n in g if n["down"] and not n["up"]]
        if not two_stems or (len(g) >= 2 and (not ups or not downs)) or (not ups and not downs):
            srt = sorted(g, key=lambda n: -n["midi"])
            hi, lo = [srt[0]], [srt[-1]]
        else:
            hi, lo = ups or None, downs or None
            if len(g) == 1:
                h0 = g[0]
                other = [m for m in staff["notes"] if m is not h0 and abs(m["x"] - h0["x"]) < 3 * sp
                         and (m["down"] if h0["up"] else m["up"])]
                if not other and not any(abs(r["x"] - h0["x"]) < 1.5 * sp for r in staff["rests"]):
                    hi = lo = [h0]
        if hi:
            out[names[0]].append((g[0]["x"], min(n["dur"] for n in hi), hi))
        if lo:
            out[names[1]].append((g[0]["x"], min(n["dur"] for n in lo), lo))
    for r in staff["rests"]:
        # silence au-dessus du milieu : voix du haut ; au-dessous : voix du bas
        target = names[0] if r["y"] > staff["mid"] + 0.3 * sp else names[1] if r["y"] < staff["mid"] - 0.3 * sp else None
        for name in ([target] if target else names):
            if not any(abs(e[0] - r["x"]) < 0.8 * sp for e in out[name]):
                out[name].append((r["x"], r["dur"], None))
    return out


def build(systems):
    from music21 import clef as m21clef, key as m21key, meter, note, chord, stream, tie, metadata
    time_sig = next((s["time"] for sy in systems for s in sy if s["time"]), (4, 4))
    fifths = next((s["fifths"] for sy in systems for s in sy), 0)
    bar = Fraction(4 * time_sig[0], time_sig[1])
    voices = {n: [] for n in NAMES}  # mesures de chaque voix : [[événements]]
    clefs = {}
    for system in systems:
        # barres vues sur au moins la moitié des portées du système (une queue qui couvre une portée n'en est pas une)
        sp0 = system[0]["sp"]
        cand = sorted(c for s in system for c in s["cuts"])
        cuts = []
        for c in cand:
            if cuts and c - cuts[-1] < 1.5 * sp0:
                continue
            votes = sum(1 for s in system if any(abs(c - d) < 1.5 * sp0 for d in s["cuts"]))
            if votes >= max(1, (len(system) + 1) // 2):
                cuts.append(c)
        n_meas = max(1, len(cuts))
        seen = set()
        for staff, names in plan_of(system):
            ev = split_voices(staff, names)
            for name in names:
                seen.add(name)
                cl = staff["clefs"][0][1] if staff["clefs"] else ("G", 0)
                clefs.setdefault(name, cl)
                meas = [[] for _ in range(n_meas)]
                for e in sorted(ev[name], key=lambda e: e[0]):
                    k = next((i for i, c in enumerate(cuts) if e[0] < c), n_meas - 1)
                    meas[min(k, n_meas - 1)].append(e)
                voices[name] += meas
        for name in NAMES:
            if name not in seen:
                voices[name] += [[] for _ in range(n_meas)]  # portée masquée : la voix se tait
    score = stream.Score()
    score.insert(0, metadata.Metadata(title=""))
    total = max(len(m) for m in voices.values())
    for name in NAMES:
        if not any(voices[name]):
            continue
        part = stream.Part()
        part.partName = name
        cl = clefs.get(name, ("G", 0))
        for i in range(total):
            m = stream.Measure(number=i + 1)
            if i == 0:
                m.append({"G": m21clef.Treble8vbClef() if cl[1] < 0 else m21clef.TrebleClef(), "F": m21clef.BassClef(),
                          "C": m21clef.AltoClef()}[cl[0]])
                m.append(m21key.KeySignature(fifths))
                m.append(meter.TimeSignature(f"{time_sig[0]}/{time_sig[1]}"))
            evs = voices[name][i] if i < len(voices[name]) else []
            at = Fraction(0)
            for _x, dur, group in evs:
                q = float(dur)
                if group is None:
                    el = note.Rest(quarterLength=q)
                elif len(group) == 1:
                    el = note.Note(midi=group[0]["midi"], quarterLength=q)
                else:
                    el = chord.Chord([n_["midi"] for n_ in group], quarterLength=q)
                if group is not None and all(n_["tie"] for n_ in group):
                    el.tie = tie.Tie("stop")
                m.insert(float(at), el)
                at += dur
            if not evs:
                m.insert(0, note.Rest(quarterLength=float(bar)))
            part.append(m)
        # liaisons : la note qui précède une note liée commence la liaison
        prev = None
        for el in part.recurse().notes:
            if el.tie is not None and el.tie.type == "stop" and prev is not None:
                prev.tie = tie.Tie("start" if prev.tie is None else "continue")
            prev = el
        score.append(part)
    return score


def main(src, out):
    systems = read_pdf(src)
    n = sum(len(s["notes"]) for sy in systems for s in sy)
    if not systems or n < 8:
        sys.exit(2)
    score = build(systems)
    score.write("musicxml", fp=str(out), makeNotation=False)
    print(f"PDF gravé lu directement : {len(systems)} systèmes, {n} notes", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
