import { Capacitor } from '@capacitor/core';
import { AIT_SERVER } from './serveur';

/** Page d'achat en ligne d'AIT (LigdiCash : Orange Money, Moov Money), ouverte dans le navigateur du téléphone ou de l'ordinateur. */
export const SHOP_SERVER = AIT_SERVER;

export function shopUrl(params: { produit?: 'licence' | 'acces'; renouveler?: string; machine?: string }, server = SHOP_SERVER): string {
  const q = new URLSearchParams(Object.entries(params).filter(([, v]) => !!v) as [string, string][]);
  return `${server.replace(/\/+$/, '')}/acheter?${q}`;
}

/** Sur téléphone, le lien sort de l'application vers le navigateur ; ailleurs, nouvel onglet (ou navigateur de l'ordinateur). */
export const SHOP_TARGET = Capacitor.isNativePlatform() ? '_self' : '_blank';
