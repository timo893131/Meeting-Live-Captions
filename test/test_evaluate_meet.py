import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import evaluate_meet as ev


class ScoringTests(unittest.TestCase):
    def test_reference_cleaning_keeps_words_and_drops_markdown(self):
        text = '### 第一章　神的經綸\r\n\r\n**神聖的分賜**（約四24）\n> 引用'
        cleaned = ev.clean_reference(text)
        self.assertNotIn('#', cleaned); self.assertNotIn('**', cleaned); self.assertNotIn('>', cleaned)
        self.assertEqual(ev.normalize(cleaned), '第一章神的經綸神聖的分賜約四24引用')
        self.assertEqual(ev.normalize(ev.without_parentheses(cleaned)), '第一章神的經綸神聖的分賜引用')

    def test_simplified_hypothesis_is_compared_in_traditional(self):
        from opencc import OpenCC
        self.assertEqual(ev.normalize('神的经纶，召会！', OpenCC('s2tw')), '神的經綸召會')

    def test_cer_term_accuracy_and_fixed_broken_counts(self):
        reference = '我們讀以弗所書和召會生活'
        spans = ev.term_spans(reference, ev.church_terms())
        self.assertEqual([t for _, _, t in spans], ['以弗所書', '召會生活'])
        bad, ok_bad = ev.score(reference, '我們讀以服所書和詔會生活', spans)
        good, ok_good = ev.score(reference, reference, spans)
        self.assertEqual((bad['terms_correct'], good['terms_correct']), (0, 2))
        self.assertAlmostEqual(bad['cer'], 2/12, places=3); self.assertEqual(good['cer'], 0)
        self.assertEqual(sum(b and not a for a, b in zip(ok_bad, ok_good)), 2)

    def test_live_corrections_are_applied_per_segment(self):
        out = ev.corrections(['我們讀以服所書', '耶蘇愛我'])
        self.assertEqual(out['phonetic'], ['我們讀以弗所書', '耶穌愛我'])
        self.assertEqual(out['glossary'][1], '耶穌愛我')

    def test_chrome_export_lines_drop_times(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'01.chrome.txt'
            path.write_text('上午10:01:02 第一句\n下午3:04:05 第二句\n\n沒有時間的行\n', encoding='utf-8')
            self.assertEqual(ev.chrome_segments(path), ['第一句', '第二句', '沒有時間的行'])

    def test_chrome_only_run_scores_raw_and_corrected(self):
        with tempfile.TemporaryDirectory() as folder:
            meet = Path(folder)/'MEET'; meet.mkdir()
            (meet/'01.mp3').write_bytes(b'ID3synthetic')
            (meet/'01.txt').write_text('## 標題\n我們讀以弗所書', encoding='utf-8')
            (meet/'01.chrome.txt').write_text('上午10:00:00 標題我們讀以服所書\n', encoding='utf-8')
            sys.argv = ['evaluate_meet.py', '--meet', str(meet), '--output', str(Path(folder)/'run')]
            ev.main()
            report = json.loads((Path(folder)/'run/report.json').read_text(encoding='utf-8'))
            variants = report['pairs'][0]['conditions'][0]['variants']
            self.assertEqual(variants['full/raw']['terms_correct'], 0)
            self.assertEqual(variants['full/phonetic']['cer'], 0)
            self.assertTrue(report['sealed_test'])


if __name__ == '__main__':
    unittest.main()
