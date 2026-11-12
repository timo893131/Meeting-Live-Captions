// Find church terms worth adding to the same-sound correction (public/church-terms.js), on DEVELOPMENT data.
//
// Candidates = frequent 2–4 character words of the correct church text (Recovery Version + Life-Study).
// For each candidate the live rule (public/phonetic.js, strict readings as for host-added terms) is run on the
// recognizer output of the development set:
//   fixes      the heard text was changed into the term AND that message's text contains the term
//   doubtful   changed into the term, but the message's text does not contain it (possible false edit)
//   blocked    would match, but the heard text is an everyday word the rule never touches (分次, 恩典)
//   false_text changes the rule makes into the term on the correct church text itself (must be 0)
// The table is a proposal: terms are added by hand, then the pinyin table is rebuilt and the development set
// re-scored. Never run this on the sealed MEET test.
//
// Usage: node scripts/mine-same-sound-terms.mjs --run <eval run folder> --refs <dev folder> --corpus <folder>...
//        [--condition whisper_live_vad_10s] [--min-count 40] [--top 80]
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, loadPinyin, phoneticCorrect} from '../public/phonetic.js';
import {Converter} from 'opencc-js/cn2t';

// The website converts Whisper's text to Traditional (Taiwan) before correcting it; do the same here.
const toTraditional = Converter({from: 'cn', to: 'tw'});

const args = process.argv.slice(2);
const option = (name, fallback) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : fallback; };
const corpusFolders = (() => { const out = []; for (let i = 0; i < args.length; i++) if (args[i] === '--corpus') while (args[i + 1] && !args[i + 1].startsWith('--')) out.push(args[++i]); return out; })();
const run = option('--run'), refs = option('--refs'), condition = option('--condition', 'whisper_live_vad_10s');
const minCount = Number(option('--min-count', 40)), top = Number(option('--top', 80));
if (!run || !refs || !corpusFolders.length) throw new Error('Usage: --run <folder> --refs <folder> --corpus <folder>...');

const walk = folder => readdirSync(folder).flatMap(name => {
  const path = join(folder, name);
  return statSync(path).isDirectory() ? walk(path) : name.endsWith('.txt') ? [path] : [];
});
const CJK = /[㐀-䶿一-鿿豈-﫿]+/gu;
// Function characters that rarely start or end a term (cheap cleanup of n-gram fragments).
const EDGE = new Set('的了是在我們你他她它祂這那就也都而與和及或但並把被給對從向於以為之其所著過來去上下中裡裏有沒不要會能可一個些麼什說到很再又才還已將'.split(''));

// 1. Candidates from the correct church text.
const corpusLines = corpusFolders.flatMap(walk).flatMap(file => readFileSync(file, 'utf8').split('\n'));
// Counted level by level (a 3-gram only when both its 2-grams are frequent…) so millions of rare n-grams
// never have to be held in memory; edge function characters are dropped afterwards.
const runs = corpusLines.flatMap(line => (line.match(CJK) || []).map(run => Array.from(run)));
const counts = new Map();
let frequent = null;
for (let n = 2; n <= 4; n++) {
  const level = new Map();
  for (const chars of runs) for (let i = 0; i + n <= chars.length; i++) {
    const gram = chars.slice(i, i + n).join('');
    if (frequent && !(frequent.has(chars.slice(i, i + n - 1).join('')) && frequent.has(chars.slice(i + 1, i + n).join('')))) continue;
    level.set(gram, (level.get(gram) || 0) + 1);
  }
  frequent = new Set([...level].filter(([, c]) => c >= minCount).map(([g]) => g));
  for (const gram of frequent) {
    const chars = Array.from(gram);
    if (!EDGE.has(chars[0]) && !EDGE.has(chars[n - 1])) counts.set(gram, level.get(gram));
  }
}
const existing = new Set(DEFAULT_TERMS);
const candidates = [...counts].filter(([g, n]) => n >= minCount && !existing.has(g)).sort((a, b) => b[1] - a[1]).map(([g]) => g);

// 2. Development recognizer output and its (non-verbatim) message text.
const readings = loadPinyin(pinyinData), everyday = readings.common;
// Only terms whose toneless syllables occur in a text can match there: index them so each call stays small.
const toneless = chars => chars.map(c => (readings.primary.get(c) || c).replace(/\d$/, ''));
const keyOf = term => toneless(Array.from(term)).join(' ');
const byKey = new Map();
for (const t of candidates) { const k = keyOf(t); (byKey.get(k) || byKey.set(k, []).get(k)).push(t); }
function relevant(text, pool = byKey) {
  const syllables = toneless(Array.from(text)), found = [];
  for (let n = 2; n <= 4; n++) for (let i = 0; i + n <= syllables.length; i++) {
    const hit = pool.get(syllables.slice(i, i + n).join(' ')); if (hit) found.push(...hit);
  }
  return [...new Set(found)];
}
const pairs = readdirSync(run).map(name => name.match(new RegExp(`^(\\d+)\\.${condition}\\.json$`))).filter(Boolean).map(m => m[1]);
if (!pairs.length) throw new Error(`No NN.${condition}.json in ${run}`);
const existingDoubtful = new Map();  // edits by terms already built in, where the message text lacks the term
const stats = new Map(candidates.map(t => [t, {fixes: 0, doubtful: 0, blocked: 0, false_text: 0, heard: new Map()}]));
for (const pair of pairs) {
  const reference = readFileSync(join(refs, `${pair}.txt`), 'utf8');
  const segments = JSON.parse(readFileSync(join(run, `${pair}.${condition}.json`), 'utf8')).raw.map(s => toTraditional(s));
  for (const segment of segments) {
    const terms = [...DEFAULT_TERMS, ...relevant(segment)];
    for (const change of phoneticCorrect(segment, terms).changes) {
      if (existing.has(change.to) && !reference.includes(change.to)) existingDoubtful.set(`${change.from}→${change.to}`, (existingDoubtful.get(`${change.from}→${change.to}`) || 0) + 1);
      const s = stats.get(change.to); if (!s) continue;
      reference.includes(change.to) ? s.fixes++ : s.doubtful++;
      s.heard.set(change.from, (s.heard.get(change.from) || 0) + 1);
    }
    readings.common = new Set();  // what the everyday-word guard holds back
    for (const change of phoneticCorrect(segment, terms).changes) {
      const s = stats.get(change.to);
      if (s && everyday.has(change.from) && reference.includes(change.to)) { s.blocked++; s.heard.set(change.from + '（一般詞）', (s.heard.get(change.from + '（一般詞）') || 0) + 1); }
    }
    readings.common = everyday;
  }
}

// 3. False edits on the correct text, for the candidates that helped.
const shortlist = candidates.filter(t => stats.get(t).fixes + stats.get(t).blocked >= 2);
const shortKeys = new Map();
for (const t of shortlist) { const k = keyOf(t); (shortKeys.get(k) || shortKeys.set(k, []).get(k)).push(t); }
for (const line of corpusLines) {
  const terms = relevant(line, shortKeys);
  if (terms.length) for (const change of phoneticCorrect(line, terms).changes) stats.get(change.to).false_text++;
}

const rows = shortlist.map(t => ({term: t, corpus: counts.get(t), ...stats.get(t)}))
  .sort((a, b) => (b.fixes + b.blocked) - (a.fixes + a.blocked) || b.corpus - a.corpus).slice(0, top);
console.log(`開發資料 ${pairs.length} 篇（${condition}）；候選詞 ${candidates.length} 個（正確文字出現 ≥ ${minCount} 次）\n`);
console.log('| 詞 | 正確文字出現 | 修好 | 存疑 | 被一般詞擋下 | 正確文字誤改 | 聽成（次數） | 建議 |');
console.log('| --- | --- | --- | --- | --- | --- | --- | --- |');
for (const r of rows) {
  const heard = [...r.heard].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([w, n]) => `${w}×${n}`).join('、');
  const advice = r.false_text ? '不加（會改錯正確文字）' : r.fixes >= 2 && r.doubtful * 4 <= r.fixes ? '加入'
    : r.blocked >= 2 && !r.fixes ? '需確認一般詞' : '觀察';
  console.log(`| ${r.term} | ${r.corpus} | ${r.fixes} | ${r.doubtful} | ${r.blocked} | ${r.false_text} | ${heard} | ${advice} |`);
}
const doubtful = [...existingDoubtful].sort((a, b) => b[1] - a[1]).slice(0, 30);
if (doubtful.length) {
  console.log('\n現有專名的存疑修改（該篇文字沒有這個詞；可能改錯，也可能是講員額外說的）\n');
  console.log('| 修改 | 次數 |\n| --- | --- |');
  for (const [edit, n] of doubtful) console.log(`| ${edit} | ${n} |`);
}
