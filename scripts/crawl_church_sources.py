#!/usr/bin/env python3
"""Collect bounded church source pages and audio indexes; never a training dataset."""
import argparse
import json
import re
import urllib.parse
import urllib.error
from pathlib import Path

from bs4 import BeautifulSoup
from inspect_twgbr import inspect_page
from review_sources import PageReview
from tw_speech_pilot import BoundedFetcher, atomic_json, now, preserve_bytes, sha256


def eligible(url):
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme == 'https' and parts.hostname == 'line.twgbr.org'
            and not parts.username and not parts.password and parts.port in (None, 443)
            and not parts.query and not parts.fragment
            and bool(re.fullmatch(r'/life-study/(?:\d+(?:_\d+)?\.html)?|/recoveryversion/bible/\d+\.html', parts.path)))


def collect(root, config, fetcher):
    root = Path(root)
    if (config.get('training_enabled') is not False or config.get('download_audio') is not False
            or config.get('rights_status') != 'pending' or not 1 <= config['limits']['max_pages'] <= 10):
        raise ValueError('This crawler only supports at most 10 pending-rights pages and audio URLs')
    for name in ['raw', 'processed', 'manifests', 'text_only', 'review', 'reports']:
        (root/name).mkdir(parents=True, exist_ok=True)
    report = dict(started_at=now(), status='in_progress', pages_acquired=0, text_documents=0,
                  audio_urls_discovered=0, catalog_documents=0, audio_downloaded=0,
                  downloaded_hours=0, usable_paired_hours=0, pending_review_hours=0,
                  locally_verified_hours=0, trained=False, baseline_status='unrun',
                  rights_status='pending', training_ready=False, failures=[])
    pages = []; audio_index = {}; queue = list(dict.fromkeys(config['seeds'])); visited = set()
    if any(not eligible(url) for url in queue):
        raise ValueError('Seed outside permitted source paths')
    # Saved receipts and HTTP cache enable replay without downloading completed pages again.
    while queue and len(visited) < config['limits']['max_pages']:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        page_id = sha256(url.encode())
        receipt = root/'raw'/f'{page_id}.json'
        try:
            if receipt.exists():
                record = json.loads(receipt.read_text())
                for path_key, hash_key in [('raw_path', 'sha256'), ('text_path', 'text_sha256')]:
                    if record.get(path_key):
                        path = (root/record[path_key]).resolve(strict=True)
                        if not path.is_relative_to(root.resolve()) or sha256(path.read_bytes()) != record[hash_key]:
                            raise ValueError('Saved source receipt hash/path mismatch')
                if record['source_url'] != url:
                    raise ValueError('Saved source URL mismatch')
            else:
                payload = fetcher.get(url)
                raw_path = root/'raw'/f'{page_id}.html'
                preserve_bytes(raw_path, payload)
                structure = inspect_page(payload, url)
                # Index pages are navigation only; never turn those into reference transcripts.
                text = None
                if structure['kind'] != 'index':
                    if not structure['selector_verified']:
                        raise ValueError('Document selector not verified; raw page retained for review')
                    soup = BeautifulSoup(payload, 'html.parser')
                    body = soup.select_one('#verses')
                    for node in body.select('script,style,template,#chapternav,.button,audio,center'):
                        node.decompose()
                    text = body.get_text('\n', strip=True)
                    if not text:
                        raise ValueError('Empty document body')
                parser = PageReview(); parser.feed(payload.decode('utf-8-sig'))
                summary = parser.summary(url, config['allowed_hosts'])
                fetched_at = fetcher.state['cache'][sha256(url.encode())]['fetched_at']
                record = dict(id=page_id, source_url=url, retrieved_at=fetched_at,
                              raw_path=str(raw_path.relative_to(root)), sha256=sha256(payload),
                              title=structure['title'], kind=structure['kind'],
                              audio_urls=structure['audio_urls'], links=summary['same_host_links'],
                              text_path=None, text_sha256=None, rights_status='pending',
                              transcript_status='web_text_not_verified_verbatim',
                              verbatim_alignment_verified=False, training_ready=False)
                if text is not None:
                    text_path = root/'text_only'/f'{page_id}.txt'
                    encoded = text.encode('utf-8'); preserve_bytes(text_path, encoded)
                    record.update(text_path=str(text_path.relative_to(root)), text_sha256=sha256(encoded))
                preserve_bytes(receipt, (json.dumps(record, ensure_ascii=False, indent=2)+'\n').encode())
            pages.append(record)
            for media_url in record['audio_urls']:
                audio_index.setdefault(media_url, []).append(url)
            for link in record['links']:
                if eligible(link) and link not in visited and link not in queue:
                    queue.append(link)
            print(json.dumps(dict(event='page_collected', url=url, pages=len(pages),
                                  has_text=bool(record['text_path']), audio_urls=len(record['audio_urls'])), ensure_ascii=False), flush=True)
        except Exception as error:
            report['failures'].append(dict(url=url, type=type(error).__name__, reason=str(error).split('?')[0][:250]))
            # A failed host preflight is one failure, not ten repeated page attempts.
            if ('https://line.twgbr.org' not in fetcher.robots or 'robots' in str(error).lower()
                    or isinstance(error, urllib.error.URLError)):
                break
    catalogs = []
    for url in config.get('catalog_urls', []):
        try:
            payload = fetcher.get(url)
            path = root/'raw'/f'catalog-{sha256(url.encode())}.source'
            preserve_bytes(path, payload)
            catalogs.append(dict(source_url=url, sha256=sha256(payload), path=str(path.relative_to(root)),
                                 retrieved_at=fetcher.state['cache'][sha256(url.encode())]['fetched_at'],
                                 kind='official_catalog_metadata_not_audio', license_status='pending_release_data_card'))
        except Exception as error:
            report['failures'].append(dict(url=url, type=type(error).__name__, reason=str(error).split('?')[0][:250]))
    def save_jsonl(path, rows):
        previous = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
        index = {row.get('id', row['source_url']): row for row in previous}
        for row in rows:
            key = row.get('id', row['source_url'])
            if key in index and index[key] != row:
                if path.name != 'audio-index.jsonl':
                    raise ValueError('Existing collection index differs; use a new versioned root')
                row = dict(row, page_urls=sorted(set(index[key]['page_urls'] + row['page_urls'])))
            index[key] = row
        temporary = path.with_suffix('.tmp')
        temporary.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in index.values()))
        temporary.replace(path)
    # The same input root replays the same discovery order; never overwrite an old collection.
    save_jsonl(root/'manifests/pages.jsonl', pages)
    save_jsonl(root/'manifests/catalogs.jsonl', catalogs)
    save_jsonl(root/'review/audio-index.jsonl', [dict(source_url=url, page_urls=parents,
        downloaded=False, license_status='pending', transcript_status='not_paired', training_ready=False)
        for url, parents in sorted(audio_index.items())])
    report.update(finished_at=now(), pages_acquired=len(pages), text_documents=sum(bool(p['text_path']) for p in pages),
                  audio_urls_discovered=len(audio_index), catalog_documents=len(catalogs),
                  http_requests_cumulative=fetcher.state['requests'], http_body_bytes_cumulative=fetcher.state['body_bytes'],
                  sources_configured=2, sources_attempted=len({urllib.parse.urlsplit(url).path.split('/')[1] for url in visited}), output=str(root), quality_status='not_audio_qc; text/audio alignment unrun',
                  status='collected_pending_rights_and_alignment' if pages else 'site_blocked_catalog_only' if catalogs else 'blocked')
    atomic_json(root/'reports/collection-report.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='sources/church-crawl.json')
    parser.add_argument('--output', default='data/church-crawl/twgbr-v1')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text()); root = Path(args.output).resolve()
    report = collect(root, config, BoundedFetcher(root, config))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    if not report['pages_acquired']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
