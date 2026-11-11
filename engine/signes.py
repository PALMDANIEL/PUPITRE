"""
Altérations écrites dans la mesure (♯ ♮ ♭ devant une note), relues sur l'image : sur une photo ou une vieille copie,
Audiveris en perd beaucoup (≈ 1,6 % des notes du banc d'essai : le la♯ d'un mi majeur lu la, le sol♯ d'un la mineur
lu sol) ou prend un dièse pour un bécarre. Chaque note de sa lecture est replacée sur l'image (sa position est dans
le MusicXML, en dixièmes d'interligne), puis on compare l'encre juste à sa gauche, lignes de portée ôtées, aux
dessins du dièse, du bécarre et du bémol (police Bravura, celle d'Audiveris). Un signe nettement reconnu, à la
hauteur de la note, remplace celui qu'Audiveris a lu (ou son absence) ; l'altération vaut pour la suite de la mesure.

Liaisons (PDF net seulement) : deux notes de même hauteur qui se suivent dans une voix, reliées par un arc sur l'image,
qu'Audiveris a écarté (sans liaison, la note tenue est chantée deux fois).

Usage : python3 signes.py <lecture.mxl> <page-01.png> [page-02.png …] [--sans-signes] [--sans-liaisons] [--flou]
(réécrit la lecture ; rien si rien à changer)
"""
import os, sys, zipfile, pathlib
import xml.etree.ElementTree as ET

import cv2
import numpy as np

import imgio

GLYPHS = {"sharp": "", "natural": "", "flat": ""}
ALTER = {"sharp": 1.0, "natural": 0.0, "flat": -1.0}
BOTTOM = {("G", 2): 31, ("F", 4): 19, ("C", 3): 25, ("C", 4): 23, ("C", 1): 29, ("F", 3): 21, ("C", 2): 27}
SCORE, MARGIN = float(os.environ.get("PUPITRE_SIGNES_SEUIL", "0.44")), 0.12
PLACE_AGAIN = os.environ.get("PUPITRE_SIGNES_REVOTE", "1") == "1"  # portées non placées revotées à la bonne échelle


def _read(path):
    if str(path).endswith(".mxl"):
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith(".xml") and not n.startswith("META"))
            return ET.fromstring(z.read(name)), name
    return ET.parse(path).getroot(), None


def _write(path, root, name):
    data = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    if name is None:
        pathlib.Path(path).write_bytes(data)
        return
    with zipfile.ZipFile(path) as z:
        items = [(i, z.read(i.filename)) for i in z.infolist()]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for info, content in items:
            z.writestr(info, data if info.filename == name else content)


def notes_of(root):
    """Notes d'une lecture : page, système, portée, position x (dixièmes), nom, octave, altération, signe écrit."""
    d = root.find("defaults")
    pw = float(d.findtext("page-layout/page-width"))
    lm = float(d.findtext("page-layout/page-margins/left-margin") or 0)
    out = []
    for pi, part in enumerate(root.findall("part")):
        page, system, x0, sysleft, clefs, octs = 0, -1, 0.0, 0.0, {}, {}
        for mindex, m in enumerate(part.findall("measure")):
            pr = m.find("print")
            if pr is not None and pr.get("new-page") == "yes":
                page += 1
                system = -1
            if system < 0 or (pr is not None and pr.get("new-system") == "yes"):
                system += 1
                x0 = 0.0
                sl = pr.find("system-layout/system-margins/left-margin") if pr is not None else None
                sysleft = float(sl.text) if sl is not None else sysleft
                first = True
            else:
                first = False
            for c in m.iter("clef"):
                n = int(c.get("number", "1"))
                clefs[n] = (c.findtext("sign"), int(c.findtext("line") or 0))
                octs[n] = int(c.findtext("clef-octave-change") or 0)
            for k, n in enumerate(m.findall("note")):
                if n.find("pitch") is None or n.get("default-x") is None or n.find("grace") is not None:
                    continue
                st = int(n.findtext("staff") or 1)
                out.append(dict(part=pi, staff=st, page=page, system=system, measure=m, first=first, el=n,
                                voice=n.findtext("voice") or "1", mindex=mindex, order=k,
                                tied={t.get("type") for t in n.findall("tie")},
                                x=lm + sysleft + x0 + float(n.get("default-x")), step=n.findtext("pitch/step"),
                                octave=int(n.findtext("pitch/octave")), alter=float(n.findtext("pitch/alter") or 0),
                                acc=n.findtext("accidental"), clef=clefs.get(st), oc=octs.get(st, 0)))
            x0 += float(m.get("width") or 0)
    return out, pw


def place(notes, pw, img, page):
    """Pixels de chaque note de la page : x par l'échelle, puis recalé sur les têtes vues ; y par la portée et la hauteur."""
    import pupitres
    H, W = img.shape
    staves = pupitres.find_staves(img)
    mine = [n for n in notes if n["page"] == page]
    if not mine or not staves:
        return []
    # têtes pleines vues sur l'image
    ink = (img < 128).astype(np.uint8)
    sp0 = float(np.median([(bb - tt) / 4 for tt, bb, _l, _r in staves]))
    k = max(3, int(0.55 * sp0)) | 1
    heads = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    _nb, _lab, st, cen = cv2.connectedComponentsWithStats(heads, 8)
    keep = [(c[0], c[1], s_[cv2.CC_STAT_WIDTH]) for s_, c in zip(st[1:], cen[1:])
            if 0.6 * sp0 <= s_[cv2.CC_STAT_HEIGHT] <= 1.6 * sp0 and 0.8 * sp0 <= s_[cv2.CC_STAT_WIDTH] <= 2.2 * sp0]
    B = np.array(keep, float) if keep else np.zeros((0, 3))

    def y_on(n, staff):
        t, b_, _l, _r = staff
        d = "CDEFGAB".index(n["step"]) + 7 * n["octave"] + 1
        return b_ - (d - BOTTOM[n["clef"]] - 7 * n["oc"]) * (b_ - t) / 8

    # chaque groupe de notes (système, partie, portée de la partie) va sur la portée de l'image où ses têtes sont vues :
    # Audiveris éparpille parfois une page en plus de parties qu'il n'y a de portées par système (8 pour 4)
    groups = {}
    for n in mine:
        n["xy"] = None
        if n["clef"] in BOTTOM:
            groups.setdefault((n["system"], n["part"], n["staff"]), []).append(n)
    def vote(group, xmap, reach):
        best, votes = None, 0
        for staff in staves:
            sp = (staff[1] - staff[0]) / 4
            v = 0
            for n in group:
                x, y = xmap(n["x"]), y_on(n, staff)
                if len(B) and ((np.abs(B[:, 1] - y) <= 0.45 * sp) & (np.abs(B[:, 0] - x) <= reach * sp)).any():
                    v += 1
            if v > votes:
                best, votes = staff, v
        if best is None or votes < max(2, 0.3 * len(group)):
            return False
        t, b_, _l, _r = best
        for n in group:
            n["xy"], n["sp"], n["staff_tb"] = (n["x"] * W / pw, y_on(n, best)), (b_ - t) / 4, (t, b_)
        return True

    left = [g for g in groups.values() if not vote(g, lambda x: x * W / pw, 3)]
    if left and PLACE_AGAIN:
        # échelle approchée (largeur de page) parfois fausse de 10 % : les portées restées sans place sont revotées
        # avec l'échelle mesurée sur les têtes des portées placées
        pairs = []
        for n in mine:
            if n["xy"] and len(B):
                ok = (np.abs(B[:, 1] - n["xy"][1]) <= 0.45 * n["sp"]) & (np.abs(B[:, 0] - n["xy"][0]) <= 6 * n["sp"])
                if ok.any():
                    pairs.append((n["x"], B[np.flatnonzero(ok)[np.argmin(np.abs(B[ok, 0] - n["xy"][0]))], 0]))
        if len(pairs) >= 8:
            X, Y = np.array(pairs).T
            a, c = np.polyfit(X, Y, 1)
            for _ in range(3):  # écarts trop grands retirés (tête voisine prise pour la bonne)
                res = np.abs(a * X + c - Y)
                keep_ = res <= max(1.0 * sp0, np.percentile(res, 60))
                if keep_.sum() < 6:
                    break
                a, c = np.polyfit(X[keep_], Y[keep_], 1)
            for g in left:
                vote(g, lambda x: a * x + c, 1.5)
    placed = [n for n in mine if n["xy"]]
    if len(placed) < 4:
        return []

    def nearest(x, y, sp, reach):
        if not len(B):
            return None
        ok = (np.abs(B[:, 1] - y) <= 0.45 * sp) & (np.abs(B[:, 0] - x) <= reach)
        if not ok.any():
            return None
        return B[np.flatnonzero(ok)[np.argmin(np.abs(B[ok, 0] - x))]]

    for sysno in sorted({n["system"] for n in placed}):
        group = [n for n in placed if n["system"] == sysno]
        pairs = [(n["xy"][0], b[0]) for n in group if (b := nearest(*n["xy"], n["sp"], 6 * n["sp"])) is not None]
        fitted = False
        if len(pairs) >= 4:
            X, Y = np.array(pairs).T
            rng = np.random.default_rng(len(pairs))
            best = None
            for _ in range(80):
                i, j = rng.choice(len(pairs), 2, replace=False)
                if abs(X[i] - X[j]) < 10 * sp0:
                    continue
                a = (Y[i] - Y[j]) / (X[i] - X[j])
                c = Y[i] - a * X[i]
                inl = np.abs(a * X + c - Y) <= 0.6 * sp0
                if best is None or inl.sum() > best.sum():
                    best = inl
            if best is not None and best.sum() >= max(4, 0.5 * len(pairs)):
                a, c = np.polyfit(X[best], Y[best], 1)
                for n in group:
                    n["xy"] = (a * n["xy"][0] + c, n["xy"][1])
                fitted = True
        for n in group:
            b = nearest(*n["xy"], n["sp"], 0.9 * n["sp"]) if fitted else None
            n["head"] = None if b is None else b[0] - b[2] / 2
            if not fitted:
                n["xy"] = None  # position trop incertaine : on ne lit pas de signe pour elle
    return [n for n in placed if n["xy"]]


def read_signs(notes, img, blurry=False, both=False):
    """Score de chaque signe juste à gauche de chaque note (lignes de portée ôtées), à la hauteur de la note.
    blurry (photo floue) : un dièse empâté ressemble à une tête de note et partait avec elles ; il est cherché sur
    l'encre où seules les lignes sont ôtées (les bécarres et bémols, eux, s'y confondent avec têtes et queues)."""
    import pupitres
    ink = (img < 128).astype(np.uint8)
    sp0 = float(np.median([n["sp"] for n in notes]))
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (int(2 * sp0), 1)))
    # têtes pleines effacées aussi : une tête et sa queue ressemblent à un bémol (panse et hampe)
    k = max(3, int(0.55 * sp0)) | 1
    heads = cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))),
                       np.ones((3, 3), np.uint8))
    sym = (ink & (1 - lines) & (1 - heads)).astype(np.float32)
    sym_blur = (ink & (1 - lines)).astype(np.float32) if blurry or both else None
    tpl = {k: pupitres._glyph(c, sp0).astype(np.float32) for k, c in GLYPHS.items()}
    # partie du signe hors de ses traits verticaux (panse du bémol, barres du dièse et du bécarre) : une queue de note
    # seule ressemble à la hampe d'un bémol, il faut aussi la panse
    body = {}
    for k, t in tpl.items():
        tall = t.sum(0) >= 0.6 * t.shape[0]
        tall = cv2.dilate(tall.astype(np.uint8)[None, :], np.ones((1, 3), np.uint8))[0] > 0
        body[k] = t * (~tall)[None, :]
    H, W = ink.shape
    for n in notes:
        n["scores"] = {}
        x, y = n["xy"]
        sp = n["sp"]
        xl = n["head"] if n.get("head") is not None else x - 0.65 * sp
        x0, x1 = int(xl - 2.8 * sp), int(xl - 0.05 * sp)
        y0, y1 = int(y - 2.2 * sp), int(y + 2.2 * sp)
        if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
            continue
        if both and not blurry:
            # photo nette : en plus, le dièse cherché comme sur une photo floue (collé à la tête, il partait avec elle)
            n["scores_blur"] = {k: _blur_score(sym_blur, t, k, x0, x1, y0, y1, xl, y, sp) for k, t in tpl.items()}
        for k, t in tpl.items():
            if blurry and k != "sharp":
                n["scores"][k] = _blur_score(sym_blur, t, k, x0, x1, y0, y1, xl, y, sp)
                continue
            reg = (sym_blur if blurry else sym)[y0:y1, x0:x1]
            if t.shape[0] > reg.shape[0] or t.shape[1] > reg.shape[1]:
                continue
            r = cv2.matchTemplate(reg, t, cv2.TM_CCOEFF_NORMED)
            want = (y - y0) - (0.55 * sp if k == "flat" else 0.0) - t.shape[0] / 2
            rows = np.abs(np.arange(r.shape[0]) - want) <= 0.45 * sp
            # le signe touche presque la tête (bord droit à moins d'un interligne d'elle) ; une barre de mesure est
            # plus loin, et avec un reste de ligne elle ressemble à un bémol
            right = x0 + np.arange(r.shape[1]) + t.shape[1]
            cols = (right >= xl - 1.0 * sp) & (right <= xl + 0.1 * sp)
            if not (rows.any() and cols.any()):
                continue
            sub = r[np.ix_(rows, cols)]
            i, j = np.unravel_index(int(np.argmax(sub)), sub.shape)
            row, col = np.flatnonzero(rows)[i], np.flatnonzero(cols)[j]
            patch = reg[row:row + t.shape[0], col:col + t.shape[1]]
            filled = float((patch * body[k]).sum() / max(1.0, body[k].sum()))
            n["scores"][k] = float(sub[i, j]) if filled >= 0.45 or blurry else 0.0
    return notes


def _blur_score(sym, t, k, x0, x1, y0, y1, xl, y, sp):
    """Score brut d'un signe (sans contrôle de la panse) sur l'encre aux lignes ôtées : sert de point de comparaison
    pour le dièse d'une photo floue (un bécarre aussi bien noté que le dièse : on s'abstient)."""
    reg = sym[y0:y1, x0:x1]
    if t.shape[0] > reg.shape[0] or t.shape[1] > reg.shape[1]:
        return 0.0
    r = cv2.matchTemplate(reg, t, cv2.TM_CCOEFF_NORMED)
    want = (y - y0) - (0.55 * sp if k == "flat" else 0.0) - t.shape[0] / 2
    rows = np.abs(np.arange(r.shape[0]) - want) <= 0.45 * sp
    right = x0 + np.arange(r.shape[1]) + t.shape[1]
    cols = (right >= xl - 1.0 * sp) & (right <= xl + 0.1 * sp)
    return float(r[np.ix_(rows, cols)].max()) if rows.any() and cols.any() else 0.0


SHARP_BLUR, SHARP_BLUR_MARGIN = 0.40, 0.05  # photo floue : vrais dièses 0,43–0,53, faux 0,32 au plus (bwv153.1)


def decide(n, blurry=False):
    """Signe nettement reconnu à gauche de la note (ou None). Photo floue : seulement un dièse, nettement devant le
    bécarre (sur l'encre empâtée, bécarres et bémols ne se distinguent pas des têtes et des queues)."""
    s = n.get("scores") or {}
    if not s:
        return None
    if blurry:
        return _blur_sharp(s)
    best = max(s, key=s.get)
    rest = max([v for k, v in s.items() if k != best], default=0.0)
    if s[best] >= SCORE + (0.05 if best != "sharp" else 0.0) and s[best] - rest >= MARGIN:
        return best
    return _blur_sharp(n["scores_blur"]) if n.get("scores_blur") else None


def _blur_sharp(s):
    sharp = s.get("sharp", 0.0)
    others = max(s.get("natural", 0.0), s.get("flat", 0.0) - 0.1)
    return "sharp" if sharp >= SHARP_BLUR and sharp - s.get("natural", 0.0) >= SHARP_BLUR_MARGIN and sharp > others else None


def apply(notes, blurry=False):
    """Signes reconnus écrits dans la lecture ; l'altération vaut pour la suite de la mesure, sur la même portée."""
    changed = 0
    by_measure = {}
    for n in notes:
        by_measure.setdefault((id(n["measure"]), n["staff"]), []).append(n)
    # 1re note de chaque ligne : la zone à sa gauche peut contenir l'armure ou le chiffre de mesure
    lead = {}
    for n in notes:
        if n["first"]:
            key = (n["page"], n["system"], n["part"], n["staff"])
            lead[key] = min(lead.get(key, n["x"]), n["x"])
    for group in by_measure.values():
        group.sort(key=lambda n: n["x"])
        carry = {}
        for n in group:
            here = (n["step"], n["octave"])
            leading = n["first"] and n["x"] <= lead.get((n["page"], n["system"], n["part"], n["staff"]), -1) + 5
            sign = None if leading else decide(n, blurry)
            if sign is not None and (n["acc"] != sign or n["alter"] != ALTER[sign]):
                _set(n["el"], ALTER[sign], sign)
                carry[here] = ALTER[sign]
                changed += 1
            elif n["acc"] in ALTER:
                carry[here] = ALTER[n["acc"]] if n["acc"] != "natural" else 0.0
            elif here in carry and n["alter"] != carry[here]:
                _set(n["el"], carry[here], None)
                changed += 1
    return changed


def _set(el, alter, sign):
    p = el.find("pitch")
    a = p.find("alter")
    if alter:
        if a is None:
            a = ET.Element("alter")
            p.insert(1, a)
        a.text = str(int(alter))
    elif a is not None:
        p.remove(a)
    acc = el.find("accidental")
    if sign is None:
        return
    if acc is None:
        acc = ET.Element("accidental")
        kids = list(el)
        after = next((i for i, c in enumerate(kids) if c.tag in ("type", "dot")), len(kids) - 1)
        el.insert(after + 1, acc)
    acc.text = sign


def _tie_arc(img_sym, a, b):
    """
    Arc de liaison entre deux têtes de même hauteur : au-dessus ou au-dessous d'elles, une courbe mince qui couvre
    presque tout l'espace qui les sépare (une barre de mesure entre elles, toute droite, ne compte pas).
    """
    sp = a["sp"]
    xa = (a["head"] if a.get("head") is not None else a["xy"][0] - 0.65 * sp) + 1.3 * sp
    xb = (b["head"] if b.get("head") is not None else b["xy"][0] - 0.65 * sp) - 0.1 * sp
    if xb - xa < 0.8 * sp or abs(a["xy"][1] - b["xy"][1]) > 0.4 * sp:
        return False
    y = (a["xy"][1] + b["xy"][1]) / 2
    H, W = img_sym.shape
    t, bot = a["staff_tb"]
    line_rows = {int(round(t + k * sp)) + d for k in range(5) for d in (-1, 0, 1)}  # lignes de portée : ignorées
    for lo, hi in ((y - 1.6 * sp, y - 0.25 * sp), (y + 0.25 * sp, y + 1.6 * sp)):
        y0, y1, x0, x1 = max(0, int(lo)), min(H, int(hi)), max(0, int(xa)), min(W, int(xb))
        keep = [r for r in range(y0, y1) if r not in line_rows]
        band = img_sym[keep, x0:x1] if keep else img_sym[0:0, x0:x1]
        if band.size == 0:
            continue
        tall = band.sum(0) >= 0.8 * band.shape[0]  # trait vertical (barre, queue) : colonne ignorée
        cols = band[:, ~tall]
        if cols.shape[1] < 0.6 * band.shape[1]:
            continue
        inked = cols.any(0)
        if inked.mean() < 0.65:
            continue
        thin = cols.sum(0)[inked] <= max(3, 0.4 * sp)
        # une courbe : d'une colonne à l'autre, son centre bouge peu (des lettres, des têtes voisines sautent)
        rows = np.arange(cols.shape[0])[:, None]
        centre = (cols * rows).sum(0)[inked] / np.maximum(1, cols.sum(0)[inked])
        smooth = np.median(np.abs(np.diff(centre))) <= 1.5 if len(centre) > 2 else False
        if thin.mean() >= 0.8 and smooth:
            return True
    return False


def read_ties(notes, img):
    """
    Liaisons qu'Audiveris n'a pas écrites (il en trouve les courbes, puis en écarte la plupart) : deux notes qui se
    suivent dans la même voix, de même hauteur, reliées sur l'image par un arc. Sans elles, une note tenue par-dessus
    la barre est chantée deux fois. Rend [(note, note suivante)].
    """
    if not notes:
        return []
    ink = (img < 128).astype(np.uint8)
    sp0 = float(np.median([n["sp"] for n in notes]))
    k = max(3, int(0.55 * sp0)) | 1
    heads = cv2.dilate(cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))),
                       np.ones((3, 3), np.uint8))
    sym = ink & (1 - heads)  # lignes de portée gardées : un arc les longe souvent ; leurs rangées sont ignorées
    seq = {}
    for n in notes:
        seq.setdefault((n["page"], n["part"], n["staff"], n["voice"]), []).append(n)
    pairs = []
    for group in seq.values():
        group.sort(key=lambda n: (n["mindex"], n["x"]))
        onsets = []
        for n in group:  # notes d'un même accord : même position
            if onsets and onsets[-1][0]["mindex"] == n["mindex"] and abs(onsets[-1][0]["x"] - n["x"]) < 3:
                onsets[-1].append(n)
            else:
                onsets.append([n])
        for cur, nxt in zip(onsets, onsets[1:]):
            if cur[0]["system"] != nxt[0]["system"]:
                continue  # liaison coupée par un changement de ligne : on ne la cherche pas
            for a in cur:
                for b in nxt:
                    if (a["step"], a["octave"]) == (b["step"], b["octave"]) and "start" not in a["tied"] \
                            and _tie_arc(sym, a, b):
                        pairs.append((a, b))
    return pairs


def write_ties(pairs):
    """Liaisons écrites dans la lecture : <tie> et <tied>, la seconde note prend l'altération de la première."""
    for a, b in pairs:
        for n, kind in ((a["el"], "start"), (b["el"], "stop")):
            if any(t.get("type") == kind for t in n.findall("tie")):
                continue
            tie = ET.Element("tie", {"type": kind})
            kids = list(n)
            after = next((i for i, c in enumerate(kids) if c.tag == "duration"), 0)
            n.insert(after + 1, tie)
            notations = n.find("notations")
            if notations is None:
                notations = ET.SubElement(n, "notations")
            ET.SubElement(notations, "tied", {"type": kind})
        if a["alter"] != b["alter"]:
            _set(b["el"], a["alter"], None)
    return len(pairs)


def fix(mxl, pages, signs=True, ties=True, blurry=False, both=False):
    root, name = _read(mxl)
    notes, pw = notes_of(root)
    if not notes:
        return 0, 0
    seen, links = [], []
    for k, page in enumerate(pages):
        img = imgio.imread(str(page), cv2.IMREAD_GRAYSCALE)
        if img is None:
            continue
        mine = place(notes, pw, img, k)
        if not mine:
            continue
        if signs:
            seen += read_signs(mine, img, blurry, both)
        if ties:
            links += read_ties(mine, img)
    changed = apply(seen, blurry) if signs else 0
    tied = write_ties(links) if ties else 0
    if changed or tied:
        _write(mxl, root, name)
    return changed, tied


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    args = sys.argv[1:]
    signs, ties = "--sans-signes" not in args, "--sans-liaisons" not in args
    blurry = "--flou" in args and os.environ.get("PUPITRE_SIGNES_FLOU", "1") == "1"
    both = not blurry and os.environ.get("PUPITRE_DIESES_COLLES", "1") == "1"  # photo nette : dièse collé à la tête
    args = [a for a in args if a not in ("--sans-signes", "--sans-liaisons", "--flou")]
    n, t = fix(args[0], args[1:], signs=signs, ties=ties, blurry=blurry, both=both)
    print(f"Altérations relues sur l'image : {n} notes, liaisons : {t}", file=sys.stderr)
