import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as data from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, NEAR_SKIP, loadPinyin, phoneticCorrect} from '../public/phonetic.js';
import {BOOK_ABBREVIATIONS, CHAPTERS} from '../public/bible-abbreviations.js';
import {chineseNumber, correctionOptions, parseOutline, parseReferences, splitMessages, unknownRuns} from '../public/outline.js';

const common = new Set(data.COMMON.split('|'));
const parse = (text, options = {}) => parseOutline(text, {common, known: DEFAULT_TERMS, ...options});

// Shaped like scripts/outline_ocr.py output for an outline printed with its verses (wording is made up).
const OUTLINE = `## 第一篇　門徒與基督徒

讀經：太五1，二八19，林後六14～16，門16

- 壹 我們跟從基督，以撒的神是活神的見證—太五1，弗四20～24：
  - 一 基督對彼列有甚麼和諧—林後六15。
  - 二 彼列是撒但的名稱—約壹三8。
      - 1 詩篇說到牧者—詩二三1，一一九105。

### 引用經文（綱要附的經文）

- 太5:1 但祂看見這些羣眾，就上了山。
- 林後6:15 基督對彼列有甚麼和諧？
`;

test('chinese chapter numbers and outline-style verse references', () => {
  for (const [text, value] of Object.entries({一: 1, 十四: 14, 二十: 20, 二三: 23, 一一九: 119, 一百一十九: 119})) {
    assert.equal(chineseNumber(text), value, text);
  }
  const refs = parseReferences('見弗一23，三17～19；約十四6～7；林前十二12；詩一一九105；門16；弗七3。多一些人');
  assert.deepEqual(refs.map(r => [r.book, r.chapter, r.verse, r.to]),
    [['弗', 1, 23, 23], ['弗', 3, 17, 19], ['約', 14, 6, 7], ['林前', 12, 12, 12], ['詩', 119, 105, 105], ['門', 1, 16, 16]]);
});

test('parses title, scripture, points, quoted verses and refs from converter Markdown', () => {
  const outline = parse(OUTLINE);
  assert.equal(outline.title, '門徒與基督徒');
  assert.equal(outline.points.length, 4);
  assert.ok(outline.points[0].startsWith('我們跟從基督'));  // the 壹 marker is dropped
  assert.deepEqual(outline.quotes.map(q => q.ref), ['太5:1', '林後6:15']);
  assert.equal(outline.refs.length, 10);
  // Built-in terms it uses, plus the books its references cite (太 → 馬太福音, 門 → 腓利門書).
  for (const term of ['以撒', '馬太福音', '腓利門書', '哥林多後書', '以弗所書', '詩篇']) assert.ok(outline.known.includes(term), term);
  // 基督、彼列 in 2+ points (particles 對、是 split them from their neighbours); 基督徒 is a 3-char word in the title.
  assert.deepEqual(outline.terms, ['基督', '彼列', '基督徒']);
  assert.deepEqual(parse(OUTLINE, {minCount: 1}).terms.includes('彼列'), true);
});

test('plain text copied from a PDF and an empty or messy outline do not break', () => {
  const plain = parse('信徒(一) 第二篇\n永遠的生命\n讀經:約壹一1~2\n壹 永遠的生命就是神的生命——約壹一1~2。');
  assert.equal(plain.title, '永遠的生命');
  assert.equal(plain.refs[0].book, '約壹');
  assert.deepEqual(parse('').terms, []);
  assert.equal(parse('隨便打的字\n\n\n###\n- \n約99:99 不存在').quotes.length, 1);
  const long = parse(OUTLINE.repeat(80));  // about 18,000 chars
  assert.ok(long.terms.length <= 300);
});

test('everyday single-char words never form a term', () => {
  const dictionary = {has: word => common.has(word)};
  assert.deepEqual(unknownRuns('基督對彼列有甚麼和諧', dictionary), ['基督', '彼列']);  // 基督 is missing from the everyday list
  assert.deepEqual(unknownRuns('節是說到神', dictionary), []);
});

test('near sounds only for built-in terms this outline uses, never NEAR_SKIP ones', () => {
  loadPinyin(data);
  const options = correctionOptions(parse(OUTLINE), {nearSkip: NEAR_SKIP});
  assert.ok(options.nearTerms.has('以撒'));
  assert.ok(!options.nearTerms.has('詩篇'));  // NEAR_SKIP: 四篇 → 詩篇 false edits in correct text
  const terms = [...DEFAULT_TERMS, ...options.terms];
  assert.equal(phoneticCorrect('亞伯拉罕生以沙', terms).text, '亞伯拉罕生以沙');  // site default: strict only
  assert.equal(phoneticCorrect('亞伯拉罕生以沙', terms, {nearTerms: options.nearTerms}).text, '亞伯拉罕生以撒');
  assert.equal(phoneticCorrect('基督對彼烈有甚麼和諧', terms, {nearTerms: options.nearTerms}).text, '基督對彼列有甚麼和諧');
  assert.equal(phoneticCorrect('基督對彼烈有甚麼和諧').text, '基督對彼烈有甚麼和諧');  // without the outline
  assert.deepEqual(correctionOptions(null), {terms: [], nearTerms: null});
});

test('allowing near sounds never drops a tone-slip match the site already makes', () => {
  loadPinyin(data);
  // 汴亞敏 → 便雅憫 is a one-tone slip; with 便雅憫 allowed near sounds it must still be corrected.
  assert.equal(phoneticCorrect('猶大和汴亞敏的族長').text, '猶大和便雅憫的族長');
  assert.equal(phoneticCorrect('猶大和汴亞敏的族長', DEFAULT_TERMS, {nearTerms: new Set(['便雅憫'])}).text, '猶大和便雅憫的族長');
});

test('full-width verse digits and a title name used once', () => {
  const outline = parse('第三篇　被擄之人在瑪拉坦尼的帶領下歸回\n讀經：拉一１～４，代下三六２２～２３\n壹　波斯王的詔令');
  assert.deepEqual(outline.refs.map(r => [r.book, r.chapter, r.verse, r.to]), [['拉', 1, 1, 4], ['代下', 36, 22, 23]]);
  assert.ok(outline.known.includes('以斯拉記'));
  assert.deepEqual(outline.terms, ['瑪拉坦尼']);  // the made-up title name, though only once; not 「下歸回」
});

test('a whole-training Markdown file splits into its messages', () => {
  const file = '# ex\n\n## （篇題前的內容）\n\n封面\n\n## 第一篇　門徒\n\n讀經：太五1\n\n- 壹 甲\n\n## 第十二篇　新郎\n\n- 壹 乙\n';
  const parts = splitMessages(file);
  assert.deepEqual(parts.map(p => p.label), ['第一篇　門徒', '第十二篇　新郎']);
  assert.ok(parts[0].text.startsWith('## 第一篇') && parts[0].text.includes('讀經：太五1') && !parts[0].text.includes('乙'));
  assert.equal(parse(parts[1].text).title, '新郎');
  assert.deepEqual(splitMessages('## 第一篇　只有一篇\n- 壹 甲'), [{label: '', text: '## 第一篇　只有一篇\n- 壹 甲'}]);
});

test('book tables agree with the Python converters', () => {
  const python = readFileSync(new URL('../scripts/outline_pdf_to_md.py', import.meta.url), 'utf8');
  const list = python.match(/BOOK_ABBREVIATIONS = \[([\s\S]*?)\]/)[1].match(/'([^']+)'/g).map(s => s.slice(1, -1));
  assert.deepEqual(list, BOOK_ABBREVIATIONS);
  const ocr = readFileSync(new URL('../scripts/outline_ocr.py', import.meta.url), 'utf8');
  const counts = ocr.match(/CHAPTERS = dict\(zip\(outline\.BOOK_ABBREVIATIONS, \[([\s\S]*?)\]\)\)/)[1]
    .replace(/#[^\n]*/g, '').match(/\d+/g).map(Number);
  assert.deepEqual(counts, CHAPTERS);
});
