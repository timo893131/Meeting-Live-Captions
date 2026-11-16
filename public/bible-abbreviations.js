// Recovery Version book abbreviations in canonical order (創 = 創世記 … 啟 = 啟示錄) and chapter counts.
// Kept out of church-terms.js, whose string literals the Python scripts read as the term list.
// scripts/outline_pdf_to_md.py and scripts/outline_ocr.py hold the same tables (test/outline.test.js checks they agree).
export const BOOK_ABBREVIATIONS = ['創', '出', '利', '民', '申', '書', '士', '得', '撒上', '撒下', '王上', '王下', '代上', '代下',
  '拉', '尼', '斯', '伯', '詩', '箴', '傳', '歌', '賽', '耶', '哀', '結', '但', '何', '珥', '摩', '俄', '拿', '彌', '鴻', '哈',
  '番', '該', '亞', '瑪', '太', '可', '路', '約', '徒', '羅', '林前', '林後', '加', '弗', '腓', '西', '帖前', '帖後', '提前',
  '提後', '多', '門', '來', '雅', '彼前', '彼後', '約壹', '約貳', '約參', '猶', '啟'];
export const CHAPTERS = [50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42, 150, 31, 12, 8, 66, 52, 5, 48,
  12, 14, 3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4, 28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4, 5, 3, 6, 4, 3, 1, 13, 5, 5, 3, 5, 1, 1,
  1, 22];
export const SINGLE_CHAPTER = new Set(['俄', '門', '約貳', '約參', '猶']);
