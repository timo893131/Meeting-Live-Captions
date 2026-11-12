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

    def test_error_breakdown_and_long_deletions(self):
        reference = '甲'*30 + '乙丙丁'
        metrics, _ = ev.score(reference, '乙戊丁X', [])
        self.assertEqual((metrics['substitutions'], metrics['deletions'], metrics['insertions']), (1, 30, 1))
        self.assertEqual((metrics['long_deletion_runs'], metrics['long_deletion_chars']), (1, 30))

    def test_live_chunks_cut_in_pauses_and_split_long_speech(self):
        r = ev.RATE
        regions = [dict(start=0, end=4*r), dict(start=5*r, end=9*r), dict(start=10*r, end=14*r),
                   dict(start=16*r, end=50*r)]
        chunks = ev.vad_chunks(regions, 60*r, 10*r)
        self.assertEqual(chunks[0], (0, 9*r))            # two pauses-separated phrases fit in 10 s
        self.assertTrue(all(end - start <= 10*r for start, end in chunks))
        self.assertEqual(chunks[-1][1], 50*r)
        self.assertEqual(ev.fixed_chunks(25*r, 10*r), [(0, 10*r), (10*r, 20*r), (20*r, 25*r)])

    def test_hymn_is_removed_for_speech_only_and_sung_text_is_not_counted(self):
        text = '講道第一段。\n講道最後一句話到此結束了。\n\n一　哦主，在我你是生命，\n（副）哦主，你是生命之靈，\n二　第二節歌詞'
        speech = ev.without_hymn(text)
        self.assertEqual(ev.normalize(speech), '講道第一段講道最後一句話到此結束了')
        self.assertEqual(ev.without_hymn('只有講道\n一　單獨一行編號'), '只有講道\n一　單獨一行編號')
        reference = ev.normalize('前面的內容' * 10 + speech)
        hypothesis = reference + '唱歌被辨識成的許多文字唱歌被辨識成的許多文字'
        self.assertEqual(ev.cut_after_reference_end(reference, hypothesis), reference)

    def test_bag_counts_do_not_need_alignment(self):
        reference = ev.normalize('召會生活在以弗所書。神的經綸。召會')
        spans = ev.category_spans(reference, ev.church_terms(), ev.bible_names())
        hypothesis = ev.normalize('講員說了很多話：神的經綸、以弗所書、召會、召會、召會')
        metrics, _ = ev.score(reference, hypothesis, spans)
        # Text: 召會生活, 以弗所書, 經綸, 召會 (召會生活 is one longer term). Heard: all but 召會生活, 召會 three times.
        self.assertEqual((metrics['term_occurrences'], metrics['terms_bag_found'], metrics['terms_bag_extra']), (4, 3, 2))

    def test_life_study_dev_set_uses_single_audio_messages_and_skips_shared_books(self):
        sys.path.insert(0, str(ROOT/'scripts'))
        import build_life_study_dev_set as dev
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for n, messages in ((1, [1, 2, 3]), (10, [1, 2]), (40, [1, 2])):
                name = dev.archive.folder(n)
                (root/'life-study/text'/name).mkdir(parents=True); (root/'life-study/audio'/name).mkdir(parents=True)
                for k in messages:
                    (root/'life-study/text'/name/f'{k:03d}.txt').write_text(f'第{k}篇 召會', encoding='utf-8')
                    (root/'life-study/audio'/name/f'{k:03d}.mp3').write_bytes(b'ID3' + bytes([k]))
            (root/'life-study/audio'/dev.archive.folder(40)/'002-2.mp3').write_bytes(b'ID3')
            found = dev.available(root)
            self.assertEqual(found, {1: [1, 2, 3], 40: [1]})  # 10 shares 9's Life-Study; 40/002 has two parts
            picks = dev.pick(found, 2)
            self.assertEqual(picks[0][0], 1); self.assertNotEqual(picks[0][1], 1)
            sys.argv = ['x', '--archive', str(root), '--output', str(root/'dev'), '--count', '2']
            dev.main()
            manifest = json.loads((root/'dev/manifest.json').read_text(encoding='utf-8'))
            self.assertEqual([m['reference'] for m in manifest], ['not_verbatim', 'not_verbatim'])
            self.assertTrue((root/'dev/01.mp3').exists() and (root/'dev/02.txt').exists())

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


class WorkersAITests(unittest.TestCase):
    def test_condition_names(self):
        self.assertEqual(ev.condition_name('cfvad10'), 'workers_ai_live_vad_10s')
        self.assertEqual(ev.condition_name('vad10'), 'whisper_live_vad_10s')

    def test_request_reads_text_and_stops_on_daily_allocation(self):
        import io, urllib.error, numpy as np
        sent = []

        class Response(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def ok(request, timeout):
            sent.append(json.loads(request.data))
            return Response(json.dumps({'success': True, 'result': {'text': ' 召會生活 '}}).encode())
        text = ev.workers_ai_request(np.zeros(1600, np.float32), 'acct', 'tok', opener=ok)
        self.assertEqual(text, '召會生活')
        self.assertEqual((sent[0]['language'], sent[0]['vad_filter'], sent[0]['condition_on_previous_text']), ('zh', False, False))

        def quota(request, timeout):
            body = io.BytesIO(json.dumps({'errors': [{'code': 3036, 'message': 'Account limited'}]}).encode())
            raise urllib.error.HTTPError(request.full_url, 429, 'Too Many Requests', {}, body)
        with self.assertRaises(ev.QuotaExhausted):
            ev.workers_ai_request(np.zeros(1600, np.float32), 'acct', 'tok', opener=quota)

    def test_budget_stops_and_resume_continues_from_saved_chunks(self):
        import numpy as np
        from unittest import mock
        samples = np.zeros(25*ev.RATE, np.float32)
        calls = []
        fake = lambda chunk, account, token: calls.append(len(chunk)) or f'第{len(calls)}段'
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ev, 'decode_audio', return_value=samples), \
                mock.patch.dict('os.environ', {'CF_ACCOUNT_ID': 'a', 'CF_API_TOKEN': 't'}):
            partial = Path(folder)/'01.partial.json'
            with self.assertRaises(ev.QuotaExhausted):  # 10 s chunks; budget allows two
                ev.transcribe_workers_ai('01.mp3', 'fixed', 10, partial, dict(used=0, max=21/60), request=fake)
            self.assertEqual(len(json.loads(partial.read_text(encoding='utf-8'))), 2)
            texts, timing = ev.transcribe_workers_ai('01.mp3', 'fixed', 10, partial, dict(used=0, max=10), request=fake)
        self.assertEqual(texts, ['第1段', '第2段', '第3段'])
        self.assertEqual(calls, [10*ev.RATE, 10*ev.RATE, 5*ev.RATE])
        self.assertEqual(timing['chunks'], 3)
        self.assertGreater(timing['neurons_estimate'], 0)


    def test_run_pauses_on_budget_and_resumes_with_reuse(self):
        import numpy as np
        from unittest import mock
        samples = np.zeros(25*ev.RATE, np.float32)
        fake = mock.Mock(side_effect=lambda chunk, account, token: '我們讀以服所書')
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ev, 'decode_audio', return_value=samples), \
                mock.patch.object(ev, 'workers_ai_request', fake), \
                mock.patch.dict('os.environ', {'CF_ACCOUNT_ID': 'a', 'CF_API_TOKEN': 't'}):
            meet = Path(folder)/'MEET'; meet.mkdir()
            (meet/'01.mp3').write_bytes(b'ID3synthetic')
            (meet/'01.txt').write_text('我們讀以弗所書', encoding='utf-8')
            first, second = Path(folder)/'run1', Path(folder)/'run2'
            sys.argv = ['evaluate_meet.py', '--meet', str(meet), '--output', str(first), '--conditions', 'cffixed10',
                        '--cf-max-minutes', str(15/60)]
            with self.assertRaises(SystemExit) as stopped:
                ev.main()
            self.assertEqual(stopped.exception.code, 3)
            sys.argv = ['evaluate_meet.py', '--meet', str(meet), '--output', str(second), '--conditions', 'cffixed10',
                        '--reuse', str(first)]
            ev.main()
            report = json.loads((second/'report.json').read_text(encoding='utf-8'))
        self.assertEqual(fake.call_count, 3)  # one chunk before the pause, two after: none sent twice
        condition = report['pairs'][0]['conditions'][0]
        self.assertEqual(condition['condition'], 'workers_ai_live_fixed_10s')
        self.assertEqual(condition['variants']['full/phonetic']['terms_correct'], 1)
        self.assertEqual(report['workers_ai_model'], ev.CF_MODEL)


if __name__ == '__main__':
    unittest.main()
