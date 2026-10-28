import { Injectable, OnDestroy, signal } from '@angular/core';

export interface Track { id: string; url: string }

@Injectable()
export class AudioEngine implements OnDestroy {
  readonly playing = signal(false);
  readonly loading = signal(false);
  readonly position = signal(0);
  readonly duration = signal(0);
  readonly volumes = signal<Record<string, number>>({});
  readonly muted = signal<ReadonlySet<string>>(new Set());
  readonly error = signal<string | null>(null);

  private ctx: AudioContext | null = null;
  private buffers = new Map<string, AudioBuffer>();
  private gains = new Map<string, GainNode>();
  private sources: AudioBufferSourceNode[] = [];
  private startedAt = 0;
  private offset = 0;
  private raf = 0;
  private token = 0;

  async load(tracks: Track[]) {
    const token = ++this.token;
    this.halt();
    this.loading.set(true);
    this.error.set(null);
    try {
      const ctx = this.context();
      const decoded = await Promise.all(tracks.map(async (t) => {
        const res = await fetch(t.url);
        if (!res.ok) throw new Error(t.url);
        return [t.id, await ctx.decodeAudioData(await res.arrayBuffer())] as const;
      }));
      if (token !== this.token) return;
      this.buffers = new Map(decoded);
      for (const g of this.gains.values()) g.disconnect();
      this.gains.clear();
      const vols = { ...this.volumes() };
      for (const [id] of decoded) {
        const g = ctx.createGain();
        g.connect(this.output());
        this.gains.set(id, g);
        vols[id] ??= 1;
      }
      this.volumes.set(vols);
      // chaque piste est déjà à plein niveau : ensemble, elles dépasseraient le maximum (craquements sur les accords forts)
      this.output().gain.value = 1 / Math.sqrt(Math.max(1, decoded.length));
      this.applyGains();
      this.duration.set(Math.max(0, ...decoded.map(([, b]) => b.duration)));
      this.offset = Math.min(this.offset, this.duration());
      this.position.set(this.offset);
    } catch {
      if (token === this.token) this.error.set('L’audio n’a pas pu être chargé. Rechargez la page.');
    } finally {
      if (token === this.token) this.loading.set(false);
    }
  }

  setVolume(id: string, v: number) {
    this.volumes.update((x) => ({ ...x, [id]: v }));
    this.applyGains();
  }
  toggleMute(id: string) {
    this.muted.update((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
    this.applyGains();
  }
  clearMutes() {
    this.muted.set(new Set());
    this.applyGains();
  }

  async play() {
    if (this.playing() || !this.buffers.size) return;
    const ctx = this.context();
    await ctx.resume();
    if (this.offset >= this.duration() - 0.05) this.offset = 0;
    const t0 = ctx.currentTime + 0.05;
    this.sources = [];
    for (const [id, buf] of this.buffers) {
      if (this.offset >= buf.duration) continue;
      const s = ctx.createBufferSource();
      s.buffer = buf;
      s.connect(this.gains.get(id)!);
      s.start(t0, this.offset);
      this.sources.push(s);
    }
    this.startedAt = t0 - this.offset;
    this.playing.set(true);
    this.raf = requestAnimationFrame(this.tick);
  }

  pause() {
    if (!this.playing()) return;
    this.offset = this.now();
    this.stopSources();
    this.playing.set(false);
  }

  toggle() {
    if (this.playing()) this.pause(); else void this.play();
  }

  seek(t: number) {
    const was = this.playing();
    if (was) { this.stopSources(); this.playing.set(false); }
    this.offset = Math.max(0, Math.min(t, this.duration()));
    this.position.set(this.offset);
    if (was) void this.play();
  }

  ngOnDestroy() {
    this.halt();
    void this.ctx?.close();
  }

  private halt() {
    this.stopSources();
    this.playing.set(false);
  }
  private context() {
    return (this.ctx ??= new AudioContext());
  }
  private master: GainNode | null = null;
  /** Sortie commune : volume d'ensemble puis limiteur (jamais de saturation, même toutes voix à fond). */
  private output(): GainNode {
    if (!this.master) {
      const ctx = this.context();
      this.master = ctx.createGain();
      const limiter = ctx.createDynamicsCompressor();
      limiter.threshold.value = -3; limiter.knee.value = 3; limiter.ratio.value = 20;
      limiter.attack.value = 0.002; limiter.release.value = 0.12;
      this.master.connect(limiter).connect(ctx.destination);
    }
    return this.master;
  }
  private now() {
    return this.ctx ? Math.max(0, this.ctx.currentTime - this.startedAt) : this.offset;
  }
  private applyGains() {
    if (!this.ctx) return;
    for (const [id, g] of this.gains) {
      const v = this.muted().has(id) ? 0 : (this.volumes()[id] ?? 1);
      g.gain.setTargetAtTime(v, this.ctx.currentTime, 0.03);
    }
  }
  private stopSources() {
    cancelAnimationFrame(this.raf);
    for (const s of this.sources) {
      try { s.stop(); } catch { }
      s.disconnect();
    }
    this.sources = [];
  }
  private tick = () => {
    const t = this.now();
    if (t >= this.duration()) {
      this.stopSources();
      this.playing.set(false);
      this.offset = 0;
      this.position.set(0);
      return;
    }
    this.position.set(t);
    this.raf = requestAnimationFrame(this.tick);
  };
}
