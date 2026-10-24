import { HttpEventType } from '@angular/common/http';
import { computed, inject } from '@angular/core';
import { patchState, signalStore, withComputed, withMethods, withState } from '@ngrx/signals';
import { firstValueFrom } from 'rxjs';
import { BUSY, ScoreMeta, ScoresApi, errorMessage } from './api';

interface LibraryState { scores: ScoreMeta[]; loaded: boolean; uploading: boolean; uploadProgress: number; error: string | null }

export const LibraryStore = signalStore(
  { providedIn: 'root' },
  withState<LibraryState>({ scores: [], loaded: false, uploading: false, uploadProgress: 0, error: null }),
  withComputed(({ scores }) => ({
    anyBusy: computed(() => scores().some((s) => BUSY.includes(s.status))),
  })),
  withMethods((store, api = inject(ScoresApi)) => ({
    async load() {
      try {
        patchState(store, { scores: await firstValueFrom(api.list()), loaded: true });
      } catch (e) {
        patchState(store, { error: errorMessage(e), loaded: true });
      }
    },
    upload(files: File[]): Promise<ScoreMeta> {
      patchState(store, { uploading: true, uploadProgress: 0, error: null });
      return new Promise((resolve, reject) => {
        api.upload(files).subscribe({
          next: (ev) => {
            if (ev.type === HttpEventType.UploadProgress && ev.total) {
              patchState(store, { uploadProgress: Math.round((100 * ev.loaded) / ev.total) });
            } else if (ev.type === HttpEventType.Response && ev.body) {
              patchState(store, { uploading: false, scores: [ev.body, ...store.scores()] });
              resolve(ev.body);
            }
          },
          error: (e) => {
            patchState(store, { uploading: false, error: errorMessage(e) });
            reject(e);
          },
        });
      });
    },
    async remove(id: string) {
      try {
        await firstValueFrom(api.remove(id));
        patchState(store, { scores: store.scores().filter((s) => s.id !== id) });
      } catch (e) {
        patchState(store, { error: errorMessage(e) });
      }
    },
  })),
);
