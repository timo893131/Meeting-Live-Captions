import test from 'node:test';
import assert from 'node:assert/strict';
import * as data from '../public/pinyin-zh.js';
import {loadPinyin} from '../public/phonetic.js';
import {alignCaption, chapterNumeral, preparePassages, verseLabel} from '../public/verse-align.js';

// Made-up "verses" (not Bible text), shaped like /api/verses results.
const VERSES = [
  {book: '弗', chapter: 6, verse: 1, text: '弟兄們在召會中彼此配搭，一同事奉主；'},
  {book: '弗', chapter: 6, verse: 2, text: '眾聖徒同心合意，在禱告上恆切不住。'},
  {book: '詩', chapter: 119, verse: 105, text: '燈臺的光照亮我們腳前的路。'}
];

test('reference labels in Recovery Version style', () => {
  assert.deepEqual([1, 10, 14, 20, 23, 119, 150].map(chapterNumeral), ['一', '十', '十四', '二十', '二三', '一一九', '一五○']);
  assert.equal(verseLabel('弗', 1, 22, 23), '弗一22～23');
  assert.equal(verseLabel('約', 14, 6, 6), '約十四6');
});

test('a caption reading a verse becomes the verse text; only the reading part is replaced', () => {
  loadPinyin(data);
  const passages = preparePassages(VERSES);
  assert.equal(passages.length, 2);  // 弗6:1-2 together, 詩119:105 alone
  const read = alignCaption('弟兄們在照會中彼此配達一同侍奉主', passages);
  assert.deepEqual([read.text, read.label], ['弟兄們在召會中彼此配搭，一同事奉主；', '弗六1']);
  const intro = alignCaption('我們一起來讀第二節眾聖徒同心合意在禱告上恆切不住', passages);
  assert.equal(intro.text, '我們一起來讀第二節眾聖徒同心合意，在禱告上恆切不住。');
  assert.equal(intro.label, '弗六2');
  const across = alignCaption('一同事奉主眾聖徒同心合意', passages);  // across two verses
  assert.equal(across.label, '弗六1～2');
});

test('unsure or unrelated captions stay as they are', () => {
  loadPinyin(data);
  const passages = preparePassages(VERSES);
  for (const caption of ['今天我們要來看召會生活', '弟兄們要好好配搭', '燈臺', '我們在禱告中', '']) {
    assert.equal(alignCaption(caption, passages), null, caption);
  }
  // Words the speaker inserted or said differently stop the replacement (two non-matching chars in a row).
  assert.equal(alignCaption('弟兄們在召會中第二小點彼此配搭一同事奉主', passages), null);
  assert.equal(alignCaption('弟兄們在召會中彼此幫助一同事奉主', passages), null);
  assert.equal(alignCaption('在禱告上恆久不住', passages, {minChars: 6}), null);  // under 10 chars: must match exactly
  assert.ok(alignCaption('眾聖徒同心合意在禱告上恆久不住', passages));  // 14 chars: one different char is allowed
  assert.ok(alignCaption('弟兄們在召會中彼此配搭一同事奉主眾聖徒同心合一在禱告上恆切不住', passages));  // 1 miss in 30
  assert.equal(alignCaption('弟兄們在召會中彼此配搭一同事奉主', []), null);
  assert.equal(alignCaption('弟兄們在召會中彼此配搭一同事奉主', passages, {minIdentity: 1.01}), null);
});
