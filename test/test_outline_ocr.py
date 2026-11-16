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

    def recovery_version(self, folder):
        text = Path(folder)/'rv'
        text.mkdir()
        (text/'40-馬太福音.txt').write_text('馬太福音\n馬太福音 第 5 章\n壹 登山\n1 但祂看見這些羣眾，就上了山；既已坐下，門徒到祂跟前來。\n'
                                       '2 祂就開口教訓他們，說，\n', encoding='utf-8')
        (text/'49-以弗所書.txt').write_text('以弗所書\n以弗所書 第 4 章\n23 而在你們心思的靈裏得以更新，\n'
                                       '24 並且穿上了新人，這新人是照着神，在那實際的義和聖中所創造的。\n', encoding='utf-8')
        return text

    def test_load_recovery_version_reads_verses_not_outline_lines(self):
        with tempfile.TemporaryDirectory() as folder:
            verses = outline_ocr.load_recovery_version(self.recovery_version(folder))
        self.assertEqual(verses[('太', 5, 1)][:6], '但祂看見這些')
        self.assertEqual(sorted(verses), [('太', 5, 1), ('太', 5, 2), ('弗', 4, 23), ('弗', 4, 24)])

    def test_checks_flag_impossible_chapters_measure_quotes_and_move_verse_lines(self):
        messages = [{'number': '一', 'scripture': ['弗七3，猶二5'], 'quotes': [
            {'ref': '太5:1', 'text': '但祂看見這些群眾,就上了山;既已坐下,門徒到祂跟前來。'},  # 羣→群：1 個錯字
            {'ref': '弗4:23', 'text': '而在你們心思的靈裏得以更新,'},
            {'ref': '弗4:24', 'text': ''}, {'ref': '弗9:1', 'text': '不存在'}],
            'items': [{'text': '壹 我們是基督的門徒', 'level': 1},
                      {'text': '並且穿上了新人,這新人是照着神,在那實際的義和聖中所創造的。', 'level': 0},
                      {'text': '我們正在從一個天然的人被訓練成一個神人', 'level': 0}]}]
        with tempfile.TemporaryDirectory() as folder:
            verses = outline_ocr.load_recovery_version(self.recovery_version(folder))
        result = outline_ocr.check_messages(messages, verses)
        self.assertEqual([r['reference'] for r in result['invalid_references']], ['弗七3', '猶二5'])
        check = result['verse_check']
        self.assertEqual((check['quotes_checked'], check['errors'], check['verse_text_lines_moved']), (2, 1, 1))
        self.assertEqual(check['worst'][0]['ref'], '太5:1')
        self.assertEqual(check['unknown_refs'], [{'message': '第一篇', 'ref': '弗9:1'}])
        self.assertEqual([i['text'][:4] for i in messages[0]['items']], ['壹 我們', '我們正在'])  # 講解文字留著
        self.assertEqual(messages[0]['verse_text'][0][:4], '並且穿上')
        self.assertEqual(len(result['warnings']), 2)

    def test_fitting_distance_allows_cut_off_verses(self):
        self.assertEqual(outline_ocr.fitting_distance('心思的靈', '而在你們心思的靈裏得以更新'), 0)
        self.assertEqual(outline_ocr.fitting_distance('心恩的靈', '而在你們心思的靈裏得以更新'), 1)
        self.assertEqual(outline_ocr.quote_keys('林後6:14~16'), [('林後', 6, 14), ('林後', 6, 15), ('林後', 6, 16)])

    def test_real_ocr_layout_series_title_continuation_quotes_and_split_markers(self):
        pages = [outline_ocr.ocr_text_to_page(t) for t in (
            '________________\n\n信徒(一) 第一篇\n門徒、信徒、聖徒和基督徒\n讀經:太五1,二八19,林後六14~16\n'
            '但祂看見這些羣眾,就上了山;既已坐下,門徒到祂跟前來。\n太5:1\n太28:19\n'
            '壹 我們是基督的門徒,就是跟從基督\n的人—太五1,弗四20~24:\n弗4:20 但你們並不是這樣學了基督;\n'
            '弗6:17 還要接受救恩的頭盔; 弗6:18 時時在靈裏禱告,\n提後3:15 提後3:16\n3\n我們的心思得更新—詩一一九105。\n'
            '2026 Living Stream Ministry\n1',
            '________________\n\n2\n第一篇(續)\n(三) 我們屬靈的行事為人—弗六12。\n2026 Living Stream Ministry\n2',
            '________________\n\n信徒(一) 第二篇\n召會\n讀經:弗一22~23\n壹 召會是基督的身體—弗一23。\n'
            '2026 Living Stream Ministry\n3')]
        with tempfile.TemporaryDirectory() as folder:
            report = outline_ocr.outline.convert(Path(folder)/'ts.pdf', folder, pages=pages,
                                                 checks=lambda m: outline_ocr.check_messages(m))
            markdown = (Path(folder)/'ts.md').read_text(encoding='utf-8')
        self.assertEqual([(m['number'], m['title']) for m in report['messages']],
                         [('一', '門徒、信徒、聖徒和基督徒'), ('二', '召會')])
        self.assertEqual(report['continuation_headers'], 1)
        self.assertEqual(report['messages'][0]['quoted_verses'], 7)
        self.assertIn('- 壹 我們是基督的門徒,就是跟從基督的人—太五1,弗四20~24:', markdown)
        self.assertIn('      - 3 我們的心思得更新—詩一一九105。', markdown)  # 單獨一行的標號接回下一行
        self.assertIn('    - (三) 我們屬靈的行事為人', markdown)
        self.assertIn('- 弗6:18 時時在靈裏禱告,', markdown)
        self.assertNotIn('Living Stream', markdown)
        self.assertNotIn('第一篇(續)', markdown)
        self.assertEqual(report['warnings'], [])

    def test_run_uses_cache_and_writes_markdown_with_checks(self):
        texts = [PAGE_ONE, PAGE_TWO, PAGE_THREE]
        calls = []

        def fake_ocr(service, image, language=None):
            calls.append(image)
            return texts[len(calls) - 1]

        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            pages = [(n, f'image{n}'.encode()) for n in (1, 2, 3)]
            render = lambda pdf, only=None: [(n, image) for n, image in pages if only is None or n in only]
            with mock.patch.object(outline_ocr, 'render_pages', side_effect=render), \
                    mock.patch.object(outline_ocr, 'page_count', return_value=3), \
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
            self.assertNotIn('verse_check', report)  # 沒有恢復本資料夾就不比對經文
            saved = json.loads((folder/'out'/'outline.report.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['ocr'], {'engine': 'google-drive', 'language': 'auto', 'cache': str(folder/'cache')})

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
                calls.append(('create', kwargs.get('ocrLanguage'), kwargs['body']['mimeType']))
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
        self.assertEqual(calls, [('create', None, 'application/vnd.google-apps.document'), ('export', 'text/plain'),
                                 ('delete', 'doc')])
        calls.clear()
        with mock.patch.object(outline_ocr.time, 'sleep') as sleep, self.assertRaises(HttpError):
            outline_ocr.google_ocr(mock.Mock(files=lambda: Files(fail=True)), b'jpeg')
        self.assertEqual(len(calls), 1)
        sleep.assert_not_called()

    def test_run_drops_rejected_language_hint_and_keeps_going(self):
        rejected = Exception('400')
        rejected.resp = mock.Mock(status=400)
        rejected.content = b'{"location": "ocrLanguage", "message": "Invalid Value"}'
        seen = []

        def fake_ocr(service, image, language=None):
            seen.append(language)
            if language:
                raise rejected
            return PAGE_THREE

        messages = []
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with mock.patch.object(outline_ocr, 'render_pages', return_value=[(1, b'a'), (2, b'b')]), \
                    mock.patch.object(outline_ocr, 'page_count', return_value=2), \
                    mock.patch.object(outline_ocr, 'google_ocr', side_effect=fake_ocr):
                report = outline_ocr.run(folder/'o.pdf', folder/'cache', folder/'out', None, language='zh-TW',
                                         log=messages.append)
        self.assertEqual(seen, ['zh-TW', None, None])  # 第一頁被拒後改自動偵測，之後不再送語言提示
        self.assertEqual(report['ocr']['language'], 'auto')
        self.assertTrue(any('自動偵測' in m for m in messages))

    def test_other_client_errors_are_not_hidden(self):
        other = Exception('403')
        other.resp = mock.Mock(status=403)
        other.content = b'{"reason": "insufficientPermissions"}'
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with mock.patch.object(outline_ocr, 'render_pages', return_value=[(1, b'a')]), \
                    mock.patch.object(outline_ocr, 'page_count', return_value=1), \
                    mock.patch.object(outline_ocr, 'google_ocr', side_effect=other), self.assertRaises(Exception) as caught:
                outline_ocr.run(folder/'o.pdf', folder/'cache', folder/'out', None, language='zh', log=lambda *_: None)
        self.assertIs(caught.exception, other)

    def test_ocr_fixes_unspaced_markers_chapter_misreads_and_stray_spaces(self):
        page = outline_ocr.ocr_text_to_page('\n'.join([
            '頁首', '第三篇 生命', '壹 甲事:', '一 第一點。', '二 第二點,說到『那', '生命』。',
            '三在全宇宙中只有一個生命—約壹-1~2,路-53,約+28。',  # 少了空白的標號；「一」讀成 -、「十」讀成 +
            '一個人若有生命就活着。',  # 不是下一個號碼（三之後應是四）：接回上一點
            '四 惟 一的生命—約一4。', '-', '永遠的生命:', '頁尾']))
        with tempfile.TemporaryDirectory() as folder:
            report = outline_ocr.outline.convert(Path(folder)/'x.pdf', folder, pages=[page],
                                                 checks=lambda m: outline_ocr.check_messages(m))
            markdown = (Path(folder)/'x.md').read_text(encoding='utf-8')
        self.assertIn('  - 三 在全宇宙中只有一個生命—約壹一1~2,路一53,約十28。一個人若有生命就活着。', markdown)
        self.assertIn('  - 四 惟一的生命—約一4。', markdown)
        self.assertIn('  - 一 永遠的生命:', markdown)
        self.assertEqual((report['unspaced_markers'], report['ocr_chapter_fixes']), (1, 3))
        self.assertEqual(report['invalid_references'], [])

    def test_wrapped_title_marker_before_header_and_glued_quote_tail(self):
        pages = [outline_ocr.ocr_text_to_page('\n'.join(lines)) for lines in (
            ['頁首', '第三篇', '甲、乙、', '丙和丁', '讀經:太三12', '太3:12 祂手裏拿着簸箕。 壹 信徒是麥子—太三12:', '頁尾', '1'],
            ['頁首', '壹', '第八篇', '認識基督', '讀經:太二1', '太2:1 經文內容。', '另一行經文。', '基督是王—太二1~2:',
             '頁尾', '2'])]
        with tempfile.TemporaryDirectory() as folder:
            report = outline_ocr.outline.convert(Path(folder)/'t.pdf', folder, pages=pages,
                                                 checks=lambda m: outline_ocr.check_messages(m))
            markdown = (Path(folder)/'t.md').read_text(encoding='utf-8')
        self.assertEqual([m['title'] for m in report['messages'] if m['number']], ['甲、乙、丙和丁', '認識基督'])
        self.assertIn('- 太3:12 祂手裏拿着簸箕。\n', markdown)  # 接在經文後面的要點拆出來
        self.assertIn('- 壹 信徒是麥子—太三12:', markdown)
        self.assertIn('讀經：太二1', markdown)
        self.assertIn('- 壹 基督是王—太二1~2:', markdown)  # 標號等到像要點的行，不接到經文內容
        self.assertIn('\n另一行經文。\n', markdown)
        self.assertEqual(report['quote_tails_split'], 1)

    def test_psalm_headings_and_print_variants_are_not_ocr_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            text = Path(folder)/'rv'
            text.mkdir()
            (text/'19-詩篇.txt').write_text('詩篇\n詩篇 第 23 篇\n1 耶和華是我的牧者，我必不致缺乏。\n'
                                          '2 祂使我躺臥在青草地上，領我在可安歇的水邊。\n', encoding='utf-8')
            (text/'40-馬太福音.txt').write_text('馬太福音 第 9 章\n12 耶穌聽見，就說，強健的人用不著醫生，有病的人纔用得著。\n',
                                           encoding='utf-8')
            verses = outline_ocr.load_recovery_version(text)
        self.assertIn(('詩', 23, 2), verses)
        messages = [{'number': '一', 'scripture': [], 'items': [], 'quotes': [
            {'ref': '太9:12', 'text': '耶穌聽見,就說,強健的人用不着醫生,有病的人纔用得着。'},
            {'ref': '詩23:1', 'text': '耶和華是我的牧者,我必不致缺乏。 二 我們要跟從祂。'}]}]
        check = outline_ocr.check_messages(messages, verses)['verse_check']
        self.assertEqual((check['quotes_checked'], check['errors'], check['unknown_refs']), (2, 0, []))
        self.assertGreater(check['cer_counting_print_variants'], 0)  # 着／著 只在原始字數裏算錯

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
            self.assertEqual(outline_ocr.page_count(path), 1)
            self.assertEqual(list(outline_ocr.render_pages(path, only=set())), [])
            self.assertTrue(rendered[0][1].startswith(b'\xff\xd8'))
            self.assertLessEqual(len(rendered[0][1]), outline_ocr.MAX_IMAGE_BYTES)


if __name__ == '__main__':
    unittest.main()
