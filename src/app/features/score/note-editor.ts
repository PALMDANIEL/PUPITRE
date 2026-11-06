/**
 * Correction des notes dans la partition reconstituée (MusicXML, une portée par voix) : chaque note est retrouvée par
 * sa portée, sa mesure, son temps dans la mesure et son rang à ce temps — la même clé que celle calculée sur les notes
 * affichées par OSMD (score-viewer.eachNote) —, puis montée ou descendue d'un degré, ou altérée.
 */
export type NoteEdit = 'haut' | 'bas' | 'diese' | 'bemol' | 'becarre';

export interface NoteRef { el: Element; voice: string; measure: number; fifths: number }

const STEPS = ['C', 'D', 'E', 'F', 'G', 'A', 'B'];
const FR: Record<string, string> = { C: 'Do', D: 'Ré', E: 'Mi', F: 'Fa', G: 'Sol', A: 'La', B: 'Si' };
const SHARPS = 'FCGDAEB', FLATS = 'BEADGCF';
/** Temps en 960e de ronde : entier, comme Math.round(Timestamp.RealValue × 960) côté OSMD */
const TICKS = 960;

const child = (el: Element, name: string) => Array.from(el.children).find((c) => c.tagName === name) ?? null;
const num = (el: Element | null, fallback = 0) => (el && el.textContent ? Number(el.textContent) : fallback);

/** Altération que l'armure donne à ce degré (fifths > 0 : dièses, < 0 : bémols). */
export function keyAlter(step: string, fifths: number) {
  if (fifths > 0) return SHARPS.slice(0, fifths).includes(step) ? 1 : 0;
  if (fifths < 0) return FLATS.slice(0, -fifths).includes(step) ? -1 : 0;
  return 0;
}

export function indexNotes(doc: Document): Map<string, NoteRef> {
  const names = new Map<string, string>();
  for (const sp of Array.from(doc.getElementsByTagName('score-part'))) {
    names.set(sp.getAttribute('id') ?? '', child(sp, 'part-name')?.textContent?.trim() || 'Voix');
  }
  const map = new Map<string, NoteRef>();
  Array.from(doc.getElementsByTagName('part')).forEach((part, p) => {
    const voice = names.get(part.getAttribute('id') ?? '') ?? `Voix ${p + 1}`;
    let divisions = 1, fifths = 0;
    Array.from(part.children).filter((c) => c.tagName === 'measure').forEach((measure, m) => {
      let t = 0, last = 0;
      const ranks = new Map<number, number>();
      for (const el of Array.from(measure.children)) {
        if (el.tagName === 'attributes') {
          divisions = num(child(el, 'divisions'), divisions) || divisions;
          const k = child(el, 'key');
          if (k && child(k, 'fifths')) fifths = num(child(k, 'fifths'));
        } else if (el.tagName === 'backup') {
          t -= num(child(el, 'duration'));
        } else if (el.tagName === 'forward') {
          t += num(child(el, 'duration'));
        } else if (el.tagName === 'note') {
          const chord = !!child(el, 'chord');
          const start = chord ? last : t;
          if (!chord) { last = t; if (!child(el, 'grace')) t += num(child(el, 'duration')); }
          if (!child(el, 'pitch')) continue;
          const at = Math.round((start * TICKS) / (4 * divisions));
          const rank = ranks.get(at) ?? 0;
          ranks.set(at, rank + 1);
          map.set(`${p}:${m}:${at}:${rank}`, { el, voice, measure: m + 1, fifths });
        }
      }
    });
  });
  return map;
}

function pitchOf(el: Element) {
  const pitch = child(el, 'pitch')!;
  return { pitch, step: child(pitch, 'step')?.textContent?.trim() ?? 'C', alter: num(child(pitch, 'alter')), octave: num(child(pitch, 'octave'), 4) };
}

/** « Sol♯4 » */
export function noteLabel(el: Element) {
  const { step, alter, octave } = pitchOf(el);
  return `${FR[step] ?? step}${alter > 0 ? '♯'.repeat(alter) : alter < 0 ? '♭'.repeat(-alter) : ''}${octave}`;
}

function setText(parent: Element, name: string, value: string, before?: string) {
  let el = child(parent, name);
  if (!el) {
    el = parent.ownerDocument.createElementNS(parent.namespaceURI, name);
    const ref = before ? child(parent, before) : null;
    parent.insertBefore(el, ref);
  }
  el.textContent = value;
}

/** Signe écrit devant la note (après la figure et ses points, avant la hampe, la portée, les ligatures, les paroles). */
function setAccidental(el: Element, sign: string | null) {
  const old = child(el, 'accidental');
  if (old) el.removeChild(old);
  if (!sign) return;
  const acc = el.ownerDocument.createElementNS(el.namespaceURI, 'accidental');
  acc.textContent = sign;
  const after = ['time-modification', 'stem', 'notehead', 'notehead-text', 'staff', 'beam', 'notations', 'lyric', 'play', 'listen'];
  const ref = Array.from(el.children).find((c) => after.includes(c.tagName)) ?? null;
  el.insertBefore(acc, ref);
}

export function editNote(ref: NoteRef, edit: NoteEdit) {
  const { pitch, step, octave } = pitchOf(ref.el);
  let alter: number;
  let sign: string | null = null;
  if (edit === 'haut' || edit === 'bas') {
    const index = STEPS.indexOf(step) + 7 * octave + (edit === 'haut' ? 1 : -1);
    const next = STEPS[((index % 7) + 7) % 7];
    setText(pitch, 'step', next);
    setText(pitch, 'octave', String(Math.floor(index / 7)));
    alter = keyAlter(next, ref.fifths);  // nouveau degré : l'altération de l'armure
  } else {
    alter = edit === 'diese' ? 1 : edit === 'bemol' ? -1 : 0;
    sign = edit === 'diese' ? 'sharp' : edit === 'bemol' ? 'flat' : 'natural';
  }
  const old = child(pitch, 'alter');
  if (alter) setText(pitch, 'alter', String(alter), 'octave');
  else if (old) pitch.removeChild(old);
  setAccidental(ref.el, sign);
}
