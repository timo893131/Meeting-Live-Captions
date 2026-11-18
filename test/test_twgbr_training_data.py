"""M3 builder (scripts/build_twgbr_training_data.py) on synthetic data: no real audio, text or model.
Needs rapidfuzz, numpy, opencc-python-reimplemented, beautifulsoup4, pypinyin (.venv); skipped otherwise."""
import array
import copy
import importlib.util
import json
import math
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
MISSING = [name for name in ('rapidfuzz', 'numpy', 'opencc', 'bs4', 'pypinyin') if importlib.util.find_spec(name) is None]

if not MISSING:
    import numpy as np
    from opencc import OpenCC
    import build_twgbr_training_data as m
    import cloud_training_data as gate

VERSES = ['起初神創造諸天與地。', '而地變為荒廢空虛，淵面黑暗；神的靈覆翼在水面上。', '神說，要有光，就有了光。',
          '神看光是好的，就把光暗分開了。', '神稱光為晝，稱暗為夜；有晚上，有早晨，是頭一日。',
          '神說，諸水之間要有廣闊的空間，將水與水分開。', '神就造出廣闊的空間，將空間以下的水，與空間以上的水分開；事就這樣成了。',
          '神稱廣闊的空間為天；有晚上，有早晨，是第二日。']
CHAR, PAUSE = 0.22, 0.6


def message_verses(message):
    """Life-Study fixture text: different per message, so recordings do not share clip texts."""
    return [v.replace('神', '神主父子'[message - 1]) for v in VERSES]


def speech(phrases, converter_input=lambda t: t):
    """Whisper-like words (one per char, simplified/punctuation-free) with pauses between phrases."""
    words, t = [], 0.4
    for phrase in phrases:
        for char in phrase:
            if char in '，。；：、':
                t += 0.15
                continue
            words.append([round(t, 3), round(t + CHAR, 3), converter_input(char)]); t += CHAR
        t += PAUSE
    return words, t + 0.4


@unittest.skipIf(MISSING, f'needs {MISSING}')
class AlignmentTests(unittest.TestCase):
    def clips(self, phrases, text, kind='bible', by_sound=True):
        words, total = speech(phrases)
        reference, positions = m.reference_chars(text)
        chars = m.hypothesis_chars(words)
        hypothesis = ''.join(c for c, _, _ in chars)
        keys = (m.sounds(hypothesis), m.sounds(reference)) if by_sound else None
        match = m.align(hypothesis, reference, keys)
        return m.make_clips(chars, match, reference, text, positions, total, m.POLICY['max_cer'][kind], m.POLICY, keys)

    def test_spelling_variants_and_names_heard_by_sound_do_not_count_against_a_clip(self):
        # 裡/裏, 他/祂, 積澱/基甸: the audio says the text; Whisper only writes it differently.
        text = '\n'.join(['基甸在酒醡那裏打麥子，為要防備米甸人。', '耶和華的使者向基甸顯現，對他說，大能的勇士阿，耶和華與你同在。',
                          '基甸說，主阿，耶和華若與我們同在，我們何至遭遇這一切事？祂的奇事在哪裏？'])
        heard = [line.replace('裏', '裡').replace('基甸', '積澱').replace('祂', '他').replace('阿', '啊') for line in text.split('\n')]
        by_chars, rejected = self.clips(heard, text, by_sound=False)
        by_sound, _ = self.clips(heard, text)
        self.assertTrue(rejected)  # by chars these clips look 10-15 % wrong
        self.assertEqual(''.join(c['text'] for c in by_sound), text.replace('\n', ''))  # by sound: all of it, labelled with the text
        self.assertTrue(all(c['alignment_cer'] == 0 and c['char_cer'] > 0.05 for c in by_sound))

    def test_clean_reading_becomes_5_to_30_s_clips_labelled_with_the_original_text(self):
        text = '\n'.join(VERSES)
        clips, rejected = self.clips(VERSES, text)
        self.assertTrue(clips)
        self.assertEqual(rejected, {})
        self.assertEqual(''.join(c['text'] for c in clips), ''.join(VERSES))  # covers everything, keeps punctuation
        for clip in clips:
            self.assertTrue(5 <= clip['end'] - clip['start'] <= 30, clip)
            self.assertEqual(clip['alignment_cer'], 0)
            self.assertIn(clip['text'][-1], '，。；')  # cut at a pause, after the punctuation

    def test_speaker_remarks_not_in_the_text_never_enter_a_label(self):
        remark = '弟兄姊妹我們在這裡要停一下好好的來看看這一點非常要緊'
        phrases = VERSES[:4] + [remark] + VERSES[4:]
        clips, rejected = self.clips(phrases, '\n'.join(VERSES), kind='life_study')
        self.assertTrue(clips)
        joined = ''.join(c['text'] for c in clips)
        self.assertNotIn('弟兄', joined)
        for clip in clips:
            self.assertNotIn('弟兄', clip['text'])
            self.assertLessEqual(clip['alignment_cer'], 0.15)
        # The clip around the remark cannot match the text: it is cut away or rejected, never kept.
        self.assertFalse(any('弟兄' in c['whisper'] for c in clips))

    def test_misheard_words_count_against_the_threshold(self):
        heard = [v.translate(str.maketrans('神光水暗', '人燈火明')) for v in VERSES]  # different sounds
        clean, _ = self.clips(VERSES, '\n'.join(VERSES))
        clips, rejected = self.clips(heard, '\n'.join(VERSES))
        self.assertLess(sum(c['end'] - c['start'] for c in clips), sum(c['end'] - c['start'] for c in clean))
        self.assertTrue(all(c['alignment_cer'] <= 0.10 for c in clips))
        self.assertTrue(all(c['text'] in ''.join(VERSES) for c in clips))  # the label is still the published text

    def test_a_short_pause_is_enough_where_the_text_has_punctuation(self):
        words, total = speech(VERSES)
        reference, positions = m.reference_chars('\n'.join(VERSES))
        chars = m.hypothesis_chars(words)  # word ends stretched to 0.1 s before the next word, as Whisper often does
        chars = [(c, a, chars[i+1][1] - 0.1 if i + 1 < len(chars) else b) for i, (c, a, b) in enumerate(chars)]
        match = m.align(''.join(c for c, _, _ in chars), reference)
        breaks = m.punctuation_breaks('\n'.join(VERSES), positions)
        self.assertEqual(m.cut_points(chars, match, 0.25, 2), [0, len(chars)])
        points = m.cut_points(chars, match, 0.25, 2, breaks, 0.08)
        self.assertGreater(len(points), 10)
        self.assertTrue(all(match[b-1] in breaks for b in points[1:-1]))  # never inside a phrase

    def test_label_keeps_punctuation_and_turns_heading_line_breaks_into_a_stop(self):
        text = '神創造天地\n起初神創造諸天與地。'
        reference, positions = m.reference_chars(text)
        self.assertEqual(m.label_text(text, positions, 0, len(reference)), '神創造天地。起初神創造諸天與地。')

    def test_psalms_chapters_are_found_by_their_篇_headings(self):
        import build_bible_dev_set as bible_dev
        book = '\n'.join(['詩篇', '詩篇 第 1 篇', '1 不從惡人的計謀，', '詩篇 第 2 篇', '1 外邦為甚麼吼鬧，', '詩篇 第 3 篇', '1 耶和華阿，'])
        self.assertEqual(bible_dev.chapter_text(book, '詩篇', 1), '不從惡人的計謀，')
        self.assertEqual(bible_dev.chapter_text(book, '詩篇', 2), '外邦為甚麼吼鬧，')

    def test_split_is_stable_and_about_two_percent(self):
        ids = [f'rv-{b:02d}-{c:03d}' for b in range(1, 67) for c in range(1, 20)]
        validation = [i for i in ids if m.split_of(i) == 'validation']
        self.assertEqual(validation, [i for i in ids if m.split_of(i) == 'validation'])
        self.assertTrue(0.005 < len(validation)/len(ids) < 0.05, len(validation))


def write_wav(path, seconds):
    step = 0.02 + (int(m.sha256_bytes(str(path).encode())[:6], 16) % 1000)/20000  # distinct audio per file
    values = (np.sin(np.arange(int(seconds*16000))*step)*8000).astype('<i2')
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(16000); out.writeframes(values.tobytes())


def read_wav(path):
    with wave.open(str(path), 'rb') as stream:
        return np.frombuffer(stream.readframes(stream.getnframes()), '<i2').astype(np.float32)/32768


@unittest.skipIf(MISSING, f'needs {MISSING}')
class PipelineTests(unittest.TestCase):
    def archive(self, root):
        """Genesis 1-3 (chapter 3 is in the bible dev set) and Life-Study of Genesis messages 1-4 (2 has two audio
        files; 4 is the life-study dev-set pick, which is excluded even without that dev set's manifest)."""
        archive = root/'twgbr-archive'
        book = ['創世記']
        for chapter in (1, 2, 3):
            book += [f'創世記 第 {chapter} 章'] + [f'{i} {v}' for i, v in enumerate(VERSES, 1)]
            write_wav(archive/f'recovery-version/audio/01-創世記/{chapter:03d}.mp3', speech(VERSES)[1])
        (archive/'recovery-version/text').mkdir(parents=True)
        (archive/'recovery-version/text/01-創世記.txt').write_text('\n'.join(book) + '\n', encoding='utf-8')
        (archive/'bible-dev-v1').mkdir()
        (archive/'bible-dev-v1/manifest.json').write_text(json.dumps([{'book': 1, 'chapter': 3}]), encoding='utf-8')
        for message in (1, 2, 3, 4):
            (archive/'life-study/text/01-創世記').mkdir(parents=True, exist_ok=True)
            (archive/f'life-study/text/01-創世記/{message:03d}.txt').write_text('\n'.join(message_verses(message)), encoding='utf-8')
            write_wav(archive/f'life-study/audio/01-創世記/{message:03d}.mp3', speech(message_verses(message))[1])
        write_wav(archive/'life-study/audio/01-創世記/002-2.mp3', 1)
        return archive

    def build(self, root, life_study_messages=5):
        archive, output = self.archive(root), root/'data/twgbr-v1'
        plan = m.plan(archive, life_study_messages)
        for row in plan['recordings']:  # a fixed split for the fixture (real runs use split_of)
            row['split'] = 'validation' if row['id'] == 'rv-01-002' else 'train'
        for row in plan['recordings']:
            words, total = speech(VERSES if row['kind'] == 'bible' else message_verses(row['message']))
            if row['id'] == 'ls-01-001':
                words = [[s, e, '灵' if w == '靈' else w] for s, e, w in words]  # simplified output is converted
            (output/'cache').mkdir(parents=True, exist_ok=True)
            (output/'cache'/f'{row["id"]}.json').write_text(json.dumps(dict(
                id=row['id'], audio_sha256=m.sha256_file(archive/row['audio']), audio_seconds=total, words=words)), encoding='utf-8')
        report = m.segment(plan, archive, output, OpenCC('s2tw'), decode=read_wav)
        return archive, output, plan, report

    def test_plan_excludes_dev_sets_and_multi_part_messages(self):
        with tempfile.TemporaryDirectory() as folder:
            plan = m.plan(self.archive(Path(folder)), 5)
            ids = [r['id'] for r in plan['recordings']]
            self.assertEqual(sorted(ids), ['ls-01-001', 'ls-01-003', 'rv-01-001', 'rv-01-002'])
            reasons = {e['id']: e['reason'] for e in plan['excluded']}
            self.assertEqual(reasons['rv-01-003'], 'bible_dev_set')
            self.assertEqual(reasons['ls-01-002'], 'several_audio_files')
            self.assertEqual(reasons['ls-01-004'], 'life_study_dev_set')
            self.assertEqual(m.plan(self.archive(Path(folder)/'again'), 1)['counts']['life_study'], 1)

    def test_segment_writes_gate_ready_manifests_and_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            archive, output, plan, report = self.build(root)
            train = [json.loads(l) for l in (output/'manifests/train.jsonl').read_text(encoding='utf-8').splitlines()]
            validation = [json.loads(l) for l in (output/'manifests/validation.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(train)
            # Same verses in every fixture recording: validation clips repeat train text, so they are dropped.
            self.assertEqual(validation, [])
            self.assertGreater(report['validation_dropped_same_text_as_train'], 0)
            row = train[0]
            self.assertEqual(row['license_status'], 'owner_internal_decision')
            self.assertEqual(row['rights_evidence_ref'], 'docs/spec-large-meeting.md#2')
            self.assertEqual(row['transcript_status'], 'source_text_aligned')
            self.assertIsNone(row['speaker_id'])
            sources = {'rv': ''.join(VERSES), 'ls': {f'ls-01-{k:03d}': ''.join(message_verses(k)) for k in (1, 3)}}
            for r in train:  # every label is a piece of its own recording's text
                self.assertIn(r['text'], sources['rv'] if r['recording_id'].startswith('rv') else sources['ls'][r['recording_id']])
            self.assertFalse(any('灵' in r['text'] for r in train))  # labels are the publisher's text, never Whisper's
            self.assertTrue(any(r['recording_id'] == 'ls-01-001' and '靈' in r['text'] for r in train))
            with wave.open(str(output/row['audio_filepath'])) as clip:
                self.assertEqual((clip.getframerate(), clip.getnchannels(), clip.getsampwidth()), (16000, 1, 2))
                self.assertAlmostEqual(clip.getnframes()/16000, row['duration'], places=2)
            self.assertIn('恢復本朗讀', (output/'reports/data-report.md').read_text(encoding='utf-8'))
            self.assertEqual(report['by_source']['bible']['recordings_transcribed'], 2)
            # Rerun reuses the saved rows (same stamp) and gives identical manifests.
            before = (output/'manifests/train.jsonl').read_bytes()
            m.segment(plan, archive, output, OpenCC('s2tw'), decode=lambda p: self.fail('audio decoded again'))
            self.assertEqual((output/'manifests/train.jsonl').read_bytes(), before)

    def gate_config(self, output):
        config = json.loads((ROOT/'training/cloud-whisper-lora.json').read_text())
        config['data'].update(root=str(output), require_known_speakers=False)
        return config

    def with_test_and_validation(self, output, train):
        """Move one recording to validation and add a synthetic human-verified test row, as M4 will."""
        moved = [r for r in train if r['recording_id'] == 'ls-01-003']
        kept = [r for r in train if r['recording_id'] != 'ls-01-003' and r['text'] not in {x['text'] for x in moved}]
        for r in moved:
            r.update(split='validation', training_ready=False, evaluation_ready=True)
        test_wav = output/'test/sealed.wav'
        write_wav(test_wav, 6)
        test = dict(id='t1', audio_filepath='test/sealed.wav', text='合成測試句', duration=6.0, sha256=m.sha256_file(test_wav),
                    split='test', recording_id='meet-x', speaker_id='s1', license_status='approved', allowed_uses=['internal_evaluation'],
                    rights_evidence_ref='synthetic', evaluation_ready=True, transcript_status='human_verified',
                    local_reference_verified=True, near_duplicate_review='passed')
        return kept, moved, test

    def write_manifests(self, output, kept, moved, test):
        for name, rows in (('train', kept), ('validation', moved), ('test', [test])):
            (output/f'manifests/{name}.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')

    def test_gate_accepts_the_explicit_categories_and_nothing_looser(self):
        with tempfile.TemporaryDirectory() as folder:
            _, output, _, _ = self.build(Path(folder))
            train = [json.loads(l) for l in (output/'manifests/train.jsonl').read_text(encoding='utf-8').splitlines()]
            kept, moved, test = self.with_test_and_validation(output, train)
            self.assertTrue(kept and moved)
            self.write_manifests(output, kept, moved, test)
            report, data = gate.inspect_manifests(self.gate_config(output))
            self.assertEqual(report['status'], 'passed', report['errors'][:3])
            self.assertFalse(report['speaker_isolation_verified_by_declared_ids'])
            self.assertIn(dict(split='train', license_status='owner_internal_decision', transcript_status='source_text_aligned',
                               rows=len(kept)), report['rights_and_label_categories'])
            edits = [lambda r: r.update(rights_evidence_ref='somewhere else'),
                     lambda r: r.update(license_status='pending'),
                     lambda r: r.update(alignment_cer=0.2, alignment_max_cer=0.2),
                     lambda r: r.update(alignment_cer=0.12),  # above its own source threshold (10 %)
                     lambda r: r.update(alignment_cer=None),
                     lambda r: r.update(alignment_cer=math.nan),
                     lambda r: r.update(near_duplicate_review='unrun'),
                     lambda r: r.update(transcript_status='machine_generated')]
            for edit in edits:
                rows = copy.deepcopy(kept); edit(rows[0])
                self.write_manifests(output, rows, moved, test)
                report, _ = gate.inspect_manifests(self.gate_config(output))
                self.assertEqual(report['status'], 'failed', edit)
            sealed = dict(test, transcript_status='source_text_aligned', alignment_cer=0.0, alignment_max_cer=0.1,
                          near_duplicate_review='exact_text_checked')
            self.write_manifests(output, kept, moved, sealed)
            report, _ = gate.inspect_manifests(self.gate_config(output))
            self.assertEqual(report['status'], 'failed')  # the sealed test needs human labels


@unittest.skipIf(MISSING, f'needs {MISSING}')
class TranscribeTests(unittest.TestCase):
    def test_transcribe_skips_cached_recordings_and_stops_at_the_time_budget(self):
        class Word:
            def __init__(self, start, end, word): self.start, self.end, self.word = start, end, word
        class Segment:
            words = [Word(0.5, 0.8, '神'), Word(0.8, 1.1, '說')]
        class Model:
            calls = 0
            def transcribe(self, samples, **options):
                assert options['word_timestamps'] and options['language'] == 'zh'
                Model.calls += 1
                return iter([Segment()]), None
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('a', 'b'):
                write_wav(root/f'{name}.mp3', 2)
            plan = dict(recordings=[dict(id='a', audio='a.mp3'), dict(id='b', audio='b.mp3')])
            (root/'out/cache').mkdir(parents=True)
            (root/'out/cache/a.json').write_text('{}')
            result = m.transcribe(plan, root, root/'out', None, 'fake', 60, decode=read_wav, model=Model())
            self.assertEqual((result, Model.calls), (dict(transcribed=1, remaining=0), 1))
            cache = json.loads((root/'out/cache/b.json').read_text())
            self.assertEqual(cache['words'], [[0.5, 0.8, '神'], [0.8, 1.1, '說']])
            self.assertEqual(cache['audio_seconds'], 2.0)
            (root/'out/cache/b.json').unlink()
            self.assertEqual(m.transcribe(dict(recordings=[dict(r, kind='bible') for r in plan['recordings']]), root, root/'out', None,
                                          'fake', 60, decode=read_wav, model=Model(), max_recordings=1)['transcribed'], 0)  # a already counts
            (root/'out/cache/b.json').unlink(missing_ok=True)
            self.assertEqual(m.transcribe(plan, root, root/'out', None, 'fake', 0, decode=read_wav, model=Model())['remaining'], 1)


class NotebookTests(unittest.TestCase):
    def test_notebook_is_unexecuted_pinned_and_starts_with_a_trial(self):
        import ast, re
        notebook = json.loads((ROOT/'notebooks/twgbr_training_data.ipynb').read_text(encoding='utf-8'))
        code = [''.join(c['source']) for c in notebook['cells'] if c['cell_type'] == 'code']
        for cell, source in zip([c for c in notebook['cells'] if c['cell_type'] == 'code'], code):
            ast.parse(source)
            self.assertIsNone(cell['execution_count']); self.assertEqual(cell['outputs'], [])
        joined = '\n'.join(code)
        self.assertRegex(joined, r"COMMIT = '[0-9a-f]{40}'")
        self.assertIn('TRIAL = True', joined)
        self.assertIn("'--trial', '5'", joined)
        self.assertIn("e76620f83d5f5b69efd3d87e3dc180c1bd21df9fbebacfd4335e5e1efcc018da", joined)  # same pinned model as the dev checks
        for command in ('plan', 'transcribe', 'segment'):
            self.assertIn(f"step('{command}'", joined)


if __name__ == '__main__':
    unittest.main()
