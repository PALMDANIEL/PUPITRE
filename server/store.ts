import { config } from './config';
import { fileStore } from './store-files';
import { pgStore } from './store-pg';
import type { Store } from './store-base';
import type { ScoreMeta } from './types';

export { dirOf, isId } from './store-base';

let store: Store;

/** PostgreSQL si DATABASE_URL est défini (installation serveur), sinon fichiers locaux (version installable). */
export async function initDb() {
  store = config.store === 'postgres' ? pgStore : fileStore;
  await store.init();
}

export const readMeta = (id: string) => store.read(id);
export const writeMeta = (meta: ScoreMeta) => store.write(meta);
export const patchMeta = (id: string, patch: Partial<ScoreMeta>) => store.patch(id, patch);
export const listMetas = () => store.list();
export const removeScore = (id: string) => store.remove(id);
