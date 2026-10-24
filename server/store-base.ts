import path from 'node:path';
import { config } from './config';
import type { ScoreMeta } from './types';

const ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export const isId = (id: unknown): id is string => typeof id === 'string' && ID_RE.test(id);
export const dirOf = (id: string) => path.join(config.storageDir, id);

export interface Store {
  init(): Promise<void>;
  read(id: string): Promise<ScoreMeta | null>;
  write(meta: ScoreMeta): Promise<ScoreMeta>;
  patch(id: string, patch: Partial<ScoreMeta>): Promise<ScoreMeta>;
  list(): Promise<ScoreMeta[]>;
  remove(id: string): Promise<void>;
}
