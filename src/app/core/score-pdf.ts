/**
 * Copies notées en PDF, prêtes à imprimer ou à envoyer :
 * - copie nettoyée : les pages de la photo ou du scan, redressées et nettoyées par le moteur (fond blanc, encre noire) ;
 * - partition reconstituée : la partition regravée proprement à partir des notes lues et corrigées
 *   (une portée par voix, nommée, bonne octave, bonne clé, paroles).
 * Tout se fait dans l'appareil (aucun serveur) : marche aussi sur le téléphone, hors ligne.
 */
const A4 = { w: 595.28, h: 841.89 };  // points PDF
const MARGIN = 22;

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('page illisible'));
    img.src = url;
  });
}

export async function cleanCopyPdf(pageUrls: string[], title: string): Promise<Blob> {
  title = title.normalize('NFC');
  const { jsPDF } = await import('jspdf');
  const doc = new jsPDF({ unit: 'pt', format: 'a4', compress: true });
  doc.setProperties({ title: `${title} – copie nettoyée`, creator: 'Pupitre (AIT)' });
  for (const [i, url] of pageUrls.entries()) {
    const img = await loadImage(url);
    if (i) doc.addPage();
    const s = Math.min((A4.w - 2 * MARGIN) / img.naturalWidth, (A4.h - 2 * MARGIN) / img.naturalHeight);
    const w = img.naturalWidth * s, h = img.naturalHeight * s;
    doc.addImage(img, 'PNG', (A4.w - w) / 2, (A4.h - h) / 2, w, h, undefined, 'FAST');
  }
  return doc.output('blob');
}

/** Titre du chant et noms des voix (renommées dans l'application) écrits dans la partition avant la gravure. */
function retitle(xml: string, title: string, names: string[]): string {
  const doc = new DOMParser().parseFromString(xml, 'application/xml');
  const root = doc.documentElement;
  root.querySelectorAll('work, movement-title, credit').forEach((el) => el.remove());
  const mt = doc.createElement('movement-title');
  mt.textContent = title;
  const anchor = root.querySelector('identification') ?? root.querySelector('part-list');
  root.insertBefore(mt, anchor);
  root.querySelectorAll('part-list > score-part').forEach((sp, i) => {
    if (!names[i]) return;
    let pn = sp.querySelector('part-name');
    if (!pn) { pn = doc.createElement('part-name'); sp.prepend(pn); }
    pn.textContent = names[i];
    sp.querySelector('part-abbreviation')?.remove();
  });
  return new XMLSerializer().serializeToString(doc);
}

export async function rebuiltScorePdf(xml: string, title: string, names: string[]): Promise<Blob> {
  // accents décomposés (noms de fichiers du Mac : « e » + accent) : le PDF ne sait écrire que la forme composée
  title = title.normalize('NFC');
  names = names.map((n) => n.normalize('NFC'));
  const mod: any = await import('opensheetmusicdisplay');
  const OpenSheetMusicDisplay = mod.OpenSheetMusicDisplay ?? mod.default?.OpenSheetMusicDisplay ?? mod.default;
  const host = document.createElement('div');
  // hors de l'écran mais rendu (taille fixe : la mise en page A4 en dépend)
  host.style.cssText = 'position:fixed;left:-12000px;top:0;width:1100px;background:#fff;';
  document.body.append(host);
  try {
    const osmd = new OpenSheetMusicDisplay(host, {
      autoResize: false, backend: 'svg', pageFormat: 'A4_P', pageBackgroundColor: '#FFFFFF',
      drawTitle: false, drawSubtitle: false, drawComposer: false, drawCredits: false, drawPartNames: true,
      drawMeasureNumbers: true, drawingParameters: 'default',
    });
    await osmd.load(retitle(xml, title, names));
    osmd.render();
    const pages = Array.from(host.querySelectorAll('svg')) as SVGSVGElement[];
    if (!pages.length) throw new Error('partition vide');
    const { jsPDF } = await import('jspdf');
    await import('svg2pdf.js');
    const doc = new jsPDF({ unit: 'pt', format: 'a4', compress: true });
    doc.setProperties({ title: `${title} – partition reconstituée`, creator: 'Pupitre (AIT)' });
    // titre écrit par le PDF lui-même (accents garantis), la partition en dessous, à l'échelle de la page
    const TITLE = 54;
    for (const [i, svg] of pages.entries()) {
      if (i) doc.addPage();
      const top = i === 0 ? TITLE : 14;
      if (i === 0) {
        doc.setFont('times', 'bold');
        doc.setFontSize(19);
        doc.text(doc.splitTextToSize(title, A4.w - 80)[0] ?? title, A4.w / 2, 40, { align: 'center' });
      }
      const sw = Number(svg.getAttribute('width')) || 1100, sh = Number(svg.getAttribute('height')) || 1556;
      const k = Math.min(A4.w / sw, (A4.h - top) / sh);
      await (doc as any).svg(svg, { x: (A4.w - sw * k) / 2, y: top, width: sw * k, height: sh * k });
    }
    doc.setFont('times', 'normal');
    doc.setFontSize(8);
    doc.setTextColor(120);
    for (let p = 1; p <= doc.getNumberOfPages(); p++) {
      doc.setPage(p);
      doc.text(`Reconstituée par Pupitre (AIT) – page ${p}/${doc.getNumberOfPages()}`, A4.w / 2, A4.h - 14, { align: 'center' });
    }
    return doc.output('blob');
  } finally {
    host.remove();
  }
}
