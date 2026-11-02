import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import crawl_church_sources as crawler
from tw_speech_pilot import BoundedFetcher


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}


class CrawlTests(unittest.TestCase):
    def config(self):
        config = json.loads((ROOT/'sources/church-crawl.json').read_text())
        config['limits'].update(interval_seconds=0, max_pages=3)
        config['catalog_urls'] = []
        return config

    def opener(self, calls, fail_bible=False):
        class Opener:
            def open(self, request, **kwargs):
                url = request.full_url; calls.append(url)
                if url.endswith('robots.txt'):
                    return Response(b'User-agent: *\nAllow: /\n')
                if url.endswith('/life-study/'):
                    return Response(b'<title>Synthetic index</title><a href="1.html">one</a><a href="2.html">two</a><a href="https://example.org/">outside</a>')
                if '/recoveryversion/' in url and fail_bible:
                    raise urllib.error.URLError('synthetic network outage')
                if url.endswith('.mp3'):
                    raise AssertionError('Audio URLs must never be downloaded')
                return Response(b'<title>Synthetic document</title><div id="verses"><div id="chapternav">NAVIGATION</div><h3 id="C1Gen">Heading</h3><p class="calibre2">SYNTHETIC TEXT ONLY</p><audio src="mp3/ot/Gen-001.mp3"></audio></div><footer>FOOTER</footer>')
        return Opener()

    def test_discovery_scope_originals_text_audio_index_and_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cfg = self.config(); calls = []
            fetcher = BoundedFetcher(root, cfg); fetcher.opener = self.opener(calls)
            report = crawler.collect(root, cfg, fetcher)
            self.assertEqual(report['pages_acquired'], 3)
            self.assertEqual(report['text_documents'], 2)
            self.assertEqual(report['audio_downloaded'], 0)
            self.assertEqual(report['usable_paired_hours'], 0)
            self.assertFalse(report['training_ready'])
            for file in (root/'text_only').glob('*.txt'):
                self.assertIn('SYNTHETIC TEXT ONLY', file.read_text())
                self.assertNotIn('NAVIGATION', file.read_text()); self.assertNotIn('FOOTER', file.read_text())
            self.assertFalse(any('example.org' in url or url.endswith('.mp3') for url in calls))
            before = len(calls)
            resumed = BoundedFetcher(root, cfg); resumed.opener = self.opener(calls)
            again = crawler.collect(root, cfg, resumed)
            self.assertEqual(again['pages_acquired'], 3); self.assertEqual(len(calls), before)

    def test_partial_collection_can_resume_without_overwriting_old_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cfg = self.config(); calls = []
            fetcher = BoundedFetcher(root, cfg); fetcher.opener = self.opener(calls, fail_bible=True)
            report = crawler.collect(root, cfg, fetcher)
            self.assertEqual(report['pages_acquired'], 1)
            original = {path: path.read_bytes() for path in (root/'raw').glob('*.json')}
            resumed = BoundedFetcher(root, cfg); resumed.opener = self.opener(calls)
            report = crawler.collect(root, cfg, resumed)
            self.assertEqual(report['pages_acquired'], 3)
            for path, content in original.items(): self.assertEqual(path.read_bytes(), content)
            self.assertEqual(len((root/'manifests/pages.jsonl').read_text().splitlines()), 3)

    def test_failed_preflight_stops_site_but_catalog_remains_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); cfg = self.config(); calls = []
            catalog = 'https://raw.githubusercontent.com/common-voice/cv-dataset/main/README.md'
            cfg['catalog_urls'] = [catalog]
            class Opener:
                def open(self, request, **kwargs):
                    url = request.full_url; calls.append(url)
                    if 'line.twgbr.org' in url: raise urllib.error.URLError('synthetic proxy refusal')
                    return Response(b'User-agent: *\nAllow: /\n' if url.endswith('robots.txt') else b'Synthetic catalog only')
            fetcher = BoundedFetcher(root, cfg); fetcher.opener = Opener()
            report = crawler.collect(root, cfg, fetcher)
            self.assertEqual(sum('line.twgbr.org' in url for url in calls), 1)
            self.assertEqual(report['status'], 'site_blocked_catalog_only')
            self.assertEqual(report['catalog_documents'], 1)
            self.assertEqual(report['pages_acquired'], 0)

    def test_source_path_scope_excludes_audio_queries_and_external_hosts(self):
        for url in ['https://example.org/life-study/1.html', 'http://line.twgbr.org/life-study/',
                    'https://line.twgbr.org/life-study/mp3/ot/Gen-001.mp3',
                    'https://line.twgbr.org/life-study/1.html?next=anything']:
            self.assertFalse(crawler.eligible(url))


if __name__ == '__main__':
    unittest.main()
