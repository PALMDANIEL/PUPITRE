"""
Pré-traitement : PDF ou photos -> pages nettoyées (cadrage, éclairage, bords, inclinaison).
Usage : python3 preprocess.py <source.pdf|image|dossier_de_pages> <dossier_sortie>
Images : JPG, PNG, HEIC/HEIF (iPhone), WEBP, TIFF (plusieurs pages), BMP. Un dossier = ses fichiers dans l'ordre des noms.
"""
import os, sys, cv2, numpy as np, pathlib, tempfile
import imgio
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # HEIC indisponible : les autres formats fonctionnent
    pass

IMAGES = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}


def best_angle(bw, span=3.0):
    """
    Angle (degrés) qui remet les lignes de portée à l'horizontale : celui qui rend le profil des rangées le plus
    contrasté (chaque ligne tombe alors sur une seule rangée). Recherche grossière puis fine, sur l'image réduite
    de moitié : durée constante (une demi-seconde), même sur une photocopie bruitée. 0 si l'image n'a pas de
    lignes marquées (le gain de contraste doit dépasser 10 %).
    """
    small = cv2.resize(255 - bw, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA).astype(np.float32)
    h, w = small.shape

    def sharpness(angle):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rows = cv2.warpAffine(small, M, (w, h), flags=cv2.INTER_NEAREST).sum(1)
        return float(np.var(rows))

    best = max(np.arange(-span, span + 0.01, 0.25), key=sharpness)
    best = max(np.arange(best - 0.25, best + 0.26, 0.05), key=sharpness)
    return float(best) if sharpness(best) > 1.1 * sharpness(0.0) else 0.0


def _hough_angle(bw):
    """Ancien calcul de l'angle (Hough probabiliste), gardé pour le banc d'essai : PUPITRE_REDRESSEMENT=hough."""
    lines = cv2.HoughLinesP(255 - bw, 1, np.pi / 1800, 200, minLineLength=bw.shape[1] // 3, maxLineGap=20)
    angles = [a for a in (np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in (lines[:, 0] if lines is not None else [])) if abs(a) < 5]
    return float(np.median(angles)) if angles else 0.0


def deskew(bw):
    """
    Redresse la page (jusqu'à 5°) d'après ses lignes de portée : angle cherché par le profil des rangées, de durée
    constante. La transformée de Hough, utilisée avant sur les pages peu chargées, prenait 33 à 103 s par page sur une
    photo (grain, ombre) quand l'ordinateur était occupé, pour le même angle à 0,3° près (profil : 1 à 3 s) ; la
    surveillance « aucun signe de vie pendant 5 minutes » pouvait alors arrêter la lecture.
    """
    h, w = bw.shape
    angle = best_angle(bw, 5.0) if os.environ.get("PUPITRE_REDRESSEMENT") != "hough" else _hough_angle(bw)
    if abs(angle) < 0.05:
        return bw
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(bw, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)


def _ink_map(gray):
    """
    Encre de la page réduite à 1000 px, en contraste relatif au papier (0 à 1), sans seuillage : une photo floue,
    sombre ou très compressée garde ainsi ses lignes de portée. Le fond hors de la feuille (table) est mis à zéro.
    """
    k = 1000 / max(gray.shape)
    g = cv2.resize(gray, None, fx=k, fy=k, interpolation=cv2.INTER_AREA).astype(np.float32)
    bg = cv2.GaussianBlur(cv2.dilate(g, np.ones((15, 15), np.uint8)), (0, 0), 8)
    paper = cv2.erode((bg > 0.55 * np.percentile(bg, 95)).astype(np.uint8), np.ones((25, 25), np.uint8))
    return np.clip((bg - g) / np.maximum(bg, 1), 0, 1) * paper


def _line_edges(ink):
    """Bords des longs traits horizontaux et des longs traits verticaux (moyenne sur 41 px le long du trait)."""
    horiz = np.abs(cv2.Sobel(cv2.blur(ink, (41, 1)), cv2.CV_32F, 0, 1, ksize=3))
    vert = np.abs(cv2.Sobel(cv2.blur(ink, (1, 41)), cv2.CV_32F, 1, 0, ksize=3))
    return horiz, vert


def upright(gray):
    """
    Photo prise de côté (sans indication d'orientation) : les lignes de portée doivent être horizontales.
    On ne tourne que si les longs traits verticaux l'emportent nettement (rapport < 0,8) : page droite, le rapport
    horizontal / vertical vaut 1,2 à 2,8 sur les photos du banc (floues, sombres, WhatsApp, petites portées) et 0,85
    au moins sur une photocopie usée. L'ancien test (seuillage puis ouverture) tournait à tort une photo sur quatre.
    """
    horiz, vert = _line_edges(_ink_map(gray))
    if horiz.sum() >= 0.8 * vert.sum():
        return gray

    # Dans quel sens tourner ? Clé, armure et chiffrage sont au début de chaque portée : le côté gauche est le plus chargé.
    def left_heavy(img):
        ink = _ink_map(img)
        lines, _ = _line_edges(ink)
        rows = lines.sum(1)
        staff = cv2.dilate((rows > 0.3 * rows.max()).astype(np.uint8)[:, None], np.ones((7, 1), np.uint8))[:, 0] > 0
        cols = lines[staff].sum(0)  # étendue des portées, mesurée sur leurs seules rangées
        span = np.where(cols > 0.25 * cols.max())[0]
        if not len(span):
            return 0
        x0, x1 = int(span.min()), int(span.max())
        band = max(1, (x1 - x0) // 10)
        dark = ink[staff] > 0.3
        return int(dark[:, x0:x0 + band].sum()) - int(dark[:, x1 - band:x1].sum())
    cw, ccw = cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE), cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE)
    return cw if left_heavy(cw) >= left_heavy(ccw) else ccw


def crop_page(gray):
    """Photo d'une feuille posée sur une table : on repère la feuille (le plus grand quadrilatère clair) et on la remet à plat."""
    h, w = gray.shape
    k = 1000 / max(h, w)
    small = cv2.GaussianBlur(cv2.resize(gray, None, fx=k, fy=k), (5, 5), 0)
    _, mask = cv2.threshold(small, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((25, 25), np.uint8))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return gray
    c = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(c) / (small.shape[0] * small.shape[1])
    if not 0.3 < area < 0.97:  # pas de fond visible (scan, capture) ou feuille introuvable
        return gray
    quad = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    if len(quad) != 4:
        return gray
    pts = quad.reshape(4, 2).astype(np.float32) / k
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    tl, br, tr, bl = pts[np.argmin(s)], pts[np.argmax(s)], pts[np.argmin(d)], pts[np.argmax(d)]
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    M = cv2.getPerspectiveTransform(np.float32([tl, tr, br, bl]), np.float32([[0, 0], [width, 0], [width, height], [0, height]]))
    return cv2.warpPerspective(gray, M, (width, height), borderValue=255)


def to_gray(gray):
    scale = 2480 / gray.shape[1]
    if abs(scale - 1) > 0.05:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    return gray


def edge_width(gray):
    """Largeur des bords de l'encre en pixels (page à 2480 px) : 2 sur un PDF net, 4 à 5 sur une photo, 7 à 8 si floue."""
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31).astype(np.float32)
    ink = np.clip(bg - gray.astype(np.float32), 0, None)
    slope = np.hypot(cv2.Sobel(ink, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(ink, cv2.CV_32F, 0, 1, ksize=3)) / 8
    return float(np.percentile(ink, 99.5) / max(np.percentile(slope, 99.5), 1e-6))


BLUR = 5.5  # largeur de bord au-delà de laquelle la photo est renforcée (banc : photos nettes 5,3 au plus, floues 7 à 8)


def blur_shape(gray):
    """
    Forme du flou (covariance en pixels²) : largeur des bords mesurée dans quatre directions. Un bougé étale le flou dans
    un sens : photo bougée de côté, les traits verticaux (queues, barres de mesure, dièses) sont deux fois plus étalés que
    les lignes de portée (largeur 11 à 12 contre 8,5), et ce sont eux qui disparaissaient au seuillage.
    """
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31).astype(np.float32)
    ink = np.clip(bg - gray.astype(np.float32), 0, None)
    a = np.percentile(ink, 99.5)
    ix = cv2.Sobel(ink, cv2.CV_32F, 1, 0, ksize=3) / 8
    iy = cv2.Sobel(ink, cv2.CV_32F, 0, 1, ksize=3) / 8
    var = {}
    for deg in (0, 45, 90, 135):  # bord de pente maximale = flou gaussien d'écart-type largeur / 2,5
        t = np.radians(deg)
        var[deg] = (a / max(float(np.percentile(np.abs(np.cos(t) * ix + np.sin(t) * iy), 99.5)), 1e-6) / 2.5) ** 2
    sxy = (var[45] - var[135]) / 2
    return np.array([[var[0], sxy], [sxy, var[90]]])


def unblur(gray):
    """
    Photo floue (mise au point manquée, bougé) : le seuillage coupait les lignes de portée en pointillés et faisait des
    clés une tache. Un renforcement des contours, dosé selon le flou mesuré, les rend avant le nettoyage (banc : une copie
    floue passe de « aucune portée lue » à 89/67/67/69 %, une autre de 30-42 % à 43-51 %).
    """
    w = edge_width(gray)
    if w <= BLUR:
        return gray
    amount = min(1.5, (w - BLUR) * 0.75)
    soft = cv2.GaussianBlur(gray.astype(np.float32), (0, 0), w / 2.5)
    return np.clip(gray + amount * (gray.astype(np.float32) - soft), 0, 255).astype(np.uint8)


def interline(gray):
    """
    Écart entre deux lignes de portée (pixels), comme le mesure Audiveris : dans chaque colonne, distance la plus
    fréquente entre deux traits d'encre successifs. Page à 2480 px : 21-22 sur les gravures courantes, 14 sur un recueil
    à petites portées ; 0 si la page n'a pas de portées.
    """
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31)
    ink = (cv2.divide(gray, bg, scale=255)[:, ::3] < 180).astype(np.int8)
    cols, rows = np.nonzero(np.diff(ink, axis=0).T == 1)
    gaps = np.diff(rows)[np.diff(cols) == 0]
    hist = np.convolve(np.bincount(gaps[(gaps >= 6) & (gaps <= 80)], minlength=81), [1, 2, 1], "same")
    return int(np.argmax(hist)) if hist.max() > 0 else 0


def is_digital(gray):
    """Page issue d'un logiciel de gravure (fond blanc pur, presque pas de gris) et non d'un scan ou d'une photo."""
    return np.mean(gray > 245) > 0.8 and np.mean((gray > 60) & (gray < 200)) < 0.08


def speck_density(gray):
    """
    Petites taches d'encre (moins de 12 points) par mégapixel : mesure de saleté de la copie.
    Une tache compte si elle est au moins deux fois plus sombre que le papier autour, après un léger débruitage : le
    grain d'une photo sombre ou la compression d'une photo WhatsApp ne comptent plus (un simple seuillage leur donnait
    170 à 470, plus qu'une vraie copie tachée). Banc : photos propres 0 à 80 ; « Dieu nous te louons » 203, « Fa damba » 437.
    """
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31).astype(np.float32)
    ink = (cv2.medianBlur(gray, 3).astype(np.float32) < 0.5 * np.maximum(bg, 1)).astype(np.uint8)
    n, _lab, st, _ = cv2.connectedComponentsWithStats(ink, 8)
    return float(np.count_nonzero(st[1:, cv2.CC_STAT_AREA] < 12)) / (ink.size / 1e6)


def plain_page(gray):
    """Simple seuillage : le nettoyage complet abîme les pages déjà propres (Audiveris peut alors planter)."""
    return cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)[1]


def _ridges(s, axis, lo, d=0):
    """
    Crête d'un trait mince : maximum local du contraste en travers du trait (axis 0 : trait horizontal, 1 : vertical).
    d : exige aussi du papier de part et d'autre, à d pixels (sinon une lettre, un chiffre de mesure ou le côté d'une tête
    donnent aussi une crête). Une queue est ainsi coupée là où elle croise une ligne de portée : refermé par lines.
    """
    ridge = (s >= np.roll(s, 1, axis)) & (s >= np.roll(s, -1, axis)) & (s >= lo)
    if d:
        ridge &= s - np.maximum(np.roll(s, d, axis), np.roll(s, -d, axis)) >= 0.4 * s
    return ridge


def blur_threshold(gray, plain, hi=0.45, lo=0.12, mid=0.30):
    """
    Seuillage d'une photo floue. Le seuillage adaptatif (encre = plus sombre que la moyenne locale) y faisait deux
    erreurs : loin de l'encre, le halo du flou passait pour de l'encre (lignes de portée épaisses de 12 px, têtes collées
    aux lignes) ; près de l'encre, la moyenne baissait et les traits fins disparaissaient (queues coupées dans la portée,
    dièses réduits à des points, barres en pointillés). Dans la bande des portées, chaque sorte de signe a son critère :
      - têtes, ligatures, clés : contraste d'au moins hi (formes compactes, sans halo) ;
      - lignes de portée, queues, barres : la crête du trait (maximum du contraste en travers, papier de part et
        d'autre), même pâle (lo), gardée si elle est longue (1,5 interligne à l'horizontale, 1,2 à la verticale),
        retracée sur 3 pixels d'épaisseur ; le papier est cherché à la distance où le flou s'éteint (bougé de côté :
        les traits verticaux sont étalés deux fois plus) ;
      - crochets, courbes des clés, liaisons, contour des têtes blanches : crête d'un trait (pas d'un point) de
        contraste moyen (mid), à l'écart des petits points (sinon une étoile se dessine autour de chacun).
    Hors de cette bande (paroles, titre), plain : le seuillage ordinaire (des crêtes hachaient les lettres).
    """
    sp = interline(gray) or 21
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31).astype(np.float32)
    c = np.clip(1 - gray.astype(np.float32) / np.maximum(bg, 1), 0, 1)
    rect = lambda w, h: cv2.getStructuringElement(cv2.MORPH_RECT, (max(1, int(w)), max(1, int(h)) | 1))
    blobs = c >= hi
    ink = blobs.copy()

    def lines(ridge, axis, length, own=0.0):
        """
        Crêtes longues d'au moins length interlignes, retracées sur 3 pixels d'épaisseur. own : part de cette longueur
        faite de crête hors des taches noires (deux points ou deux têtes l'un au-dessus de l'autre ont aussi une crête
        verticale, et les relier inventerait une barre ou une queue).
        """
        along = lambda k: rect(k, 1) if axis == 0 else rect(1, k)
        across = np.ones((3, 1) if axis == 0 else (1, 3), np.uint8)
        fat = cv2.dilate(ridge.astype(np.uint8), across)  # une crête bruitée zigzague d'un pixel
        fat = cv2.morphologyEx(fat, cv2.MORPH_CLOSE, along(max(3, sp // 2)))  # coupée là où un autre trait la croise
        out = cv2.dilate(cv2.morphologyEx(fat, cv2.MORPH_OPEN, along(max(5, length * sp))) & fat, across)
        if own:
            n, lab, _st, _ = cv2.connectedComponentsWithStats(out, 8)
            mine = np.bincount(lab[ridge & ~blobs], minlength=n)
            keep = mine >= own * length * sp
            keep[0] = False
            out = keep[lab].astype(np.uint8)
        return out

    smooth_h, smooth_v = cv2.blur(c, (9, 1)), cv2.blur(c, (1, 9))  # lissés le long du trait
    # lignes de portée : traits isolés (papier dessus et dessous) longs de 4 interlignes ; la bande des portées en part
    strict = lines(_ridges(smooth_h, 0, lo, 6), 0, 1.5)
    long_ = cv2.morphologyEx(strict, cv2.MORPH_OPEN, rect(4 * sp, 1))
    staves = cv2.dilate(long_, rect(6 * sp, 1.4 * sp)) > 0
    music = cv2.dilate(long_, rect(6 * sp, 4.4 * sp)) > 0  # de 2,2 interlignes au-dessus à 2,2 au-dessous
    # dans la portée, la crête suffit : sous la clé, l'armure et le chiffrage, la ligne passe entre des signes
    ink |= (strict > 0) | ((lines(_ridges(smooth_h, 0, lo), 0, 1.5) > 0) & staves)
    # traits verticaux isolés à leur tour, à la distance où le flou horizontal (bougé) s'éteint
    side = int(np.clip(round(2.2 * np.sqrt(blur_shape(gray)[0, 0])), 5, 12))
    ink |= lines(_ridges(smooth_v, 1, lo, side), 1, 1.2, own=0.9) > 0
    s = cv2.GaussianBlur(c, (0, 0), 1.0)
    count = np.zeros(c.shape, np.uint8)
    for dy, dx in ((1, 0), (0, 1), (1, 1), (1, -1)):
        count += ((s >= np.roll(s, (dy, dx), (0, 1))) & (s >= np.roll(s, (-dy, -dx), (0, 1)))).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(blobs.astype(np.uint8), 8)
    dot = (st[:, cv2.CC_STAT_AREA] <= 0.35 * sp * sp) & (st[:, cv2.CC_STAT_WIDTH] <= 0.8 * sp) & (st[:, cv2.CC_STAT_HEIGHT] <= 0.8 * sp)
    dot[0] = False
    near = cv2.dilate(dot[lab].astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    thin = cv2.dilate(((count >= 1) & (count <= 3) & (s >= mid) & ~near).astype(np.uint8), np.ones((2, 2), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(thin, 8)
    keep = st[:, cv2.CC_STAT_AREA] >= sp
    keep[0] = False
    ink |= keep[lab]
    return np.where(music, np.where(ink, 0, 255), plain).astype(np.uint8)


def clean_page(gray, blurred=False):
    """
    Page nettoyée, en deux versions qui ne diffèrent que dans la bande de 3 % du bord : (page, pour Audiveris).
    Pour Audiveris, toute la bande est effacée, comme avant (ombres, table, bord du livret). Pour la page (disposition,
    lecture par homr, affichage), on n'efface que ce qui touche le bord de l'image ou tient dans son premier centième :
    photo cadrée serré, la clé et la ligne qui relie les portées d'un système tombent dans la bande (petites portées :
    disposition non reconnue, donc ni double lecture ni armure reprise de homr). Audiveris, lui, lisait plus mal avec ces
    signes de bord (banc : photos sur deux portées 96,9 → 94,3 %, photo sombre 87 → 56 %, la ligne du système gardée
    lui faisant perdre l'armure d'une portée sur deux) ; l'ôter pour lui seul cassait d'autres lectures (penchées, floues
    à quatre portées) : il reçoit donc exactement l'image d'avant.
    """
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31)
    flat = cv2.divide(gray, bg, scale=255)
    bw = cv2.adaptiveThreshold(flat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)
    raw = bw.copy()

    h, w = bw.shape
    # Taches et traits de bord : décidés d'un coup pour toutes les composantes (un masque de la page entière par
    # tache faisait exploser le temps sur une photocopie tachée : des minutes, puis l'arrêt par la surveillance)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(255 - bw, 8)
    x, y, cw, ch = stats[:, 0], stats[:, 1], stats[:, 2], stats[:, 3]
    near_edge = (x < w * 0.07) | (x + cw > w * 0.93) | (y < h * 0.02) | (y + ch > h * 0.98)
    long_thin = ((ch > h * 0.5) & (cw < w * 0.06)) | ((cw > w * 0.5) & (ch < h * 0.03))
    erase = near_edge & long_thin
    erase[0] = False  # fond
    bw[erase[lab]] = 255
    m = int(min(h, w) * 0.03)
    band = np.zeros((h, w), bool)
    band[:, :m] = band[:, -m:] = band[:m, :] = band[-m:, :] = True
    n, lab, stats, _ = cv2.connectedComponentsWithStats(255 - bw, 8)
    x, y, cw, ch = stats[:, 0], stats[:, 1], stats[:, 2], stats[:, 3]
    e = m // 3
    outside = (x + cw <= e) | (x >= w - e) | (y + ch <= e) | (y >= h - e)
    touching = (x == 0) | (y == 0) | (x + cw == w) | (y + ch == h)
    wipe = outside | touching
    wipe[0] = False
    page, old = bw.copy(), bw.copy()
    page[band & wipe[lab]] = 255
    old[band] = 255
    if os.environ.get("PUPITRE_MARGE") == "ancienne":
        page = old.copy()
    if blurred:
        # bords de page décidés sur le seuillage ordinaire : avec des traits fins, la ligne qui relie les portées d'un
        # système ne touche plus les lignes de portée, et elle passait pour le bord de la page (effacée)
        ridge = blur_threshold(gray, bw)
        page, old = ridge.copy(), np.where(band, 255, ridge).astype(np.uint8)
        page[(raw < 128) & (np.where(band & wipe[lab], 255, bw) >= 128)] = 255
        old[(raw < 128) & (bw >= 128)] = 255
        if os.environ.get("PUPITRE_MARGE") == "ancienne":
            page = old.copy()
    out = []
    for img in (page, old):
        n, lab_, stats_, _ = cv2.connectedComponentsWithStats(255 - img, 8)
        specks = stats_[:, cv2.CC_STAT_AREA] < 6
        specks[0] = False
        img[specks[lab_]] = 255
        out.append(deskew(img))
    return out[0], out[1]


DASHED = 0.08  # part des traits horizontaux qui tiennent sur 1/12 de page (pages saines : 18 à 64 %, photocopie usée : 0)


def level(bw):
    """
    Remet la page d'aplomb d'après ses lignes de portée, même en pointillés (photocopie) : on cherche l'angle
    qui rend le profil des rangées le plus contrasté (les lignes tombent alors chacune sur une seule rangée).
    """
    best = best_angle(bw, 3.0)
    H, W = bw.shape
    if abs(best) >= 0.05:
        M = cv2.getRotationMatrix2D((W / 2, H / 2), best, 1.0)
        bw = cv2.warpAffine(bw, M, (W, H), flags=cv2.INTER_NEAREST, borderValue=255)
    return unshear(bw)


def unshear(bw):
    """
    Photocopie de travers : une fois les lignes de portée horizontales, les barres de mesure peuvent rester penchées.
    Audiveris ne relie alors plus les portées d'un même système. On redresse les grands traits verticaux.
    """
    ink = (bw < 128).astype(np.uint8)
    H, W = bw.shape
    tall = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40)))
    # pente de chaque grand trait vertical (barre de mesure, accolade) : droite x = a·y + b ajustée sur ses pixels.
    # (pas de transformée de Hough : sa durée dépend du contenu de l'image, et pouvait dépasser l'heure)
    n, lab, st, _ = cv2.connectedComponentsWithStats(tall, 8)
    slopes = []
    for k in range(1, n):
        x, y, w, h, _a = st[k]
        if h < 150 or w > 0.05 * h:
            continue
        ys, xs = np.nonzero(lab[y:y + h, x:x + w] == k)
        if len(ys) >= 100:
            slopes.append(float(np.polyfit(ys, xs, 1)[0]))
    if len(slopes) < 5:
        return bw
    k = float(np.median(slopes))
    if abs(k) < 0.003:  # moins de 3 px sur 1000 : rien à faire
        return bw
    M = np.float32([[1, -k, k * H / 2], [0, 1, 0]])
    return cv2.warpAffine(bw, M, (W, H), flags=cv2.INTER_NEAREST, borderValue=255)


def _staves_in(profile, lo=0.2):
    """Lignes de portée d'une bande verticale : rangées d'encre horizontale, par groupes de 5 régulièrement espacées."""
    rows = np.flatnonzero(profile >= lo)
    lines, start = [], None
    for k, r in enumerate(rows):
        if start is None:
            start = r
        if k + 1 == len(rows) or rows[k + 1] != r + 1:
            if r - start <= 8:  # une ligne de portée est mince
                lines.append(((start + r) / 2, r - start + 1))
            start = None
    staves, i = [], 0
    while i + 4 < len(lines):
        ys = [lines[i + j][0] for j in range(5)]
        gaps = np.diff(ys)
        if 10 <= gaps.mean() <= 70 and gaps.max() - gaps.min() <= 0.25 * gaps.mean():
            staves.append([lines[i + j] for j in range(5)])
            i += 5
        else:
            i += 1
    return staves


def dashed_lines(bw):
    """
    Lignes de portée en tirets ? Sur une page saine, les traits horizontaux minces tiennent sur de longues distances ;
    sur une photocopie usée, il n'en reste que des bouts. On compare l'encre gardée par une ouverture courte et longue.
    """
    ink = (bw < 128).astype(np.uint8)
    w = ink.shape[1]
    short = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (8, 1))).sum()
    long_ = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(60, w // 12), 1))).sum()
    return short > 0 and long_ / short < DASHED


def thin_strokes(bw):
    """Fragments d'encre horizontaux et minces (morceaux de lignes de portée, pas les ligatures épaisses)."""
    ink = (bw < 128).astype(np.uint8)
    frag = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (8, 1)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(frag, 8)
    keep = np.zeros(n, np.uint8)
    keep[1:] = st[1:, cv2.CC_STAT_HEIGHT] <= 6
    return keep[lab]


def line_strokes(bw):
    """Traits horizontaux, lignes continues comprises (même touchant les notes) ; têtes de notes et ligatures ôtées."""
    ink = (bw < 128).astype(np.uint8)
    flat = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (8, 1)))
    thick = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 8)))
    return flat & (1 - cv2.dilate(thick, np.ones((3, 1), np.uint8)))


def staff_chains(bw, strip=160, lo=0.12, thin=None):
    """
    Portées d'une page, suivies de bande en bande (même hauteur, à une demi-interligne près) :
    liste de chaînes [(x0, x1, [(y, épaisseur) × 5]), …], une par portée, de gauche à droite.
    """
    thin = thin_strokes(bw) if thin is None else thin
    w = thin.shape[1]
    chains = []
    for x0 in range(0, w, strip):
        x1 = min(w, x0 + strip)
        for staff in _staves_in(thin[:, x0:x1].sum(1) / (x1 - x0), lo):
            spacing = (staff[4][0] - staff[0][0]) / 4
            chain = next((c for c in chains if c[-1][0] < x0 and abs(c[-1][2][0][0] - staff[0][0]) < spacing / 2), None)
            if chain is None:
                chains.append([(x0, x1, staff)])
            else:
                chain.append((x0, x1, staff))
    return thin, chains


def restore_strokes(bw, bands=None):
    """
    Photocopie usée : queues de notes, barres et ligatures en pointillés, têtes de notes mouchetées. On referme
    les petits trous des signes (pas des lignes de portée, mises à part : sinon les têtes s'y colleraient).
    bands : [(haut, bas)] des portées ; on n'y touche qu'à elles, jamais aux lignes de paroles (les lettres
    s'empâteraient : « san » deviendrait une tache, illisible).
    """
    ink = (bw < 128).astype(np.uint8)
    lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (41, 1)))
    signs = ink & (1 - lines)
    fixed = ink.copy()
    # (pas de fermeture horizontale : elle collait la clé, l'armure et les chiffres de mesure entre eux)
    for kernel in (cv2.getStructuringElement(cv2.MORPH_RECT, (1, 7)),      # queues, barres de mesure
                   cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))):  # têtes de notes
        fixed |= cv2.morphologyEx(signs, cv2.MORPH_CLOSE, kernel)
    if bands is not None:
        keep = np.zeros(ink.shape[0], bool)
        for top, bottom in bands:
            keep[max(0, int(top)):max(0, int(bottom))] = True
        fixed[~keep] = ink[~keep]
    return np.where(fixed > 0, 0, 255).astype(np.uint8)


def repair_staff_lines(bw):
    """
    Photocopies et fax : lignes de portée réduites à des tirets, qu'Audiveris ne reconnaît plus comme portées
    (il perd alors des voix entières). On repère les 5 lignes de chaque portée, bande par bande, d'après leurs
    fragments horizontaux minces, et on les retrace d'un trait continu (aussi entre deux bandes où la portée est vue),
    puis on referme les signes en pointillés (restore_strokes). Une page dont les lignes sont déjà continues
    n'est pas touchée.
    """
    if not dashed_lines(bw):
        return bw
    bw = level(bw)
    thin, chains = staff_chains(bw)
    out = bw.copy()

    def draw(x0, x1, y0, y1, t):
        for x in range(x0, x1, 8):  # petits segments : suit une légère pente
            xe = min(x1, x + 8)
            y = int(round(y0 + (y1 - y0) * ((x - x0) / max(1, x1 - x0))))
            cv2.rectangle(out, (x, y - (t - 1) // 2), (xe - 1, y + t // 2), 0, -1)

    for chain in chains:
        if len(chain) < 2:
            continue  # vue dans une seule bande : trop peu sûr
        thick = max(2, min(4, int(round(np.median([t for _a, _b, st_ in chain for _y, t in st_])))))
        # bouts de la portée : là où ses fragments commencent et finissent vraiment (pas le bord des bandes)
        def ends(x0, x1, staff):
            cols = np.stack([thin[max(0, int(y) - 2):int(y) + 3, x0:x1].any(0) for y, _t in staff]).sum(0) >= 3
            xs = np.flatnonzero(cols)
            return (x0 + int(xs[0]), x0 + int(xs[-1]) + 1) if len(xs) else (x0, x1)
        left, right = ends(*chain[0])[0], ends(*chain[-1])[1]
        # la portée commence souvent avant la première bande reconnue (clé, armure) : on suit ses fragments vers la gauche
        ys0 = [y for y, _t in chain[0][2]]
        while left > 0:
            lo = max(0, left - 40)
            cols = np.stack([thin[max(0, int(y) - 2):int(y) + 3, lo:left].any(0) for y in ys0]).sum(0) >= 3
            xs = np.flatnonzero(cols)
            if not len(xs):
                break
            left = lo + int(xs[0])
            if xs[0] > 0:
                break
        chain[0] = (left, chain[0][1], chain[0][2])
        chain[-1] = (chain[-1][0], right, chain[-1][2])
        for k, (xa0, xa1, sa) in enumerate(chain):
            for y, _t in sa:
                draw(xa0, xa1, y, y, thick)
            if k + 1 < len(chain):
                xb0, _xb1, sb = chain[k + 1]
                for (ya, _ta), (yb, _tb) in zip(sa, sb):
                    draw(xa1, xb0, ya, yb, thick)
    # bandes des portées : des têtes de notes au-dessus (2,5 interlignes) à la fin des queues dessous, avant les paroles
    bands = []
    for chain in chains:
        if len(chain) >= 2:
            top = float(np.median([st[0][0] for _a, _b, st in chain]))
            bottom = float(np.median([st[4][0] for _a, _b, st in chain]))
            sp = (bottom - top) / 4
            bands.append((top - 2.5 * sp, bottom + 1.5 * sp))
    return restore_strokes(out, bands)


def pdf_pages(pdf, tmp):
    """Pages du PDF en niveaux de gris à 300 dpi (pypdfium2 : embarqué, rien à installer)."""
    import pypdfium2 as pdfium
    try:
        doc = pdfium.PdfDocument(str(pdf))
    except Exception:
        sys.exit("Ce PDF est illisible ou protégé par un mot de passe.")
    pages = []
    for page in doc:
        img = page.render(scale=300 / 72, grayscale=True).to_numpy()
        pages.append((img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), False))
    return pages




def image_pages(path):
    """Toutes les pages d'une image (un TIFF peut en contenir plusieurs), orientées selon l'appareil photo."""
    try:
        im = Image.open(path)
    except Exception:
        sys.exit(f"Image illisible ({path.name}) : utilisez un PDF, un JPG, un PNG ou une photo HEIC.")
    out = []
    for i in range(getattr(im, "n_frames", 1)):
        im.seek(i)
        frame = ImageOps.exif_transpose(im.copy()).convert("L")
        out.append((np.array(frame), True))
    return out


def load_pages(src, tmp):
    """(image en niveaux de gris, est_une_photo) pour chaque page, dans l'ordre."""
    files = sorted(p for p in src.iterdir() if not p.name.startswith(".")) if src.is_dir() else [src]
    pages = []
    for k, f in enumerate(files):
        ext = f.suffix.lower()
        if ext == ".pdf":
            pages += pdf_pages(f, tmp)
        elif ext in IMAGES:
            pages += image_pages(f)
        else:
            sys.exit(f"Fichier non pris en charge : {f.name}")
    return pages


def main(src, out_dir):
    src, out = pathlib.Path(src), pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        pages = load_pages(src, t)
        if not pages:
            sys.exit("Le fichier ne contient aucune page lisible.")
        best, other, pages_out, digital, worn, specks = [], [], [], 0, 0, []
        for i, (raw, photo) in enumerate(pages, 1):
            if photo:
                raw = upright(crop_page(raw))
            gray = to_gray(raw)
            specks.append(speck_density(gray))  # avant le renforcement, qui ferait ressortir le grain de la photo
            # photo floue : seuillage par crêtes (PUPITRE_SEUIL_FLOU=adaptatif : l'ancien, pour le banc d'essai)
            blurred = photo and edge_width(gray) > BLUR and os.environ.get("PUPITRE_SEUIL_FLOU") != "adaptatif"
            if photo:
                gray = unblur(gray)
            plain = plain_page(gray)
            worn += dashed_lines(plain)
            page, for_audiveris = clean_page(gray, blurred)
            plain, cleaned, for_audiveris = repair_staff_lines(plain), repair_staff_lines(page), repair_staff_lines(for_audiveris)
            if is_digital(gray):
                digital += 1
                pages_out.append(plain); best.append(plain); other.append(for_audiveris)
            else:
                pages_out.append(cleaned); best.append(for_audiveris); other.append(plain)
            imgio.imwrite(str(out / f"page-{i:02d}.png"), pages_out[-1])
            print(f"actif:page {i}/{len(pages)}", flush=True)  # signe de vie : omr.py le relaie à la surveillance
    # clean.pdf : la meilleure version pour Audiveris ; alt.pdf : l'autre, essayée si la première échoue.
    for name, imgs in (("clean.pdf", best), ("alt.pdf", other)):
        pil = [Image.fromarray(a) for a in imgs]
        pil[0].save(out / name, save_all=True, append_images=pil[1:], resolution=300)
    # photocopie usée (lignes en tirets) : omr.py tente alors la lecture voix par voix
    (out / "usee").write_text(str(worn), encoding="utf-8") if worn else (out / "usee").unlink(missing_ok=True)
    # saleté de la copie : petites taches par mégapixel (médiane des pages) ; omr.py décide d'après elle (SALETE)
    (out / "salete").write_text(f"{float(np.median(specks)):.0f}", encoding="utf-8")
    print(f"Pages préparées : {len(best)} (dont {digital} numériques{f', {worn} usées' if worn else ''})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
