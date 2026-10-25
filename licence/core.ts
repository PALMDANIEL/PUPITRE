/**
 * Licences Pupitre : texte « PUP1.<contenu>.<signature> », signé par AIT avec une clé privée Ed25519.
 * L'application ne contient que la clé publique : elle vérifie une licence, mais ne peut pas en fabriquer.
 */
import { createPrivateKey, createPublicKey, generateKeyPairSync, sign, verify } from 'node:crypto';

export const PREFIX = 'PUP1';

export interface LicencePayload {
  /** Numéro de licence, ex. AIT-2026-0007 */
  id: string;
  /** Chorale ou client */
  client: string;
  contact?: string;
  /** Identifiant de la machine autorisée (voir machine.ts) */
  machine: string;
  /** Date d'émission, AAAA-MM-JJ */
  issued: string;
  /** Dernier jour d'utilisation, AAAA-MM-JJ ; null = licence définitive */
  expires: string | null;
  edition: 'standard';
}

const b64 = (b: Buffer) => b.toString('base64url');
const unb64 = (s: string) => Buffer.from(s, 'base64url');

export function generateKeys(): { privatePem: string; publicPem: string } {
  const { privateKey, publicKey } = generateKeyPairSync('ed25519');
  return {
    privatePem: privateKey.export({ type: 'pkcs8', format: 'pem' }).toString(),
    publicPem: publicKey.export({ type: 'spki', format: 'pem' }).toString(),
  };
}

/** Signe un contenu JSON sous la forme « <préfixe>.<contenu>.<signature> » (licences PUP1, codes d'accès PUPA1). */
export function signToken(prefix: string, payload: object, privatePem: string): string {
  const body = `${prefix}.${b64(Buffer.from(JSON.stringify(payload)))}`;
  return `${body}.${b64(sign(null, Buffer.from(body), createPrivateKey(privatePem)))}`;
}

/** Lit un texte signé collé par l'utilisateur (espaces et retours à la ligne tolérés). */
export function decodeToken<T>(prefix: string, text: string, publicPem: string, what: string): T {
  const clean = text.replace(/\s+/g, '');
  const parts = clean.split('.');
  if (parts.length !== 3 || parts[0] !== prefix) throw new LicenceError('format', `Ce texte n’est pas ${what}.`);
  const body = `${parts[0]}.${parts[1]}`;
  let ok = false;
  try { ok = verify(null, Buffer.from(body), createPublicKey(publicPem), unb64(parts[2])); } catch { ok = false; }
  if (!ok) throw new LicenceError('signature', `Ce texte n’est pas valide (il a été modifié ou ne vient pas d’AIT).`);
  try {
    return JSON.parse(unb64(parts[1]).toString('utf8')) as T;
  } catch {
    throw new LicenceError('format', `Ce texte n’est pas ${what}.`);
  }
}

export function signLicence(payload: LicencePayload, privatePem: string): string {
  return signToken(PREFIX, payload, privatePem);
}

export function decodeLicence(text: string, publicPem: string): LicencePayload {
  return decodeToken<LicencePayload>(PREFIX, text, publicPem, 'une licence Pupitre');
}

export type LicenceProblem = 'format' | 'signature' | 'machine' | 'expired' | 'clock' | 'missing';

export class LicenceError extends Error {
  constructor(readonly problem: LicenceProblem, message: string) { super(message); }
}

const day = (d: Date) => d.toISOString().slice(0, 10);

/**
 * Vérifie une licence pour cette machine et cette date.
 * lastSeen : dernier jour où l'application a fonctionné ; si l'horloge revient en arrière de plus d'un jour,
 * c'est qu'on a reculé la date pour prolonger une licence expirée.
 */
export function checkLicence(text: string, publicPem: string, machine: string, now: Date, lastSeen?: string | null): LicencePayload {
  const lic = decodeLicence(text, publicPem);
  if (lic.machine !== machine) {
    throw new LicenceError('machine', `Cette licence a été délivrée pour un autre ordinateur (${lic.machine}).`);
  }
  const today = day(now);
  if (lastSeen && today < day(new Date(new Date(lastSeen).getTime() - 86_400_000))) {
    throw new LicenceError('clock', 'La date de cet ordinateur semble avoir été reculée. Remettez-la à l’heure pour utiliser Pupitre.');
  }
  if (lic.expires && today > lic.expires) {
    throw new LicenceError('expired', `Votre licence a expiré le ${frDate(lic.expires)}. Contactez AIT pour la renouveler.`);
  }
  return lic;
}

export function frDate(iso: string) {
  return new Date(`${iso}T12:00:00Z`).toLocaleDateString('fr-FR', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
}

/** Jours restants (0 le dernier jour) ; null pour une licence définitive. */
export function daysLeft(lic: LicencePayload, now: Date): number | null {
  if (!lic.expires) return null;
  return Math.round((Date.parse(`${lic.expires}T00:00:00Z`) - Date.parse(`${day(now)}T00:00:00Z`)) / 86_400_000);
}
