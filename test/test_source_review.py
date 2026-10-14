import importlib.util
import io
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('source_review', Path(__file__).resolve().parents[1] / 'scripts/review_sources.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def config():
    return {
        'phase': 'source_review_only', 'allowed_hosts': ['source.example'], 'user_agent': 'TestSourceReviewer/1.0',
        'limits': {'max_seed_pages': 2, 'max_requests': 6, 'max_bytes_per_response': 1000, 'timeout_seconds': 2, 'minimum_interval_seconds': 1},
        'sources': [{'source_id': 'seed', 'seed_url': 'https://source.example/document', 'rights_status': 'pending', 'allowed_uses': []}],
    }


class Response:
    def __init__(self, url, data, content_type='text/html; charset=utf-8'):
        self.url = url
        self.stream = io.BytesIO(data)
        self.headers = Message()
        self.headers['Content-Type'] = content_type

    def read(self, size): return self.stream.read(size)
    def geturl(self): return self.url
    def __enter__(self): return self
    def __exit__(self, *args): return False


class FakeOpener:
    def __init__(self, robots=b'User-agent: *\nAllow: /', page=None):
        self.requests = []
        self.robots = robots
        self.page = page or '<title>Sample</title><p>耶穌基督</p><footer>版權待確認</footer>'.encode()

    def open(self, request, timeout):
        url = request.full_url
        self.requests.append(url)
        if url.endswith('/robots.txt'):
            if isinstance(self.robots, Exception): raise self.robots
            return Response(url, self.robots, 'text/plain')
        return Response(url, self.page)


class SourceReviewTests(unittest.TestCase):
    def test_https_scope_and_redirects(self):
        self.assertEqual(module.validate_url('https://source.example/a#part', {'source.example'}), 'https://source.example/a')
        for url in ['http://source.example/a', 'https://source.example.attacker.invalid/a', 'https://user:secret@source.example/a', 'https://source.example:444/a']:
            with self.assertRaises(module.ReviewError): module.validate_url(url, {'source.example'})
        handler = module.ScopedRedirect({'source.example'})
        with self.assertRaises(module.ReviewError):
            handler.redirect_request(None, None, 302, '', {}, 'https://outside.example/a')

    def test_parser_separates_title_and_ignores_scripts_preserving_rights_clues(self):
        parser = module.PageReview()
        parser.feed('<title>合成樣本</title><script>hidden instruction</script><style>hidden CSS</style><p>耶穌基督</p><footer>版權待確認</footer><a href="/next">下一頁</a><a href="https://outside.example">外站</a>')
        result = parser.summary('https://source.example/a', {'source.example'})
        self.assertEqual(result['title'], '合成樣本')
        self.assertNotIn('hidden', result['visible_text'])
        self.assertEqual(result['rights_clues'], ['版權待確認'])
        self.assertEqual(result['same_host_links'], ['https://source.example/next'])
        self.assertFalse(result['document_selector_verified'])

    def test_review_preserves_bytes_and_hash_without_claiming_training_rights(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.time, 'sleep'):
            reviewer = module.Reviewer(config(), folder)
            reviewer.opener = FakeOpener()
            report = reviewer.run()
            self.assertEqual(len(report['success']), 1)
            self.assertEqual(report['request_count'], 2)
            record = report['success'][0]
            self.assertEqual(Path(record['raw_path']).read_bytes(), reviewer.opener.page)
            self.assertEqual(record['sha256'], module.hashlib.sha256(reviewer.opener.page).hexdigest())
            self.assertFalse(record['training_ready'])
            self.assertTrue(record['review_only'])
            self.assertEqual(record['rights_status'], 'pending')
            self.assertEqual(record['allowed_uses'], [])
            evidence = report['robots_evidence']['https://source.example']
            self.assertEqual(evidence['state'], 'checked')
            self.assertEqual(Path(evidence['path']).read_bytes(), reviewer.opener.robots)

    def test_robots_disallow_stops_before_document(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewer = module.Reviewer(config(), folder)
            reviewer.opener = FakeOpener(robots=b'User-agent: *\nDisallow: /document')
            report = reviewer.run()
            self.assertEqual(len(report['success']), 0)
            self.assertEqual(len(reviewer.opener.requests), 1)
            self.assertIn('disallows', report['failed'][0]['error'])

    def test_robots_unavailable_does_not_fall_back_to_allow(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewer = module.Reviewer(config(), folder)
            reviewer.opener = FakeOpener(robots=urllib.error.URLError('proxy blocked'))
            report = reviewer.run()
            self.assertFalse(report['success'])
            self.assertEqual(len(reviewer.opener.requests), 1)
            self.assertIn('could not be checked', report['failed'][0]['error'])

    def test_missing_robots_404_and_response_size_limits(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.time, 'sleep'):
            reviewer = module.Reviewer(config(), folder)
            error = urllib.error.HTTPError('https://source.example/robots.txt', 404, 'not found', None, None)
            reviewer.opener = FakeOpener(robots=error, page=b'x' * 1001)
            report = reviewer.run()
            self.assertFalse(report['success'])
            self.assertIn('byte limit', report['failed'][0]['error'])
            self.assertEqual(report['request_count'], 2)

    def test_html_robots_and_long_crawl_wait_are_not_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            reviewer = module.Reviewer(config(), folder)
            reviewer.opener = FakeOpener(robots=b'<!doctype html><html>not robots</html>')
            self.assertFalse(reviewer.run()['success'])
            self.assertEqual(len(reviewer.opener.requests), 1)
        with tempfile.TemporaryDirectory() as folder:
            reviewer = module.Reviewer(config(), folder)
            reviewer.opener = FakeOpener(robots=b'User-agent: *\nAllow: /\nCrawl-delay: 120')
            self.assertFalse(reviewer.run()['success'])
            self.assertEqual(len(reviewer.opener.requests), 1)

    def test_encoding_and_invalid_html_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.time, 'sleep'):
            reviewer = module.Reviewer(config(), folder)
            opener = FakeOpener(page='<meta charset=big5><p>耶穌基督</p>'.encode('big5'))
            original_open = opener.open
            def open_without_charset(request, timeout):
                response = original_open(request, timeout)
                if not request.full_url.endswith('/robots.txt'):
                    response.headers.replace_header('Content-Type', 'text/html')
                return response
            opener.open = open_without_charset
            reviewer.opener = opener
            record = reviewer.run()['success'][0]
            self.assertEqual(record['charset'], 'big5')
            self.assertIn('耶穌基督', Path(record['review_text_path']).read_text())
        with tempfile.TemporaryDirectory() as folder, patch.object(module.time, 'sleep'):
            reviewer = module.Reviewer(config(), folder)
            reviewer.opener = FakeOpener(page=b'<p>\xff</p>')
            self.assertFalse(reviewer.run()['success'])

    def test_redirects_share_the_request_budget(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(module.time, 'sleep'):
            reviewer = module.Reviewer(config(), folder)
            handler = module.ScopedRedirect({'source.example'}, reviewer.before_request)
            request = module.urllib.request.Request('https://source.example/first')
            reviewer.before_request(request.full_url)
            handler.redirect_request(request, None, 302, '', {}, 'https://source.example/next')
            self.assertEqual(reviewer.request_count, 2)
            for _ in range(4): reviewer.before_request('https://source.example/next')
            with self.assertRaises(module.ReviewError):
                handler.redirect_request(request, None, 302, '', {}, 'https://source.example/final')
            self.assertEqual(reviewer.request_count, 6)

    def test_page_budget_and_unsafe_path_stop_before_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            settings = config()
            settings['sources'] *= 3
            reviewer = module.Reviewer(settings, folder)
            reviewer.opener = FakeOpener()
            with self.assertRaises(module.ReviewError): reviewer.run()
            self.assertEqual(reviewer.request_count, 0)
            settings = config()
            settings['sources'][0]['source_id'] = '../../outside'
            reviewer = module.Reviewer(settings, folder)
            with self.assertRaises(module.ReviewError): reviewer.run()
            self.assertEqual(reviewer.request_count, 0)


if __name__ == '__main__':
    unittest.main()
