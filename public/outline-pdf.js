// Read an outline PDF in the host's browser (nothing is uploaded). Text PDFs give their exact text; a scanned PDF
// has no text layer and needs OCR (notebooks/outline_ocr.ipynb). pdf.js is loaded only when a PDF is picked.
// The cleaning mirrors scripts/outline_pdf_to_md.py: headers/footers and page numbers that repeat at the top or
// bottom of many pages are dropped, and 「第一篇(續)」 continuation headers are not new messages.

const PDFJS = '/vendor/pdfjs/';
const PAGE_NUMBER = /^[\s\-—–·]*(?:第\s*)?(?:\d+|[ivxlc]+|[IVXLC]+)\s*(?:頁)?[\s\-—–·]*$/;
const CONTINUED = /第\s*[一二三四五六七八九十百\d]+\s*篇\s*[（(]\s*續\s*[)）]/;
const shape = line => line.replace(/\s+/g, '').replace(/\d+/g, '#');

/** pdf.js text items of one page → lines (top to bottom, left to right). */
export function itemsToLines(items) {
  const rows = [];
  for (const item of items) {
    if (!item.str || !item.str.trim()) continue;
    const [x, y] = [item.transform[4], item.transform[5]], size = Math.abs(item.transform[3]) || 10;
    let row = rows.find(r => Math.abs(r.y - y) <= size * 0.4);
    if (!row) { row = {y, items: []}; rows.push(row); }
    row.items.push({x, end: x + (item.width || 0), size, text: item.str});
  }
  rows.sort((a, b) => b.y - a.y);
  // A visible gap between two pieces is a space (「信徒(一)　第一篇」「壹　以撒…」); PDFs often draw it as a gap, not a character.
  return rows.map(row => row.items.sort((a, b) => a.x - b.x)
    .map((piece, i, all) => (i && piece.x - all[i - 1].end > piece.size * 0.3 ? ' ' : '') + piece.text).join('').replace(/[ \t　]+/g, ' ').trim())
    .filter(Boolean);
}

/** Pages of lines → one text: drop repeated headers/footers, page numbers and continuation headers. */
export function cleanPages(pages) {
  const edge = (lines, i) => i < 2 || i >= lines.length - 2;
  const counts = new Map();
  for (const lines of pages) {
    for (const s of new Set(lines.filter((_, i) => edge(lines, i)).map(shape))) counts.set(s, (counts.get(s) || 0) + 1);
  }
  const repeated = new Set([...counts].filter(([, n]) => pages.length >= 3 && n >= Math.max(3, pages.length * 0.3)).map(([s]) => s));
  const out = [];
  for (const lines of pages) {
    lines.forEach((line, i) => {
      if (edge(lines, i) && (repeated.has(shape(line)) || PAGE_NUMBER.test(line))) return;
      if (CONTINUED.test(line) && line.length <= 20) return;
      out.push(line);
    });
  }
  return out.join('\n');
}

let pdfjs = null;
async function loadPdfjs() {
  if (!pdfjs) {
    pdfjs = await import(PDFJS + 'pdf.min.mjs');
    pdfjs.GlobalWorkerOptions.workerSrc = PDFJS + 'pdf.worker.min.mjs';
  }
  return pdfjs;
}

/**
 * pdfToText(file, {onProgress}) → {text, pages, emptyPages}
 * A page with fewer than 20 characters counts as empty (scanned or picture); when most pages are empty the
 * caller tells the host to convert the file with OCR instead.
 */
export async function pdfToText(file, {onProgress = () => {}} = {}) {
  const lib = await loadPdfjs();
  const data = new Uint8Array(await file.arrayBuffer());
  const pdf = await lib.getDocument({data, cMapUrl: PDFJS + 'cmaps/', cMapPacked: true, isEvalSupported: false}).promise;
  const pages = [];
  let emptyPages = 0;
  try {
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n);
      const lines = itemsToLines((await page.getTextContent()).items);
      if (lines.join('').replace(/\s/g, '').length < 20) emptyPages++;
      pages.push(lines);
      onProgress(n, pdf.numPages);
    }
  } finally {
    await pdf.destroy();
  }
  return {text: cleanPages(pages), pages: pages.length, emptyPages};
}
