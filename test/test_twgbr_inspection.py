import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from email.message import Message

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import inspect_twgbr
import probe_audio
from review_sources import ReviewError


class MetadataTests(unittest.TestCase):
    def test_document_boundaries_remove_navigation(self):
        raw = b'<title>Example</title><div id="verses"><div id="chapternav"><p class="calibre2">navigation</p></div><h3 id="C1Gen">Chapter 1</h3><p class="calibre2">Synthetic text</p><h3 id="C2Gen">Chapter 2</h3><p class="calibre2">Synthetic text 2</p></div><footer>footer</footer>'
        result = inspect_twgbr.inspect_page(raw, 'https://line.twgbr.org/recoveryversion/bible/01.html')
        self.assertEqual(result['chapter_numbers'], [1, 2])
        self.assertEqual(result['paragraph_count'], 2)
        self.assertTrue(result['selector_verified'])
        self.assertFalse(result['training_ready'])

    def test_number_mapping_is_not_verbatim_alignment(self):
        raw = b'<div id="verses"><h3 id="C2Gen">Message</h3><p class="calibre2">Synthetic body</p><audio><source src="mp3/ot/Gen-002.mp3"></audio></div>'
        result = inspect_twgbr.inspect_page(raw, 'https://line.twgbr.org/life-study/1_2.html')
        self.assertTrue(result['audio_number_matches_heading'])
        self.assertFalse(result['verbatim_alignment_verified'])
        mismatch = raw.replace(b'Gen-002', b'Gen-003')
        self.assertFalse(inspect_twgbr.inspect_page(mismatch, 'https://line.twgbr.org/life-study/1_2.html')['audio_number_matches_heading'])

    def test_missing_selector_is_not_replaced_by_whole_page(self):
        with self.assertRaises(ValueError):
            inspect_twgbr.inspect_page(b'<body>only navigation</body>', 'https://line.twgbr.org/life-study/1.html')

    def test_checksum_mismatch_stops_inspection(self):
        with tempfile.TemporaryDirectory() as folder:
            page = Path(folder) / 'page.html'; page.write_bytes(b'<div>changed</div>')
            report = Path(folder) / 'report.json'; report.write_text(json.dumps({'success': [{'raw_path': str(page), 'sha256': '0'*64}]}))
            with self.assertRaises(ValueError): inspect_twgbr.inspect_reports([report])


class FakeResponse:
    def __init__(self, status, data=b'X'*4096, content_range='bytes 0-4095/8000'):
        self.status = status; self.data = data; self.read_count = 0
        self.headers = Message(); self.headers['Content-Range'] = content_range
        self.headers['Content-Type'] = 'audio/mpeg'; self.headers['Content-Length'] = '8000'
    def geturl(self): return 'https://line.twgbr.org/life-study/mp3/ot/Gen-002.mp3'
    def read(self, maximum): self.read_count += 1; return self.data[:maximum]
    def __enter__(self): return self
    def __exit__(self, *args): return False


class AudioTests(unittest.TestCase):
    def reviewer(self, ranged):
        responses = iter([FakeResponse(200), ranged])
        return SimpleNamespace(
            hosts={'line.twgbr.org'}, config={'user_agent':'Synthetic-test'},
            limits={'max_bytes_per_response':1000000,'timeout_seconds':2}, request_count=2,
            can_fetch=lambda url: True, before_request=lambda url: None,
            opener=SimpleNamespace(open=lambda request, timeout: next(responses)))

    @patch('probe_audio.shutil.which', return_value='/synthetic/ffprobe')
    def test_server_ignoring_range_does_not_trigger_body_download(self, _):
        ranged = FakeResponse(200)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ReviewError): probe_audio.probe_audio(self.reviewer(ranged), ranged.geturl(), folder, 4096)
        self.assertEqual(ranged.read_count, 0)

    @patch('probe_audio.shutil.which', return_value='/synthetic/ffprobe')
    def test_invalid_range_is_rejected_before_body_read(self, _):
        ranged = FakeResponse(206, content_range='bytes 100-4195/8000')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ReviewError): probe_audio.probe_audio(self.reviewer(ranged), ranged.geturl(), folder, 4096)
        self.assertEqual(ranged.read_count, 0)

    @patch('probe_audio.shutil.which', return_value='/synthetic/ffprobe')
    def test_range_covering_full_recording_is_not_read(self, _):
        ranged = FakeResponse(206, content_range='bytes 0-4095/4096')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ReviewError): probe_audio.probe_audio(self.reviewer(ranged), ranged.geturl(), folder, 4096)
        self.assertEqual(ranged.read_count, 0)

    @patch('probe_audio.shutil.which', return_value='/synthetic/ffprobe')
    @patch('probe_audio.subprocess.run', return_value=SimpleNamespace(returncode=0,stdout='{"streams":[{"codec_name":"mp3"}]}'))
    def test_valid_prefix_does_not_claim_full_recording_or_training(self, *_):
        ranged = FakeResponse(206)
        with tempfile.TemporaryDirectory() as folder:
            report = probe_audio.probe_audio(self.reviewer(ranged), ranged.geturl(), folder, 4096)
            self.assertEqual(report['bytes_downloaded'],4096)
            self.assertFalse(report['full_audio_downloaded'])
            self.assertFalse(report['verbatim_alignment_verified'])
            self.assertFalse(report['training_ready'])


if __name__ == '__main__': unittest.main()
