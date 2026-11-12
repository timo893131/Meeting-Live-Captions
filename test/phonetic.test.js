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
    '弟兄們伸延': '弟兄們申言',
    '拿厄米和波阿斯': '拿俄米和波阿斯',
    '尼布加尼撒王': '尼布甲尼撒王',
    '摩鴉鄉間': '摩押鄉間'
  };
  for (const [heard, expected] of Object.entries(cases)) assert.equal(phoneticCorrect(heard).text, expected, heard);
  assert.deepEqual(phoneticCorrect('生命毒精').changes, [{from: '生命毒精', to: '生命讀經', index: 0}]);
});

test('correct text and ordinary words are left alone', () => {
  loadPinyin(data);
  assert.equal(phoneticCorrect('尼利米勒').text, '尼利米勒');  // different initial (ni/yi): not a same-sound error
  assert.equal(phoneticCorrect('馬丁路德').text, '馬丁路德');  // Life-Study uses 路德 for Luther; 路得 is not a target
  assert.equal(phoneticCorrect('撒迦利亞說').text, '撒迦利亞說');  // two different persons share this sound
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

test('terms added from the Life-Study development set fix their errors without touching everyday phrases', () => {
  loadPinyin(data);
  const fixed = {'神的經論': '神的經綸', '神經倫的目標': '神經綸的目標', '西安山': '錫安山', '主被定十字架': '主被釘十字架',
    '受高者': '受膏者', '加勒底人': '迦勒底人', '提摩泰': '提摩太', '神的形象': '神的形像', '神的管制': '神的管治'};
  for (const [heard, expected] of Object.entries(fixed)) assert.equal(phoneticCorrect(heard).text, expected, heard);
  // Words the owner confirmed as misrecognitions in meetings (2026-11-12), corrected although they are words.
  const confirmed = {'屬靈的征戰': '屬靈的爭戰', '神的奧秘': '神的奧祕', '看見意象': '看見異象', '到西安': '到錫安',
    '神的工藝': '神的公義', '基督實話在那靈裡': '基督實化在那靈裡'};
  for (const [heard, expected] of Object.entries(confirmed)) assert.equal(phoneticCorrect(heard).text, expected, heard);
  for (const everyday of ['神的果子', '每地方都有', '他說菲利斯人', '意向', '公益', '石化', '實際']) {
    assert.equal(phoneticCorrect(everyday).text, everyday, everyday);
  }
});
