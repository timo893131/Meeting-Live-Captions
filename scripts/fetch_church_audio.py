#!/usr/bin/env python3
"""Download a few indexed church audio files for private internal evaluation; never training data."""
import argparse
import json
from pathlib import Path

from tw_speech_pilot import BoundedFetcher, atomic_json, now, preserve_bytes, sha256

MAX_FILES = 5


def load_index(collection):
    rows = {}
    for line in (Path(collection)/'review/audio-index.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line); rows[row['source_url']] = row
    pages = {}
    for line in (Path(collection)/'manifests/pages.jsonl').read_text(encoding='utf-8').splitlines():
        if line.strip():
            row = json.loads(line); pages[row['source_url']] = row
    return rows, pages


def fetch(root, config, fetcher):
    root = Path(root)
    if (config.get('training_enabled') is not False or config.get('rights_status') != 'pending'
            or config.get('purpose') != 'internal_evaluation_pending_rights'
            or not 1 <= len(config['audio_urls']) <= MAX_FILES):
        raise ValueError(f'Only up to {MAX_FILES} pending-rights files for internal evaluation are supported')
    index, pages = load_index(config['collection'])
    for name in ['raw', 'manifests', 'reports']:
        (root/name).mkdir(parents=True, exist_ok=True)
    rows = []; failures = []
    for url in config['audio_urls']:
        if url not in index:
            raise ValueError('Audio URL was not discovered by the text collection: '+url)
        page_url = index[url]['page_urls'][0]; page = pages[page_url]
        try:
            data = fetcher.get(url)
            if not data.startswith((b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2')):
                raise ValueError('Response is not an MP3 stream')
            digest = sha256(data); path = root/'raw'/f'{digest}.mp3'
            if not path.exists():
                preserve_bytes(path, data)
            rows.append(dict(id=digest[:16], source_url=url, page_url=page_url, page_title=page.get('title'),
                             page_text_path=page.get('text_path'), page_text_sha256=page.get('text_sha256'),
                             audio_path=str(path.relative_to(root)), sha256=digest, bytes=len(data),
                             retrieved_at=fetcher.state['cache'][sha256(url.encode())]['fetched_at'],
                             rights_status='pending', allowed_use='internal_evaluation_pending_rights',
                             transcript_status='web_text_not_verified_verbatim', training_ready=False,
                             split='unassigned'))
            print(json.dumps(dict(event='audio_fetched', url=url, bytes=len(data))), flush=True)
        except Exception as error:
            failures.append(dict(url=url, type=type(error).__name__, reason=str(error)[:250]))
    (root/'manifests/audio.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in rows), encoding='utf-8')
    report = dict(finished_at=now(), files=len(rows), bytes=sum(r['bytes'] for r in rows), failures=failures,
                  http_requests_cumulative=fetcher.state['requests'], rights_status='pending',
                  training_ready=False, purpose=config['purpose'])
    atomic_json(root/'reports/fetch-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='sources/church-audio-eval-v1.json')
    parser.add_argument('--output', default='data/church-audio/twgbr-eval-v1')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    root = Path(args.output).resolve()
    report = fetch(root, config, BoundedFetcher(root, config))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['files']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
