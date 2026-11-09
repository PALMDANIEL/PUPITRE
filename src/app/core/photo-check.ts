/**
 * Contrôle d'une photo de partition avant l'envoi, dans le téléphone (ou le navigateur) : une photo floue, sombre,
 * dans l'ombre ou trop petite se lit mal, et il vaut mieux la reprendre tout de suite que découvrir des notes fausses.
 * Mesures sur l'image réduite à 1200 px, réglées sur le banc d'essai (engine/bench, make_reels.py) :
 *  - flou : largeur des bords de l'encre (contraste ÷ pente la plus forte) : photos nettes 2,2 à 2,5, floues 3,2 à 3,5 ;
 *  - sombre : clarté du papier (médiane) : photos éclairées 205 et plus, dans l'ombre 108 à 131 ;
 *  - ombre : papier le plus sombre ÷ le plus clair (zone centrale) : 0,80 et plus sans ombre, 0,44 à 0,76 avec ;
 *  - petite : plus petit côté sous 1000 px (photo transmise par WhatsApp : 905 px).
 * Le conseil n'empêche pas l'envoi : une copie unique, même médiocre, reste lisible en partie.
 */
export type PhotoProblem = 'floue' | 'sombre' | 'ombre' | 'petite';

export const PHOTO_ADVICE: Record<PhotoProblem, string> = {
  floue: 'Photo floue : tenez le téléphone immobile et touchez la partition à l’écran pour faire la mise au point.',
  sombre: 'Photo trop sombre : approchez-vous d’une fenêtre ou d’une lampe.',
  ombre: 'Ombre sur la page : tenez le téléphone pour que son ombre ne tombe pas sur la feuille.',
  petite: 'Image trop petite (photo reçue par WhatsApp ?) : prenez la photo d’origine, ou envoyez-la comme « document ».',
};

const LONG = 1200;
const BLOCK = 16;
export const LIMITS = { edge: 3.0, paper: 160, shade: 0.65, side: 1000 };

export interface PhotoMeasure { width: number; height: number; paper: number; shade: number; edge: number }

/** Mesures de la photo (null si le navigateur ne sait pas la décoder : HEIC sur certains téléphones, PDF). */
export async function measurePhoto(file: File): Promise<PhotoMeasure | null> {
  if (!file.type.startsWith('image/')) return null;
  let bitmap: ImageBitmap;
  try { bitmap = await createImageBitmap(file); } catch { return null; }
  const k = Math.min(1, LONG / Math.max(bitmap.width, bitmap.height));
  const w = Math.max(BLOCK * 4, Math.round(bitmap.width * k)), h = Math.max(BLOCK * 4, Math.round(bitmap.height * k));
  const canvas = document.createElement('canvas');
  canvas.width = w; canvas.height = h;
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
  ctx.drawImage(bitmap, 0, 0, w, h);
  const measure = { width: bitmap.width, height: bitmap.height };
  bitmap.close();
  const rgba = ctx.getImageData(0, 0, w, h).data;
  const gray = new Float32Array(w * h);
  for (let i = 0, j = 0; i < gray.length; i++, j += 4) gray[i] = 0.299 * rgba[j] + 0.587 * rgba[j + 1] + 0.114 * rgba[j + 2];

  // papier local : clarté maximale de chaque bloc, lissée sur 3 × 3 blocs
  const hb = Math.floor(h / BLOCK), wb = Math.floor(w / BLOCK);
  const blocks = new Float32Array(hb * wb);
  for (let by = 0; by < hb; by++) for (let bx = 0; bx < wb; bx++) {
    let m = 0;
    for (let y = by * BLOCK; y < (by + 1) * BLOCK; y++) for (let x = bx * BLOCK; x < (bx + 1) * BLOCK; x++) m = Math.max(m, gray[y * w + x]);
    blocks[by * wb + bx] = m;
  }
  const smooth = new Float32Array(hb * wb);
  for (let by = 0; by < hb; by++) for (let bx = 0; bx < wb; bx++) {
    let s = 0;
    for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
      const yy = Math.min(hb - 1, Math.max(0, by + dy)), xx = Math.min(wb - 1, Math.max(0, bx + dx));
      s += blocks[yy * wb + xx];
    }
    smooth[by * wb + bx] = s / 9;
  }
  // zone centrale (70 %) pour la clarté du papier et l'ombre : la table autour de la feuille ne compte pas
  const central: number[] = [];
  for (let by = Math.floor(hb * 0.15); by < Math.floor(hb * 0.85); by++)
    for (let bx = Math.floor(wb * 0.15); bx < Math.floor(wb * 0.85); bx++) central.push(smooth[by * wb + bx]);
  central.sort((a, b) => a - b);
  const at = (arr: number[], q: number) => arr[Math.min(arr.length - 1, Math.max(0, Math.floor(q * (arr.length - 1))))];
  const paper = at(central, 0.5);
  const shade = at(central, 0.05) / Math.max(at(central, 0.95), 1);

  // netteté : toute la page sauf un liseré ; encre = papier local − pixel ; largeur des bords = contraste ÷ pente
  const y0 = Math.floor(hb * 0.04) * BLOCK, y1 = Math.floor(hb * 0.96) * BLOCK;
  const x0 = Math.floor(wb * 0.04) * BLOCK, x1 = Math.floor(wb * 0.96) * BLOCK;
  const ink = (x: number, y: number) => Math.max(0, smooth[Math.floor(y / BLOCK) * wb + Math.floor(x / BLOCK)] - gray[y * w + x]);
  const inkHist = new Uint32Array(256), slopeHist = new Uint32Array(512);
  let n = 0, ns = 0;
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) {
    inkHist[Math.min(255, Math.round(ink(x, y)))]++; n++;
    if (y > y0 && y < y1 - 1 && x > x0 && x < x1 - 1) {
      const gx = (ink(x + 1, y) - ink(x - 1, y)) / 2, gy = (ink(x, y + 1) - ink(x, y - 1)) / 2;
      slopeHist[Math.min(511, Math.round(2 * Math.hypot(gx, gy)))]++; ns++;
    }
  }
  const pct = (hist: Uint32Array, total: number, q: number, scale: number) => {
    let acc = 0;
    for (let i = 0; i < hist.length; i++) { acc += hist[i]; if (acc >= q * total) return i / scale; }
    return (hist.length - 1) / scale;
  };
  const contrast = pct(inkHist, n, 0.995, 1), slope = pct(slopeHist, ns, 0.995, 2);
  return { ...measure, paper, shade, edge: contrast / Math.max(slope, 1e-6) };
}

/** Problèmes de la photo, du plus gênant au moins gênant (vide si elle est bonne ou si on ne sait pas la lire). */
export async function checkPhoto(file: File): Promise<PhotoProblem[]> {
  const m = await measurePhoto(file);
  if (!m) return [];
  const out: PhotoProblem[] = [];
  if (m.edge > LIMITS.edge) out.push('floue');
  if (m.paper < LIMITS.paper) out.push('sombre');
  else if (m.shade < LIMITS.shade) out.push('ombre');
  if (Math.min(m.width, m.height) < LIMITS.side) out.push('petite');
  return out;
}
