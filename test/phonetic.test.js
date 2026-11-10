import test from 'node:test';
import assert from 'node:assert/strict';
import * as data from '../public/pinyin-zh.js';
import {DEFAULT_TERMS, loadPinyin, parseTerms, phoneticCorrect, pinyinReady} from '../public/phonetic.js';

test('unchanged until the pinyin data is loaded', () => {
  if (!pinyinReady()) assert.equal(phoneticCorrect('以服所書').text, '以服所書');
});

test('same-sound misrecognitions of church terms are corrected', () => {
  loadPinyin(data);
  const cases = {
    '我們來看以服所書': '我們來看以弗所書',
    '生命毒精第一篇': '生命讀經第一篇',
    '詔會生活': '召會生活',
    '以弗所書的戒言': '以弗所書的介言',
    '約翰三書': '約翰參書',
    '我們讀創世紀': '我們讀創世記',
    '照會生活': '召會生活',
    '讀真言第三章': '讀箴言第三章',
    '神的腈綸': '神的經綸',
    '弟兄們伸延': '弟兄們申言'
  };
  for (const [heard, expected] of Object.entries(cases)) assert.equal(phoneticCorrect(heard).text, expected, heard);
  assert.deepEqual(phoneticCorrect('生命毒精').changes, [{from: '生命毒精', to: '生命讀經', index: 0}]);
});

test('correct text and ordinary words are left alone', () => {
  loadPinyin(data);
  for (const text of ['以弗所書第一章', '台灣戒嚴時期', '約伯繼續說', '利未祭司', '這是規條和律法', '眾生平等',
    '肯贖就贖出來', '交通號誌', '他在禱告', '今天天氣很好']) {
    assert.equal(phoneticCorrect(text).text, text, text);
  }
});

test('host-added terms use strict primary readings; glossary pairs are not terms', () => {
  loadPinyin(data);
  assert.deepEqual(parseTerms('耶蘇=耶穌\n王弟兄\n\n一\n'), ['王弟兄']);
  assert.equal(phoneticCorrect('今天王第兄分享', [...DEFAULT_TERMS, '王弟兄']).text, '今天王弟兄分享');
  assert.equal(phoneticCorrect('今天王第兄分享').text, '今天王第兄分享');
});

test('longer terms win and replacements are not processed again', () => {
  loadPinyin(data);
  assert.equal(phoneticCorrect('詔會生活很好').text, '召會生活很好');
  assert.equal(phoneticCorrect('召會召會').changes.length, 0);
});
