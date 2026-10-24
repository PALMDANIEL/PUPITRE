import type { CapacitorConfig } from '@capacitor/cli';

// Application mobile Pupitre (Android / iOS) : l'interface Angular en mode « lecteur de packs », sans serveur.
const config: CapacitorConfig = {
  appId: 'bf.ait.pupitre',
  appName: 'Pupitre',
  webDir: 'dist/pupitre/browser',
  backgroundColor: '#050918',
  android: { allowMixedContent: false },
  ios: { contentInset: 'never' },
};

export default config;
