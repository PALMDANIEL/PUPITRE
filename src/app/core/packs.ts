import { Injectable, signal } from '@angular/core';
import { unzipSync, strFromU8 } from 'fflate';
import { Manifest, ScoreMeta, registerFiles } from './api';

/** Pack de répétition (.pupitre) exporté par Pupitre sur ordinateur, gardé dans le téléphone. */
export interface PackSummary {
  id: string;
  title: string;
  importedAt: string;
  manifest: Manifest;
  size: number;
}
interface PackRecord extends PackSummary { files: Record<string, Blob> }

const DB = 'pupitre-lecteur';
const STORE = 'packs';

function db(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: 'id' });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, run: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const d = await db();
  return new Promise((resolve, reject) => {
    const req = run(d.transaction(STORE, mode).objectStore(STORE));
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

const MIME: Record<string, string> = { mp3: 'audio/mpeg', musicxml: 'application/vnd.recordare.musicxml+xml', json: 'application/json' };

@Injectable({ providedIn: 'root' })
export class PackStore {
  readonly packs = signal<PackSummary[]>([]);
  readonly loaded = signal(false);
  readonly importing = signal(false);
  readonly error = signal<string | null>(null);
  private opened = new Map<string, string[]>();

  async load() {
    try {
      const all = await tx<PackRecord[]>('readonly', (s) => s.getAll() as IDBRequest<PackRecord[]>);
      this.packs.set(all.map(({ files: _f, ...summary }) => summary).sort((a, b) => b.importedAt.localeCompare(a.importedAt)));
    } catch {
      this.error.set('Impossible de lire les chants enregistrés sur ce téléphone.');
    } finally {
      this.loaded.set(true);
    }
  }

  /** Importe un ou plusieurs fichiers .pupitre ; renvoie l'identifiant du dernier importé. */
  async import(files: File[]): Promise<string | null> {
    this.importing.set(true);
    this.error.set(null);
    let last: string | null = null;
    try {
      for (const file of files) {
        let entries: Record<string, Uint8Array>;
        try { entries = unzipSync(new Uint8Array(await file.arrayBuffer())); } catch {
          throw new Error(`« ${file.name} » n’est pas un pack Pupitre. Demandez à votre chef de chœur le fichier .pupitre.`);
        }
        const info = entries['pack.json'] ? JSON.parse(strFromU8(entries['pack.json'])) : null;
        if (info?.format !== 'pupitre-pack') throw new Error(`« ${file.name} » n’est pas un pack Pupitre.`);
        const blobs: Record<string, Blob> = {};
        for (const [name, data] of Object.entries(entries)) {
          if (!name.startsWith('audio/') || name.endsWith('/')) continue;
          const short = name.slice('audio/'.length);
          blobs[short] = new Blob([data as BlobPart], { type: MIME[short.split('.').pop() ?? ''] ?? 'application/octet-stream' });
        }
        const manifest = { ...info.manifest, voices: info.manifest.voices.map((v: Manifest['voices'][number]) => ({ ...v, practice: '' })) } as Manifest;
        const missing = [manifest.score, ...manifest.voices.map((v) => v.stem)].filter((f) => !blobs[f]);
        if (missing.length) throw new Error(`Pack incomplet (${missing.join(', ')} manquant).`);
        // Même chant réimporté (nouvelle version du chef de chœur) : il remplace l'ancien
        const existing = this.packs().find((p) => p.title === info.title);
        const id = existing?.id ?? crypto.randomUUID();
        const record: PackRecord = { id, title: info.title, importedAt: new Date().toISOString(), manifest, files: blobs, size: file.size };
        await tx('readwrite', (s) => s.put(record));
        this.close(id);
        last = id;
      }
      await this.load();
      return last;
    } catch (e) {
      this.error.set((e as Error).message || 'Import impossible.');
      return null;
    } finally {
      this.importing.set(false);
    }
  }

  async remove(id: string) {
    this.close(id);
    await tx('readwrite', (s) => s.delete(id));
    await this.load();
  }

  /** Prépare un pack pour le lecteur : ses fichiers deviennent des adresses locales lues par l'interface habituelle. */
  async open(id: string): Promise<ScoreMeta | null> {
    const rec = await tx<PackRecord | undefined>('readonly', (s) => s.get(id) as IDBRequest<PackRecord | undefined>);
    if (!rec) return null;
    this.close(id);
    const urls = Object.fromEntries(Object.entries(rec.files).map(([name, blob]) => [name, URL.createObjectURL(blob)]));
    this.opened.set(id, Object.values(urls));
    registerFiles(id, urls);
    return {
      id, title: rec.title, originalName: `${rec.title}.pupitre`, source: 'musicxml', partitionFile: rec.manifest.score,
      corrected: false, pages: [], status: 'ready', progress: 100, error: null, tempo: rec.manifest.tempo, timbre: rec.manifest.timbre,
      // révision = date d'import : un chant recréé (nouvelle sonorité) recharge ses pistes dans le lecteur
      manifest: rec.manifest, revision: Date.parse(rec.importedAt) || 0, createdAt: rec.importedAt, updatedAt: rec.importedAt,
    };
  }

  /** Renommer une voix d'un chant enregistré sur le téléphone. */
  async renameVoice(id: string, voice: string, name: string): Promise<void> {
    const rec = await tx<PackRecord | undefined>('readonly', (s) => s.get(id) as IDBRequest<PackRecord | undefined>);
    if (!rec) return;
    rec.manifest = { ...rec.manifest, voices: rec.manifest.voices.map((v) => (v.id === voice ? { ...v, name } : v)) };
    rec.importedAt = new Date().toISOString();  // le lecteur recharge le chant
    await tx('readwrite', (s) => s.put(rec));
    await this.load();
  }

  /** Partition MusicXML d'un chant enregistré (pour recréer son audio en ligne). */
  async scoreFile(id: string): Promise<{ title: string; file: Blob; name: string } | null> {
    const rec = await tx<PackRecord | undefined>('readonly', (s) => s.get(id) as IDBRequest<PackRecord | undefined>);
    const blob = rec?.files[rec.manifest.score];
    return rec && blob ? { title: rec.title, file: blob, name: rec.manifest.score } : null;
  }

  close(id: string) {
    for (const url of this.opened.get(id) ?? []) URL.revokeObjectURL(url);
    this.opened.delete(id);
    registerFiles(id, null);
  }
}
