#!/usr/bin/env python3
"""Upload the Recovery Version text to the private R2 bucket for verse alignment (spec-large-meeting.md M2).

Reads <archive>/recovery-version/text/NN-書名.txt (the TWGBR download on Drive) and writes one object per chapter:
  rv/<book 01–66>/<chapter 001–150>.json = {"book": "弗", "chapter": 1, "verses": {"1": "…", …}}
plus rv/manifest.json (counts and a hash of the text). The Worker (cloudflare/verses.js) reads them for a room's
host only. Rights: TWGBR, internal use decided by the user (spec section 2); the bucket stays private.

  python scripts/upload_scripture.py --archive <twgbr-archive> --output out/   # build only (check before upload)
  python scripts/upload_scripture.py --archive <twgbr-archive> --upload         # needs R2_ACCOUNT_ID,
                                                                                  # R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY
"""
import argparse
import hashlib
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import outline_ocr  # noqa: E402
from outline_pdf_to_md import BOOK_ABBREVIATIONS  # noqa: E402

BUCKET = 'meeting-captions-scripture'


def chapter_key(book, chapter):
    return f'rv/{BOOK_ABBREVIATIONS.index(book) + 1:02d}/{chapter:03d}.json'


def build(text_dir):
    """→ (objects {key: bytes}, report). Fails when a book file or a chapter is missing."""
    verses = outline_ocr.load_recovery_version(text_dir)
    chapters = {}
    for (book, chapter, verse), text in verses.items():
        chapters.setdefault((book, chapter), {})[str(verse)] = text
    missing = [f'{book}{chapter}' for book in BOOK_ABBREVIATIONS
               for chapter in range(1, outline_ocr.CHAPTERS[book] + 1) if (book, chapter) not in chapters]
    objects = {}
    for (book, chapter), items in sorted(chapters.items(), key=lambda item: chapter_key(*item[0])):
        ordered = dict(sorted(items.items(), key=lambda kv: int(kv[0])))
        objects[chapter_key(book, chapter)] = json.dumps({'book': book, 'chapter': chapter, 'verses': ordered},
                                                         ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    digest = hashlib.sha256(b''.join(objects[key] for key in sorted(objects))).hexdigest()
    report = {'created_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'chapters': len(objects),
              'expected_chapters': sum(outline_ocr.CHAPTERS.values()), 'verses': len(verses),
              'missing_chapters': missing, 'sha256': digest,
              'rights': 'TWGBR Recovery Version; internal use by the owner (docs/spec-large-meeting.md#2); private bucket'}
    objects['rv/manifest.json'] = json.dumps(report, ensure_ascii=False, indent=1).encode('utf-8')
    return objects, report


def r2_client():
    import boto3
    account = os.environ['R2_ACCOUNT_ID'].strip()
    return boto3.client('s3', endpoint_url=f'https://{account}.r2.cloudflarestorage.com', region_name='auto',
                        aws_access_key_id=os.environ['R2_ACCESS_KEY_ID'].strip(),
                        aws_secret_access_key=os.environ['R2_SECRET_ACCESS_KEY'].strip())


def upload(objects, client, bucket=BUCKET, log=print):
    def put(item):
        key, body = item
        client.put_object(Bucket=bucket, Key=key, Body=body, ContentType='application/json; charset=utf-8')
        return key
    done = 0
    with ThreadPoolExecutor(max_workers=16) as pool:
        for _key in pool.map(put, objects.items()):
            done += 1
            if done % 200 == 0 or done == len(objects):
                log(f'已上傳 {done}／{len(objects)}')
    sample = json.loads(client.get_object(Bucket=bucket, Key=chapter_key('弗', 1))['Body'].read())
    return sample


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--archive', type=Path, required=True, help='twgbr-archive folder (has recovery-version/text)')
    parser.add_argument('--output', type=Path, help='also write the objects here (to check them)')
    parser.add_argument('--upload', action='store_true')
    parser.add_argument('--bucket', default=BUCKET)
    args = parser.parse_args(argv)
    objects, report = build(args.archive/'recovery-version'/'text')
    print(json.dumps({k: report[k] for k in ('chapters', 'expected_chapters', 'verses', 'sha256')}, ensure_ascii=False))
    if report['missing_chapters']:
        print('缺少的章：', '、'.join(report['missing_chapters'][:50]))
        return 1
    if args.output:
        for key, body in objects.items():
            (args.output/key).parent.mkdir(parents=True, exist_ok=True)
            (args.output/key).write_bytes(body)
    if args.upload:
        sample = upload(objects, r2_client(), args.bucket)
        print('讀回檢查 弗1:1：', sample['verses'].get('1', '')[:20])
    return 0


if __name__ == '__main__':
    sys.exit(main())
