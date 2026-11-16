import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import outline_pdf_to_md as converter  # noqa: E402

HEADER = '二○二六年冬季訓練　信息綱要'


def page(lines, height=800):
    """lines: (text, y, size)."""
    return {'height': height, 'width': 600, 'lines': [{'text': t, 'y': y, 'x': 50, 'size': s} for t, y, s in lines]}


def synthetic_pages():
    return [
        page([(HEADER, 20, 9), ('目　錄', 100, 16), ('第一篇　基督是神的奧祕..........1', 140, 11),
              ('第二篇　召會是基督的身體..........5', 160, 11), ('i', 780, 9)]),
        page([(HEADER, 20, 9), ('第一篇', 100, 16), ('基督是神的奧祕', 125, 16), ('讀經：西二2，一26～27，', 170, 11),
              ('弗三4', 186, 11), ('壹　神的奧祕是基督，', 220, 11), ('祂是神的具體化身——西二9。', 236, 11),
              ('一　基督是神的奧祕；召會是基督的奧祕——弗三4，五32。', 260, 11), ('1', 780, 9)]),
        page([(HEADER, 20, 9), ('1　我們需要看見⼀個異象——徒二六19。', 100, 11), ('a　在靈裏——約四24。', 120, 11),
              ('貳　召會是基督的身體——林前十二12，門16。', 150, 11), ('2', 780, 9)]),
        page([(HEADER, 20, 9), ('第二篇　召會是基督的身體', 100, 16), ('讀經：弗一22～23', 140, 11),
              ('壹　召會是基督的豐滿——弗一23。', 170, 11), ('3', 780, 9)]),
    ]


class OutlineConversionTests(unittest.TestCase):
    def convert(self, pages):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        report = converter.convert(Path(folder.name)/'outline.pdf', folder.name, pages=pages)
        markdown = (Path(folder.name)/'outline.md').read_text(encoding='utf-8')
        return report, markdown, Path(folder.name)

    def test_messages_scripture_points_and_wrapped_lines(self):
        report, markdown, folder = self.convert(synthetic_pages())
        numbers = [m['number'] for m in report['messages']]
        self.assertEqual(numbers, [None, '一', '二'])  # 目錄頁是篇題前的內容，不算一篇
        self.assertEqual(report['toc_lines_skipped'], 2)
        self.assertIn('## 第一篇　基督是神的奧祕', markdown)
        self.assertIn('讀經：西二2，一26～27，弗三4', markdown)
        self.assertIn('- 壹 神的奧祕是基督，祂是神的具體化身——西二9。', markdown)  # 換行接續、全形空白
        self.assertIn('  - 一 基督是神的奧祕', markdown)
        self.assertIn('    - 1 我們需要看見一個異象', markdown)  # 康熙部首「⼀」→「一」，跨頁仍在同一篇
        self.assertIn('      - a 在靈裏', markdown)
        self.assertNotIn(HEADER, markdown)
        self.assertEqual(report['running_lines_removed'], 8)
        first = report['messages'][1]
        self.assertEqual((first['title'], first['points'], first['unmarked_lines']), ('基督是神的奧祕', 5, 0))
        self.assertEqual(first['verse_references'], 8)
        self.assertEqual(report['warnings'], [])
        self.assertTrue((folder/'outline'/'02.md').read_text(encoding='utf-8').startswith('## 第二篇'))

    def test_verse_reference_pattern(self):
        found = converter.REF_RE.findall('見弗一23，三17～19；約十四6～7；林前十二12；詩二三1；門16；猶20～21。一個人')
        self.assertEqual(found, ['弗一23，三17～19', '約十四6～7', '林前十二12', '詩二三1', '門16', '猶20～21'])
        self.assertEqual(converter.REF_RE.findall('多一些亞伯拉罕來二十個人'), [])

    def test_warnings_for_scanned_pages_private_use_and_missing_scripture(self):
        pages = [page([('第一篇　標題', 100, 16), ('壹　要點', 140, 11)]), page([])]
        report, _, _ = self.convert(pages)
        text = '\n'.join(report['warnings'])
        self.assertIn('沒有文字層', text)
        self.assertIn('私用區', text)
        self.assertIn('第一篇沒有「讀經：」行', text)

    @unittest.skipUnless(importlib.util.find_spec('pymupdf'), 'PyMuPDF not installed')
    def test_real_pdf_text_layer(self):
        import pymupdf
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'sample.pdf'
            document = pymupdf.open()
            for source in synthetic_pages():
                pdf_page = document.new_page(width=600, height=800)
                for line in source['lines']:
                    pdf_page.insert_text((50, line['y'] + line['size']), line['text'], fontname='china-t',
                                         fontsize=line['size'])
            document.save(path)
            report = converter.convert(path, Path(folder)/'out')
            self.assertEqual([m['number'] for m in report['messages']], [None, '一', '二'])
            self.assertEqual(report['messages'][1]['verse_references'], 8)
            self.assertEqual(report['pages_without_text'], [])
            saved = json.loads((Path(folder)/'out'/'sample.report.json').read_text(encoding='utf-8'))
            self.assertEqual(saved['pages'], 4)


if __name__ == '__main__':
    unittest.main()
