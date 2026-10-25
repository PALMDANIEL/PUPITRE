// CI : clé d'essai et code d'accès d'essai pour tester le serveur en ligne (sans la vraie clé AIT).
import fs from 'node:fs';
import { signAccess } from '../../licence/acces';
import { generateKeys } from '../../licence/core';

const { privatePem, publicPem } = generateKeys();
fs.writeFileSync(process.argv[2], publicPem);
const today = new Date().toISOString().slice(0, 10);
process.stdout.write(signAccess({ id: 'ACC-2026-9999', client: 'Essai CI', issued: today, expires: null, kind: 'acces' }, privatePem));
