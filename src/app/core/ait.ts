import { Injectable, computed, signal } from '@angular/core';
import { Share } from '@capacitor/share';
import jsQR from 'jsqr';
import { parseKeyQr, seal, signToken, unseal, type SealedKey } from './ait-crypto';
import { addDuration } from './duree';

/**
 * Espace AIT (administrateur, sur son téléphone) : créer les licences d'ordinateur et les codes d'accès des chorales.
 * La clé AIT est importée une fois (QR code affiché par le Mac), gardée chiffrée par un code PIN,
 * et n'est déchiffrée en mémoire que le temps de la session.
 */
export interface IssuedItem {
  kind: 'licence' | 'acces';
  id: string;
  client: string;
  contact: string;
  machine: string;
  issued: string;
  expires: string | null;
  createdAt: string;
  text: string;
}

export const ADMIN_SERVER = 'https://pupitre-lecture.vercel.app';

/** Élément du registre du serveur (licence ou code), avec sa dernière connexion. */
export interface ServerItem {
  id: string; kind: 'licence' | 'acces'; client: string; contact: string | null; machine: string | null;
  issued: string | null; expires: string | null; status: 'active' | 'revoked'; reason: string | null;
  first_seen: string | null; last_seen: string | null; app_version: string | null; os: string | null; uses: number;
}
export interface ServerEvent { at: string; kind: string; item_id: string | null; client: string | null; detail: Record<string, unknown> | null }
export type Overview = Record<'licences' | 'licences_desactivees' | 'codes' | 'codes_desactives' | 'en_ligne' | 'actifs_7j' | 'clients' | 'lectures' | 'lectures_24h', number>;

const KEY = 'pupitre-ait-cle';
const REGISTRY = 'pupitre-ait-registre';
const ATTEMPTS = 'pupitre-ait-essais';
const ALPHABET = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789';

function load<T>(key: string, fallback: T): T {
  try { return (JSON.parse(localStorage.getItem(key) ?? 'null') as T) ?? fallback; } catch { return fallback; }
}
function store(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* stockage plein ou indisponible */ }
}

/** ABCD-EFGH-JKMN-PQRS à partir d'une saisie libre (minuscules, espaces, tirets oubliés) ; null si invalide. */
export function normalizeMachineId(text: string): string | null {
  const s = text.toUpperCase().replace(/[^A-Z0-9]/g, '');
  if (s.length !== 16 || [...s].some((c) => !ALPHABET.includes(c))) return null;
  return s.match(/.{4}/g)!.join('-');
}

/** Lit le QR code d'une photo (clé AIT affichée sur le Mac). */
export async function readQrPhoto(file: File): Promise<string> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const ctx = canvas.getContext('2d', { willReadFrequently: true })!;
  ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const img = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const found = jsQR(img.data, img.width, img.height, { inversionAttempts: 'attemptBoth' });
  if (!found?.data) throw new Error('Aucun QR code lisible sur la photo. Rapprochez-vous de l’écran, sans reflet, et réessayez.');
  return found.data;
}

@Injectable({ providedIn: 'root' })
export class AitStore {
  readonly sealed = signal<SealedKey | null>(load<SealedKey | null>(KEY, null));
  readonly registry = signal<IssuedItem[]>(load<IssuedItem[]>(REGISTRY, []));
  private readonly seed = signal<Uint8Array | null>(null);
  readonly hasKey = computed(() => !!this.sealed());
  readonly unlocked = computed(() => !!this.seed());

  async setup(qrText: string, pin: string) {
    if (!/^\d{6,8}$/.test(pin)) throw new Error('Le code PIN doit faire 6 à 8 chiffres.');
    if (/^(\d)\1+$/.test(pin) || '0123456789'.includes(pin) || '9876543210'.includes(pin)) throw new Error('Code PIN trop facile à deviner (111111, 123456…) : choisissez-en un autre.');
    const seed = parseKeyQr(qrText);
    const sealed = await seal(seed, pin);
    store(KEY, sealed);
    this.sealed.set(sealed);
    this.seed.set(seed);
  }

  async unlock(pin: string) {
    const sealed = this.sealed();
    if (!sealed) throw new Error('Aucune clé sur ce téléphone.');
    const tries = load<{ fails: number; until: number }>(ATTEMPTS, { fails: 0, until: 0 });
    const wait = Math.ceil((tries.until - Date.now()) / 1000);
    if (wait > 0) throw new Error(`Trop d’essais. Réessayez dans ${wait > 90 ? Math.ceil(wait / 60) + ' minutes' : wait + ' secondes'}.`);
    try {
      this.seed.set(await unseal(sealed, pin));
      store(ATTEMPTS, { fails: 0, until: 0 });
    } catch (e) {
      // À partir du 3e échec, attente doublée à chaque fois : 30 s, 1 min, 2 min… jusqu'à 1 h.
      const fails = tries.fails + 1;
      store(ATTEMPTS, { fails, until: fails >= 3 ? Date.now() + Math.min(3_600_000, 30_000 * 2 ** (fails - 3)) : 0 });
      throw e;
    }
  }

  lock() {
    this.seed()?.fill(0);
    this.seed.set(null);
  }

  /** Retire la clé de ce téléphone (le registre est conservé). */
  forget() {
    this.lock();
    try { localStorage.removeItem(KEY); } catch { /* déjà absent */ }
    this.sealed.set(null);
  }

  /** Numéros distincts de ceux du Mac (AIT-2026-0001) : AIT-2026-T0001, ACC-2026-T0001. */
  private nextId(kind: 'licence' | 'acces', year: string) {
    const prefix = `${kind === 'licence' ? 'AIT' : 'ACC'}-${year}-T`;
    const n = this.registry().filter((i) => i.id.startsWith(prefix)).length + 1;
    return `${prefix}${String(n).padStart(4, '0')}`;
  }

  private add(item: IssuedItem) {
    const list = [item, ...this.registry()];
    this.registry.set(list);
    store(REGISTRY, list);
    return item;
  }

  createLicence(form: { client: string; contact: string; machine: string; duree: string; debut: string }): IssuedItem {
    const seed = this.seed() ?? (() => { throw new Error('Espace AIT verrouillé.'); })();
    const client = form.client.trim();
    if (!client) throw new Error('Indiquez le client (nom de la chorale).');
    const machine = normalizeMachineId(form.machine);
    if (!machine) throw new Error('Identifiant d’ordinateur invalide : 16 caractères, ex. ABCD-EFGH-JKMN-PQRS (affiché dans Pupitre chez le client).');
    const issued = form.debut || new Date().toISOString().slice(0, 10);
    const expires = addDuration(issued, form.duree);
    const id = this.nextId('licence', issued.slice(0, 4));
    const payload = { id, client, ...(form.contact.trim() ? { contact: form.contact.trim() } : {}), machine, issued, expires, edition: 'standard' };
    return this.add({ kind: 'licence', id, client, contact: form.contact.trim(), machine, issued, expires, createdAt: new Date().toISOString(),
      text: signToken('PUP1', payload, seed) });
  }

  createAccess(form: { client: string; contact: string; duree: string; debut: string }): IssuedItem {
    const seed = this.seed() ?? (() => { throw new Error('Espace AIT verrouillé.'); })();
    const client = form.client.trim();
    if (!client) throw new Error('Indiquez la chorale.');
    const issued = form.debut || new Date().toISOString().slice(0, 10);
    const expires = addDuration(issued, form.duree);
    const id = this.nextId('acces', issued.slice(0, 4));
    const payload = { id, client, ...(form.contact.trim() ? { contact: form.contact.trim() } : {}), issued, expires, kind: 'acces' };
    return this.add({ kind: 'acces', id, client, contact: form.contact.trim(), machine: '', issued, expires, createdAt: new Date().toISOString(),
      text: signToken('PUPA1', payload, seed) });
  }

  /** Appel d'administration : jeton PUPADM1 signé par la clé AIT, valable 9 minutes. */
  async admin<T>(path: string, init: { method?: string; body?: unknown } = {}, server = ADMIN_SERVER): Promise<T> {
    const seed = this.seed() ?? (() => { throw new Error('Espace AIT verrouillé.'); })();
    const token = signToken('PUPADM1', { kind: 'admin', exp: new Date(Date.now() + 9 * 60_000).toISOString(), nonce: crypto.randomUUID() }, seed);
    let res: Response;
    try {
      res = await fetch(`${server}/api/admin${path}`, {
        method: init.method ?? 'GET',
        headers: { Authorization: `PupitreAdmin ${token}`, ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
        body: init.body ? JSON.stringify(init.body) : undefined,
      });
    } catch {
      throw new Error('Serveur AIT injoignable : vérifiez la connexion Internet.');
    }
    const data = await res.json().catch(() => null) as (T & { error?: string }) | null;
    if (!res.ok) throw new Error(data?.error ?? `Erreur du serveur (${res.status}).`);
    return data as T;
  }

  /** Inscrit au registre du serveur les licences et codes créés sur ce téléphone (même hors ligne). */
  syncRegistry() {
    const items = this.registry().map((i) => i.text);
    return items.length ? this.admin<{ count: number }>('/enregistrer', { method: 'POST', body: { items } }) : Promise.resolve({ count: 0 });
  }

  csv(): string {
    const q = (v: string) => `"${v.replace(/"/g, '""')}"`;
    const rows = this.registry().map((i) => [i.id, i.kind === 'licence' ? 'licence' : 'code d’accès', i.client, i.contact, i.machine, i.issued, i.expires ?? 'illimitée'].map(q).join(','));
    return ['numero,type,client,contact,machine,debut,fin', ...rows].join('\n');
  }

  /** WhatsApp, SMS, e-mail… (feuille de partage du téléphone) ; à défaut, copie dans le presse-papiers. */
  async share(title: string, text: string): Promise<'shared' | 'copied'> {
    try {
      await Share.share({ title, text, dialogTitle: title });
      return 'shared';
    } catch (e) {
      if (/cancel/i.test(String((e as Error)?.message ?? e))) return 'shared';
      await navigator.clipboard.writeText(text);
      return 'copied';
    }
  }
}
