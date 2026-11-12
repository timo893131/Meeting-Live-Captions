#!/usr/bin/env python3
"""Build a Life-Study development set (message audio + message text) from the private TWGBR archive.

The Life-Study audio is a speaker reading the message with his own remarks, so the web text is NOT a verbatim
reference: score it with evaluate_meet.py --development --loose-reference (alignment-free term counts), and
use it to find church terms the recognizer gets wrong (scripts/mine-same-sound-terms.mjs). It is development
data, never the sealed MEET test; rights are pending (private use only, no training).

Messages are spread over the Life-Study books deterministically; message 1 of each book is avoided (book
introduction) and only messages with a single audio file are used.

Usage: python scripts/build_life_study_dev_set.py --archive <twgbr-archive> --output <folder> [--count 16]
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import download_twgbr_archive as archive  # noqa: E402


def available(root):
    """{book: [message numbers with text and exactly one audio file]} for books with their own Life-Study."""
    found = {}
    for n in range(1, 67):
        if n in archive.SHARED_LIFE_STUDY:
            continue
        texts = root/'life-study/text'/archive.folder(n)
        audio = root/'life-study/audio'/archive.folder(n)
        if not texts.is_dir() or not audio.is_dir():
            continue
        messages = []
        for text in sorted(texts.glob('*.txt')):
            k = text.stem
            if k.isdigit() and (audio/f'{k}.mp3').exists() and not (audio/f'{k}-2.mp3').exists():
                messages.append(int(k))
        if messages:
            found[n] = messages
    return found


def pick(found, count):
    books = sorted(found)
    picks = []
    for i in range(min(count, len(books))):
        book = books[(i*len(books))//count]
        messages = [m for m in found[book] if m != 1] or found[book]
        picks.append((book, messages[(book*7) % len(messages)]))
    return picks


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--archive', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--count', type=int, default=16)
    args = parser.parse_args()
    root, output = Path(args.archive), Path(args.output)
    found = available(root)
    if not found:
        raise SystemExit(f'在 {root} 找不到生命讀經文字與音訊（life-study/text、life-study/audio）')
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index, (book, message) in enumerate(pick(found, args.count), 1):
        pair, folder = f'{index:02d}', archive.folder(book)
        text = (root/f'life-study/text/{folder}/{message:03d}.txt').read_text(encoding='utf-8')
        (output/f'{pair}.txt').write_text(text, encoding='utf-8')
        source = root/f'life-study/audio/{folder}/{message:03d}.mp3'
        target = output/f'{pair}.mp3'
        if not target.exists() or target.stat().st_size != source.stat().st_size:
            shutil.copyfile(source, target)
        manifest.append(dict(id=pair, book=book, book_name=archive.BOOKS[book-1], message=message,
                             text_chars=len(text), audio_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
                             purpose='development_not_sealed', reference='not_verbatim',
                             rights_status='pending_private_use'))
        print(f'{pair} {archive.BOOKS[book-1]}生命讀經 第 {message} 篇（{len(text)} 字）', flush=True)
    (output/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
