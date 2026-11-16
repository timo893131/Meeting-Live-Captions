import test from 'node:test';
import assert from 'node:assert/strict';
import {MAX_VERSES, chapterKey, parseVerseRefs, readVerses} from '../cloudflare/verses.js';

test('verse references parse with limits; impossible ones are refused', () => {
  assert.deepEqual(parseVerseRefs('弗1:23, 約14:6-7,約壹1:1~2').refs, [
    {book: '弗', chapter: 1, from: 23, to: 23}, {book: '約', chapter: 14, from: 6, to: 7}, {book: '約壹', chapter: 1, from: 1, to: 2}]);
  for (const bad of ['', '弗7:1', '弗1:0', '弗1:5-3', '詩119:1-176', 'X1:1', '弗1:1;DROP', '弗一23']) {
    assert.ok(parseVerseRefs(bad).error, bad);
  }
  const many = Array.from({length: 6}, (_, i) => `詩${119 - i}:1-59`).join(',');
  assert.match(parseVerseRefs(many).error, new RegExp(String(MAX_VERSES)));
  assert.equal(chapterKey('弗', 1), 'rv/49/001.json');
  assert.equal(chapterKey('詩', 119), 'rv/19/119.json');
});

test('verses are read once per chapter; missing ones are listed', async () => {
  const loaded = [];
  const store = {'rv/49/001.json': {book: '弗', chapter: 1, verses: {22: '甲', 23: '乙'}}};
  const result = await readVerses(parseVerseRefs('弗1:22-23,弗1:23,弗1:24,約1:1').refs, async key => {
    loaded.push(key); return store[key] || null;
  });
  assert.deepEqual(result.verses.map(v => [v.ref, v.text]), [['弗1:22', '甲'], ['弗1:23', '乙']]);
  assert.deepEqual(result.missing, ['弗1:24', '約1:1']);
  assert.deepEqual(loaded, ['rv/49/001.json', 'rv/43/001.json']);
});
