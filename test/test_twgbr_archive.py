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
         "<div id='chapternav'>NAV</div>回首頁<h3 id='C1Ruth'>路得記 第 1 章</h3><p>1</p><p>SYNTHETIC VERSE</p>"
         "<h3 id='C2Ruth'>路得記 第 2 章</h3></div>")
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

    def test_chapters_counted_from_headings_not_wrong_player_setting(self):
        page = BIBLE.replace("numChapters: '2'", 'numChapters: 5').encode()  # 播放器寫 5，經文只有 2 章
        pages = {'https://line.twgbr.org/recoveryversion/bible/66.html': page,
                 'https://plan.bible365.today/plan/mp3/bible/66/01-Ruth.mp3': b'ID3', 'https://plan.bible365.today/plan/mp3/bible/66/02-Ruth.mp3': b'ID3'}
        with tempfile.TemporaryDirectory() as folder:
            archive = FakeArchive(folder, pages); arch.bible(archive, [66], False, True, 0)
            self.assertEqual(archive.errors, []); self.assertEqual(archive.book_stats[66]['chapters'], 2)

    def test_bible_audio_url_rules_verified_on_site(self):
        base = 'https://plan.bible365.today/plan/mp3/bible'
        self.assertEqual(arch.bible_audio_url(1, 1, 50, 'Genesis'), base+'/01/01-Genesis.mp3')
        self.assertEqual(arch.bible_audio_url(9, 1, 31, '1 Samuel'), base+'/09/01-1%20Samuel.mp3')
        self.assertEqual(arch.bible_audio_url(19, 1, 150, 'Psalms'), base+'/19/001-Psalms.mp3')
        self.assertEqual(arch.bible_audio_url(19, 150, 150, 'Psalms'), base+'/19/150-Psalms.mp3')

    def test_certificate_failure_stops_instead_of_logging_every_book(self):
        class CertFail(FakeArchive):
            def fetch(self, url):
                self.calls.append(url); raise arch.CertificateProblem('self-signed certificate in certificate chain')
        with tempfile.TemporaryDirectory() as folder:
            archive = CertFail(folder, {})
            with self.assertRaises(arch.CertificateProblem):
                arch.bible(archive, [1, 2, 3], True, False, 0)
            self.assertEqual(len(archive.calls), 1)

    def test_ssl_context_keeps_verification_on(self):
        context, _ = arch.ssl_context()
        self.assertEqual(context.verify_mode, arch.ssl.CERT_REQUIRED)
        with self.assertRaises(OSError):
            arch.ssl_context('/nonexistent/company-root.cer')

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

    def test_every_book_kept_shared_audio_copied_and_external_links_ignored(self):
        mp3 = b'ID3' + b'\0'*32; pages = {}
        for n in (9, 10):
            pages[f'https://line.twgbr.org/life-study/{n}.html'] = INDEX.format(n=n).encode()
            pages[f'https://line.twgbr.org/life-study/{n}_2.html'] = INDEX.format(n=n).encode()
        pages['https://line.twgbr.org/life-study/mp3/ot/1Sa-001.mp3'] = mp3
        with tempfile.TemporaryDirectory() as folder:
            archive = FakeArchive(folder, pages); arch.life_study(archive, [9, 10], True, True, 0)
            self.assertEqual(archive.errors, [])
            self.assertFalse(any('example.org' in url for url in archive.calls))
            self.assertEqual(archive.calls.count('https://line.twgbr.org/life-study/mp3/ot/1Sa-001.mp3'), 1)
            for name in ('09-撒母耳記上', '10-撒母耳記下'):
                self.assertTrue((Path(folder)/f'life-study/text/{name}/002.txt').exists())
                self.assertTrue((Path(folder)/f'life-study/audio/{name}/001.mp3').exists())
            arch.write_readme(archive, argparse.Namespace(collections='life-study', books=[9, 10], no_text=False,
                                                          no_audio=False, limit_per_book=0))
            readme = (Path(folder)/'README.md').read_text(encoding='utf-8')
            self.assertIn('逐卷清單', readme); self.assertIn('| 10-撒母耳記下 | — | 0／? | 2／2 |', readme)
            rows = [json.loads(l) for l in (Path(folder)/'manifest.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(all(len(r['sha256']) == 64 for r in rows))

    def test_zip_marks_chinese_names_as_utf8(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'arch'; (root/'life-study/text/01-創世記').mkdir(parents=True)
            (root/'life-study/text/01-創世記/001.txt').write_text('SYNTHETIC', encoding='utf-8')
            target = arch.make_zip(root, Path(folder)/'out.zip')
            with zipfile.ZipFile(target) as bundle:
                info = bundle.infolist()[0]
                self.assertEqual(info.filename, 'arch/life-study/text/01-創世記/001.txt')
                self.assertTrue(info.flag_bits & 0x800)

    def test_non_mp3_response_is_an_error_not_a_file(self):
        pages = {'https://line.twgbr.org/recoveryversion/bible/08.html': BIBLE.encode(),
                 'https://plan.bible365.today/plan/mp3/bible/08/01-Ruth.mp3': b'<html>error</html>'}
        with tempfile.TemporaryDirectory() as folder:
            archive = FakeArchive(folder, pages); arch.bible(archive, [8], False, True, 1)
            self.assertEqual(len(archive.errors), 1)
            self.assertFalse((Path(folder)/'recovery-version/audio/08-路得記/001.mp3').exists())


if __name__ == '__main__':
    unittest.main()
