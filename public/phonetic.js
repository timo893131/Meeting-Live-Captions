// Same-sound church-term correction for recognized captions (runs in the browser; no server, no model).
// A window of the caption is replaced by a term only when every heard character's most common toned pinyin
// matches the term's reading (terms of 3+ chars allow one char that differs only in tone)
// (option near, books and church terms only: any number of chars may differ in tone or by a Taiwan Mandarin merger such as sh/s, eng/en, n/l,
// as long as at least as many chars are already identical and no such char lies inside an everyday word of the
// caption (nor at its edge, nor in NEAR_PROTECT), and no other term of the same length fits equally:
// 招會 → 召會, 聲言者 → 申言者, but not 生養 → 申言, 祭司的 → 路司得, 亞拉伯 → 亞拿伯 or 雅閣 → 雅各／雅歌)
// (e.g. 以服所書 → 以弗所書, 生命毒精 → 生命讀經, 詔會 → 召會). Exact occurrences of any term are protected,
// longer terms win, and replaced text is never processed again.

import {DEFAULT_TERMS, CORE_DEFAULT_TERMS, BIBLE_NAMES} from './church-terms.js';
export {DEFAULT_TERMS, CORE_DEFAULT_TERMS, BIBLE_NAMES};

const MIN_LENGTH = 2;
// Real words that a near-sound match would break but the word list lacks (only the near option uses them).
// Add words found in the development set or in correct text (term-precision.mjs --near), never from MEET.
export const NEAR_PROTECT = ['亞拉伯'];
// The near option only applies to books and church terms (CORE_DEFAULT_TERMS), never to Bible person/place names
// (in the correct Recovery Version + Life-Study text they caused about 400 false edits: 約二→約珥, 撒迦利雅→撒迦利亞,
// 約雅斤→約雅敬), and not to the church terms that caused ≥5 false edits each there (聖言→申言, 那領→那靈, 四篇→詩篇…).
export const NEAR_SKIP = ['申言', '那靈', '詩篇', '神的形像', '遮覆', '耶穌', '配搭'];
const NEAR_TERMS = new Set(CORE_DEFAULT_TERMS.filter(term => !NEAR_SKIP.includes(term)));
let readings = null;

/** Load the generated data ({PINYIN, TERMS, COMMON, PROTECT} from pinyin-zh.js). */
export function loadPinyin({PINYIN, TERMS = {}, COMMON = '', PROTECT = []}) {
  const primary = new Map();
  for (const [syllable, chars] of Object.entries(PINYIN)) for (const char of chars) primary.set(char, syllable);
  readings = {primary, terms: new Map(Object.entries(TERMS).map(([t, r]) => [t, r.map(list => new Set(list))])),
    common: new Set([...(COMMON ? COMMON.split('|') : []), ...PROTECT])};
  readings.nearCommon = new Set([...readings.common, ...NEAR_PROTECT]);
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

// Mergers common in Taiwan Mandarin (and in "fuzzy pinyin" input methods): zh/z, ch/c, sh/s, n/l, f/h, r/l;
// eng/en, ing/in, ang/an (also iang/ian, uang/uan).
const toneless = syllable => syllable.replace(/\d$/, '');
const INITIAL = /^(zh|ch|sh|[bpmfdtnlgkhjqxrzcsyw])?(.*)$/;
const MERGE_INITIAL = {zh: 'z', ch: 'c', sh: 's', n: 'l', f: 'h', r: 'l'};
const mergedCache = new Map();
function merged(syllable) {
  let key = mergedCache.get(syllable);
  if (key === undefined) {
    const [, initial = '', final] = toneless(syllable).match(INITIAL);
    key = (MERGE_INITIAL[initial] ?? initial) + '|' + final.replace(/(an|en|in)g$/, '$1');
    mergedCache.set(syllable, key);
  }
  return key;
}
// Per term: [Set of toneless syllables, Set of merged keys] for each char (computed once per accepted-readings list).
const looseCache = new WeakMap();
function looseReadings(accepted) {
  let loose = looseCache.get(accepted);
  if (!loose) {
    loose = accepted.map(set => [new Set([...set].map(toneless)), new Set([...set].map(merged))]);
    looseCache.set(accepted, loose);
  }
  return loose;
}
/** Same syllable ignoring tone, or the same after the Taiwan Mandarin mergers (shen/sheng, sa/sha, lan/nan). */
export function soundsNear(a, b) {
  return Boolean(a && b) && (toneless(a) === toneless(b) || merged(a) === merged(b));
}

// True when one of the positions lies inside an everyday word (2–4 chars) of the caption: 祭司的 → 路司得 breaks 祭司.
function insideCommonWord(chars, positions, common) {
  for (const p of positions) {
    for (let size = 2; size <= 4; size++) {
      for (let i = Math.max(0, p - size + 1); i <= p && i + size <= chars.length; i++) {
        if (common.has(chars.slice(i, i + size).join(''))) return true;
      }
    }
  }
  return false;
}

/**
 * Replace same-sound misrecognitions of known terms. Returns {text, changes:[{from,to,index}]}.
 * Without the pinyin table loaded the text is returned unchanged. {near: true} also accepts near sounds (see top).
 */
export function phoneticCorrect(text, terms = DEFAULT_TERMS, {near = false} = {}) {
  if (!readings || !text) return {text, changes: []};
  const chars = Array.from(text);
  const list = [...new Set(terms)].map(term => Array.from(term)).filter(term => term.length >= MIN_LENGTH)
    .sort((a, b) => b.length - a.length);
  const locked = new Array(chars.length).fill(false);
  const lockExact = term => {
    for (let i = 0; i + term.length <= chars.length; i++) {
      if (term.every((c, k) => chars[i + k] === c)) for (let k = 0; k < term.length; k++) locked[i + k] = true;
    }
  };
  // Longest terms first. Before each length, lock exact occurrences of the terms of that length, so a correct
  // term is never rewritten into another term of the same or shorter length, while a longer same-sound term may
  // still cover a shorter exact one (約翰三書 → 約翰參書 although 約翰 is itself a term).
  const changes = [], common = readings.common;
  const heardOf = chars.map(c => readings.primary.get(c));
  // Window starts by first char and by its merged sound: a term only visits windows whose first char could match.
  const startsByChar = new Map(), startsBySound = new Map();
  const add = (map, key, i) => { const list = map.get(key); if (list) list.push(i); else map.set(key, [i]); };
  chars.forEach((c, i) => { add(startsByChar, c, i); if (heardOf[i]) add(startsBySound, merged(heardOf[i]), i); });
  const starts = (term, loose) => {
    const set = new Set(startsByChar.get(term[0]) || []);
    for (const key of loose[0][1]) for (const i of startsBySound.get(key) || []) set.add(i);
    return [...set].sort((a, b) => a - b);
  };
  const nearFits = (other, i) => {
    const accepted = termReadings(other);
    if (!accepted) return false;
    const loose = looseReadings(accepted);
    return other.every((c, k) => chars[i + k] === c ||
      (heardOf[i + k] && !locked[i + k] && loose[k][1].has(merged(heardOf[i + k]))));
  };
  let lockedLength = Infinity;
  for (const term of list) {
    if (term.length < lockedLength) {
      lockedLength = term.length;
      for (const other of list) if (other.length === lockedLength) lockExact(other);
    }
    const accepted = termReadings(term);
    if (!accepted) continue;
    const loose = looseReadings(accepted), nearTerm = near && NEAR_TERMS.has(term.join(''));
    for (const i of starts(term, loose)) {
      if (i + term.length > chars.length) break;
      let differs = false, ok = true;
      let toneSlips = 0;
      const nearChars = [];
      for (let k = 0; k < term.length; k++) {
        const c = chars[i + k], heard = heardOf[i + k];
        if (locked[i + k]) { ok = false; break; }
        if (c !== term[k] && !accepted[k].has(heard)) {
          if (nearTerm && heard && loose[k][1].has(merged(heard))) nearChars.push(i + k);
          // Terms of 3+ chars tolerate one char with the right syllable but another tone (拿厄米 → 拿俄米).
          else if (term.length >= 3 && toneSlips === 0 && heard && loose[k][0].has(toneless(heard))) toneSlips++;
          else { ok = false; break; }
        }
        if (c !== term[k]) differs = true;
      }
      if (!ok || !differs) continue;
      // A near match keeps at least as many identical chars as near ones (招會 → 召會, 聲言者 → 申言者; not 生養 → 申言),
      // changes no char of an everyday word, and is skipped when another term of the same length fits the same
      // window just as well (雅閣 could be 雅各 or 雅歌).
      if (nearChars.length) {
        const same = term.filter((c, k) => chars[i + k] === c).length;
        if (same < nearChars.length || insideCommonWord(chars, nearChars, readings.nearCommon)) continue;
        if (list.some(other => other !== term && other.length === term.length && nearFits(other, i))) continue;
      }
      // A tone-slip match must not swallow an everyday word (是「實際」 is not 士師記).
      if (toneSlips && chars.slice(i, i + term.length).some((c, k, w) => k + 1 < w.length && common.has(c + w[k + 1]))) continue;
      const from = chars.slice(i, i + term.length).join(''), end = i + term.length;
      // Refuse when the heard text is itself a common word (戒嚴、呻吟), or when it forms a common word with
      // the neighbouring char that the correction would break (約伯「繼續」、利未「祭司」).
      const prev = i > 0 ? chars[i - 1] : '', next = end < chars.length ? chars[end] : '';
      if (common.has(from)) continue;
      if (nearChars.length && ((prev && common.has(prev + chars[i])) || (next && common.has(chars[end - 1] + next)))) continue;
      if (prev && common.has(prev + chars[i]) && !common.has(prev + term[0])) continue;
      if (next && common.has(chars[end - 1] + next) && !common.has(term[term.length - 1] + next)) continue;
      for (let k = 0; k < term.length; k++) { chars[i + k] = term[k]; locked[i + k] = true; }
      changes.push({from, to: term.join(''), index: i});
    }
  }
  return {text: chars.join(''), changes};
}
