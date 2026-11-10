// Same-sound church-term correction for recognized captions (runs in the browser; no server, no model).
// A window of the caption is replaced by a term only when every heard character's most common toned pinyin
// matches the term's reading
// (e.g. 以服所書 → 以弗所書, 生命毒精 → 生命讀經, 詔會 → 召會). Exact occurrences of any term are protected,
// longer terms win, and replaced text is never processed again.

import {DEFAULT_TERMS} from './church-terms.js';
export {DEFAULT_TERMS};

const MIN_LENGTH = 2;
let readings = null;

/** Load the generated data ({PINYIN, TERMS, COMMON, PROTECT} from pinyin-zh.js). */
export function loadPinyin({PINYIN, TERMS = {}, COMMON = '', PROTECT = []}) {
  const primary = new Map();
  for (const [syllable, chars] of Object.entries(PINYIN)) for (const char of chars) primary.set(char, syllable);
  readings = {primary, terms: new Map(Object.entries(TERMS).map(([t, r]) => [t, r.map(list => new Set(list))])),
    common: new Set([...(COMMON ? COMMON.split('|') : []), ...PROTECT])};
  return readings;
}

export const pinyinReady = () => readings !== null;

// Accepted readings for each char of a term: precomputed for built-in terms (重生＝chong2, 調和＝tiao2),
// otherwise only each char's most common reading (strict) for terms the host adds.
function termReadings(term) {
  const key = term.join('');
  if (readings.terms.has(key)) return readings.terms.get(key);
  const list = term.map(c => readings.primary.get(c));
  return list.every(Boolean) ? list.map(s => new Set([s])) : null;
}

/** Glossary lines without "=" are extra same-sound terms; "a=b" lines stay exact replacements. */
export function parseTerms(value) {
  return value.split('\n').map(line => line.trim()).filter(line => line && !line.includes('=') && Array.from(line).length >= MIN_LENGTH);
}

/**
 * Replace same-sound misrecognitions of known terms. Returns {text, changes:[{from,to,index}]}.
 * Without the pinyin table loaded the text is returned unchanged.
 */
export function phoneticCorrect(text, terms = DEFAULT_TERMS) {
  if (!readings || !text) return {text, changes: []};
  const chars = Array.from(text);
  const list = [...new Set(terms)].map(term => Array.from(term)).filter(term => term.length >= MIN_LENGTH)
    .sort((a, b) => b.length - a.length);
  const locked = new Array(chars.length).fill(false);
  // Protect exact occurrences first so a correct term is never rewritten into another term.
  for (const term of list) {
    for (let i = 0; i + term.length <= chars.length; i++) {
      if (term.every((c, k) => chars[i + k] === c)) for (let k = 0; k < term.length; k++) locked[i + k] = true;
    }
  }
  const changes = [], common = readings.common;
  for (const term of list) {
    const accepted = termReadings(term);
    if (!accepted) continue;
    for (let i = 0; i + term.length <= chars.length; i++) {
      let differs = false, ok = true;
      for (let k = 0; k < term.length; k++) {
        const c = chars[i + k];
        if (locked[i + k] || (c !== term[k] && !accepted[k].has(readings.primary.get(c)))) { ok = false; break; }
        if (c !== term[k]) differs = true;
      }
      if (!ok || !differs) continue;
      const from = chars.slice(i, i + term.length).join(''), end = i + term.length;
      // Refuse when the heard text is itself a common word (戒嚴、呻吟), or when it forms a common word with
      // the neighbouring char that the correction would break (約伯「繼續」、利未「祭司」).
      const prev = i > 0 ? chars[i - 1] : '', next = end < chars.length ? chars[end] : '';
      if (common.has(from)) continue;
      if (prev && common.has(prev + chars[i]) && !common.has(prev + term[0])) continue;
      if (next && common.has(chars[end - 1] + next) && !common.has(term[term.length - 1] + next)) continue;
      for (let k = 0; k < term.length; k++) { chars[i + k] = term[k]; locked[i + k] = true; }
      changes.push({from, to: term.join(''), index: i});
    }
  }
  return {text: chars.join(''), changes};
}
