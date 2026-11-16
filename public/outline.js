// The message outline a host pastes before a meeting (spec-large-meeting.md M1). It stays in the host's browser:
// never sent to the server or to viewers. parseOutline() reads the title, points, verse references and this
// meeting's terms; the terms join the strict same-sound correction (no near sounds) next to the built-in terms.
// Accepts the Markdown from scripts/outline_pdf_to_md.py / outline_ocr.py or plain text copied from a PDF.
import {BOOK_ABBREVIATIONS, CHAPTERS, SINGLE_CHAPTER} from './bible-abbreviations.js';
import {BIBLE_BOOKS} from './church-terms.js';

const CN_NUM = '一二三四五六七八九十百○〇';
const books = [...BOOK_ABBREVIATIONS].sort((a, b) => b.length - a.length).join('|');
const single = [...SINGLE_CHAPTER].sort((a, b) => b.length - a.length).join('|');
const VERSE = String.raw`\d+(?:[上下])?(?:[～~\-－–]\d+(?:[上下])?)?`;
// 弗一23、約十四6～7、林前十二12、詩二三1、門16, continued by 「，三17」「，18」.
const REF = new RegExp(String.raw`(?:(?:${books})[${CN_NUM}]+${VERSE}|(?:${single})${VERSE})(?:[，,、](?:[${CN_NUM}]+)?${VERSE})*`, 'g');
const PIECE = new RegExp(String.raw`^(${books})?([${CN_NUM}]+)?(\d+)[上下]?(?:[～~\-－–](\d+))?`);
// Quoted verses in an outline printed with its verses: 「太5:1 但祂看見…」.
const QUOTE = new RegExp(String.raw`^(${books})(\d+):(\d+)(?:[～~\-－–](\d+))?(?:\s+|$)`);
const MESSAGE = /第\s*[一二三四五六七八九十百\d]+\s*篇[\s　]*(?:[（(]\s*續\s*[)）])?[\s　]*(.*)$/;
const SCRIPTURE = /^(?:讀經|读经)\s*[:：]\s*(.*)$/;
const MARKER = /^(?:[壹貳參叁肆伍陸柒捌玖拾]+|[一二三四五六七八九十]+|[（(][一二三四五六七八九十\d０-９a-zａ-ｚ]+[)）]|\d{1,2}|[a-z])(?:[\s　、.．]+|$)/;
const DIGITS = {'○': 0, '〇': 0, 一: 1, 二: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9};
// Particles, pronouns and common single-char verbs: a term never contains one (「的生命」「基督是」「說到神」 are not terms).
const EDGE = new Set(Array.from('的了是在和與及並而就也都要我你他她祂牠們這那其為着著裏裡之所以使把被從對於乃即有無不能得地個些或且但若因如此向給讓叫將已還又再更最很甚麼嗎呢吧一二三四五六七八九十說到來去看纔才可會上中下'));
export const MAX_TERMS = 300;

/** 二三 = 23, 十四 = 14, 二十 = 20, 一百一十九 = 119, 一一九 = 119. */
export function chineseNumber(text) {
  if (!/[十百]/.test(text)) return Array.from(text).reduce((value, c) => value * 10 + DIGITS[c], 0);
  let value = 0, current = 0;
  for (const c of text) {
    if (c === '百') { value += (current || 1) * 100; current = 0; }
    else if (c === '十') { value += (current || 1) * 10; current = 0; }
    else current = current * 10 + DIGITS[c];
  }
  return value + current;
}

/** Verse references in outline style (弗一23，三17～19) → [{book, chapter, verse, to, text}]; impossible chapters are skipped. */
export function parseReferences(text) {
  const refs = [];
  for (const match of String(text).matchAll(REF)) {
    let book = null, chapter = null;
    for (const piece of match[0].split(/[，,、]/)) {
      const parsed = piece.match(PIECE);
      if (!parsed) continue;
      book = parsed[1] || book;
      if (parsed[2]) chapter = chineseNumber(parsed[2]);
      else if (SINGLE_CHAPTER.has(book)) chapter = 1;
      const verse = Number(parsed[3]), to = parsed[4] ? Number(parsed[4]) : verse;
      const index = BOOK_ABBREVIATIONS.indexOf(book);
      if (index < 0 || !chapter || chapter > CHAPTERS[index] || verse < 1 || to < verse) continue;
      refs.push({book, chapter, verse, to, text: piece});
    }
  }
  return refs;
}

const stripMarkdown = line => line.replace(/^#{1,6}\s*/, '').replace(/^\s*[-*+]\s+/, '').replace(/[ \t　]+/g, ' ').trim();

/** Longest-match split with the dictionary; runs of 2+ single chars it does not know, trimmed of particles. */
export function unknownRuns(run, dictionary) {
  const chars = Array.from(run), tokens = [];
  for (let i = 0; i < chars.length;) {
    let length = 1;
    for (let n = Math.min(6, chars.length - i); n >= 2; n--) if (dictionary.has(chars.slice(i, i + n).join(''))) { length = n; break; }
    tokens.push(chars.slice(i, i + length).join('')); i += length;
  }
  const runs = [];
  let current = [];
  const flush = () => {
    while (current.length && EDGE.has(current[0])) current.shift();
    while (current.length && EDGE.has(current[current.length - 1])) current.pop();
    if (current.length >= 2 && current.length <= 6) runs.push(current.join(''));
    current = [];
  };
  // A particle or common single-char word always ends a run (基督「對」彼列、彼列「是」撒但).
  for (const token of tokens) { if (Array.from(token).length === 1 && !EDGE.has(token)) current.push(token); else flush(); }
  flush();
  return runs;
}

/**
 * A file with several messages (the converter's whole-training Markdown with one 「## 第X篇　篇題」 section per
 * message, or the text of a whole-training PDF) → [{label, text}]; a file with one message → one part.
 */
export function splitMessages(text) {
  const lines = String(text || '').split(/\r?\n/), parts = [];
  let current = null;
  for (const line of lines) {
    // 「## 第一篇　篇題」 (converter Markdown) or plain text from a PDF: 「第一篇 篇題」「信徒(一) 第一篇」 (title on the next line).
    const heading = line.match(/^##\s+(第\s*[一二三四五六七八九十百\d]+\s*篇.*)$/) ||
      line.match(/^(?:[^，。；：,;:\s]{1,12}[\s　]+)?(第\s*[一二三四五六七八九十百\d]+\s*篇(?:[\s　]+[^（(].{0,40})?)$/);
    if (heading) { current = {label: heading[1].trim(), lines: [line]}; parts.push(current); continue; }
    if (!current) continue;
    current.lines.push(line);
    if (/篇$/.test(current.label) && line.trim()) current.label += '　' + line.trim();  // title on its own line
  }
  if (parts.length < 2) return [{label: '', text: String(text || '').trim()}];
  return parts.map(part => ({label: part.label, text: part.lines.join('\n').trim()}));
}

/** Same terms on every call for the same text (the host may paste a long outline: parse once, reuse). */
let cache = {key: null, value: null};

/**
 * parseOutline(text, {common, known}) → {title, points, refs, quotes, terms, known}
 *   common: Set of everyday words (pinyin-zh.js COMMON) never used as terms.
 *   known: built-in terms; those found in the outline are listed in `known` (they are corrected anyway).
 *   known: built-in terms found in the outline and the books its references cite; correctionOptions() lets
 *   only these use near sounds (tone, Taiwan mergers) for this meeting.
 *   terms: this meeting's new terms — words the everyday dictionary does not know (names, places, rare church
 *   words) that occur at least minCount times: each line is split into dictionary words (longest match first);
 *   a run of 2–6 leftover single chars, trimmed of particles at its edges, is a candidate (「彼列」「麥基洗德」).
 *   A single occurrence is too often a run of everyday single-char words (「節是說到神」), except a 3+ char word in
 *   the title (often the message's main name).
 */
export function parseOutline(text, {common = new Set(), known = [], minCount = 2} = {}) {
  const key = `${minCount}\u0000${known.length}\u0000${common.size}\u0000${text}`;
  if (cache.key === key) return cache.value;
  let title = '';
  const points = [], scripture = [], quotes = [];
  // Full-width digits (拉一１～４) as plain digits, so verse references parse.
  const plain = String(text || '').replace(/[０-９]/g, d => String.fromCharCode(d.charCodeAt(0) - 0xFEE0));
  for (const raw of plain.split(/\r?\n/)) {
    if (/^#{3,6}\s/.test(raw.trim())) continue;  // section headings the converter adds (### 引用經文…)
    const line = stripMarkdown(raw);
    if (!line) continue;
    const message = line.match(MESSAGE);
    if (message && line.indexOf('第') <= 20 && !/[，。；]/.test(line.slice(0, line.indexOf('第')))) {
      if (!title && message[1]) title = message[1].trim();
      continue;
    }
    const verses = line.match(SCRIPTURE);
    if (verses) { scripture.push(verses[1]); continue; }
    const quote = line.match(QUOTE);
    if (quote) {
      quotes.push({ref: `${quote[1]}${quote[2]}:${quote[3]}${quote[4] ? '～' + quote[4] : ''}`, text: line.slice(quote[0].length).trim()});
      continue;
    }
    if (!title && !MARKER.test(line) && !parseReferences(line).length && Array.from(line).length <= 40) { title = line; continue; }
    points.push(line.replace(MARKER, ''));
  }
  const refs = parseReferences([...scripture, title, ...points].join('\n'));
  const knownSet = new Set(known);
  const dictionary = {has: word => common.has(word) || knownSet.has(word)};
  const counts = new Map();
  const inTitle = new Set();
  [title, ...points].forEach((line, index) => {
    for (const run of line.replace(new RegExp(REF.source, 'g'), ' ').match(/[\u4e00-\u9fff]+/g) || []) {
      for (const term of unknownRuns(run, dictionary)) {
        counts.set(term, (counts.get(term) || 0) + 1);
        if (index === 0) inTitle.add(term);
      }
    }
  });
  // Built-in terms in the outline, plus the books its verse references cite (弗一23 → 以弗所書).
  const cited = refs.map(ref => BIBLE_BOOKS[BOOK_ABBREVIATIONS.indexOf(ref.book)]);
  const knownFound = [...new Set([...[...knownSet].filter(term => [title, ...points].some(line => line.includes(term))),
    ...cited.filter(book => knownSet.has(book))])];
  // A word of 3+ chars in the title counts even once (所羅巴伯 in 「被擄之人在所羅巴伯的君王領導之下歸回」).
  const picked = [...counts].filter(([term, n]) => (n >= minCount || (inTitle.has(term) && Array.from(term).length >= 3))
    && !knownSet.has(term))
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : 1)).slice(0, MAX_TERMS);
  const value = {title, points, refs, quotes, terms: picked.map(([term]) => term), known: knownFound};
  cache = {key, value};
  return value;
}

/**
 * How the captions use a parsed outline (app.js and scripts/apply-corrections.mjs share this):
 * extra strict same-sound terms, and the terms allowed near sounds — only built-in terms this outline uses,
 * never those that caused many false edits in correct text (NEAR_SKIP).
 */
export function correctionOptions(parsed, {nearSkip = []} = {}) {
  if (!parsed) return {terms: [], nearTerms: null};
  const skip = new Set(nearSkip);
  return {terms: parsed.terms, nearTerms: new Set(parsed.known.filter(term => !skip.has(term)))};
}
