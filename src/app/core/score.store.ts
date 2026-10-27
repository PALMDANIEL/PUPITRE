import { computed, inject } from '@angular/core';
import { patchState, signalStore, withComputed, withHooks, withMethods, withState } from '@ngrx/signals';
import { firstValueFrom } from 'rxjs';
import { BUSY, Langue, ScoreMeta, ScoresApi, Timbre, Voyelle, errorMessage } from './api';

interface ScoreState { score: ScoreMeta | null; loading: boolean; error: string | null; actionError: string | null }

export const ScoreStore = signalStore(
  withState<ScoreState>({ score: null, loading: true, error: null, actionError: null }),
  withComputed(({ score }) => ({
    busy: computed(() => !!score() && BUSY.includes(score()!.status)),
  })),
  withMethods((store, api = inject(ScoresApi)) => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    const poll = async (id: string) => {
      clearTimeout(timer);
      try {
        const s = await firstValueFrom(api.get(id));
        patchState(store, { score: s, loading: false, error: null });
        if (BUSY.includes(s.status)) timer = setTimeout(() => poll(id), 1500);
      } catch (e) {
        patchState(store, { loading: false, error: errorMessage(e) });
      }
    };

    const act = async (fn: (id: string) => Promise<ScoreMeta>) => {
      const id = store.score()?.id;
      if (!id) return;
      patchState(store, { actionError: null });
      try {
        patchState(store, { score: await fn(id) });
        void poll(id);
      } catch (e) {
        patchState(store, { actionError: errorMessage(e) });
      }
    };

    return {
      load(id: string) {
        patchState(store, { loading: true, score: null, error: null });
        void poll(id);
      },
      render: (opts: { tempo: number; timbre: Timbre; langue?: Langue; paroles?: Record<string, string> | null; voyelle?: Voyelle }) => act((id) => firstValueFrom(api.render(id, opts))),
      retry: () => act((id) => firstValueFrom(api.retry(id))),
      uploadCorrection: (file: File) => act((id) => firstValueFrom(api.correct(id, file))),
      stop() { clearTimeout(timer); },
    };
  }),
  withHooks({ onDestroy(store) { store.stop(); } }),
);
