// Recovery Version verses for verse alignment (spec-large-meeting.md M2). The text lives in a private R2 bucket
// (binding SCRIPTURE), one object per chapter, written by scripts/upload_scripture.py:
//   rv/<book number 01–66>/<chapter 001–150>.json = {"book": "弗", "chapter": 1, "verses": {"1": "…", …}}
// Only a room's host may read it (checked by the room's Durable Object), a few verses at a time; it is never cached.
import {BOOK_ABBREVIATIONS, CHAPTERS} from '../public/bible-abbreviations.js';

export const MAX_REFS = 80;          // references per request
export const MAX_VERSES = 300;       // verses per request (a long outline cites about 100)
export const MAX_RANGE = 60;         // verses in one range (詩一一九 has 176: ask in parts)
const books = [...BOOK_ABBREVIATIONS].sort((a, b) => b.length - a.length).join('|');
const REF = new RegExp(`^(${books})(\\d{1,3}):(\\d{1,3})(?:[-~～](\\d{1,3}))?$`);

export const chapterKey = (book, chapter) =>
  `rv/${String(BOOK_ABBREVIATIONS.indexOf(book) + 1).padStart(2, '0')}/${String(chapter).padStart(3, '0')}.json`;

/** '弗1:23,約14:6-7' → {refs: [{book, chapter, from, to}]} or {error}. */
export function parseVerseRefs(value) {
  const pieces = String(value || '').split(',').map(piece => piece.trim()).filter(Boolean);
  if (!pieces.length) return {error: '沒有指定經節。'};
  if (pieces.length > MAX_REFS) return {error: `一次最多 ${MAX_REFS} 處經節。`};
  const refs = [];
  let total = 0;
  for (const piece of pieces) {
    const match = piece.match(REF);
    if (!match) return {error: `經節格式不正確：${piece.slice(0, 20)}`};
    const book = match[1], chapter = Number(match[2]), from = Number(match[3]), to = Number(match[4] || match[3]);
    if (chapter < 1 || chapter > CHAPTERS[BOOK_ABBREVIATIONS.indexOf(book)] || from < 1 || to < from || to - from >= MAX_RANGE) {
      return {error: `經節不存在：${piece.slice(0, 20)}`};
    }
    total += to - from + 1;
    if (total > MAX_VERSES) return {error: `一次最多 ${MAX_VERSES} 節。`};
    refs.push({book, chapter, from, to});
  }
  return {refs};
}

/**
 * readVerses(refs, load) → {verses: [{ref, book, chapter, verse, text}], missing: [ref]}
 * load(key) returns the chapter object or null; each chapter is loaded once.
 */
export async function readVerses(refs, load) {
  const chapters = new Map();
  for (const {book, chapter} of refs) {
    const key = chapterKey(book, chapter);
    if (!chapters.has(key)) chapters.set(key, load(key));
  }
  const verses = [], missing = [], seen = new Set();
  for (const {book, chapter, from, to} of refs) {
    const data = await chapters.get(chapterKey(book, chapter));
    for (let verse = from; verse <= to; verse++) {
      const ref = `${book}${chapter}:${verse}`;
      if (seen.has(ref)) continue;
      seen.add(ref);
      const text = data?.verses?.[String(verse)];
      if (typeof text === 'string') verses.push({ref, book, chapter, verse, text});
      else missing.push(ref);
    }
  }
  return {verses, missing};
}
