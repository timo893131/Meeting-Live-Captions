// Precision check for same-sound terms on text that is already correct (e.g. the Recovery Version and
// Life-Study archive): every change made there is a false or variant edit. Prints {term: changes} as JSON.
// Usage: node scripts/term-precision.mjs <folder-with-.txt-files>... [--terms core|all] [--near]
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, CORE_DEFAULT_TERMS, loadPinyin, phoneticCorrect} from '../public/phonetic.js';

const args = process.argv.slice(2), folders = args.filter(a => !a.startsWith('--'));
const terms = args.includes('core') ? CORE_DEFAULT_TERMS : DEFAULT_TERMS, near = args.includes('--near');
loadPinyin(pinyinData);
const counts = {}, examples = {};
const walk = folder => readdirSync(folder).flatMap(name => {
  const path = join(folder, name);
  return statSync(path).isDirectory() ? walk(path) : name.endsWith('.txt') ? [path] : [];
});
for (const file of folders.flatMap(walk)) {
  for (const line of readFileSync(file, 'utf8').split('\n')) {
    for (const change of phoneticCorrect(line, terms, {near}).changes) {
      counts[change.to] = (counts[change.to] || 0) + 1;
      (examples[change.to] ||= new Set()).add(change.from);
    }
  }
}
const result = Object.fromEntries(Object.entries(counts).sort((a, b) => b[1] - a[1])
  .map(([term, n]) => [term, {changes: n, heard: [...examples[term]].slice(0, 5)}]));
process.stdout.write(JSON.stringify(result, null, 1) + '\n');
