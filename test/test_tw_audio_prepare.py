"""Synthetic generated waveforms only; these tests do not validate real speech labels."""
import hashlib
import importlib.util
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

spec = importlib.util.spec_from_file_location('tw_audio_prepare', Path(__file__).parents[1] / 'scripts/tw_audio_prepare.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def generate_wav(file, seconds=6, frequency=440, amplitude=5000, rate=16000, channels=1, constant=None):
    with wave.open(str(file), 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        samples = bytearray()
        for i in range(int(seconds * rate)):
            value = constant if constant is not None else round(amplitude * math.sin(2 * math.pi * frequency * i / rate))
            samples.extend(struct.pack('<h', value) * channels)
        output.writeframes(samples)


def record(root, identifier, text=None, speaker=None, recording=None):
    file = root / 'raw' / (identifier + '.wav')
    return dict(id=identifier, audio_filepath=str(file.relative_to(root)), text=text or identifier,
                language='zh-TW', source_url='urn:synthetic-test:' + identifier,
                recording_id=recording or 'recording-' + identifier, speaker_id=speaker,
                transcript_status='provider_reference', license_status='approved',
                sha256=module.file_sha256(file))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / 'raw').mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def create(self, identifier, **kwargs):
        generate_wav(self.root / 'raw' / (identifier + '.wav'), **kwargs)

    def test_working_copy_preserves_raw_text_hashes_and_unknown_speaker(self):
        self.create('one', channels=2, rate=24000)
        text = '台灣 AI [en]OpenAI[/en] [nan]咱[/nan] cafe\u0301\r\n１２３。'
        source = record(self.root, 'one', text=text)
        original_hash = source['sha256']
        result = module.prepare_records([source], self.root)
        row = result['records'][0]
        self.assertEqual(row['raw_text'], text)
        self.assertEqual(row['text'], text)
        self.assertEqual(row['normalized_text'], '台灣 AI [en]OpenAI[/en] [nan]咱[/nan] café\n１２３。')
        self.assertEqual(module.file_sha256(self.root / source['audio_filepath']), original_hash)
        self.assertEqual(row['raw_sha256'], original_hash)
        self.assertEqual(module.file_sha256(self.root / row['audio_filepath']), row['sha256'])
        with wave.open(str(self.root / row['audio_filepath'])) as converted:
            self.assertEqual(converted.getnchannels(), 1)
            self.assertEqual(converted.getframerate(), 16000)
        self.assertAlmostEqual(row['duration'], 6.0, places=3)
        self.assertIsNone(row['speaker_id'])
        self.assertEqual(row['transcript_status'], 'provider_reference')
        self.assertFalse(row['local_reference_verified'])
        self.assertFalse(row['training_ready'])
        self.assertFalse(result['report']['speaker_isolation_guaranteed'])
        self.assertEqual(result['report']['locally_human_verified_seconds'], 0)
        self.assertEqual(row['qc']['background_music_check'], 'unrun')
        self.assertEqual(row['split'], 'unassigned')
        self.assertEqual(result['report']['split_status'], 'blocked_pending_near_duplicate_review')

    def test_wrong_hash_and_broken_audio_are_rejected(self):
        self.create('wrong')
        wrong = record(self.root, 'wrong')
        wrong['sha256'] = 'f' * 64
        bad_file = self.root / 'raw' / 'broken.wav'
        bad_file.write_bytes(b'not an audio recording')
        broken = record(self.root, 'broken')
        result = module.prepare_records([wrong, broken], self.root)
        self.assertEqual(result['report']['rejected'], 2)
        self.assertEqual(result['records'][0]['failure_reason'], 'raw_hash_mismatch')
        self.assertFalse((self.root / 'processed' / 'wrong.wav').exists())
        self.assertFalse((self.root / 'processed' / 'broken.wav').exists())

    def test_silence_clipping_and_long_clips_are_reviewed_not_cut(self):
        self.create('silent', constant=0)
        self.create('clipped', constant=32767)
        self.create('long', seconds=31)
        result = module.prepare_records([record(self.root, name) for name in ['silent', 'clipped', 'long']], self.root)
        silent, clipped, long = result['records']
        self.assertEqual(silent['qc']['silence_sample_ratio'], 1)
        self.assertEqual(silent['qc']['longest_silent_run_seconds'], 6)
        self.assertIn('mostly_silent_audio', silent['review_reasons'])
        self.assertEqual(clipped['qc']['clipping_sample_ratio'], 1)
        self.assertIn('clipping_above_0.1_percent', clipped['review_reasons'])
        self.assertIn('full_clip_over_30s_needs_manual_aligned_segmentation', long['review_reasons'])
        self.assertEqual(long['segment_start'], 0)
        self.assertEqual(long['segment_end'], 31)
        self.assertEqual(long['text'], 'long')
        self.assertEqual(len(result['records']), 3)
        self.assertEqual(result['report']['provider_baseline_candidates'], 0)

    def test_duplicate_checks_and_transitive_group_proposals_do_not_split_speakers(self):
        names = ['a', 'b', 'c', 'd', 'e', 'f', 'g']
        for i, name in enumerate(names):
            self.create(name, frequency=440 + i * 55)
        # Same PCM, different raw container bytes; valid trailing metadata is ignored by decoder.
        original = (self.root / 'raw' / 'a.wav').read_bytes()
        (self.root / 'raw' / 'g.wav').write_bytes(original + b'trailing-metadata')
        rows = [record(self.root, 'a', speaker='s1', recording='r1'),
                record(self.root, 'b', speaker='s1', recording='r2'),
                record(self.root, 'c', speaker='s2', recording='r2'),
                record(self.root, 'd', speaker='s3', recording='r3'),
                record(self.root, 'e', text='same text', speaker='s4', recording='r4'),
                record(self.root, 'f', text='same text', speaker='s5', recording='r5'),
                record(self.root, 'g', speaker='s6', recording='r6')]
        result = module.prepare_records(rows, self.root)
        actual = {row['id']: row for row in result['records']}
        self.assertEqual(result['report']['independent_components'], 3)
        self.assertEqual(actual['a']['group_id'], actual['b']['group_id'])
        self.assertEqual(actual['b']['group_id'], actual['c']['group_id'])
        self.assertEqual(actual['a']['proposed_split'], actual['c']['proposed_split'])
        self.assertTrue(actual['f']['duplicate_excluded'])
        self.assertTrue(actual['g']['duplicate_excluded'])
        self.assertIn('pcm_sha256', [item['kind'] for item in actual['g']['duplicate_matches']])
        self.assertIn('normalized_text', [item['kind'] for item in actual['f']['duplicate_matches']])
        active = [row for row in result['records'] if row['candidate_for_provider_baseline']]
        self.assertEqual({row['proposed_split'] for row in active}, {'train', 'validation', 'test'})
        self.assertTrue(all(row['split'] == 'unassigned' for row in result['records']))
        for field in ['speaker_id', 'recording_id']:
            observed = {}
            for row in active:
                self.assertNotIn(row[field], {key for key, split in observed.items() if split != row['proposed_split']})
                observed[row[field]] = row['proposed_split']

    def test_pending_license_machine_labels_and_existing_output_are_not_promoted(self):
        self.create('pending')
        self.create('machine', frequency=550)
        pending = record(self.root, 'pending')
        pending['license_status'] = 'pending'
        machine = record(self.root, 'machine')
        machine['transcript_status'] = 'machine_generated'
        result = module.prepare_records([pending, machine], self.root)
        self.assertEqual(result['report']['provider_baseline_candidates'], 0)
        output = self.root / 'processed' / 'pending.wav'
        saved = output.read_bytes()
        repeated = module.prepare_records([pending], self.root)
        self.assertEqual(repeated['records'][0]['failure_reason'], 'output_exists_not_overwritten')
        self.assertEqual(output.read_bytes(), saved)
        self.assertFalse(repeated['records'][0]['training_ready'])

    def test_outside_symlink_and_duplicate_ids_are_rejected(self):
        self.create('safe')
        row = record(self.root, 'safe')
        outside = self.root.parent / ('outside-' + self.root.name + '.wav')
        outside.write_bytes((self.root / 'raw' / 'safe.wav').read_bytes())
        try:
            link = self.root / 'raw' / 'escape.wav'
            link.symlink_to(outside)
            escaped = {**row, 'id': 'escaped', 'audio_filepath': 'raw/escape.wav'}
            result = module.prepare_records([escaped], self.root)
            self.assertEqual(result['records'][0]['failure_reason'], 'path_outside_root')
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                module.prepare_records([row, row], self.root)
        finally:
            outside.unlink()


if __name__ == '__main__':
    unittest.main()
