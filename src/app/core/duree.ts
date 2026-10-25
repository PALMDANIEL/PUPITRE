/** Durées des licences et des codes d'accès : « 1a », « 6m », « 30j » ou « illimitee » (partagé par l'outil Mac et le téléphone). */
export function addDuration(start: string, duree: string): string | null {
  if (/^illimit/i.test(duree)) return null;
  const m = /^(\d+)\s*([ajm])/i.exec(duree);
  if (!m) throw new Error('Durée invalide. Exemples : 1a (un an), 6m (six mois), 30j (trente jours), illimitee.');
  const n = Number(m[1]);
  const d = new Date(`${start}T12:00:00Z`);
  const unit = m[2].toLowerCase();
  if (unit === 'a') d.setUTCFullYear(d.getUTCFullYear() + n);
  if (unit === 'm') d.setUTCMonth(d.getUTCMonth() + n);
  if (unit === 'j') d.setUTCDate(d.getUTCDate() + n);
  d.setUTCDate(d.getUTCDate() - 1); // une licence d'un an émise le 24/10 vaut jusqu'au 23/10 inclus
  return d.toISOString().slice(0, 10);
}
