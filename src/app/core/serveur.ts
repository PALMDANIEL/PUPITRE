/**
 * Serveur en ligne d'AIT (lecture des photos, vente, administration). Page servie par ce serveur lui-même (navigateur
 * sur son adresse) : la même adresse, sans rien à régler ; application (téléphone, ordinateur) : le VPS d'AIT.
 * L'ancien hébergement Vercel est fermé depuis le 19/11/2026.
 */
export const AIT_SERVER_DEFAULT = 'https://pupitre-102-204-24-173.sslip.io';

function sameOrigin(): string | null {
  try {
    const { protocol, hostname, origin } = window.location;
    if (protocol !== 'https:' && protocol !== 'http:') return null;
    if (hostname === 'localhost' || hostname === '127.0.0.1' || hostname === '[::1]') return null; // ordinateur, téléphone
    return origin;
  } catch {
    return null;
  }
}

export const AIT_SERVER = sameOrigin() ?? AIT_SERVER_DEFAULT;
