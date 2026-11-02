import importlib.util
import io
import array
import math
import wave
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location('tw_pilot', ROOT/'scripts/tw_speech_pilot.py')
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)
spec2 = importlib.util.spec_from_file_location('tw_baseline', ROOT/'scripts/tw_speech_baseline.py')
baseline = importlib.util.module_from_spec(spec2)
spec2.loader.exec_module(baseline)


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}


class FetchTests(unittest.TestCase):
    def config(self):
        config = json.loads((ROOT/'sources/taiwan-mandarin-pilot.json').read_text())
        config['limits']['interval_seconds'] = 0
        return config

    def test_resume_verifies_cached_bytes_and_does_not_download_twice(self):
        with tempfile.TemporaryDirectory() as root:
            f = pilot.BoundedFetcher(root, self.config())
            class Opener:
                def open(self, req, **kwargs):
                    return Response(b'User-agent: *\nAllow: /\n' if req.full_url.endswith('robots.txt') else b'synthetic payload')
            f.opener = Opener()
            self.assertEqual(f.get('https://huggingface.co/test'), b'synthetic payload')
            self.assertEqual(f.state['requests'], 2)
            resumed = pilot.BoundedFetcher(root, self.config())
            self.assertEqual(resumed.get('https://huggingface.co/test'), b'synthetic payload')
            self.assertEqual(resumed.state['requests'], 2)
            key = pilot.sha256(b'https://huggingface.co/test')
            (resumed.cache/key).write_bytes(b'tampered')
            with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
                resumed.get('https://huggingface.co/test')

    def test_limits_prevent_oversize_requests_and_cross_host_redirects(self):
        with tempfile.TemporaryDirectory() as root:
            config = self.config(); config['limits']['max_total_body_bytes'] = 4
            f = pilot.BoundedFetcher(root, config)
            class Opener:
                def open(self, req, **kwargs): return Response(b'12345')
            f.opener = Opener()
            with self.assertRaisesRegex(RuntimeError, 'budget'):
                f.get('https://huggingface.co/test', robots=False)
            self.assertEqual(f.state['body_bytes'], 4)
            with self.assertRaisesRegex(ValueError, 'Unapproved'):
                f.get('https://unapproved.example/test', robots=False)
        with tempfile.TemporaryDirectory() as root:
            f = pilot.BoundedFetcher(root, self.config())
            class Redirect:
                def open(self, req, **kwargs):
                    raise urllib.error.HTTPError(req.full_url, 302, 'redirect', {'Location': 'https://unapproved.example/audio'}, None)
            f.opener = Redirect()
            with self.assertRaisesRegex(ValueError, 'Unapproved'):
                f.get('https://huggingface.co/test', robots=False)
            self.assertEqual(f.state['requests'], 1)

    def test_robots_denial_and_long_retry_after_stop_requests(self):
        with tempfile.TemporaryDirectory() as root:
            f = pilot.BoundedFetcher(root, self.config())
            class Denied:
                def open(self, req, **kwargs): return Response(b'User-agent: *\nDisallow: /\n')
            f.opener = Denied()
            with self.assertRaisesRegex(RuntimeError, 'robots'):
                f.get('https://huggingface.co/test')
            self.assertEqual(f.state['requests'], 1)
        with tempfile.TemporaryDirectory() as root:
            f = pilot.BoundedFetcher(root, self.config())
            class RateLimit:
                def open(self, req, **kwargs):
                    raise urllib.error.HTTPError(req.full_url, 429, 'rate limit', {'Retry-After': '120'}, None)
            f.opener = RateLimit()
            with self.assertRaisesRegex(RuntimeError, 'later run'):
                f.get('https://huggingface.co/test', robots=False)
            self.assertEqual(f.state['requests'], 1)

    def test_fifteen_synthetic_assets_flow_from_collection_to_safe_preparation(self):
        # Structural integration only: tones and prompts are NOT real speech pairs.
        prepare_spec = importlib.util.spec_from_file_location('tw_prepare_integration', ROOT/'scripts/tw_audio_prepare.py')
        prepare = importlib.util.module_from_spec(prepare_spec)
        prepare_spec.loader.exec_module(prepare)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ['raw', 'processed', 'manifests', 'text_only', 'review', 'reports']:
                (root/name).mkdir()
            config = self.config()
            fixtures = {}
            provider_rows = []
            for index in range(15):
                buffer = io.BytesIO()
                values = array.array('h', (int(1200*math.sin(2*math.pi*(200+index*10)*i/16000)) for i in range(81600)))
                with wave.open(buffer, 'wb') as out:
                    out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(values.tobytes())
                url = f'https://datasets-server.huggingface.co/synthetic/{index}.wav'
                fixtures[url] = buffer.getvalue()
                provider_rows.append(dict(row_idx=index, row=dict(audio=[dict(src=url)], raw_transcription=f'Synthetic prompt {index}', path=f'fixture-{index}.wav')))
            fixtures[config['source']['card_url']] = b'---\nlicense: cc-by-4.0\n---\nSYNTHETIC TEST CARD ONLY'
            fixtures[config['source']['rows_url']] = json.dumps(dict(rows=provider_rows)).encode()
            class Opener:
                def open(self, req, **kwargs):
                    return Response(b'User-agent: *\nAllow: /\n' if req.full_url.endswith('robots.txt') else fixtures[req.full_url])
            fetcher = pilot.BoundedFetcher(root, config);fetcher.opener = Opener()
            records, failures = pilot.collect(root, config, fetcher)
            self.assertEqual(len(records), 15);self.assertEqual(failures, [])
            prepared = prepare.prepare_records(records, root)
            self.assertEqual(prepared['report']['records'], 15)
            self.assertEqual(prepared['report']['training_ready_seconds'], 0)
            self.assertEqual(prepared['report']['locally_human_verified_seconds'], 0)
            self.assertTrue(all(r['split']=='unassigned' and not r['local_reference_verified'] for r in prepared['records']))
            self.assertFalse(prepared['report']['speaker_isolation_guaranteed'])
            before = fetcher.state['requests']
            resumed, failures = pilot.collect(root, config, fetcher)
            self.assertEqual(fetcher.state['requests'], before)
            self.assertEqual(records, resumed)

    def test_license_is_checked_from_card_not_public_availability(self):
        values = ['cc-by-4.0', '"cc-by-4.0"', "'cc-by-4.0'", '[cc-by-4.0]', '\n- cc-by-4.0', '\n  - cc-by-4.0', 'cc-by-4.0 # provider comment']
        for value in values:
            report=pilot.check_license('---\nlicense: '+value+'\n---\nDescription', 'cc-by-4.0')
            self.assertEqual(report['status'],'approved')
            self.assertEqual(report['declared_licenses'],['cc-by-4.0'])
        report=pilot.check_license('\ufeff---\r\nlicense: [CC-BY-4.0]\r\n---\r\nBody','cc-by-4.0')
        self.assertEqual(report['status'],'approved')
        for card in ['Publicly available', '---\nlicense: unknown\n---\nDescription']:
            with self.assertRaises(ValueError):pilot.check_license(card, 'cc-by-4.0')

    def test_mixed_different_duplicate_and_unsafe_license_yaml_cannot_approve(self):
        fields=['license: cc-by-sa-4.0','license: [cc-by-4.0, cc-by-nc-4.0]','license: []','license: 42','dataset_info: {license: cc-by-4.0}','license: unknown\nlicense: cc-by-4.0','license: !!python/object/apply:builtins.print [unsafe]']
        for field in fields:
            with self.assertRaises(pilot.LicenseVerificationError) as caught:
                pilot.check_license('---\n'+field+'\n---\nlicense: cc-by-4.0','cc-by-4.0')
            self.assertEqual(caught.exception.license_details['status'],'pending')
        with self.assertRaises(pilot.LicenseVerificationError) as caught:
            pilot.check_license('---\nlicense: [cc-by-4.0, cc-by-nc-4.0]\n---','cc-by-4.0')
        self.assertEqual(caught.exception.license_details['declared_licenses'],['cc-by-4.0','cc-by-nc-4.0'])

    def test_failed_license_keeps_evidence_and_never_fetches_rows_or_audio(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);config=self.config();calls=[]
            card=b'---\nlicense:\n- cc-by-nc-4.0\n---\nSynthetic test card'
            class Fetcher:
                def get(self,url,**kwargs):
                    calls.append(url)
                    if url!=config['source']['card_url']:raise AssertionError('Rows/audio fetched before license approval')
                    return card
            with self.assertRaises(pilot.LicenseVerificationError):pilot.collect(root,config,Fetcher())
            review=json.loads((root/'review/license-review.json').read_text())
            self.assertEqual(calls,[config['source']['card_url']])
            self.assertEqual(review['status'],'pending')
            self.assertEqual(review['declared_licenses'],['cc-by-nc-4.0'])
            self.assertEqual(review['card_sha256'],pilot.sha256(card))
            self.assertEqual((root/'raw/dataset-card.md').read_bytes(),card)


class BaselineTests(unittest.TestCase):
    def test_reference_policy_never_promotes_machine_or_unverified_labels(self):
        row = dict(id='synthetic', license_status='approved', candidate_for_provider_baseline=True, transcript_status='provider_reference', text='測試', local_reference_verified=False)
        self.assertEqual(len(baseline.eligible([row], 'verified_only')[0]), 0)
        self.assertEqual(len(baseline.eligible([row], 'provider_provisional')[0]), 1)
        self.assertEqual(len(baseline.eligible([{**row, 'transcript_status': 'machine_generated'}], 'provider_provisional')[0]), 0)
        self.assertEqual(len(baseline.eligible([{**row, 'license_status': 'pending'}], 'provider_provisional')[0]), 0)
        self.assertEqual(len(baseline.eligible([{**row, 'text': '[EN]hi[/EN]'}], 'provider_provisional')[0]), 0)
        self.assertEqual(len(baseline.eligible([{**row, 'transcript_status': 'unknown'}], 'provider_provisional')[0]), 0)
        self.assertEqual(len(baseline.eligible([{**row, 'text': ''}], 'provider_provisional')[0]), 0)
        with self.assertRaises(ValueError):baseline.eligible([row], 'invalid_policy')

    def test_cer_uses_existing_versioned_character_alignment(self):
        result = baseline.score([dict(id='synthetic', reference='台灣，abc', hypothesis='台灣abc!')], ROOT)
        self.assertEqual(result['reference_characters'], 5)
        self.assertEqual(result['cer'], 0)
        result = baseline.score([dict(id='synthetic', reference='台灣', hypothesis='臺灣人')], ROOT)
        self.assertEqual(result['substitutions'], 1)
        self.assertEqual(result['insertions'], 1)
        self.assertEqual(result['cer'], 1)


if __name__ == '__main__':
    unittest.main()
