import test from 'node:test';
import assert from 'node:assert/strict';
import {cleanPages, fixOcrLine, itemsToLines} from '../public/outline-pdf.js';

const item = (str, x, y, width, size = 12) => ({str, transform: [size, 0, 0, size, x, y], width});

test('pdf.js text items become lines, a visible gap becomes a space', () => {
  const lines = itemsToLines([item('第一篇', 120, 700, 36), item('信徒(一)', 60, 700, 48), item('門徒', 60, 680, 24),
    item('與基督徒', 84, 680.5, 48), item(' ', 140, 600, 3)]);
  assert.deepEqual(lines, ['信徒(一) 第一篇', '門徒與基督徒']);
});

test('repeated headers, footers, page numbers and continuation headers are dropped', () => {
  const page = (n, body) => ['二○二六年冬季訓練', ...body, String(n), '2026 示範出版社'];
  const text = cleanPages([page(1, ['第一篇 甲', '壹 一']), page(2, ['第一篇(續)', '貳 二']), page(3, ['第二篇 乙', '壹 三'])]);
  assert.equal(text, '第一篇 甲\n壹 一\n貳 二\n第二篇 乙\n壹 三');
});

test('tesseract output: spaces, stray quotes, chapter misreads and dashes read as 一', () => {
  const cases = {
    '信徒 ( 一 )” 第一篇': '信徒(一) 第一篇',
    '讀經 : 創二一 3 , 林後六 1 5': '讀經:創二一3,林後六15',
    '壹 ” 以撒是應許之子一創二一 3 。': '壹 以撒是應許之子—創二一3。',
    '有了永遠的生命就永不滅亡—約+28~29。': '有了永遠的生命就永不滅亡—約十28~29。',
    '永遠的生命就是神的生命——約壹-1~2。': '永遠的生命就是神的生命——約壹一1~2。',
    '-': '一',
    '三一神的經綸': '三一神的經綸',  // no space after 三 in the scan: not a marker
    '( 三 ) 我們屬靈的行事為人': '(三) 我們屬靈的行事為人',
    '統一的心': '統一的心',
    '2026 Living Stream Ministry': '2026 Living Stream Ministry'
  };
  for (const [ocr, expected] of Object.entries(cases)) assert.equal(fixOcrLine(ocr), expected, ocr);
});
