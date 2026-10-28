import { Mp3Encoder } from '@breezystack/lamejs';

const RATE = 44100;
const FRAME = 1152;

/**
 * Piste de travail fabriquée sur le téléphone, comme celle de l'ordinateur :
 * sa voix au centre, environ 12 dB devant ; les autres en fond, écartées à gauche et à droite.
 * Les pistes de la voix sont mixées hors temps réel, puis encodées en MP3 (128 kbit/s, stéréo).
 */
export async function practiceTrack(stems: string[], own: number, onProgress?: (p: number) => void): Promise<Blob> {
  const decoder = new OfflineAudioContext(2, RATE, RATE);
  const buffers = await Promise.all(stems.map(async (url) => decoder.decodeAudioData(await (await fetch(url)).arrayBuffer())));
  const length = Math.max(...buffers.map((b) => Math.ceil(b.duration * RATE)));
  const ctx = new OfflineAudioContext(2, length, RATE);
  buffers.forEach((buffer, j) => {
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    const gain = ctx.createGain();
    gain.gain.value = j === own ? 1 : 0.25;
    const pan = ctx.createStereoPanner();
    pan.pan.value = j === own ? 0 : (j % 2 === 0 ? -0.6 : 0.6);
    src.connect(gain).connect(pan).connect(ctx.destination);
    src.start();
  });
  onProgress?.(10);
  const mixed = await ctx.startRendering();
  const left = mixed.getChannelData(0);
  const right = mixed.getChannelData(1);

  // niveau d'écoute comme les autres fichiers (≈ −18 dB efficaces sur les passages chantés, +18 dB au plus),
  // puis limiteur doux au-dessus de 0,7 : jamais de saturation
  const BLOCK = 4410;
  let energy = 0, blocks = 0;
  for (let start = 0; start < length; start += BLOCK) {
    let e = 0;
    const end = Math.min(length, start + BLOCK);
    for (let i = start; i < end; i++) e += (left[i] * left[i] + right[i] * right[i]) / 2;
    e /= end - start;
    if (e > 3e-5) { energy += e; blocks++; }  // blocs au-dessus de −45 dB : on ignore les silences
  }
  const gain = blocks ? Math.min(8, 0.126 / Math.sqrt(energy / blocks)) : 1;
  const soft = (x: number) => {
    const a = Math.abs(x * gain);
    return Math.sign(x) * (a <= 0.7 ? a : 0.7 + 0.29 * Math.tanh((a - 0.7) / 0.29));
  };
  const scale = 32767;

  const enc = new Mp3Encoder(2, RATE, 128);
  const parts: Uint8Array[] = [];
  const l = new Int16Array(FRAME);
  const r = new Int16Array(FRAME);
  for (let start = 0, n = 0; start < length; start += FRAME, n++) {
    const size = Math.min(FRAME, length - start);
    for (let i = 0; i < size; i++) { l[i] = soft(left[start + i]) * scale; r[i] = soft(right[start + i]) * scale; }
    const out = enc.encodeBuffer(size === FRAME ? l : l.subarray(0, size), size === FRAME ? r : r.subarray(0, size));
    if (out.length) parts.push(out.slice());
    if (n % 200 === 0) {  // laisse l'écran respirer et affiche l'avancement
      onProgress?.(10 + Math.round((90 * start) / length));
      await new Promise((ok) => setTimeout(ok));
    }
  }
  parts.push(enc.flush().slice());
  onProgress?.(100);
  return new Blob(parts as BlobPart[], { type: 'audio/mpeg' });
}
