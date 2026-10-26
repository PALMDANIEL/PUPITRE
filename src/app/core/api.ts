import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';

export type ScoreStatus = 'queued' | 'preprocessing' | 'recognizing' | 'rendering' | 'ready' | 'failed';
export type Timbre = 'choeur' | 'piano' | 'chant';
/** Langue des voix chantées. */
export type Langue = 'fr' | 'la' | 'en' | 'mos' | 'dyu';
export const LANGUES: { id: Langue; label: string }[] = [
  { id: 'fr', label: 'Français' }, { id: 'la', label: 'Latin' }, { id: 'en', label: 'Anglais' },
  { id: 'mos', label: 'Mooré' }, { id: 'dyu', label: 'Dioula' },
];
export const BUSY: ScoreStatus[] = ['queued', 'preprocessing', 'recognizing', 'rendering'];

export interface VoiceInfo { id: string; name: string; stem: string; practice: string; notes: number; range: [string, string]; lyrics?: string; sung?: number }
export interface Manifest {
  tempo: number; timbre: Timbre; tutti: string; score: string; langue?: Langue;
  measures: number; timeSignature: string | null; key: string; voices: VoiceInfo[];
}
export interface ScoreMeta {
  id: string; title: string; originalName: string; source: 'pdf' | 'image' | 'musicxml' | 'midi' | 'musescore';
  partitionFile: string | null; corrected: boolean; pages: string[];
  status: ScoreStatus; progress: number; error: string | null;
  tempo: number | null; timbre: Timbre; manifest: Manifest | null; revision: number;
  langue?: Langue | null; paroles?: Record<string, string> | null;
  createdAt: string; updatedAt: string;
}

export const STATUS_LABEL: Record<ScoreStatus, string> = {
  queued: 'En attente', preprocessing: 'Nettoyage de l’image', recognizing: 'Lecture des notes',
  rendering: 'Création de l’audio', ready: 'Prête', failed: 'Échec',
};

const VOICE_COLORS: Record<string, string> = {
  soprano: 'var(--soprano)', alto: 'var(--alto)', tenor: 'var(--tenor)', basse: 'var(--basse)',
};
const CYCLE = ['var(--soprano)', 'var(--alto)', 'var(--tenor)', 'var(--basse)'];
export const voiceColor = (id: string, index = 0) => VOICE_COLORS[id] ?? CYCLE[index % CYCLE.length];

export const ACCEPT = '.pdf,.png,.jpg,.jpeg,.heic,.heif,.webp,.tif,.tiff,.bmp,.mxl,.musicxml,.xml,.mid,.midi,.mscz,.mscx';

/** Fichiers d'un pack de répétition ouvert sur le téléphone : adresses locales (blob:) au lieu du serveur. */
const localFiles = new Map<string, Record<string, string>>();
export function registerFiles(id: string, urls: Record<string, string> | null) {
  if (urls) localFiles.set(id, urls); else localFiles.delete(id);
}

export const fileUrl = (s: Pick<ScoreMeta, 'id' | 'revision'>, folder: 'audio' | 'pages', file: string, download = false) =>
  localFiles.get(s.id)?.[file] ?? `/files/${s.id}/${folder}/${encodeURIComponent(file)}?v=${s.revision}${download ? '&download' : ''}`;

export function errorMessage(e: unknown): string {
  if (e instanceof HttpErrorResponse) {
    if (e.status === 0) return 'Pupitre ne répond pas. Vérifiez que le terminal « npm start » est toujours ouvert.';
    return e.error?.error ?? 'Une erreur est survenue.';
  }
  return 'Une erreur est survenue.';
}

@Injectable({ providedIn: 'root' })
export class ScoresApi {
  private readonly http = inject(HttpClient);

  list() { return this.http.get<ScoreMeta[]>('/api/scores'); }
  get(id: string) { return this.http.get<ScoreMeta>(`/api/scores/${id}`); }
  /** Plusieurs photos envoyées ensemble = les pages d'une même partition, dans l'ordre des noms. */
  upload(files: File[]) {
    const body = new FormData();
    for (const f of files) body.append('file', f);
    return this.http.post<ScoreMeta>('/api/scores', body, { reportProgress: true, observe: 'events' });
  }
  rename(id: string, title: string) { return this.http.patch<ScoreMeta>(`/api/scores/${id}`, { title }); }
  render(id: string, opts: { tempo?: number | null; timbre?: Timbre; langue?: Langue; paroles?: Record<string, string> | null }) { return this.http.post<ScoreMeta>(`/api/scores/${id}/render`, opts); }
  retry(id: string) { return this.http.post<ScoreMeta>(`/api/scores/${id}/retry`, {}); }
  correct(id: string, file: File) {
    const body = new FormData();
    body.append('file', file);
    return this.http.put<ScoreMeta>(`/api/scores/${id}/partition`, body);
  }
  remove(id: string) { return this.http.delete<void>(`/api/scores/${id}`); }
}
