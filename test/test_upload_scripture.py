import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import outline_ocr  # noqa: E402
import upload_scripture as up  # noqa: E402


def fake_archive(folder, skip=None):
    """Every chapter of every book with one made-up verse line (no Bible text)."""
    text = Path(folder)/'recovery-version'/'text'
    text.mkdir(parents=True)
    for number, (abbr, book) in enumerate(zip(outline_ocr.outline.BOOK_ABBREVIATIONS, outline_ocr.bible_books()), 1):
        lines = [book]
        for chapter in range(1, outline_ocr.CHAPTERS[abbr] + 1):
            if (abbr, chapter) == skip:
                continue
            heading = '篇' if abbr == '詩' else '章'
            lines += [f'{book} 第 {chapter} {heading}', '壹 綱要行不是經文', f'1 測試{abbr}{chapter}之一', f'2 測試{abbr}{chapter}之二']
        (text/f'{number:02d}-{book}.txt').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return Path(folder)


class FakeR2:
    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        assert Bucket == up.BUCKET and ContentType.startswith('application/json')
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        import io
        return {'Body': io.BytesIO(self.objects[Key])}


class UploadScriptureTests(unittest.TestCase):
    def test_builds_one_object_per_chapter_matching_the_worker_keys(self):
        with tempfile.TemporaryDirectory() as folder:
            objects, report = up.build(fake_archive(folder)/'recovery-version'/'text')
        self.assertEqual((report['chapters'], report['expected_chapters'], report['missing_chapters']), (1189, 1189, []))
        self.assertEqual(report['verses'], 2378)
        ephesians = json.loads(objects['rv/49/001.json'])  # same key as cloudflare/verses.js chapterKey('弗', 1)
        self.assertEqual(ephesians, {'book': '弗', 'chapter': 1, 'verses': {'1': '測試弗1之一', '2': '測試弗1之二'}})
        self.assertIn('rv/19/150.json', objects)  # Psalms headings say 第 N 篇
        self.assertIn('rv/manifest.json', objects)

    def test_missing_chapter_stops_before_upload(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = fake_archive(folder, skip=('弗', 3))
            self.assertEqual(up.build(archive/'recovery-version'/'text')[1]['missing_chapters'], ['弗3'])
            self.assertEqual(up.main(['--archive', str(archive), '--upload']), 1)  # returns before needing R2 keys

    def test_upload_puts_every_object_and_reads_one_back(self):
        with tempfile.TemporaryDirectory() as folder:
            objects, _ = up.build(fake_archive(folder)/'recovery-version'/'text')
        r2 = FakeR2()
        sample = up.upload(objects, r2, log=lambda *_: None)
        self.assertEqual(len(r2.objects), 1190)
        self.assertEqual(sample['verses']['1'], '測試弗1之一')


if __name__ == '__main__':
    unittest.main()
