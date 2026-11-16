// Apply the live caption corrections (exact glossary, then same-sound church terms) to recognized segments,
// exactly as public/app.js does for each caption. Input/output JSON on stdin/stdout:
//   in:  {"segments": ["text", ...], "glossary": "optional textarea content", "term_set": "all"|"core", "near": false,
//         "outline": "optional outline text (this meeting's terms; near sounds only for built-in terms it uses)"}
//   out: {"glossary": [...], "phonetic": [...], "changes": [[{from,to,index}], ...]}
import {readFileSync} from 'node:fs';
import {startingGlossary, parseGlossary, correctText} from '../glossary.js';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, CORE_DEFAULT_TERMS, NEAR_SKIP, loadPinyin, parseTerms, phoneticCorrect} from '../public/phonetic.js';
import {parseOutline, correctionOptions} from '../public/outline.js';

const input = JSON.parse(readFileSync(0, 'utf8'));
if (!Array.isArray(input.segments) || input.segments.some(s => typeof s !== 'string')) throw new Error('Expected {segments: string[]}');
// Default = the website's starting glossary box (empty), so the evaluation matches what visitors get.
const textarea = typeof input.glossary === 'string' ? input.glossary : startingGlossary.map(pair => pair.join('=')).join('\n');
// term_set 'core' = books + church terms only (for comparing the effect of Bible names).
const base = input.term_set === 'core' ? CORE_DEFAULT_TERMS : DEFAULT_TERMS;
loadPinyin(pinyinData);
const outline = typeof input.outline === 'string' && input.outline.trim()
  ? parseOutline(input.outline, {common: new Set(pinyinData.COMMON.split('|')), known: DEFAULT_TERMS}) : null;
const options = correctionOptions(outline, {nearSkip: NEAR_SKIP});
const pairs = parseGlossary(textarea), terms = [...base, ...options.terms, ...parseTerms(textarea)];
const glossary = [], phonetic = [], changes = [];
for (const segment of input.segments) {
  const exact = correctText(segment, pairs);
  const result = phoneticCorrect(exact, terms, options.nearTerms ? {nearTerms: options.nearTerms} : {near: input.near === true});
  glossary.push(exact); phonetic.push(result.text); changes.push(result.changes);
}
process.stdout.write(JSON.stringify({glossary, phonetic, changes, terms,
  outline: outline && {title: outline.title, terms: outline.terms, known: outline.known, refs: outline.refs.length}}));
