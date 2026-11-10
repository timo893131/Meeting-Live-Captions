// Apply the live caption corrections (exact glossary, then same-sound church terms) to recognized segments,
// exactly as public/app.js does for each caption. Input/output JSON on stdin/stdout:
//   in:  {"segments": ["text", ...], "glossary": "optional textarea content"}
//   out: {"glossary": [...], "phonetic": [...], "changes": [[{from,to,index}], ...]}
import {readFileSync} from 'node:fs';
import {defaultGlossary, parseGlossary, correctText} from '../glossary.js';
import * as pinyinData from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, loadPinyin, parseTerms, phoneticCorrect} from '../public/phonetic.js';

const input = JSON.parse(readFileSync(0, 'utf8'));
if (!Array.isArray(input.segments) || input.segments.some(s => typeof s !== 'string')) throw new Error('Expected {segments: string[]}');
const textarea = typeof input.glossary === 'string' ? input.glossary : defaultGlossary.map(pair => pair.join('=')).join('\n');
const pairs = parseGlossary(textarea), terms = [...DEFAULT_TERMS, ...parseTerms(textarea)];
loadPinyin(pinyinData);
const glossary = [], phonetic = [], changes = [];
for (const segment of input.segments) {
  const exact = correctText(segment, pairs), result = phoneticCorrect(exact, terms);
  glossary.push(exact); phonetic.push(result.text); changes.push(result.changes);
}
process.stdout.write(JSON.stringify({glossary, phonetic, changes, terms}));
