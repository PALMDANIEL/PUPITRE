/**
 * Identifiant de la machine : empreinte stable de l'identifiant matériel, sous la forme ABCD-EFGH-JKLM-NPQR.
 * Mac : IOPlatformUUID ; Windows : MachineGuid ; Linux : /etc/machine-id.
 * Seule l'empreinte est montrée et envoyée à AIT, jamais l'identifiant brut.
 */
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';

// Alphabet sans 0/O ni 1/I/L, pour être dicté au téléphone sans erreur
const ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';

function rawId(): string {
  try {
    if (process.platform === 'darwin') {
      const out = execFileSync('/usr/sbin/ioreg', ['-rd1', '-c', 'IOPlatformExpertDevice'], { encoding: 'utf8' });
      const m = /"IOPlatformUUID"\s*=\s*"([^"]+)"/.exec(out);
      if (m) return m[1];
    } else if (process.platform === 'win32') {
      const out = execFileSync('reg', ['query', 'HKLM\\SOFTWARE\\Microsoft\\Cryptography', '/v', 'MachineGuid'],
        { encoding: 'utf8', windowsHide: true });
      const m = /MachineGuid\s+REG_SZ\s+([0-9a-fA-F-]+)/.exec(out);
      if (m) return m[1];
    } else {
      for (const f of ['/etc/machine-id', '/var/lib/dbus/machine-id']) {
        if (fs.existsSync(f)) return fs.readFileSync(f, 'utf8').trim();
      }
    }
  } catch { /* on retombe sur le nom de la machine ci-dessous */ }
  return `${os.hostname()}|${os.userInfo().username}`;
}

export function format(digest: Buffer): string {
  let out = '';
  for (let i = 0; i < 16; i++) out += ALPHABET[digest[i] % ALPHABET.length];
  return out.match(/.{4}/g)!.join('-');
}

let cached: string | null = null;
export function machineId(): string {
  cached ??= format(createHash('sha256').update(`pupitre-ait:${rawId().toUpperCase()}`).digest());
  return cached;
}

/** Normalise un identifiant saisi à la main (minuscules, espaces, tirets oubliés). */
export function normalizeMachineId(text: string): string | null {
  const s = text.toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (s.length !== 16 || [...s].some((c) => !ALPHABET.includes(c))) return null;
  return s.match(/.{4}/g)!.join('-');
}
