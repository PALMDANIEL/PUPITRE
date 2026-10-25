/**
 * Codes d'accès au serveur de lecture AIT (application mobile : photo de partition lue en ligne).
 * Un code par chorale : « PUPA1.<contenu>.<signature> », signé par AIT, avec une date de fin.
 * Le serveur ne garde aucune liste de comptes : il vérifie la signature et range les partitions par code.
 */
import { decodeToken, frDate, LicenceError, signToken } from './core';

export const ACCESS_PREFIX = 'PUPA1';

export interface AccessPayload {
  /** Numéro du code, ex. ACC-2026-0003 : sert aussi à séparer les partitions de chaque chorale sur le serveur */
  id: string;
  client: string;
  contact?: string;
  issued: string;
  expires: string | null;
  kind: 'acces';
}

export function signAccess(payload: AccessPayload, privatePem: string): string {
  return signToken(ACCESS_PREFIX, payload, privatePem);
}

export function checkAccess(text: string, publicPem: string, now = new Date()): AccessPayload {
  const acc = decodeToken<AccessPayload>(ACCESS_PREFIX, text, publicPem, 'un code d’accès Pupitre');
  if (acc.kind !== 'acces' || !/^ACC-\d{4}-\d{4}$/.test(acc.id)) throw new LicenceError('format', 'Ce texte n’est pas un code d’accès Pupitre.');
  if (acc.expires && now.toISOString().slice(0, 10) > acc.expires) {
    throw new LicenceError('expired', `Le code d’accès de « ${acc.client} » a expiré le ${frDate(acc.expires)}. Contactez AIT pour le renouveler.`);
  }
  return acc;
}
