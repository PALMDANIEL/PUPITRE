import { Injectable, computed, inject, signal } from '@angular/core';
import { ScoreMeta, ScoreStatus } from './api';
import { PackStore } from './packs';

/**
 * Serveur de lecture AIT (en ligne) : le téléphone envoie la photo d'une partition, le serveur lit les notes
 * et renvoie un pack de répétition, enregistré dans le téléphone (l'écoute se fait ensuite sans Internet).
 */
export interface RemoteSettings { url: string; code: string }
export interface AccessInfo { client: string; id: string; expires: string | null }
export interface RemoteJob { id: string; title: string; status: ScoreStatus; progress: number; error: string | null; startedAt: string }

const SETTINGS_KEY = 'pupitre-serveur';
const JOBS_KEY = 'pupitre-lectures';

function read<T>(key: string, fallback: T): T {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) ?? 'null') } as T; } catch { return fallback; }
}
function readJobs(): RemoteJob[] {
  try { return JSON.parse(localStorage.getItem(JOBS_KEY) ?? '[]') as RemoteJob[]; } catch { return []; }
}

export class RemoteError extends Error {}

@Injectable({ providedIn: 'root' })
export class RemoteReader {
  private readonly packs = inject(PackStore);
  readonly settings = signal<RemoteSettings>(read(SETTINGS_KEY, { url: '', code: '' }));
  readonly jobs = signal<RemoteJob[]>(readJobs());
  readonly uploading = signal(false);
  readonly uploadProgress = signal(0);
  private polling = false;

  configured() { const s = this.settings(); return !!s.url && !!s.code; }
  readonly busyCount = computed(() => this.jobs().filter((j) => j.status !== 'ready' && j.status !== 'failed').length);

  save(settings: RemoteSettings) {
    const clean = { url: settings.url.trim().replace(/\/+$/, ''), code: settings.code.replace(/\s+/g, '') };
    this.settings.set(clean);
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(clean)); } catch { /* stockage indisponible : réglage pour la session */ }
  }

  private headers(s = this.settings()): HeadersInit { return { Authorization: `Pupitre ${s.code}` }; }

  private async call<T>(path: string, init: RequestInit = {}, s = this.settings()): Promise<T> {
    if (!s.url || !s.code) throw new RemoteError('Indiquez d’abord le serveur et le code de votre chorale dans les réglages.');
    let res: Response;
    try {
      res = await fetch(`${s.url}${path}`, { ...init, headers: { ...this.headers(s), ...(init.headers ?? {}) } });
    } catch {
      throw new RemoteError('Le serveur ne répond pas. Vérifiez la connexion Internet et l’adresse du serveur.');
    }
    if (!res.ok) {
      const body = await res.json().catch(() => null) as { error?: string } | null;
      throw new RemoteError(body?.error ?? `Erreur du serveur (${res.status}).`);
    }
    return (res.headers.get('content-type') ?? '').includes('json') ? await res.json() as T : await res.blob() as T;
  }

  /** Vérifie l'adresse et le code avant de les enregistrer. */
  check(s: RemoteSettings): Promise<AccessInfo> {
    const clean = { url: s.url.trim().replace(/\/+$/, ''), code: s.code.replace(/\s+/g, '') };
    return this.call<AccessInfo>('/api/acces', {}, clean);
  }

  /** Envoie les pages (photos ou PDF) ; la lecture continue sur le serveur même si l'application est fermée. */
  send(files: File[], title: string): Promise<RemoteJob> {
    const s = this.settings();
    if (!s.url || !s.code) return Promise.reject(new RemoteError('Indiquez d’abord le serveur et le code de votre chorale dans les réglages.'));
    this.uploading.set(true);
    this.uploadProgress.set(0);
    return new Promise<RemoteJob>((resolve, reject) => {
      const body = new FormData();
      for (const f of files) body.append('file', f);
      const xhr = new XMLHttpRequest();
      xhr.open('POST', `${s.url}/api/scores`);
      xhr.setRequestHeader('Authorization', `Pupitre ${s.code}`);
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) this.uploadProgress.set(Math.round((100 * e.loaded) / e.total)); };
      xhr.onerror = () => { this.uploading.set(false); reject(new RemoteError('Envoi impossible : vérifiez la connexion Internet.')); };
      xhr.onload = async () => {
        this.uploading.set(false);
        let data: (ScoreMeta & { error?: string }) | null = null;
        try { data = JSON.parse(xhr.responseText); } catch { data = null; }
        if (xhr.status >= 300 || !data?.id) { reject(new RemoteError(data?.error ?? `Erreur du serveur (${xhr.status}).`)); return; }
        let name = data.title;
        if (title.trim()) {
          try {
            const renamed = await this.call<ScoreMeta>(`/api/scores/${data.id}`, {
              method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title: title.trim() }),
            });
            name = renamed.title;
          } catch { /* le titre par défaut reste */ }
        }
        const job: RemoteJob = { id: data.id, title: name, status: data.status, progress: data.progress, error: null, startedAt: new Date().toISOString() };
        this.store([job, ...this.jobs()]);
        void this.follow();
        resolve(job);
      };
      xhr.send(body);
    });
  }

  private store(jobs: RemoteJob[]) {
    this.jobs.set(jobs);
    try { localStorage.setItem(JOBS_KEY, JSON.stringify(jobs)); } catch { /* idem */ }
  }

  private update(id: string, patch: Partial<RemoteJob>) {
    this.store(this.jobs().map((j) => (j.id === id ? { ...j, ...patch } : j)));
  }

  dismiss(id: string) { this.store(this.jobs().filter((j) => j.id !== id)); }

  /** Suit les lectures en cours ; à la fin, télécharge le pack et l'enregistre dans « Mes chants ». */
  async follow() {
    if (this.polling) return;
    this.polling = true;
    try {
      while (this.jobs().some((j) => j.status !== 'ready' && j.status !== 'failed')) {
        for (const job of this.jobs().filter((j) => j.status !== 'ready' && j.status !== 'failed')) {
          try {
            const meta = await this.call<ScoreMeta>(`/api/scores/${job.id}`);
            if (meta.status === 'ready') {
              const blob = await this.call<Blob>(`/api/scores/${job.id}/pack`);
              const local = await this.packs.import([new File([blob], `${meta.title}.pupitre`)]);
              this.update(job.id, { status: local ? 'ready' : 'failed', progress: 100, error: local ? null : this.packs.error(), title: meta.title });
            } else {
              this.update(job.id, { status: meta.status, progress: meta.progress, error: meta.error });
            }
          } catch (e) {
            // coupure de réseau : on réessaie au tour suivant ; partition supprimée ou code refusé : on arrête
            if (!(e instanceof RemoteError) || /n’existe pas|code/i.test(e.message)) this.update(job.id, { status: 'failed', error: (e as Error).message });
          }
        }
        await new Promise((r) => setTimeout(r, 2500));
      }
    } finally {
      this.polling = false;
    }
  }
}
