"""
Pré-traitement : PDF ou photos -> pages nettoyées (cadrage, éclairage, bords, inclinaison).
Usage : python3 preprocess.py <source.pdf|image|dossier_de_pages> <dossier_sortie>
Images : JPG, PNG, HEIC/HEIF (iPhone), WEBP, TIFF (plusieurs pages), BMP. Un dossier = ses fichiers dans l'ordre des noms.
"""
import sys, cv2, numpy as np, pathlib, tempfile
from PIL import Image, ImageOps

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:  # HEIC indisponible : les autres formats fonctionnent
    pass

IMAGES = {".png", ".jpg", ".jpeg", ".heic", ".heif", ".webp", ".tif", ".tiff", ".bmp"}


def deskew(bw):
    inv = 255 - bw
    lines = cv2.HoughLinesP(inv, 1, np.pi / 1800, 200, minLineLength=bw.shape[1] // 3, maxLineGap=20)
    if lines is None:
        return bw
    angles = [np.degrees(np.arctan2(y2 - y1, x2 - x1)) for x1, y1, x2, y2 in lines[:, 0]]
    angles = [a for a in angles if abs(a) < 5]
    if not angles:
        return bw
    h, w = bw.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), float(np.median(angles)), 1.0)
    return cv2.warpAffine(bw, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=255)


def upright(gray):
    """Photo prise de côté (sans indication d'orientation) : les lignes de portée doivent être horizontales."""
    small = cv2.resize(gray, None, fx=800 / max(gray.shape), fy=800 / max(gray.shape))
    ink = cv2.adaptiveThreshold(small, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    horiz = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1))).sum()
    vert = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, 60))).sum()
    if vert <= 1.25 * horiz:
        return gray
    # Dans quel sens tourner ? Clé, armure et chiffrage sont au début de chaque portée : le côté gauche est le plus chargé.
    def left_heavy(img):
        ink = cv2.adaptiveThreshold(cv2.resize(img, None, fx=800 / max(img.shape), fy=800 / max(img.shape)),
                                    255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
        lines = cv2.morphologyEx(ink, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (60, 1)))
        rows = np.where(lines.sum(1) > 0)[0]
        if len(rows) < 10:
            return 0
        # étendue des portées : colonnes où les lignes sont nombreuses (les bords de la photo pèsent peu)
        cols = lines.sum(0)
        span = np.where(cols > 0.25 * cols.max())[0]
        x0, x1 = int(span.min()), int(span.max())
        band = max(1, (x1 - x0) // 10)
        inside = cv2.dilate((lines.sum(1) > 0).astype(np.uint8)[:, None], np.ones((5, 1), np.uint8))[:, 0] > 0
        return int(ink[inside, x0:x0 + band].sum()) - int(ink[inside, x1 - band:x1].sum())
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


def is_digital(gray):
    """Page issue d'un logiciel de gravure (fond blanc pur, presque pas de gris) et non d'un scan ou d'une photo."""
    return np.mean(gray > 245) > 0.8 and np.mean((gray > 60) & (gray < 200)) < 0.08


def plain_page(gray):
    """Simple seuillage : le nettoyage complet abîme les pages déjà propres (Audiveris peut alors planter)."""
    return cv2.threshold(gray, 160, 255, cv2.THRESH_BINARY)[1]


def clean_page(gray):
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 31)
    flat = cv2.divide(gray, bg, scale=255)
    bw = cv2.adaptiveThreshold(flat, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 15)

    h, w = bw.shape
    n, lab, stats, _ = cv2.connectedComponentsWithStats(255 - bw, 8)
    for i in range(1, n):
        x, y, cw, ch, _a = stats[i]
        near_edge = x < w * 0.07 or x + cw > w * 0.93 or y < h * 0.02 or y + ch > h * 0.98
        long_thin = (ch > h * 0.5 and cw < w * 0.06) or (cw > w * 0.5 and ch < h * 0.03)
        if near_edge and long_thin:
            bw[lab == i] = 255
    m = int(min(h, w) * 0.03)
    bw[:, :m] = 255; bw[:, -m:] = 255; bw[:m, :] = 255; bw[-m:, :] = 255

    n, lab, stats, _ = cv2.connectedComponentsWithStats(255 - bw, 8)
    for i in range(1, n):
        if stats[i, cv2.CC_STAT_AREA] < 6:
            bw[lab == i] = 255
    return deskew(bw)


DASHED = 0.08  # part des traits horizontaux qui tiennent sur 1/12 de page (pages saines : 18 à 64 %, photocopie usée : 0)


def level(bw):
    """
    Remet la page d'aplomb d'après ses lignes de portée, même en pointillés (photocopie) : on cherche l'angle
    qui rend le profil des rangées le plus contrasté (les lignes tombent alors chacune sur une seule rangée).
    """
    small = cv2.resize(255 - bw, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA).astype(np.float32)
    h, w = small.shape

    def sharpness(angle):
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rows = cv2.warpAffine(small, M, (w, h), flags=cv2.INTER_NEAREST).sum(1)
        return float(np.var(rows))

    best = max(np.arange(-3, 3.01, 0.25), key=sharpness)
    best = max(np.arange(best - 0.25, best + 0.26, 0.05), key=sharpness)
    H, W = bw.shape
    if abs(best) >= 0.05:
        M = cv2.getRotationMatrix2D((W / 2, H / 2), float(best), 1.0)
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
    lines = cv2.HoughLinesP(tall * 255, 1, np.pi / 720, 80, minLineLength=150, maxLineGap=10)
    if lines is None:
        return bw
    slopes = [(x2 - x1) / (y2 - y1) for x1, y1, x2, y2 in lines[:, 0] if abs(y2 - y1) > 150 and abs(x2 - x1) < 0.05 * abs(y2 - y1)]
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
        best, other, digital, worn = [], [], 0, 0
        for i, (raw, photo) in enumerate(pages, 1):
            if photo:
                raw = upright(crop_page(raw))
            gray = to_gray(raw)
            plain = plain_page(gray)
            worn += dashed_lines(plain)
            plain, cleaned = repair_staff_lines(plain), repair_staff_lines(clean_page(gray))
            if is_digital(gray):
                digital += 1
                best.append(plain); other.append(cleaned)
            else:
                best.append(cleaned); other.append(plain)
            cv2.imwrite(str(out / f"page-{i:02d}.png"), best[-1])
    # clean.pdf : la meilleure version pour Audiveris ; alt.pdf : l'autre, essayée si la première échoue.
    for name, imgs in (("clean.pdf", best), ("alt.pdf", other)):
        pil = [Image.fromarray(a) for a in imgs]
        pil[0].save(out / name, save_all=True, append_images=pil[1:], resolution=300)
    # photocopie usée (lignes en tirets) : omr.py tente alors la lecture voix par voix
    (out / "usee").write_text(str(worn)) if worn else (out / "usee").unlink(missing_ok=True)
    print(f"Pages préparées : {len(best)} (dont {digital} numériques{f', {worn} usées' if worn else ''})")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
