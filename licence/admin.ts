/**
 * Jeton d'administration : « PUPADM1.<contenu>.<signature> », signé par la clé AIT (Espace AIT du téléphone).
 * Valable 10 minutes : le serveur n'a besoin d'aucun mot de passe, seule la clé AIT permet d'administrer.
 */
import { decodeToken, LicenceError } from './core';

export const ADMIN_PREFIX = 'PUPADM1';
export interface AdminPayload { kind: 'admin'; exp: string; nonce: string }

export function checkAdmin(text: string, publicPem: string, now = new Date()): AdminPayload {
  const p = decodeToken<AdminPayload>(ADMIN_PREFIX, text, publicPem, 'un jeton d’administration');
  const exp = Date.parse(p.exp);
  if (p.kind !== 'admin' || Number.isNaN(exp)) throw new LicenceError('format', 'Jeton d’administration invalide.');
  if (exp < now.getTime()) throw new LicenceError('expired', 'Session d’administration expirée : rouvrez l’Espace AIT.');
  if (exp - now.getTime() > 15 * 60_000) throw new LicenceError('format', 'Jeton d’administration trop long : vérifiez l’heure du téléphone.');
  return p;
}
