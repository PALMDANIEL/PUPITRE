export type ScoreStatus = 'queued' | 'preprocessing' | 'recognizing' | 'rendering' | 'ready' | 'failed';
export type SourceKind = 'pdf' | 'image' | 'musicxml' | 'midi' | 'musescore';
/** choeur : chœur de synthèse ; reel : vrais chanteurs enregistrés (« aah », « ouh ») ; piano ; chant : voix chantées avec paroles. */
export type Timbre = 'choeur' | 'reel' | 'piano' | 'chant';
export const TIMBRES: Timbre[] = ['choeur', 'reel', 'piano', 'chant'];
export type Voyelle = 'ah' | 'oo';
/** Lecture imposée par l'utilisateur : voix par voix (chœur à quatre voix, une portée par voix : S, A, T, B) ou ordinaire */
export type Disposition = 'satb' | 'ordinaire';
/** Langue des paroles chantées : français, latin, anglais, mooré, dioula. */
export type Langue = 'fr' | 'la' | 'en' | 'mos' | 'dyu';
export const LANGUES: Langue[] = ['fr', 'la', 'en', 'mos', 'dyu'];
export const BUSY: ScoreStatus[] = ['queued', 'preprocessing', 'recognizing', 'rendering'];

export interface VoiceInfo { id: string; name: string; stem: string; practice: string; notes: number; range: [string, string]; lyrics?: string; sung?: number }

export interface Manifest {
  tempo: number; timbre: Timbre; tutti: string; score: string; rebuilt?: string; langue?: Langue; voyelle?: Voyelle;
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
  /** Voix chantées : langue et paroles saisies par voix (sinon celles de la partition) */
  langue?: Langue | null; paroles?: Record<string, string> | null;
  /** Chœur réel : voyelle chantée */
  voyelle?: Voyelle | null;
  /** Lecture imposée ; null : choisie par le moteur d'après l'image */
  disposition?: Disposition | null;
  /** Lecture faite : 'voix' = voix relues une à une (4 portées par système reconnues) */
  lecture?: 'voix' | null;
  /** Noms de voix choisis par l'utilisateur (id → nom), gardés quand l'audio est recréé */
  voiceNames?: Record<string, string> | null;
  manifest: Manifest | null;
  revision: number;
  createdAt: string; updatedAt: string;
  /** Serveur en ligne : code d'accès (ACC-…) de la chorale propriétaire ; null en local */
  owner?: string | null;
}

export interface Job { id: string; kind: 'process' | 'render' }

export class UserError extends Error {}
