import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import outline_ocr  # noqa: E402

PAGE_ONE = '''﻿二○二六年冬季訓練
第一篇
基督是神的奧祕
讀經：西二2，一26～27，詩二三1
壹 神的奧祕是基督，
祂是神的具體化身——西二9。
一 基督是神的經論——弗三4，五32，弗七3。
1
'''
PAGE_TWO = '''二○二六年冬季訓練
1 我們要活基督——腓一21。
貳 召會是基督的身體——林前十二12，門16。
2
'''
PAGE_THREE = '''二○二六年冬季訓練
第二篇 召會是基督的身體
讀經：弗一22～23
壹 召會是基督的豐滿——弗一23。
3
'''


class OutlineOcrTests(unittest.TestCase):
    def test_chinese_chapter_numbers(self):
        cases = {'一': 1, '十四': 14, '二十': 20, '二三': 23, '一一九': 119, '一百一十九': 119, '一百五十': 150, '十': 10}
        for text, value in cases.items():
            self.assertEqual(outline_ocr.chinese_number(text), value, text)

    def test_parse_references_keeps_book_and_chapter_across_continuations(self):
        found = [r[1:] for r in outline_ocr.parse_references('西二2，一26～27，18；林前十二12，門16，詩一一九105')]
        self.assertEqual(found, [('西', 2, 2), ('西', 1, 26), ('西', 1, 18), ('林前', 12, 12), ('門', 1, 16),
                                 ('詩', 119, 105)])

    def test_checks_flag_impossible_chapters_and_near_terms(self):
        messages = [{'number': '一', 'scripture': ['弗七3，猶二5'], 'items': [{'text': '神的經論與召曾', 'level': 1}]}]
        result = outline_ocr.check_messages(messages, terms=['神的經綸', '召會', '以弗所書'])
        self.assertEqual([r['reference'] for r in result['invalid_references']], ['弗七3', '猶二5'])
        self.assertEqual([(s['ocr'], s['term']) for s in result['term_suspects']], [('神的經論', '神的經綸')])
        self.assertEqual(len(result['warnings']), 2)

    def test_known_terms_include_books_and_bible_names(self):
        terms = outline_ocr.known_terms()
        self.assertIn('以弗所書', terms)
        self.assertIn('尼布甲尼撒', terms)
        self.assertNotIn('./bible-names.js', terms)

    def test_run_uses_cache_and_writes_markdown_with_checks(self):
        texts = [PAGE_ONE, PAGE_TWO, PAGE_THREE]
        calls = []

        def fake_ocr(service, image, language='zh'):
            calls.append(image)
            return texts[len(calls) - 1]

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            pages = [(n, f'image{n}'.encode()) for n in (1, 2, 3)]
            with mock.patch.object(outline_ocr, 'render_pages', return_value=pages), \
                    mock.patch.object(outline_ocr, 'google_ocr', side_effect=fake_ocr):
                report = outline_ocr.run(folder/'outline.pdf', folder/'cache', folder/'out', service=None,
                                         log=lambda *_: None)
                self.assertEqual(len(calls), 3)
                outline_ocr.run(folder/'outline.pdf', folder/'cache', folder/'out', service=None, log=lambda *_: None)
                self.assertEqual(len(calls), 3)  # 第二次全部讀快取
            markdown = (folder/'out'/'outline.md').read_text(encoding='utf-8')
            self.assertIn('## 第一篇　基督是神的奧祕', markdown)
            self.assertIn('讀經：西二2，一26～27，詩二三1', markdown)
            self.assertIn('- 壹 神的奧祕是基督，祂是神的具體化身——西二9。', markdown)
            self.assertIn('    - 1 我們要活基督', markdown)
            self.assertIn('## 第二篇　召會是基督的身體', markdown)
            self.assertNotIn('冬季訓練', markdown)
            self.assertEqual([m['number'] for m in report['messages']], ['一', '二'])
            self.assertEqual([r['reference'] for r in report['invalid_references']], ['弗七3'])
            self.assertIn(('神的經論', '神的經綸'), [(s['ocr'], s['term']) for s in report['term_suspects']])
            saved = json.loads((folder/'out'/'outline.report.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['ocr'], {'engine': 'google-drive', 'language': 'zh', 'cache': str(folder/'cache')})

    @unittest.skipUnless(importlib.util.find_spec('googleapiclient'), 'google-api-python-client not installed')
    def test_google_ocr_sends_iso_language_and_does_not_retry_client_errors(self):
        from googleapiclient.errors import HttpError
        calls = []

        class Request:
            def __init__(self, action):
                self.action = action

            def execute(self):
                return self.action()

        class Files:
            def __init__(self, fail):
                self.fail = fail

            def create(self, **kwargs):
                calls.append(('create', kwargs['ocrLanguage'], kwargs['body']['mimeType']))
                if self.fail:
                    def error():
                        raise HttpError(mock.Mock(status=400, reason='Invalid Value'), b'{}')
                    return Request(error)
                return Request(lambda: {'id': 'doc'})

            def export(self, **kwargs):
                calls.append(('export', kwargs['mimeType']))
                return Request(lambda: '\ufeff第一篇\n'.encode())

            def delete(self, **kwargs):
                calls.append(('delete', kwargs['fileId']))
                return Request(lambda: None)

        service = mock.Mock(files=lambda: Files(fail=False))
        self.assertEqual(outline_ocr.google_ocr(service, b'jpeg'), '第一篇\n')
        self.assertEqual(calls, [('create', 'zh', 'application/vnd.google-apps.document'), ('export', 'text/plain'),
                                 ('delete', 'doc')])
        calls.clear()
        with mock.patch.object(outline_ocr.time, 'sleep') as sleep, self.assertRaises(HttpError):
            outline_ocr.google_ocr(mock.Mock(files=lambda: Files(fail=True)), b'jpeg')
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    @unittest.skipUnless(importlib.util.find_spec('pymupdf'), 'PyMuPDF not installed')
    def test_rendered_pages_fit_drive_ocr_limit(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'scan.pdf'
            document = pymupdf.open()
            page = document.new_page(width=595, height=842)
            page.insert_text((50, 100), '第一篇 基督是神的奧祕', fontname='china-t', fontsize=16)
            document.save(path)
            rendered = list(outline_ocr.render_pages(path))
            self.assertEqual(len(rendered), 1)
            self.assertTrue(rendered[0][1].startswith(b'\xff\xd8'))
            self.assertLessEqual(len(rendered[0][1]), outline_ocr.MAX_IMAGE_BYTES)


if __name__ == '__main__':
    unittest.main()
