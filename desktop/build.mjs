// Compile l'application de bureau : main (avec le serveur Pupitre et la vérification des licences) et preload.
import { build } from 'esbuild';
import fs from 'node:fs';

fs.rmSync('build', { recursive: true, force: true });
const common = { bundle: true, platform: 'node', target: 'node22', format: 'cjs', sourcemap: false, logLevel: 'warning' };
await build({
  ...common,
  entryPoints: ['src/main.ts'],
  outfile: 'build/main.cjs',
  external: ['electron', 'pg-native'],
  loader: { '.pem': 'text' },
});
await build({ ...common, entryPoints: ['src/preload.ts'], outfile: 'build/preload.cjs', external: ['electron'] });
fs.copyFileSync('src/activation.html', 'build/activation.html');
console.log('Application de bureau compilée dans desktop/build');
