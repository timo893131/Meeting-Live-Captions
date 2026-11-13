// Precision check for same-sound terms on text that is already correct (e.g. the Recovery Version and
// Life-Study archive): every change made there is a false or variant edit. Prints {term: {changes, heard, context}}
// as JSON (context: up to 5 examples with 2 chars on each side, to find words for NEAR_PROTECT).
// Usage: node scripts/term-precision.mjs <folder-with-.txt-files>... [--terms core|all] [--near]
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, CORE_DEFAULT_TERMS, loadPinyin, phoneticCorrect} from '../public/phonetic.js';

const args = process.argv.slice(2), folders = args.filter(a => !a.startsWith('--'));
const terms = args.includes('core') ? CORE_DEFAULT_TERMS : DEFAULT_TERMS, near = args.includes('--near');
loadPinyin(pinyinData);
const counts = {}, examples = {}, contexts = {};
const walk = folder => readdirSync(folder).flatMap(name => {
  const path = join(folder, name);
  return statSync(path).isDirectory() ? walk(path) : name.endsWith('.txt') ? [path] : [];
});
for (const file of folders.flatMap(walk)) {
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    const chars = Array.from(line);
    for (const change of phoneticCorrect(line, terms, {near}).changes) {
      counts[change.to] = (counts[change.to] || 0) + 1;
      (examples[change.to] ||= new Set()).add(change.from);
      const end = change.index + Array.from(change.from).length;
      (contexts[change.to] ||= new Set()).add(chars.slice(Math.max(0, change.index - 2), end + 2).join(''));
    }
  }
}
const result = Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1])
  .map(([term, n]) => [term, {changes: n, heard: [...examples[term]].slice(0, 5), context: [...contexts[term]].slice(0, 5)}]));
process.stdout.write(JSON.stringify(result, null, 1) + '\n');
