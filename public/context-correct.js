// Context correction (EXPERIMENT, not loaded by the website): helpers shared by the evaluation driver
// (scripts/context-experiment.mjs) and, only if the experiment passes, a later Worker/browser integration.
//   whisperPrompt     recent church terms + the previous caption as Whisper's initial_prompt (condition A)
//   findCandidates    windows of a caption that sound like a church term but are not it (for the language model)
//   correctionMessages / parseEdits / applyEdits
//                     ask a language model for character fixes only, then keep a fix only when it is the same
//                     length, sounds the same (one other syllable allowed when it completes a 3+ char term), and
//                     does not touch a term that is already correct (condition B)
// Readings come from the generated pinyin table (public/pinyin-zh.js: one most-common reading per char).

const MIN_TERM = 2;
const MAX_EDIT_CHARS = 8;
const MAX_CHANGED = 4;
const CJK = /^[㐀-䶿一-鿿豈-﫿]$/u;
const toneless = syllable => syllable.replace(/\d$/, '');

/** {primary: char → toneless syllable, terms: term → [Set of toneless syllables per char]} */
export function soundIndex({PINYIN, TERMS = {}}) {
  const primary = new Map();
  for (const [syllable, chars] of Object.entries(PINYIN)) for (const char of chars) primary.set(char, toneless(syllable));
  const terms = new Map(Object.entries(TERMS).map(([term, list]) => [term, list.map(options => new Set(options.map(toneless)))]));
  return {primary, terms};
}

function termSounds(index, term) {
  if (index.terms.has(term)) return index.terms.get(term);
  const list = Array.from(term, c => index.primary.get(c));
  return list.every(Boolean) ? list.map(s => new Set([s])) : null;
}

function prepareTerms(terms) {
  return [...new Set(terms)].filter(t => Array.from(t).length >= MIN_TERM)
    .sort((a, b) => Array.from(b).length - Array.from(a).length || (a < b ? -1 : 1));
}

/** Positions (code points) covered by exact occurrences of any term: never rewritten. */
export function lockedPositions(chars, terms) {
  const locked = new Array(chars.length).fill(false);
  for (const term of prepareTerms(terms)) {
    const t = Array.from(term);
    for (let i = 0; i + t.length <= chars.length; i++) {
      if (t.every((c, k) => chars[i + k] === c)) for (let k = 0; k < t.length; k++) locked[i + k] = true;
    }
  }
  return locked;
}

/** Terms that occur exactly in the text, in order of first appearance. */
export function exactTerms(text, terms) {
  const found = [];
  for (const term of prepareTerms(terms)) {
    const at = text.indexOf(term);
    if (at !== -1 && !found.some(f => f.term.includes(term))) found.push({term, at});
  }
  return found.sort((a, b) => a.at - b.at).map(f => f.term);
}

/**
 * Windows that sound like a term without being it: every char matches the term's toneless reading; terms of 3+
 * chars allow one char with another syllable. Windows touching an exact term are skipped. Longest terms first,
 * one entry per term, at most `limit`. Returns [{term, from, index}].
 */
export function findCandidates(text, terms, index, {limit = 12} = {}) {
  const chars = Array.from(text), locked = lockedPositions(chars, terms), out = [];
  for (const term of prepareTerms(terms)) {
    if (out.length >= limit) break;
    const t = Array.from(term), sounds = termSounds(index, term);
    if (!sounds) continue;
    for (let i = 0; i + t.length <= chars.length; i++) {
      let other = 0, differs = false, ok = true;
      for (let k = 0; k < t.length && ok; k++) {
        if (locked[i + k]) ok = false;
        else if (chars[i + k] !== t[k]) {
          differs = true;
          if (!sounds[k].has(index.primary.get(chars[i + k]))) ok = ++other <= (t.length >= 3 ? 1 : 0);
        }
      }
      // A window inside a longer candidate adds nothing (詔會 within 詔會生活).
      const inside = out.some(c => i >= c.index && i + t.length <= c.index + Array.from(c.from).length);
      if (ok && differs && !inside) { out.push({term, from: chars.slice(i, i + t.length).join(''), index: i}); break; }
    }
  }
  return out;
}

/**
 * Condition A: Whisper initial_prompt from what was already shown — church terms heard in the last captions
 * (newest first) and the tail of the previous caption. Empty string when there is nothing yet.
 */
export function whisperPrompt(history, terms, {recent = 8, maxTerms = 12, maxChars = 60} = {}) {
  const seen = [];
  for (const caption of history.slice(-recent).reverse()) {
    for (const term of exactTerms(caption, terms)) if (!seen.includes(term)) seen.push(term);
  }
  const last = Array.from(history.length ? history[history.length - 1] : '').slice(-maxChars).join('');
  const list = seen.slice(0, maxTerms);
  return (list.length ? list.join('、') + '。' : '') + last;
}

export const SYSTEM_PROMPT = [
  '你是教會聚會即時字幕的校對員。字幕由語音辨識產生，可能有同音或近音的錯字，特別是教會用語、聖經書卷、人名地名。',
  '只修正明顯聽錯的字；不改寫、不潤飾、不增刪字、不改標點；不確定就不要改。',
  '只回答 JSON：{"edits":[{"from":"本段中逐字出現的原字串","to":"改正後字串"}]}。from 與 to 字數必須相同。沒有要改就回答 {"edits":[]}。',
].join('\n');

/** Chat messages for one caption. `context` = earlier captions (read only); `candidates` from findCandidates. */
export function correctionMessages({context = [], text, candidates = [], suffix = ''}) {
  const hints = candidates.map(c => `「${c.from}」可能是「${c.term}」`).join('；');
  const user = [`前文（只供參考，不要改）：${context.join('') || '（無）'}`,
    `可能聽錯的專名：${hints || '（無）'}`, `本段：${text}`].join('\n') + (suffix ? `\n${suffix}` : '');
  return [{role: 'system', content: SYSTEM_PROMPT}, {role: 'user', content: user}];
}

/** Model reply → [{from, to}], or null when the reply is not the requested JSON. */
export function parseEdits(reply) {
  if (typeof reply !== 'string') reply = reply == null ? '' : JSON.stringify(reply);
  const body = reply.replace(/<think>[\s\S]*?<\/think>/g, '').replace(/```(?:json)?/g, '');
  const start = body.indexOf('{'), end = body.lastIndexOf('}');
  if (start === -1 || end < start) return null;
  let data;
  try { data = JSON.parse(body.slice(start, end + 1)); } catch { return null; }
  if (!data || !Array.isArray(data.edits)) return null;
  return data.edits.filter(e => e && typeof e.from === 'string' && typeof e.to === 'string').map(e => ({from: e.from, to: e.to}));
}

function coversTerm(chars, position, terms) {
  for (const term of terms) {
    const t = Array.from(term);
    if (t.length < 3) continue;
    for (let i = Math.max(0, position - t.length + 1); i <= position && i + t.length <= chars.length; i++) {
      if (t.every((c, k) => chars[i + k] === c)) return true;
    }
  }
  return false;
}

/**
 * Apply model edits. guarded=true keeps an edit only when: same length (≤8 chars), it occurs in the text without
 * overlapping an earlier edit, ≤4 chars change, no changed char belongs to a term that was already correct, new chars
 * are CJK, and every changed char keeps its toneless syllable — except one char when the result completes a 3+ char
 * term. guarded=false applies every edit found in the text (to measure what the guard prevents).
 * Returns {text, accepted:[{from,to,index}], rejected:[{from,to,reason}]}.
 */
export function applyEdits(text, edits, {terms, index, guarded = true}) {
  const chars = Array.from(text), locked = lockedPositions(chars, terms), taken = new Array(chars.length).fill(false);
  const accepted = [], rejected = [], list = prepareTerms(terms);
  for (const {from, to} of edits || []) {
    const f = Array.from(from), t = Array.from(to);
    const reject = reason => rejected.push({from, to, reason});
    if (!f.length || from === to) { reject('empty'); continue; }
    if (guarded && f.length !== t.length) { reject('length'); continue; }
    if (guarded && f.length > MAX_EDIT_CHARS) { reject('too_long'); continue; }
    let at = -1;
    for (let i = 0; i + f.length <= chars.length; i++) {
      if (f.every((c, k) => chars[i + k] === c) && !taken.slice(i, i + f.length).some(Boolean)) { at = i; break; }
    }
    if (at === -1) { reject('not_found'); continue; }
    if (guarded) {
      const changed = f.map((c, k) => c !== t[k] ? k : -1).filter(k => k !== -1);
      if (changed.length > MAX_CHANGED) { reject('too_many'); continue; }
      if (changed.some(k => locked[at + k])) { reject('locked_term'); continue; }
      if (changed.some(k => !CJK.test(t[k]))) { reject('not_cjk'); continue; }
      const after = [...chars.slice(0, at), ...t, ...chars.slice(at + f.length)];
      const other = changed.filter(k => {
        const heard = index.primary.get(f[k]), wanted = index.primary.get(t[k]);
        return !heard || !wanted || heard !== wanted;
      });
      if (other.length > 1 || (other.length === 1 && !coversTerm(after, at + other[0], list))) { reject('sound'); continue; }
    }
    for (let k = 0; k < f.length; k++) taken[at + k] = true;
    accepted.push({from, to, index: at});
  }
  // Replace right to left so earlier indices stay valid (unguarded edits may change length).
  const out = [...chars];
  for (const edit of [...accepted].sort((a, b) => b.index - a.index)) out.splice(edit.index, Array.from(edit.from).length, ...Array.from(edit.to));
  return {text: out.join(''), accepted, rejected};
}
