import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import crawl_church_sources as crawler
import extract_church_terms as terms
import fetch_church_audio as audio
from tw_speech_pilot import BoundedFetcher


def write_collection(root, docs):
    """Synthetic crawl output: manifests/pages.jsonl plus text_only files with hashes."""
    (root/'manifests').mkdir(parents=True); (root/'text_only').mkdir(); (root/'review').mkdir()
    rows = []
    for i, (url, text) in enumerate(docs):
        data = text.encode('utf-8'); name = f'text_only/{i}.txt'; (root/name).write_bytes(data)
        rows.append(dict(id=str(i), source_url=url, title=f'doc {i}', text_path=name,
                         text_sha256=hashlib.sha256(data).hexdigest(), audio_urls=[]))
    (root/'manifests/pages.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows))
    return rows


SYNTHETIC = '在曠野中摩西帶領百姓，豫表基督的救恩。後來百姓又在曠野中行走，摩西禱告。'


class ExtractTests(unittest.TestCase):
    def docs(self):
        return [(f'https://line.twgbr.org/life-study/{i}.html', SYNTHETIC*(i+2)) for i in range(4)]

    def test_candidates_stay_pending_and_drop_fragments(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); write_collection(root, self.docs())
            ranked, coverage, stats = terms.extract(terms.load_documents([root]), min_freq=3, min_docs=2,
                                                    min_cohesion=0, min_entropy=0, known={'摩西': {'approved'}})
            found = {r['term'] for r in ranked}
            self.assertIn('摩西', found); self.assertIn('曠野', found)
            self.assertTrue(all(r['review_status'] == 'pending_review' and not r['training_ready']
                                and r['automatic_replacement'] == 'not_allowed' for r in ranked))
            self.assertEqual(coverage['摩西']['document_frequency'], 4)
            self.assertEqual(stats['documents'], 4)

    def test_leave_out_and_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); rows = write_collection(root, self.docs())
            kept = terms.load_documents([root], exclude=[rows[0]['source_url']])
            self.assertEqual(len(kept), 3)
            self.assertNotIn(rows[0]['source_url'], {d['source_url'] for d in kept})
            (root/rows[1]['text_path']).write_text('tampered')
            with self.assertRaises(ValueError):
                terms.load_documents([root])

    def test_numerals_are_not_candidates_and_variants_are_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_collection(root, [(f'https://line.twgbr.org/life-study/{i}.html', ('二十三節，大衞豫表基督。'*5)) for i in range(3)])
            docs = terms.load_documents([root])
            ranked, _, _ = terms.extract(docs, min_freq=3, min_docs=2, min_cohesion=0, min_entropy=0)
            self.assertFalse(any(terms.NUMERAL.fullmatch(r['term']) for r in ranked))
            variants = {v['term']: v['common_form'] for v in terms.variant_report(ranked, docs)}
            self.assertTrue(any('衞' in t and '衛' in c for t, c in variants.items()))


class Response(io.BytesIO):
    def __init__(self, body):
        super().__init__(body); self.headers = {'Content-Length': str(len(body))}


class CrawlScopeTests(unittest.TestCase):
    def test_follow_links_false_only_fetches_seeds(self):
        config = json.loads((ROOT/'sources/church-crawl-text-v2.json').read_text())
        self.assertFalse(config['follow_links']); self.assertFalse(config['download_audio'])
        config['seeds'] = config['seeds'][:2]; config['limits'].update(interval_seconds=0, max_pages=10)
        calls = []
        class Opener:
            def open(self, request, **kwargs):
                url = request.full_url; calls.append(url)
                if url.endswith('robots.txt'):
                    return Response(b'User-agent: *\nAllow: /\n')
                return Response(b'<title>Synthetic</title><div id="verses"><h3 id="C1Gen">Heading</h3>'
                                b'<p class="calibre2">SYNTHETIC</p><a href="/life-study/9.html">next</a></div>')
        with tempfile.TemporaryDirectory() as folder:
            fetcher = BoundedFetcher(Path(folder), config); fetcher.opener = Opener()
            report = crawler.collect(Path(folder), config, fetcher)
        self.assertEqual(report['pages_acquired'], 2)
        self.assertFalse(any(url.endswith('/life-study/9.html') for url in calls))

    def test_page_cap_still_enforced(self):
        config = json.loads((ROOT/'sources/church-crawl-text-v2.json').read_text())
        config['limits']['max_pages'] = crawler.MAX_PAGES+1
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            crawler.collect(Path(folder), config, None)


class AudioFetchTests(unittest.TestCase):
    def setup_collection(self, root):
        (root/'col/review').mkdir(parents=True); (root/'col/manifests').mkdir()
        url = 'https://line.twgbr.org/life-study/mp3/ot/Gen-001.mp3'
        (root/'col/review/audio-index.jsonl').write_text(json.dumps(dict(source_url=url, page_urls=['https://line.twgbr.org/life-study/1.html']))+'\n')
        (root/'col/manifests/pages.jsonl').write_text(json.dumps(dict(source_url='https://line.twgbr.org/life-study/1.html', title='t', text_path='text_only/a.txt', text_sha256='0'))+'\n')
        config = json.loads((ROOT/'sources/church-audio-eval-v1.json').read_text())
        config.update(collection=str(root/'col'), audio_urls=[url]); config['limits']['interval_seconds'] = 0
        return config

    def test_rows_are_internal_evaluation_only_and_non_mp3_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = self.setup_collection(root)
            for body, files in [(b'ID3' + b'\0'*64, 1), (b'<html>not audio</html>', 0)]:
                out = root/f'out{files}'
                class Opener:
                    def open(self, request, **kwargs):
                        return Response(b'User-agent: *\nAllow: /\n' if request.full_url.endswith('robots.txt') else body)
                fetcher = BoundedFetcher(out, config); fetcher.opener = Opener()
                report = audio.fetch(out, config, fetcher)
                self.assertEqual(report['files'], files); self.assertFalse(report['training_ready'])
                for line in (out/'manifests/audio.jsonl').read_text().splitlines():
                    row = json.loads(line)
                    self.assertFalse(row['training_ready']); self.assertEqual(row['split'], 'unassigned')

    def test_training_or_unindexed_audio_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); config = self.setup_collection(root)
            with self.assertRaises(ValueError):
                audio.fetch(root/'a', dict(config, training_enabled=True), None)
            with self.assertRaises(ValueError):
                audio.fetch(root/'b', dict(config, audio_urls=['https://line.twgbr.org/other.mp3']), BoundedFetcher(root/'b', config))


if __name__ == '__main__':
    unittest.main()
