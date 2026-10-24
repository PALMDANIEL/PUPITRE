export type ScoreStatus = 'queued' | 'preprocessing' | 'recognizing' | 'rendering' | 'ready' | 'failed';
export type SourceKind = 'pdf' | 'image' | 'musicxml' | 'midi' | 'musescore';
export type Timbre = 'choeur' | 'piano';
export const BUSY: ScoreStatus[] = ['queued', 'preprocessing', 'recognizing', 'rendering'];

export interface VoiceInfo { id: string; name: string; stem: string; practice: string; notes: number; range: [string, string] }

export interface Manifest {
  tempo: number; timbre: Timbre; tutti: string; score: string;
  measures: number; timeSignature: string | null; key: string; voices: VoiceInfo[];
}

export interface ScoreMeta {
  id: string; title: string; originalName: string;
  source: SourceKind; sourceFile: string;
  partitionFile: string | null;
  corrected: boolean;
  pages: string[];
  status: ScoreStatus; progress: number; error: string | null;
  tempo: number | null; timbre: Timbre;
  manifest: Manifest | null;
  revision: number;
  createdAt: string; updatedAt: string;
}

export interface Job { id: string; kind: 'process' | 'render' }

export class UserError extends Error {}
