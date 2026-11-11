"""
Altérations relues sur l'image pour les lectures de homr (portées lues une à une : copies usées, tachées, floues).

homr écrit la suite des notes de chaque ligne, sans leur place sur l'image ; ses dièses et bécarres se perdent sur une
copie abîmée (banc : copies usées à quatre portées lues par homr seul, la4 pour la♯4, ré♯ pour ré♮). Pour chaque ligne
lue (image découpée, portees.json), les têtes de notes sont repérées sur l'image (lignes de portée ôtées, têtes blanches
remplies), placées sur la portée (ligne ou interligne), puis appariées dans l'ordre aux notes de homr de même place ; le
reconnaisseur appris de signes.py (zone à gauche de la tête) dit alors s'il y a un ♯, un ♮ ou un ♭. Un signe sûr
remplace celui de homr et vaut pour la suite de la mesure.

Usage : python3 signes_homr.py <dossier des voix> <disposition : satb|grand>
(modifie sortie*/v*.musicxml en place ; écrit le nombre de notes changées)
"""
import json
import os
import pathlib
import sys
import xml.etree.ElementTree as ET

import cv2
import numpy as np

import imgio
import signes

STEPS = "CDEFGAB"
BOTTOM = {"G": 2 + 7 * 4, "G8": 2 + 7 * 3, "F": 4 + 7 * 2}  # ligne du bas : mi4, mi3 (sol 8), sol2
ALTER = {"sharp": 1, "natural": 0, "flat": -1}
# homr invente aussi des altérations (mi♯3 en mi majeur, rien devant la tête) : retirée quand le reconnaisseur est sûr
# qu'il n'y a aucun signe et qu'aucune note de même nom ne la porte plus tôt dans la mesure
REMOVE = os.environ.get("PUPITRE_SIGNES_HOMR_RETRAIT", "1") == "1"
NONE_SURE = 0.98
SHARPS_ORDER, FLATS_ORDER = "FCGDAEB", "BEADGCF"


def _key_alter(fifths):
    """Altération de chaque note dans l'armure (dièses > 0, bémols < 0)."""
    out = {st: 0 for st in STEPS}
    for st in (SHARPS_ORDER[:fifths] if fifths > 0 else FLATS_ORDER[:-fifths]):
        out[st] = 1 if fifths > 0 else -1
    return out


def heads(img, T, B):
    """Têtes de notes de la ligne : [(x du centre, y du centre, bord gauche, place)] ; place 0 = ligne du bas, 8 = du haut."""
    sp = (B - T) / 4
    H, W = img.shape
    ink = (img < 128).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(3, int(1.6 * sp)), 1)))
    body = ink & (1 - lines)
    body = cv2.morphologyEx(body, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(3, int(0.4 * sp)))))
    # têtes blanches (blanches, rondes) : leur creux rempli
    n, lab, st, _c = cv2.connectedComponentsWithStats((1 - body).astype(np.uint8), 4)
    small = (st[:, cv2.CC_STAT_AREA] < 0.9 * sp * sp) & (st[:, cv2.CC_STAT_LEFT] > 0) & (st[:, cv2.CC_STAT_TOP] > 0) & \
            (st[:, cv2.CC_STAT_LEFT] + st[:, cv2.CC_STAT_WIDTH] < W) & (st[:, cv2.CC_STAT_TOP] + st[:, cv2.CC_STAT_HEIGHT] < H)
    small[0] = False
    body = np.where(small[lab], 1, body).astype(np.uint8)
    k = max(3, int(0.6 * sp)) | 1
    blobs = cv2.morphologyEx(body, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(blobs, 8)
    out = []
    for s_, (cx, cy) in zip(st[1:], cen[1:]):
        x, y, w, h = (int(v) for v in s_[:4])
        if not (0.55 * sp <= h <= 1.5 * sp and 0.8 * sp <= w <= 2.0 * sp):
            continue
        if not (T - 3.5 * sp <= cy <= B + 3.5 * sp):
            continue
        out.append((float(cx), float(cy), float(x), int(round((B - cy) / (sp / 2)))))
    return sorted(out)


def _place(step, octave, clef):
    return STEPS.index(step) + 7 * octave - BOTTOM[clef]


def align(want, seen):
    """Appariement dans l'ordre (programmation dynamique) : want = places des notes de homr, seen = places des têtes.
    Rend [(i, j)] des paires de même place."""
    n, m = len(want), len(seen)
    INF = 1e9
    D = np.full((n + 1, m + 1), INF)
    D[0, :] = np.arange(m + 1) * 0.5  # têtes en trop (armure, débris) : peu coûteuses
    D[:, 0] = np.arange(n + 1) * 1.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            d = abs(want[i - 1] - seen[j - 1])
            match = 0.0 if d == 0 else 0.8 if d == 1 else INF
            D[i, j] = min(D[i - 1, j] + 1.0, D[i, j - 1] + 0.5, D[i - 1, j - 1] + match)
    pairs, i, j = [], n, m
    while i and j:
        d = abs(want[i - 1] - seen[j - 1])
        match = 0.0 if d == 0 else 0.8 if d == 1 else INF
        if D[i, j] == D[i - 1, j - 1] + match:
            if d == 0:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif D[i, j] == D[i - 1, j] + 1.0:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def _notes_by_line(root):
    """Notes de la partie (homr : une partie), ligne par ligne : [[(mesure, élément note)]]."""
    lines = []
    part = root.find("part")
    for m in part.findall("measure"):
        pr = m.find("print")
        if not lines or (pr is not None and pr.get("new-system") == "yes"):
            lines.append([])
        for n in m.findall("note"):
            if n.find("pitch") is not None and n.find("grace") is None:
                lines[-1].append((m, n))
    return lines


def _set(n, alter, sign):
    p = n.find("pitch")
    a = p.find("alter")
    if alter:
        if a is None:
            a = ET.Element("alter")
            p.insert(1, a)
        a.text = str(int(alter))
    elif a is not None:
        p.remove(a)
    acc = n.find("accidental")
    if sign is None:
        return
    if acc is None:
        acc = ET.Element("accidental")
        kids = list(n)
        after = next((i for i, c in enumerate(kids) if c.tag in ("type", "dot")), len(kids) - 1)
        n.insert(after + 1, acc)
    acc.text = sign


def fix_file(xml_path, spec_lines, kept, folder, clef):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    lines = _notes_by_line(root)
    c = root.find(".//attributes/clef")  # clé écrite par homr (ténor : sol sans 8, une octave plus haut)
    if c is not None and c.findtext("sign") in ("G", "F"):
        clef = c.findtext("sign") + ("8" if c.findtext("sign") == "G" and c.findtext("clef-octave-change") == "-1" else "")
    changed = 0
    W = signes._weights()
    if not W:
        return 0
    for li, notes in enumerate(lines):
        if li >= len(kept) or not notes:
            continue
        line = spec_lines[kept[li]]
        img = imgio.imread(str(folder / line["image"]), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        T, B = float(line["T"]), float(line["B"])
        sp = (B - T) / 4
        seen = heads(img, T, B)
        want = [_place(n.findtext("pitch/step"), int(n.findtext("pitch/octave")), clef) for _m, n in notes]
        pairs = align(want, [h[3] for h in seen])
        decided = {}
        rows, which = [], []
        for i, j in pairs:
            p = signes.net_patch(img, seen[j][2], seen[j][1], sp)
            if p is not None:
                rows.append(p.reshape(-1))
                which.append(i)
        if not rows:
            continue
        X = (np.array(rows, np.float32) - W["mu"]) / W["sd"]
        h = np.maximum(0, X @ W["W1"] + W["b1"])
        z = h @ W["W2"] + W["b2"]
        z -= z.max(1, keepdims=True)
        pr = np.exp(z)
        pr /= pr.sum(1, keepdims=True)
        nothing = set()
        for i, q in zip(which, pr):
            k = int(np.argmax(q))
            if k and q[k] >= signes.NET_SURE:
                decided[i] = ("sharp", "natural", "flat")[k - 1]
            elif not k and q[0] >= NONE_SURE:
                nothing.add(i)
        try:
            fifths = int(root.findtext(".//attributes/key/fifths") or 0)
        except ValueError:
            fifths = 0
        in_key = _key_alter(fifths)
        # report dans la mesure : un signe vaut pour les notes suivantes de même nom et octave
        carry, current, seen_here = {}, None, set()
        for i, (m, n) in enumerate(notes):
            if m is not current:
                carry, current, seen_here = {}, m, set()
            here = (n.findtext("pitch/step"), n.findtext("pitch/octave"))
            alter = float(n.findtext("pitch/alter") or 0)
            first_here = here not in seen_here
            seen_here.add(here)
            if REMOVE and i in nothing and i not in decided and first_here and here not in carry \
                    and alter != in_key[here[0]]:
                # altération de homr sans signe devant la tête, la première de la mesure : armure rétablie
                _set(n, in_key[here[0]], None)
                acc = n.find("accidental")
                if acc is not None:
                    n.remove(acc)
                changed += 1
                carry[here] = in_key[here[0]]  # les notes suivantes de même nom suivent
                continue
            if i in decided:
                sign = decided[i]
                if alter != ALTER[sign] or n.findtext("accidental") != sign:
                    _set(n, ALTER[sign], sign)
                    changed += 1
                carry[here] = ALTER[sign]
            elif n.findtext("accidental") in ALTER:
                carry[here] = ALTER[n.findtext("accidental")]
            elif here in carry and alter != carry[here]:
                _set(n, carry[here], None)
                changed += 1
    if changed:
        tree.write(xml_path, encoding="utf-8", xml_declaration=True)
    return changed


def fix(folder, layout):
    import pupitres
    folder = pathlib.Path(folder)
    spec = json.loads((folder / "portees.json").read_text(encoding="utf-8"))
    total = 0
    for out in sorted(folder.glob("sortie*")):
        if out.name == "sortie-entetes":
            continue
        for v, (_name, clef) in enumerate(pupitres.LAYOUTS[layout]):
            xml = out / f"v{v + 1}.musicxml"
            side = out / f"v{v + 1}.lignes.json"
            if not xml.exists() or v >= len(spec["voix"]):
                continue
            kept = json.loads(side.read_text(encoding="utf-8")) if side.exists() else list(range(len(spec["voix"][v])))
            total += fix_file(xml, spec["voix"][v], kept, folder, clef)
    return total


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    n = fix(sys.argv[1], sys.argv[2])
    print(f"Altérations relues sur l'image (lecture de homr) : {n} notes", file=sys.stderr)
