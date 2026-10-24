import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';

export type ScoreStatus = 'queued' | 'preprocessing' | 'recognizing' | 'rendering' | 'ready' | 'failed';
export type Timbre = 'choeur' | 'piano';
export const BUSY: ScoreStatus[] = ['queued', 'preprocessing', 'recognizing', 'rendering'];

export interface VoiceInfo { id: string; name: string; stem: string; practice: string; notes: number; range: [string, string] }
export interface Manifest {
  tempo: number; timbre: Timbre; tutti: string; score: string;
  measures: number; timeSignature: string | null; key: string; voices: VoiceInfo[];
}
export interface ScoreMeta {
  id: string; title: string; originalName: string; source: 'pdf' | 'image' | 'musicxml';
  partitionFile: string | null; corrected: boolean; pages: string[];
  status: ScoreStatus; progress: number; error: string | null;
  tempo: number | null; timbre: Timbre; manifest: Manifest | null; revision: number;
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

export const ACCEPT = '.pdf,.png,.jpg,.jpeg,.mxl,.musicxml,.xml';

export const fileUrl = (s: Pick<ScoreMeta, 'id' | 'revision'>, folder: 'audio' | 'pages', file: string, download = false) =>
  `/files/${s.id}/${folder}/${encodeURIComponent(file)}?v=${s.revision}${download ? '&download' : ''}`;

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
  upload(file: File) {
    const body = new FormData();
    body.append('file', file);
    return this.http.post<ScoreMeta>('/api/scores', body, { reportProgress: true, observe: 'events' });
  }
  rename(id: string, title: string) { return this.http.patch<ScoreMeta>(`/api/scores/${id}`, { title }); }
  render(id: string, opts: { tempo?: number | null; timbre?: Timbre }) { return this.http.post<ScoreMeta>(`/api/scores/${id}/render`, opts); }
  retry(id: string) { return this.http.post<ScoreMeta>(`/api/scores/${id}/retry`, {}); }
  correct(id: string, file: File) {
    const body = new FormData();
    body.append('file', file);
    return this.http.put<ScoreMeta>(`/api/scores/${id}/partition`, body);
  }
  remove(id: string) { return this.http.delete<void>(`/api/scores/${id}`); }
}
