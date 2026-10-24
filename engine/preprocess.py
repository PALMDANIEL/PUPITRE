"""
Pré-traitement : PDF ou photos -> pages nettoyées (cadrage, éclairage, bords, inclinaison).
Usage : python3 preprocess.py <source.pdf|image|dossier_de_pages> <dossier_sortie>
Images : JPG, PNG, HEIC/HEIF (iPhone), WEBP, TIFF (plusieurs pages), BMP. Un dossier = ses fichiers dans l'ordre des noms.
"""
import sys, cv2, numpy as np, subprocess, pathlib, tempfile
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


def pdf_pages(pdf, tmp):
    tmp.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", str(pdf), str(tmp / "p")], capture_output=True)
    if r.returncode:
        sys.exit("Ce PDF est illisible ou protégé par un mot de passe.")
    return [(cv2.imread(str(p), cv2.IMREAD_GRAYSCALE), False) for p in sorted(tmp.glob("p*.png"))]


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
            pages += pdf_pages(f, tmp / str(k))
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
        best, other, digital = [], [], 0
        for i, (raw, photo) in enumerate(pages, 1):
            if photo:
                raw = upright(crop_page(raw))
            gray = to_gray(raw)
            plain, cleaned = plain_page(gray), clean_page(gray)
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
    print(f"Pages préparées : {len(best)} (dont {digital} numériques)")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
