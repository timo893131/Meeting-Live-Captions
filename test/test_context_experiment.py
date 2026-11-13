import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import context_experiment as cx  # noqa: E402


def record(i, site, **extra):
    return dict(i=i, site=site, seconds=10, latency=1.0, neurons=7.77, **extra)


class ContextExperimentTests(unittest.TestCase):
    def test_reference_region_follows_unique_anchors(self):
        reference = '甲乙丙丁戊己庚辛壬癸' * 3 + '我們今天讀以弗所書第一章講到神的經綸' + '子丑寅卯辰巳午未申酉' * 3
        hypothesis = '我們今天讀以服所書第一章講到神的經倫'
        start, end = cx.reference_region(reference, hypothesis, margin=0)
        self.assertIn('第一章講到神的', reference[start:end])
        self.assertLess(end - start, 30)
        self.assertIsNone(cx.reference_region(reference, '完全無關的句子'))

    def test_prepare_keeps_chunks_inside_the_window_with_full_indices(self):
        import numpy as np
        from unittest import mock
        rate = cx.ev.RATE
        samples = np.full(60*rate, 0.25, np.float32)
        spans = [(0, 8*rate), (9*rate, 18*rate), (20*rate, 29*rate), (29*rate, 41*rate), (45*rate, 50*rate)]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)/'data'; data.mkdir()
            (data/'01.mp3').write_bytes(b'mp3'); (data/'01.txt').write_text('參考', encoding='utf-8')
            args = type('A', (), dict(data=str(data), output=str(Path(tmp)/'prep'), only=None, window_start=9, window_seconds=31))
            with mock.patch.object(cx.ev, 'decode_audio', return_value=samples), \
                 mock.patch.object(cx.ev, 'live_spans', return_value=spans), contextlib.redirect_stdout(io.StringIO()):
                cx.prepare(args)
            meta = json.loads((Path(tmp)/'prep/01.chunks.json').read_text(encoding='utf-8'))
            pcm = (Path(tmp)/'prep/01.chunks.s16').read_bytes()
        self.assertEqual([c['full_index'] for c in meta['chunks']], [1, 2])     # 29–41 s ends after the window
        self.assertEqual(meta['total_chunks'], 5)
        self.assertEqual(meta['duration_seconds'], 31)
        self.assertEqual(len(pcm), 2*18*rate)
        self.assertEqual(meta['pcm_sha256'], __import__('hashlib').sha256(pcm).hexdigest())

    def make_run(self, root, development):
        data, prepared, run = root/'data', root/'prep', root/'run'
        for folder in (data, prepared, run):
            folder.mkdir()
        (data/'01.txt').write_text('我們讀以弗所書，看見神的經綸在召會中。', encoding='utf-8')
        meta = dict(pair='01', duration_seconds=1800, window=[0, 1800] if development else None, chunks=[], total_chunks=2)
        (prepared/'01.chunks.json').write_text(json.dumps(meta), encoding='utf-8')
        base = ['我們讀以弗所書看見', '神的經倫在照會中']
        prompt = ['我們讀以弗所書看見', '神的經綸在照會中']
        (run/'01.whisper_base.json').write_text(json.dumps(dict(complete=True, records=[record(i, t) for i, t in enumerate(base)])), encoding='utf-8')
        (run/'01.whisper_prompt.json').write_text(json.dumps(dict(complete=True, records=[
            record(0, prompt[0], prompt=None), record(1, prompt[1], prompt='以弗所書。我們讀以弗所書看見')])), encoding='utf-8')
        llm = [dict(i=0, site=base[0], called=False, final=base[0], final_unguarded=base[0], candidates=[]),
               dict(i=1, site=base[1], called=True, final='神的經綸在召會中', final_unguarded='神的經綸在召會之中',
                    edits=[{'from': '經倫', 'to': '經綸'}, {'from': '照會', 'to': '召會'}, {'from': '在照會中', 'to': '在召會之中'}],
                    accepted=[{'from': '經倫', 'to': '經綸', 'index': 2}, {'from': '照會', 'to': '召會', 'index': 5}],
                    rejected=[{'from': '在照會中', 'to': '在召會之中', 'reason': 'length'}], parse_error=False,
                    tokens_in=300, tokens_out=30, latency=1.5, neurons=2.5)]
        (run/'01.llm_base__qwen.json').write_text(json.dumps(dict(complete=True, model='@cf/qwen/x', source='base', records=llm)), encoding='utf-8')
        (run/'01.llm_base__partial.partial.json').write_text('[]', encoding='utf-8')
        return data, prepared, run

    def score(self, development):
        with tempfile.TemporaryDirectory() as tmp:
            data, prepared, run = self.make_run(Path(tmp), development)
            args = type('A', (), dict(run=str(run), data=str(data), prepared=str(prepared), development=development))
            with contextlib.redirect_stdout(io.StringIO()):
                cx.score(args)
            return (json.loads((run/'context-report.json').read_text(encoding='utf-8')),
                    (run/'context-summary.md').read_text(encoding='utf-8'))

    def test_sealed_score_totals_only(self):
        report, summary = self.score(development=False)
        self.assertTrue(report['sealed_test'])
        totals = report['totals']
        self.assertEqual(set(totals), {'base', 'prompt', 'llm|@cf/qwen/x', 'llm|@cf/qwen/x|unguarded'})
        self.assertGreater(totals['llm|@cf/qwen/x']['terms_correct'], totals['base']['terms_correct'])
        self.assertGreater(totals['llm|@cf/qwen/x']['chars_fixed_vs_base'], 0)
        self.assertEqual(report['stats']['llm|@cf/qwen/x']['rejected'], {'length': 1})
        self.assertIn('語言模型 5 neurons／小時', summary)          # 2.5 neurons in half an hour
        self.assertIn('CER', summary)
        self.assertNotIn('修改明細', summary)                      # sealed test: no per-caption details
        self.assertNotIn('照會', summary)

    def test_development_lists_edits_for_review(self):
        report, summary = self.score(development=True)
        self.assertFalse(report['sealed_test'])
        self.assertIn('修改明細', summary)
        self.assertIn('經倫→經綸', summary)
        self.assertIn('擋下（length）', summary)


class NotebookTests(unittest.TestCase):
    def test_notebook_is_pinned_unexecuted_and_guards_meet(self):
        import ast
        import re
        notebook = json.loads((ROOT/'notebooks/context_correction_experiment.ipynb').read_text(encoding='utf-8'))
        source = ''
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                text = ''.join(cell['source'])
                ast.parse(text)
                self.assertIsNone(cell['execution_count']); self.assertEqual(cell['outputs'], [])
                source += text
        self.assertRegex(source, r"COMMIT = '[0-9a-f]{40}'")
        self.assertIn('NEURON_CAP = 6000', source)
        self.assertIn('if not CONFIRM_MEET', source)
        self.assertIn('len(models) != 1', source)
        self.assertNotRegex(source, r'CF_API_TOKEN\s*=\s*[\'"]')   # the token only comes from Colab secrets


    def test_near_sound_notebook_is_pinned_unexecuted_and_guards_meet(self):
        import ast
        notebook = json.loads((ROOT/'notebooks/phonetic_near_check.ipynb').read_text(encoding='utf-8'))
        source = ''
        for cell in notebook['cells']:
            if cell['cell_type'] == 'code':
                text = ''.join(cell['source'])
                ast.parse(text)
                self.assertIsNone(cell['execution_count']); self.assertEqual(cell['outputs'], [])
                source += text
        self.assertRegex(source, r"COMMIT = '[0-9a-f]{40}'")
        self.assertIn('if not CONFIRM_MEET', source)
        self.assertIn('--phonetic-near', source)
        self.assertNotIn('--model-dir', source)   # re-scoring only: no recognition, no Cloudflare


if __name__ == '__main__':
    unittest.main()
