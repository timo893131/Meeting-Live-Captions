// Verse alignment (spec-large-meeting.md M2): when a caption is the speaker reading a verse of this meeting's
// outline, show the Recovery Version characters instead of the recognizer's same-sound guesses, and mark the verse
// (弗一23). Captions and verses are compared by sound (soundKeys: no tone, Taiwan mergers), with local alignment, so a
// caption like 「我們來讀二十二節，將萬有服在祂的腳下」 only has its reading part changed. Only chars that sound the same
// take the verse's char (話行 for 畫形, 祂 for 他) and its punctuation; a char the speaker said differently (an older
// wording, 「可喜悅」 for 「可喜愛」) stays, and verse words the speaker left out are not added. When unsure, nothing changes.
import {soundKeys} from './phonetic.js';

export const MIN_CHARS = 8;         // at least this many Chinese chars of the caption must match a verse
export const MIN_IDENTITY = 0.8;    // matching sounds / aligned length
// Inside the matched part: no two non-matching chars in a row (the speaker inserted words, 「…無數第二小點他們…」,
// or put a verse in their own words, 「大發熱心」 for 「大發妒忌」), and at most one per ten chars (a short phrase must
// match exactly). Recognizer errors mostly sound the same (話行→畫形) and count as matches. (Life-Study dev set.)
export const MAX_RUN = 1;
export const PER_MISS = 10;
const MATCH = 2, MISMATCH = -1, GAP = -2;
const TRAILING = /^[，。；：！？、」』）)…—]+/;

/** Chapter numbers as the Recovery Version writes references: 一…十, 十四, 二十, 二三, 一一九. */
export function chapterNumeral(n) {
  const digits = '○一二三四五六七八九';
  if (n <= 10) return n === 10 ? '十' : digits[n];
  if (n < 20) return '十' + digits[n - 10];
  if (n < 100) return n % 10 ? digits[Math.floor(n / 10)] + digits[n % 10] : digits[n / 10] + '十';
  return String(n).split('').map(d => digits[Number(d)]).join('');
}
export const verseLabel = (book, chapter, from, to) => `${book}${chapterNumeral(chapter)}${from}${to > from ? '～' + to : ''}`;

/**
 * Verses from /api/verses ([{book, chapter, verse, text}]) → passages of consecutive verses, with sound keys.
 * Call again after the pinyin table is loaded (keys are empty before).
 */
export function preparePassages(verses) {
  const passages = [];
  for (const v of verses) {
    const last = passages[passages.length - 1];
    if (last && last.book === v.book && last.chapter === v.chapter && last.verses[last.verses.length - 1].verse === v.verse - 1) {
      last.verses.push(v);
    } else passages.push({book: v.book, chapter: v.chapter, verses: [v]});
  }
  for (const passage of passages) {
    passage.text = '';
    passage.keys = [];
    for (const v of passage.verses) {
      const offset = passage.text.length;
      for (const {index, key} of soundKeys(v.text)) passage.keys.push({index: offset + index, key, verse: v.verse});
      passage.text += v.text;
    }
  }
  return passages.filter(passage => passage.keys.length);
}

/** Best local alignment of caption keys a with passage keys b → {score, a: [start, end], b: [start, end], matches}. */
function localAlign(a, b) {
  const n = a.length, m = b.length, width = m + 1;
  const score = new Int32Array((n + 1) * width), from = new Uint8Array((n + 1) * width);  // 0 stop, 1 diag, 2 up, 3 left
  let best = 0, bestAt = 0;
  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      const at = i * width + j;
      const diag = score[at - width - 1] + (a[i - 1].key === b[j - 1].key ? MATCH : MISMATCH);
      const up = score[at - width] + GAP, left = score[at - 1] + GAP;
      let value = 0, move = 0;
      if (diag > value) { value = diag; move = 1; }
      if (up > value) { value = up; move = 2; }
      if (left > value) { value = left; move = 3; }
      score[at] = value; from[at] = move;
      if (value > best) { best = value; bestAt = at; }
    }
  }
  if (!best) return null;
  let i = Math.floor(bestAt / width), j = bestAt % width, matches = 0, misses = 0, run = 0, longestRun = 0;
  const endA = i - 1, endB = j - 1, ops = [];
  while (i > 0 && j > 0 && from[i * width + j]) {
    const move = from[i * width + j];
    const hit = move === 1 && a[i - 1].key === b[j - 1].key;
    if (hit) { matches++; run = 0; } else { misses++; longestRun = Math.max(longestRun, ++run); }
    // hit: same sound; miss: both have a char, different sounds; caption / verse: only one side has the char
    ops.push(move === 1 ? {type: hit ? 'hit' : 'miss', ci: i - 1, vi: j - 1} : move === 2 ? {type: 'caption', ci: i - 1} : {type: 'verse', vi: j - 1});
    if (move === 1) { i--; j--; } else if (move === 2) i--; else j--;
  }
  return {score: best, a: [i, endA], b: [j, endB], matches, misses, longestRun, ops: ops.reverse()};
}

/**
 * alignCaption(text, passages) → {text, label} when the caption reads a verse of the outline, else null.
 * Only the aligned part of the caption is replaced (with the verse text and its following punctuation).
 */
export function alignCaption(text, passages, {minChars = MIN_CHARS, minIdentity = MIN_IDENTITY, maxRun = MAX_RUN,
  perMiss = PER_MISS} = {}) {
  const keys = soundKeys(text);
  if (keys.length < minChars || !passages?.length) return null;
  let best = null;
  for (const passage of passages) {
    const found = localAlign(keys, passage.keys);
    if (found && (!best || found.score > best.found.score)) best = {passage, found};
  }
  if (!best) return null;
  const {passage, found} = best;
  const captionLength = found.a[1] - found.a[0] + 1, verseLength = found.b[1] - found.b[0] + 1;
  if (captionLength < minChars || found.matches / Math.max(captionLength, verseLength) < minIdentity) return null;
  if (found.longestRun > maxRun || found.misses > Math.floor(Math.max(captionLength, verseLength) / perMiss)) return null;
  const chars = Array.from(text), verseChars = Array.from(passage.text);
  const start = keys[found.a[0]].index, end = keys[found.a[1]].index;
  // Rebuild the matched part from the caption's chars: same-sound chars become the verse's, with the verse's
  // punctuation between two of them; everything else is the caption's own.
  const out = [];
  let previous = null;
  for (const op of found.ops) {
    if (op.type === 'verse') continue;
    if (previous) {
      const between = previous.type === 'hit' && op.type === 'hit' && op.vi === previous.vi + 1
        ? verseChars.slice(passage.keys[previous.vi].index + 1, passage.keys[op.vi].index)
        : chars.slice(keys[previous.ci].index + 1, keys[op.ci].index);
      out.push(...between);
    }
    out.push(op.type === 'hit' ? verseChars[passage.keys[op.vi].index] : chars[keys[op.ci].index]);
    previous = op;
  }
  // The verse's punctuation after the last matched char replaces the caption's own there.
  let after = end + 1;
  if (previous?.type === 'hit') {
    const trailing = verseChars.slice(passage.keys[previous.vi].index + 1).join('').match(TRAILING);
    if (trailing) {
      out.push(...Array.from(trailing[0]));
      while (after < chars.length && TRAILING.test(chars[after])) after++;
    }
  }
  const replaced = chars.slice(0, start).join('') + out.join('') + chars.slice(after).join('');
  const label = verseLabel(passage.book, passage.chapter, passage.keys[found.b[0]].verse, passage.keys[found.b[1]].verse);
  return {text: replaced, label, identity: Number((found.matches / Math.max(captionLength, verseLength)).toFixed(3))};
}
