/**
 * Signature des licences (PUP1) et des codes d'accès (PUPA1) sur le téléphone de l'administrateur AIT.
 * Même format et même algorithme (Ed25519) que licence/core.ts sur le Mac : un texte signé ici est accepté
 * tel quel par l'application de bureau et par le serveur de lecture. Aucune dépendance à l'interface.
 */
import * as ed from '@noble/ed25519';
import { sha512 } from '@noble/hashes/sha2.js';

ed.hashes.sha512 = sha512;

/** Clé publique AIT (les 32 octets de licence/cle-publique.pem) : vérifie que la clé importée est la bonne. */
export const AIT_PUBLIC_KEY = 'LT+1lrCLNbfLJU1HvGMXRE4wRcMWBLIvlHOSVB9Khug=';

const enc = new TextEncoder();
export const b64url = (bytes: Uint8Array) =>
  btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
export const unb64url = (text: string) =>
  Uint8Array.from(atob(text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4)), (c) => c.charCodeAt(0));

export function signToken(prefix: 'PUP1' | 'PUPA1' | 'PUPADM1', payload: object, seed: Uint8Array): string {
  const body = `${prefix}.${b64url(enc.encode(JSON.stringify(payload)))}`;
  return `${body}.${b64url(ed.sign(enc.encode(body), seed))}`;
}

/** QR code affiché par « npm run licence -- export-mobile » : PUPK1:<32 octets de la clé privée>. */
export function parseKeyQr(text: string): Uint8Array {
  const m = /^PUPK1:([A-Za-z0-9_-]{43})$/.exec(text.trim());
  if (!m) throw new Error('Ce QR code n’est pas une clé AIT (il doit venir de « npm run licence -- export-mobile »).');
  const seed = unb64url(m[1]);
  if (b64url(ed.getPublicKey(seed)) !== b64url(unb64url(AIT_PUBLIC_KEY.replace(/\+/g, '-').replace(/\//g, '_')))) {
    throw new Error('Cette clé n’est pas la clé AIT de cette version de Pupitre.');
  }
  return seed;
}

// Clé gardée chiffrée par le code PIN (PBKDF2 → AES-GCM) : sans le PIN, elle est illisible.
export interface SealedKey { salt: string; iv: string; data: string }

async function pinKey(pin: string, salt: Uint8Array) {
  const base = await crypto.subtle.importKey('raw', enc.encode(pin), 'PBKDF2', false, ['deriveKey']);
  return crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt: salt as BufferSource, iterations: 310_000 },
    base, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

export async function seal(seed: Uint8Array, pin: string): Promise<SealedKey> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, await pinKey(pin, salt), seed as BufferSource));
  return { salt: b64url(salt), iv: b64url(iv), data: b64url(data) };
}

export async function unseal(sealed: SealedKey, pin: string): Promise<Uint8Array> {
  try {
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64url(sealed.iv) as BufferSource },
      await pinKey(pin, unb64url(sealed.salt)), unb64url(sealed.data) as BufferSource);
    return new Uint8Array(plain);
  } catch {
    throw new Error('Code PIN incorrect.');
  }
}
