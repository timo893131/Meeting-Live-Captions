// Read an outline PDF in the host's browser (nothing is uploaded). Text PDFs give their exact text. Pages without a
// text layer (scans) are read with tesseract.js (Traditional Chinese, all files served by this site): slower and
// not measured against the Colab Google Drive OCR (notebooks/outline_ocr.ipynb, 0.27% on the TS26TRN sample).
// pdf.js and tesseract.js are loaded only when a PDF (or a scanned one) is picked.
// The cleaning mirrors scripts/outline_pdf_to_md.py: headers/footers and page numbers that repeat at the top or
// bottom of many pages are dropped, and 「第一篇(續)」 continuation headers are not new messages.

const PDFJS = '/vendor/pdfjs/', TESSERACT = '/vendor/tesseract/';
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

const BOOKS = '創|出|利|民|申|書|士|得|撒上|撒下|王上|王下|代上|代下|拉|尼|斯|伯|詩|箴|傳|歌|賽|耶|哀|結|但|何|珥|摩|俄|拿|彌|鴻|哈|番|該|亞|瑪|太|可|路|約|徒|羅|林前|林後|加|弗|腓|西|帖前|帖後|提前|提後|多|門|來|雅|彼前|彼後|約壹|約貳|約參|猶|啟'
  .split('|').sort((a, b) => b.length - a.length).join('|');
const OCR_CHAPTER = new RegExp(`(${BOOKS})([-+])(?=[\\d一二三四五六七八九十])`, 'g');

const DASH_AS_ONE = new RegExp(`(?<=[\\u4e00-\\u9fff])一(?=(?:${BOOKS})[一二三四五六七八九十百]+\\d)`, 'g');
const MARKER_HEAD = /^\s*([壹貳參叁肆伍陸柒捌玖拾]+|[一二三四五六七八九十]+|[（(]\s*[一二三四五六七八九十\d]+\s*[)）]|\d{1,2}|[a-z])\s+(?=\S)/;

/**
 * OCR text fixes (tesseract puts spaces between Chinese chars and digits, and adds stray ” after markers), then as in
 * scripts/outline_pdf_to_md.py: 約壹-1 → 約壹一1, 約+28 → 約十28, a lone 「-」 line is the marker 一, and a dash read
 * as 一 before a verse reference (之子一創二一3 → 之子—創二一3). Outlines quote with 『』「」, so ” “ are noise.
 * An outline marker keeps its space only when OCR saw one (「壹 以撒…」, not 「三一神…」).
 */
export function fixOcrLine(line) {
  let text = line.replace(/[∼〜˜]/g, '～').replace(/啓/g, '啟').replace(/[”“"]/g, ' ');
  const marker = text.match(MARKER_HEAD);
  if (marker) text = text.slice(marker[0].length);
  text = text.replace(/(?<=[^A-Za-z\s])[ \t\u3000]+(?=[^A-Za-z\s])/g, '').replace(/[ \t\u3000]+/g, ' ').trim();
  if (!marker && (text === '-' || text === '－')) return '一';
  text = text.replace(OCR_CHAPTER, (_m, book, sign) => book + (sign === '-' ? '一' : '十')).replace(DASH_AS_ONE, '—');
  // 「信徒(一) 第一篇」: the parsers need the space between a series name and 第X篇.
  text = text.replace(/^(\S{1,12}?[)）])(第[一二三四五六七八九十百\d]+篇)/, '$1 $2');
  return marker ? `${marker[1].replace(/\s+/g, '')} ${text}` : text;
}

let pdfjs = null, tesseract = null;
async function loadTesseract() {
  tesseract ||= (await import(TESSERACT + 'tesseract.esm.min.js')).default;
  return tesseract;
}

/** OCR one pdf.js page: render about 1600 px wide, recognize Traditional Chinese, return its lines. */
async function ocrPage(page, worker) {
  const base = page.getViewport({scale: 1});
  const viewport = page.getViewport({scale: Math.min(3, 1600 / base.width)});
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(viewport.width); canvas.height = Math.ceil(viewport.height);
  await page.render({canvasContext: canvas.getContext('2d'), viewport}).promise;
  const {data} = await worker.recognize(canvas);
  canvas.width = canvas.height = 0;
  return data.text.split('\n').map(fixOcrLine).filter(Boolean);
}
async function loadPdfjs() {
  if (!pdfjs) {
    pdfjs = await import(PDFJS + 'pdf.min.mjs');
    pdfjs.GlobalWorkerOptions.workerSrc = PDFJS + 'pdf.worker.min.mjs';
  }
  return pdfjs;
}

/**
 * pdfToText(file, {onProgress, ocr, shouldStop}) → {text, pages, emptyPages, ocrPages, stopped}
 * A page with fewer than 20 characters counts as empty (scanned or picture). With ocr: true and most pages empty,
 * the empty pages are read with tesseract.js; onProgress(stage, n, total) with stage 'text' | 'ocr'.
 */
export async function pdfToText(file, {onProgress = () => {}, ocr = false, shouldStop = () => false} = {}) {
  const lib = await loadPdfjs();
  const data = new Uint8Array(await file.arrayBuffer());
  const pdf = await lib.getDocument({data, cMapUrl: PDFJS + 'cmaps/', cMapPacked: true, isEvalSupported: false}).promise;
  const pages = [], empty = [];
  let ocrPages = 0, stopped = false;
  try {
    for (let n = 1; n <= pdf.numPages; n++) {
      const page = await pdf.getPage(n);
      const lines = itemsToLines((await page.getTextContent()).items);
      if (lines.join('').replace(/\s/g, '').length < 20) empty.push(n);
      pages.push(lines);
      onProgress('text', n, pdf.numPages);
    }
    if (ocr && empty.length > pdf.numPages / 2) {
      const {createWorker} = await loadTesseract();
      const worker = await createWorker('chi_tra', 1, {  // 1 = LSTM only
        workerPath: TESSERACT + 'worker.min.js', corePath: TESSERACT, langPath: TESSERACT.replace(/\/$/, ''), gzip: false});
      try {
        for (const n of empty) {
          if (shouldStop()) { stopped = true; break; }
          onProgress('ocr', ocrPages + 1, empty.length);
          pages[n - 1] = await ocrPage(await pdf.getPage(n), worker);
          ocrPages++;
        }
      } finally {
        await worker.terminate();
      }
    }
  } finally {
    await pdf.destroy();
  }
  return {text: cleanPages(stopped ? pages.slice(0, empty[ocrPages] - 1) : pages), pages: pages.length,
    emptyPages: empty.length, ocrPages, stopped};
}
