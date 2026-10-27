import { Injectable, computed, inject, signal } from '@angular/core';
import { Langue, ScoreMeta, ScoreStatus, Timbre, Voyelle } from './api';
import { PackStore } from './packs';
import { shrinkPhoto } from './shrink';

/**
 * Serveur de lecture AIT (en ligne) : le téléphone envoie la photo d'une partition, le serveur lit les notes
 * et renvoie un pack de répétition, enregistré dans le téléphone (l'écoute se fait ensuite sans Internet).
 */
/** direct : serveur sans stockage (Vercel) → lecture en une seule connexion (/api/lire), application ouverte */
export interface AccessInfo { client: string; id: string; issued?: string | null; expires: string | null; direct?: boolean }
export interface RemoteSettings { url: string; code: string; direct?: boolean; info?: AccessInfo | null }
export interface RemoteJob { id: string; title: string; status: ScoreStatus; progress: number; error: string | null; startedAt: string; direct?: boolean }

/** Limite d'envoi des hébergements sans serveur (4,5 Mo) : on garde de la marge. */
const DIRECT_MAX_BYTES = 4_200_000;

const SETTINGS_KEY = 'pupitre-serveur';
const JOBS_KEY = 'pupitre-lectures';

function read<T>(key: string, fallback: T): T {
  try { return { ...fallback, ...JSON.parse(localStorage.getItem(key) ?? 'null') } as T; } catch { return fallback; }
}
function readJobs(): RemoteJob[] {
  try {
    // une lecture directe ne survit pas à la fermeture de l'application
    return (JSON.parse(localStorage.getItem(JOBS_KEY) ?? '[]') as RemoteJob[]).map((j) =>
      j.direct && j.status !== 'ready' && j.status !== 'failed'
        ? { ...j, status: 'failed' as const, error: 'Lecture interrompue : l’application a été fermée. Relancez-la.' } : j);
  } catch { return []; }
}

export class RemoteError extends Error {}

/** Contenu d'un code d'accès (sans vérifier la signature : sert seulement à l'affichage et au renouvellement). */
export function decodeCode(code: string | null | undefined): { id: string; client: string; issued: string | null; expires: string | null } | null {
  const parts = (code ?? '').replace(/\s+/g, '').split('.');
  if (parts.length !== 3 || parts[0] !== 'PUPA1') return null;
  try {
    const json = decodeURIComponent(escape(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'))));
    const p = JSON.parse(json) as { id?: string; client?: string; issued?: string; expires?: string | null };
    return p.id ? { id: p.id, client: p.client ?? '', issued: p.issued ?? null, expires: p.expires ?? null } : null;
  } catch {
    return null;
  }
}

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
    const clean = { url: settings.url.trim().replace(/\/+$/, ''), code: settings.code.replace(/\s+/g, ''), direct: !!settings.direct, info: settings.info ?? null };
    this.settings.set(clean);
    try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(clean)); } catch { /* stockage indisponible : réglage pour la session */ }
  }

  /** Met à jour les dates du code (renouvellement, expiration) quand Internet est disponible ; silencieux sinon. */
  async refreshAccess() {
    const s = this.settings();
    if (!s.url || !s.code) return;
    try {
      // code renouvelé en ligne (même expiré) : le serveur renvoie le nouveau texte, installé à la place de l'ancien
      const r = await fetch(`${s.url}/api/paiement/renouvellement`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code: s.code }) })
        .then((res) => (res.ok ? res.json() as Promise<{ code: string | null }> : null)).catch(() => null);
      if (r?.code) { s.code = r.code; this.save(s); }
      const info = await this.check(s);
      if (info.client) this.save({ ...s, direct: !!info.direct, info });
    } catch { /* hors ligne ou code refusé : on garde les dernières dates connues */ }
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
  async send(pages: File[], title: string): Promise<RemoteJob> {
    const files = await Promise.all(pages.map(shrinkPhoto));
    if (this.settings().direct) return this.sendDirect(files, title);
    return this.sendQueued(files, title);
  }

  /** Serveur sans stockage : une seule connexion, progression en direct, pack reçu à la fin. */
  private async sendDirect(files: File[], title: string): Promise<RemoteJob> {
    const s = this.settings();
    if (files.reduce((n, f) => n + f.size, 0) > DIRECT_MAX_BYTES) {
      throw new RemoteError('Trop lourd pour une seule lecture : envoyez au plus 2 ou 3 pages à la fois.');
    }
    const body = new FormData();
    body.append('titre', title);
    for (const f of files) body.append('file', f);
    const job: RemoteJob = { id: crypto.randomUUID(), title, status: 'queued', progress: 0, error: null, startedAt: new Date().toISOString(), direct: true };
    this.store([job, ...this.jobs()]);
    this.uploading.set(true);
    void (async () => {
      try {
        let res: Response;
        try {
          res = await fetch(`${s.url}/api/lire`, { method: 'POST', body, headers: this.headers(s) });
        } catch {
          throw new RemoteError('Le serveur ne répond pas. Vérifiez la connexion Internet.');
        } finally {
          this.uploading.set(false);
        }
        if (!res.ok || !res.body) {
          const err = await res.json().catch(() => null) as { error?: string } | null;
          throw new RemoteError(err?.error ?? (res.status === 413 ? 'Photos trop lourdes : envoyez moins de pages à la fois.' : `Erreur du serveur (${res.status}).`));
        }
        const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
        let buffer = '';
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += value;
          const lines = buffer.split('\n');
          buffer = lines.pop() ?? '';
          for (const line of lines.filter(Boolean)) {
            const msg = JSON.parse(line) as { status?: ScoreStatus; progress?: number; error?: string; pack?: string; title?: string };
            if (msg.error) throw new RemoteError(msg.error);
            if (msg.pack) {
              const bytes = Uint8Array.from(atob(msg.pack), (c) => c.charCodeAt(0));
              const local = await this.packs.import([new File([bytes], `${msg.title ?? title}.pupitre`)]);
              if (!local) throw new RemoteError(this.packs.error() ?? 'Pack reçu illisible.');
              this.update(job.id, { status: 'ready', progress: 100, title: msg.title ?? title });
              return;
            }
            if (msg.status) this.update(job.id, { status: msg.status, progress: msg.progress ?? 0 });
          }
        }
        throw new RemoteError('La connexion a été coupée avant la fin de la lecture. Réessayez.');
      } catch (e) {
        this.update(job.id, { status: 'failed', error: (e as Error).message });
      }
    })();
    return job;
  }

  /**
   * Recrée l'audio d'un chant enregistré sur le téléphone (tempo, sonorité, voix chantées) : le serveur AIT
   * reçoit sa partition et renvoie un pack, qui remplace l'ancien. Renvoie l'identifiant du chant.
   */
  async recreate(packId: string, opts: { tempo: number; timbre: Timbre; langue?: Langue; paroles?: Record<string, string>; voyelle?: Voyelle },
                 onProgress: (pct: number) => void): Promise<string> {
    const s = this.settings();
    if (!s.url || !s.code) throw new RemoteError('Indiquez d’abord le serveur et le code de votre chorale dans les réglages.');
    const src = await this.packs.scoreFile(packId);
    if (!src) throw new RemoteError('Ce chant n’est plus sur ce téléphone.');
    const body = new FormData();
    body.append('file', new File([src.file], src.name.endsWith('.musicxml') ? src.name : 'score.musicxml'));
    body.append('titre', src.title);
    body.append('tempo', String(opts.tempo));
    body.append('timbre', opts.timbre);
    if (opts.langue) body.append('langue', opts.langue);
    if (opts.voyelle) body.append('voyelle', opts.voyelle);
    if (opts.paroles) body.append('paroles', JSON.stringify(opts.paroles));
    let res: Response;
    try {
      res = await fetch(`${s.url}/api/recreer`, { method: 'POST', body, headers: this.headers(s) });
    } catch {
      throw new RemoteError('Le serveur ne répond pas. Vérifiez la connexion Internet.');
    }
    if (!res.ok || !res.body) {
      const err = await res.json().catch(() => null) as { error?: string } | null;
      throw new RemoteError(err?.error ?? `Erreur du serveur (${res.status}).`);
    }
    const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += value;
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';
      for (const line of lines.filter(Boolean)) {
        const msg = JSON.parse(line) as { progress?: number; error?: string; pack?: string; title?: string };
        if (msg.error) throw new RemoteError(msg.error);
        if (msg.pack) {
          const bytes = Uint8Array.from(atob(msg.pack), (c) => c.charCodeAt(0));
          const id = await this.packs.import([new File([bytes], `${msg.title ?? src.title}.pupitre`)]);
          if (!id) throw new RemoteError(this.packs.error() ?? 'Pack reçu illisible.');
          return id;
        }
        if (typeof msg.progress === 'number') onProgress(msg.progress);
      }
    }
    throw new RemoteError('La connexion a été coupée avant la fin. Réessayez.');
  }

  private sendQueued(files: File[], title: string): Promise<RemoteJob> {
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
      while (this.jobs().some((j) => !j.direct && j.status !== 'ready' && j.status !== 'failed')) {
        for (const job of this.jobs().filter((j) => !j.direct && j.status !== 'ready' && j.status !== 'failed')) {
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
