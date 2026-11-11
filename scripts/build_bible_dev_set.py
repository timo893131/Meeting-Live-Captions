#!/usr/bin/env python3
"""Build a development test set from Recovery Version chapter readings (audio + chapter text).

The chapter audio is a reading of the Recovery Version text, so the chapter text is a near-verbatim
reference (outline headings are read too; verse numbers are not). This is DEVELOPMENT data for checking
term lists and correction rules; it is not a sealed test and rights are pending (private use only).

Chapters are spread over all 66 books deterministically; chapter 1 is avoided where possible because its
recording starts with a book introduction that is not in the chapter text.

Usage: python scripts/build_bible_dev_set.py --archive data/twgbr-archive-v2 --output data/bible-dev-v1
       (audio is copied from <archive>/recovery-version/audio when present, otherwise downloaded)
"""
import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import download_twgbr_archive as archive  # noqa: E402

OUTLINE_NUMBER = re.compile(r'^(?:[壹貳參肆伍陸柒捌玖拾]+|[一二三四五六七八九十]+|\d+|[A-Za-z])[.．、]\s*')
VERSE_RANGE = re.compile(r'[\s\u3000]+[一二三四五六七八九十百○〇]*\d+[上下]?(?:[～─-][^。，；]*)?$')


def chapter_text(book_text, book_name, chapter):
    """Text of one chapter: outline titles (as read aloud, without numbering) and verse text."""
    # Match on 第 N 章 only: the site writes some headings with a variant book name (腓利比書 第 2 章).
    heading = re.compile(r'^\S+ 第 (\d+) 章$')
    lines = []
    # Single-chapter books (腓利門書, 約翰二書…) have no 第 1 章 heading: the text follows the title lines.
    inside = chapter == 1 and not any(heading.match(l.strip()) for l in book_text.splitlines())
    for line in book_text.splitlines():
        if inside and not lines and line.strip() in (book_name, book_name.replace('壹', '一').replace('貳', '二').replace('參', '三')):
            continue
        match = heading.match(line.strip())
        if match:
            if inside:
                break
            inside = int(match.group(1)) == chapter
            continue
        if inside and line.strip():
            line = line.strip()
            if OUTLINE_NUMBER.match(line):
                line = VERSE_RANGE.sub('', OUTLINE_NUMBER.sub('', line))
            line = re.sub(r'^\d+\s+', '', line)  # verse numbers are not read aloud
            lines.append(line)
    return '\n'.join(lines)


def pick_chapters(chapters_by_book, count):
    picks = []
    for i in range(count):
        book = 1 + (i*66)//count
        total = chapters_by_book[book]
        chapter = 1 if total == 1 else 2 + (book*7) % (total - 1)
        picks.append((book, chapter))
    return picks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', default='data/twgbr-archive-v2')
    parser.add_argument('--output', default='data/bible-dev-v1')
    parser.add_argument('--count', type=int, default=20)
    args = parser.parse_args()
    root = Path(args.archive); output = Path(args.output); output.mkdir(parents=True, exist_ok=True)
    chapters, prefixes, texts = {}, {}, {}
    for n in range(1, 67):
        html = (root/f'recovery-version/html/{archive.folder(n)}.html').read_text(encoding='utf-8')
        chapters[n] = archive.chapter_count(html)
        prefixes[n] = re.search(r"bookMP4Prefix:\s*['\"]([^'\"]+)", html).group(1)
        texts[n] = (root/f'recovery-version/text/{archive.folder(n)}.txt').read_text(encoding='utf-8')
    manifest = []
    for index, (book, chapter) in enumerate(pick_chapters(chapters, args.count), 1):
        pair = f'{index:02d}'
        reference = chapter_text(texts[book], archive.BOOKS[book-1], chapter)
        if not reference:
            raise SystemExit(f'No text for {archive.BOOKS[book-1]} {chapter}')
        (output/f'{pair}.txt').write_text(reference+'\n', encoding='utf-8')
        audio = output/f'{pair}.mp3'
        local = root/f'recovery-version/audio/{archive.folder(book)}/{chapter:03d}.mp3'
        url = archive.bible_audio_url(book, chapter, chapters[book], prefixes[book])
        if not audio.exists():
            if local.exists():
                shutil.copyfile(local, audio)
            else:
                request = urllib.request.Request(url, headers={'User-Agent': archive.UA})
                audio.write_bytes(urllib.request.urlopen(request, timeout=120).read())
        manifest.append(dict(id=pair, book=book, book_name=archive.BOOKS[book-1], chapter=chapter, audio_url=url,
                             reference_chars=len(reference), purpose='development_not_sealed',
                             rights_status='pending_private_use'))
        print(f'{pair} {archive.BOOKS[book-1]} {chapter} 章（{len(reference)} 字）', flush=True)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
