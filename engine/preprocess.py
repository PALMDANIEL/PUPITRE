"""
Pré-traitement : PDF ou photo -> pages nettoyées (éclairage, bords, inclinaison).
Usage : python3 preprocess.py <source.pdf|.jpg|.png> <dossier_sortie>
"""
import sys, cv2, numpy as np, subprocess, pathlib, tempfile
from PIL import Image


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


def clean_page(img):
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    scale = 2480 / gray.shape[1]
    if abs(scale - 1) > 0.05:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
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


def pdf_to_images(pdf, tmp):
    subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", str(pdf), str(tmp / "p")], check=True)
    return sorted(tmp.glob("p*.png"))


def main(src, out_dir):
    src, out = pathlib.Path(src), pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as t:
        t = pathlib.Path(t)
        pages = pdf_to_images(src, t) if src.suffix.lower() == ".pdf" else [src]
        if not pages:
            sys.exit("Le PDF ne contient aucune page lisible.")
        outs = []
        for i, p in enumerate(pages, 1):
            img = cv2.imread(str(p), cv2.IMREAD_COLOR)
            if img is None:
                sys.exit("Image illisible : utilisez un PDF, un JPG ou un PNG.")
            dst = out / f"page-{i:02d}.png"
            cv2.imwrite(str(dst), clean_page(img))
            outs.append(dst)
    imgs = [Image.open(p).convert("L") for p in outs]
    imgs[0].save(out / "clean.pdf", save_all=True, append_images=imgs[1:], resolution=300)
    print(f"Pages nettoyées : {len(outs)}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
