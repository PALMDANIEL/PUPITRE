import { Component, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ADMIN_SERVER, AitStore, Overview, ServerEvent, ServerItem } from '../../core/ait';
import { frDateShort } from '../../core/dates';

const EVENT_LABEL: Record<string, string> = {
  'premiere-connexion': 'Première connexion', connexion: 'Connexion', lecture: 'Photo lue',
  desactivation: 'Désactivé', reactivation: 'Réactivé',
};
const SERVER_KEY = 'pupitre-ait-serveur';

/** Tableau de bord AIT : qui est connecté, état des licences et des codes, désactivation à distance. */
@Component({
  selector: 'app-ait-dashboard',
  imports: [FormsModule],
  template: `
    <div class="bar">
      <button class="btn" type="button" (click)="refresh()" [disabled]="loading()">{{ loading() ? 'Chargement…' : 'Actualiser' }}</button>
      <input class="search" type="search" placeholder="Rechercher un client, un numéro…" [(ngModel)]="query" name="q">
    </div>
    @if (error()) { <p class="error banner" role="alert">{{ error() }}</p> }

    @if (stats(); as s) {
      <div class="tiles">
        <div class="tile live"><b>{{ s.en_ligne }}</b><span>en ligne maintenant</span></div>
        <div class="tile"><b>{{ s.licences }}</b><span>licences{{ s.licences_desactivees ? ' · ' + s.licences_desactivees + ' désactivée(s)' : '' }}</span></div>
        <div class="tile"><b>{{ s.codes }}</b><span>codes de chorale{{ s.codes_desactives ? ' · ' + s.codes_desactives + ' désactivé(s)' : '' }}</span></div>
        <div class="tile"><b>{{ s.clients }}</b><span>clients · {{ s.actifs_7j }} actifs sur 7 j</span></div>
        <div class="tile"><b>{{ s.lectures_24h }}</b><span>photos lues en 24 h · {{ s.lectures }} au total</span></div>
      </div>
    }

    @for (g of groups(); track g.client) {
      <section class="glass client">
        <header>
          <h3>{{ g.client }}</h3>
          @if (g.allRevoked) {
            <button type="button" class="act on" (click)="client(g.client, 'active')">Réactiver le client</button>
          } @else {
            <button type="button" class="act off" (click)="client(g.client, 'revoked')">Désactiver le client</button>
          }
        </header>
        <ul>
          @for (i of g.items; track i.id) {
            <li [class.revoked]="i.status === 'revoked'">
              <div class="line">
                <span class="dot" [class.live]="online(i)" [title]="online(i) ? 'En ligne' : ''"></span>
                <b>{{ i.kind === 'licence' ? 'Ordinateur' : 'Code de chorale' }}</b>
                <span class="id">{{ i.id }}</span>
                <span class="pill" [class.ok]="i.status === 'active'" [class.failed]="i.status === 'revoked'">{{ i.status === 'active' ? 'Active' : 'Désactivée' }}</span>
              </div>
              <span class="small">
                {{ seen(i) }}{{ i.machine ? ' · ' + i.machine : '' }}{{ i.os ? ' · ' + i.os : '' }}{{ i.app_version ? ' · v' + i.app_version : '' }}{{ i.kind === 'acces' ? ' · ' + i.uses + ' photo(s) lue(s)' : '' }}
              </span>
              <span class="small">{{ i.issued ? 'du ' + date(i.issued) + ' ' : '' }}{{ i.expires ? 'au ' + date(i.expires) : '· sans date de fin' }}{{ i.reason ? ' · motif : ' + i.reason : '' }}</span>
              @if (i.status === 'active') {
                <button type="button" class="act off" (click)="item(i, 'revoked')">Désactiver</button>
              } @else {
                <button type="button" class="act on" (click)="item(i, 'active')">Réactiver</button>
              }
            </li>
          }
        </ul>
      </section>
    }
    @if (loaded() && !groups().length) { <p class="hint">Aucune licence ni aucun code dans le registre du serveur pour l’instant.</p> }

    @if (events().length) {
      <section class="glass journal">
        <h3>Journal</h3>
        <ul>
          @for (e of events(); track $index) {
            <li><span class="when">{{ when(e.at) }}</span> <b>{{ label(e.kind) }}</b> · {{ e.client ?? e.item_id }}{{ info(e) }}</li>
          }
        </ul>
      </section>
    }

    <details class="server">
      <summary>Serveur d’administration</summary>
      <input [(ngModel)]="server" name="server" (change)="saveServer()" inputmode="url">
    </details>
  `,
  styles: [`
    .bar { display: flex; gap: .6rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
    .search { flex: 1; min-width: 12rem; border-radius: 999px; border: 1px solid var(--hair); background: var(--raised); color: var(--ink); padding: .6rem 1rem; font: inherit; }
    .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .6rem; margin-bottom: 1rem; }
    .tile { padding: .8rem .9rem; border-radius: 14px; background: var(--surface); border: 1px solid var(--hair); display: grid; gap: .15rem; }
    .tile b { font: 700 1.6rem/1 var(--serif); }
    .tile span { font-size: .78rem; color: var(--ink-soft); }
    .tile.live b { color: var(--ok); }
    .client { padding: 1rem 1.1rem; margin-bottom: .8rem; }
    .client header { display: flex; justify-content: space-between; align-items: center; gap: .6rem; margin-bottom: .5rem; }
    .client h3 { font-size: 1.05rem; }
    ul { list-style: none; margin: 0; padding: 0; display: grid; gap: .6rem; }
    li { display: grid; gap: .2rem; padding-top: .6rem; border-top: 1px solid var(--hair); justify-items: start; }
    li.revoked { opacity: .75; }
    .line { display: flex; align-items: center; gap: .45rem; flex-wrap: wrap; }
    .id { font: 12px ui-monospace, 'SF Mono', Consolas, monospace; color: var(--ink-soft); }
    .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--rule); }
    .dot.live { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
    .small { font-size: .8rem; color: var(--ink-soft); }
    .act { border-radius: 999px; padding: .3rem .8rem; font-size: .8rem; font-weight: 700; cursor: pointer; background: none; }
    .act.off { border: 1px solid color-mix(in srgb, var(--danger) 60%, transparent); color: var(--danger); }
    .act.on { border: 1px solid color-mix(in srgb, var(--ok) 60%, transparent); color: var(--ok); }
    .journal { padding: 1rem 1.1rem; margin-top: 1rem; }
    .journal h3 { font-size: 1.05rem; margin-bottom: .5rem; }
    .journal li { border: 0; padding: 0; font-size: .82rem; display: block; }
    .when { color: var(--ink-soft); font-variant-numeric: tabular-nums; }
    .server { margin-top: 1rem; font-size: .82rem; color: var(--ink-soft); }
    .server input { width: 100%; margin-top: .4rem; border-radius: 10px; border: 1px solid var(--hair); background: var(--raised); color: var(--ink); padding: .5rem .7rem; font: inherit; }
    .hint { color: var(--ink-soft); }
    .banner { padding: .7rem 1rem; border-radius: 12px; border: 1px solid var(--hair); background: var(--raised); margin-bottom: 1rem; }
  `],
})
export class AitDashboard {
  private readonly ait = inject(AitStore);
  protected readonly stats = signal<Overview | null>(null);
  protected readonly items = signal<ServerItem[]>([]);
  protected readonly events = signal<ServerEvent[]>([]);
  protected readonly loading = signal(false);
  protected readonly loaded = signal(false);
  protected readonly error = signal<string | null>(null);
  protected readonly date = frDateShort;
  protected query = '';
  protected server = (() => { try { return localStorage.getItem(SERVER_KEY) || ADMIN_SERVER; } catch { return ADMIN_SERVER; } })();
  private readonly q = signal('');

  protected readonly groups = computed(() => {
    const q = this.q().toLowerCase();
    const map = new Map<string, ServerItem[]>();
    for (const i of this.items()) {
      if (q && !`${i.client} ${i.id} ${i.machine ?? ''} ${i.contact ?? ''}`.toLowerCase().includes(q)) continue;
      map.set(i.client, [...(map.get(i.client) ?? []), i]);
    }
    return [...map.entries()].map(([client, items]) => ({ client, items, allRevoked: items.every((i) => i.status === 'revoked') }));
  });

  constructor() { void this.refresh(); }

  protected saveServer() { try { localStorage.setItem(SERVER_KEY, this.server.trim().replace(/\/+$/, '')); } catch { /* idem */ } }
  private get base() { return this.server.trim().replace(/\/+$/, '') || ADMIN_SERVER; }

  protected async refresh() {
    this.q.set(this.query);
    this.loading.set(true);
    this.error.set(null);
    try {
      await this.ait.admin('/enregistrer', { method: 'POST', body: { items: this.ait.registry().map((i) => i.text) } }, this.base);
      const [stats, items, events] = await Promise.all([
        this.ait.admin<Overview>('/apercu', {}, this.base),
        this.ait.admin<ServerItem[]>('/elements', {}, this.base),
        this.ait.admin<ServerEvent[]>('/evenements?limite=60', {}, this.base),
      ]);
      this.stats.set(stats); this.items.set(items); this.events.set(events);
      this.loaded.set(true);
    } catch (e) {
      this.error.set((e as Error).message);
    } finally {
      this.loading.set(false);
    }
  }

  protected async item(i: ServerItem, status: 'active' | 'revoked') {
    const reason = status === 'revoked' ? prompt(`Désactiver ${i.id} (${i.client}) ? Motif (facultatif) :`, '') : '';
    if (reason === null) return;
    try { await this.ait.admin(`/elements/${encodeURIComponent(i.id)}/statut`, { method: 'POST', body: { status, reason } }, this.base); await this.refresh(); }
    catch (e) { this.error.set((e as Error).message); }
  }

  protected async client(client: string, status: 'active' | 'revoked') {
    const reason = status === 'revoked' ? prompt(`Désactiver TOUTES les licences et tous les codes de « ${client} » ? Motif (facultatif) :`, '') : '';
    if (reason === null) return;
    try { await this.ait.admin('/clients/statut', { method: 'POST', body: { client, status, reason } }, this.base); await this.refresh(); }
    catch (e) { this.error.set((e as Error).message); }
  }

  protected online(i: ServerItem) { return !!i.last_seen && Date.now() - Date.parse(i.last_seen) < 15 * 60_000; }
  protected seen(i: ServerItem) {
    if (!i.last_seen) return 'Jamais connecté';
    const min = Math.round((Date.now() - Date.parse(i.last_seen)) / 60_000);
    if (min < 15) return 'En ligne';
    if (min < 60) return `Vu il y a ${min} min`;
    if (min < 48 * 60) return `Vu il y a ${Math.round(min / 60)} h`;
    return `Vu il y a ${Math.round(min / 1440)} jours`;
  }
  protected when(at: string) { return new Date(at).toLocaleString('fr-FR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); }
  protected label(kind: string) { return EVENT_LABEL[kind] ?? kind; }
  protected info(e: ServerEvent) {
    const d = e.detail ?? {};
    return `${d['title'] ? ` · « ${d['title']} »` : ''}${d['reason'] ? ` · ${d['reason']}` : ''}`;
  }
}
