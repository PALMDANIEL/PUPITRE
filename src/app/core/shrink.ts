/**
 * Réduit une photo avant l'envoi : 2400 px au plus sur le grand côté, JPEG qualité 0,85 (≈ 1 Mo).
 * Largement assez pour lire les notes, et nécessaire pour les hébergements qui limitent la taille des envois.
 * Un PDF, ou une image que le téléphone ne sait pas décoder, est envoyé tel quel.
 */
const MAX_SIDE = 2400;

export async function shrinkPhoto(file: File): Promise<File> {
  if (!file.type.startsWith('image/') || (file.size < 900_000 && !/heic|heif/i.test(file.type))) return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement('canvas');
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/jpeg', 0.85));
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, '') + '.jpg', { type: 'image/jpeg' });
  } catch {
    return file;
  }
}
