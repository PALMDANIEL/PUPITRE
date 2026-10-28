/**
 * Prépare une photo avant l'envoi : aussi nette que possible (3200 px au plus sur le grand côté, soit la résolution
 * d'un scan à 300 dpi pour une page A4), puis allégée seulement si le poids dépasse la part de cette page dans la
 * limite d'envoi (hébergement Vercel : 4,5 Mo par lecture). Les notes se lisent mal sous ~1600 px de large.
 * Un PDF, ou une image que le téléphone ne sait pas décoder, est envoyé tel quel.
 */
const STEPS: [side: number, quality: number][] = [[3200, 0.9], [3200, 0.8], [2800, 0.78], [2400, 0.75], [2000, 0.7]];

export async function shrinkPhoto(file: File, budget = 2_000_000): Promise<File> {
  if (!file.type.startsWith('image/') || (file.size <= budget && !/heic|heif/i.test(file.type))) return file;
  try {
    const bitmap = await createImageBitmap(file);
    let best: Blob | null = null;
    for (const [side, quality] of STEPS) {
      const scale = Math.min(1, side / Math.max(bitmap.width, bitmap.height));
      const canvas = document.createElement('canvas');
      canvas.width = Math.round(bitmap.width * scale);
      canvas.height = Math.round(bitmap.height * scale);
      canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      best = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', quality));
      if (best && best.size <= budget) break;
    }
    bitmap.close();
    if (!best || (best.size >= file.size && !/heic|heif/i.test(file.type))) return file;
    return new File([best], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' });
  } catch {
    return file;
  }
}
