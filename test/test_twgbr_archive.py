import argparse
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import download_twgbr_archive as arch

BIBLE = ("<script>var bible = { numChapters: '2', bookMP4Prefix: 'Ruth' };</script><div id='verses'>"
         "<div id='chapternav'>NAV</div>回首頁<h3>路得記 第 1 章</h3><p>1</p><p>SYNTHETIC VERSE</p></div>")
INDEX = ("<title>撒母耳記 - 舊約生命讀經</title><div id='verses'><h3>第一篇　SYNTHETIC</h3>"
         "<audio><source src='mp3/ot/1Sa-001.mp3'></audio><p>BODY</p></div>"
         "<a href='{n}_2.html'>2</a><a href='https://example.org/x.html'>out</a>")


class FakeArchive(arch.Archive):
    def __init__(self, root, pages):
        super().__init__(root, 0.5, 0, 5, 10_000_000); self.pages = pages; self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        if url not in self.pages:
            raise OSError('synthetic 404')
        return self.pages[url]


class ArchiveTests(unittest.TestCase):
    def test_text_strips_navigation_and_joins_verse_numbers(self):
        text, title = arch.main_text(BIBLE.encode())
        self.assertEqual(title, '路得記 第 1 章')
        self.assertIn('1 SYNTHETIC VERSE', text)
        self.assertNotIn('回首頁', text); self.assertNotIn('NAV', text)

    def test_scope_rejects_other_hosts(self):
        archive = arch.Archive(tempfile.mkdtemp(), 0.5, 0, 5, 1000)
        with self.assertRaises(ValueError):
            archive.fetch('https://example.org/a.mp3')
        with self.assertRaises(ValueError):
            archive.fetch('http://line.twgbr.org/life-study/1.html')

    def test_books_argument(self):
        self.assertEqual(arch.parse_books('1,40-42'), [1, 40, 41, 42])
        with self.assertRaises(argparse.ArgumentTypeError):
            arch.parse_books('0-67')

    def test_bible_audio_urls_and_resume(self):
        mp3 = b'ID3' + b'\0'*32
        pages = {'https://line.twgbr.org/recoveryversion/bible/08.html': BIBLE.encode(),
                 'https://plan.bible365.today/plan/mp3/bible/08/01-Ruth.mp3': mp3,
                 'https://plan.bible365.today/plan/mp3/bible/08/02-Ruth.mp3': mp3}
        with tempfile.TemporaryDirectory() as folder:
            archive = FakeArchive(folder, pages); arch.bible(archive, [8], True, True, 0)
            self.assertEqual(archive.errors, [])
            self.assertTrue((Path(folder)/'recovery-version/audio/08-路得記/002.mp3').exists())
            again = FakeArchive(folder, pages); arch.bible(again, [8], True, True, 0)
            self.assertEqual(again.calls, [])  # finished files are skipped

    def test_life_study_shared_books_saved_once_and_external_links_ignored(self):
        mp3 = b'ID3' + b'\0'*32; pages = {}
        for n in (9, 10):
            pages[f'https://line.twgbr.org/life-study/{n}.html'] = INDEX.format(n=9).encode()
        pages['https://line.twgbr.org/life-study/9_2.html'] = INDEX.format(n=9).encode()
        pages['https://line.twgbr.org/life-study/mp3/ot/1Sa-001.mp3'] = mp3
        with tempfile.TemporaryDirectory() as folder:
            archive = FakeArchive(folder, pages); arch.life_study(archive, [9, 10], True, True, 0)
            self.assertFalse(any('example.org' in url for url in archive.calls))
            self.assertTrue((Path(folder)/'life-study/text/09-撒母耳記/002.txt').exists())
            self.assertFalse((Path(folder)/'life-study/html/10-撒母耳記').exists())
            arch.write_readme(archive, argparse.Namespace(collections='life-study', books=[9, 10], no_text=False,
                                                          no_audio=False, limit_per_book=0))
            readme = (Path(folder)/'README.md').read_text(encoding='utf-8')
            self.assertIn('資料夾結構', readme); self.assertIn('不公開', readme)
            rows = [json.loads(l) for l in (Path(folder)/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(all(len(r['sha256']) == 64 for r in rows))

    def test_non_mp3_response_is_an_error_not_a_file(self):
        pages = {'https://line.twgbr.org/recoveryversion/bible/08.html': BIBLE.encode(),
                 'https://plan.bible365.today/plan/mp3/bible/08/01-Ruth.mp3': b'<html>error</html>'}
        with tempfile.TemporaryDirectory() as folder:
            archive = FakeArchive(folder, pages); arch.bible(archive, [8], False, True, 1)
            self.assertEqual(len(archive.errors), 1)
            self.assertFalse((Path(folder)/'recovery-version/audio/08-路得記/001.mp3').exists())


if __name__ == '__main__':
    unittest.main()
