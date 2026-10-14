#!/usr/bin/env python3
"""Inspect already downloaded TWGBR review pages; no network or training data export."""
import argparse
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup

PARSER_VERSION = 'twgbr-structure-inspection-v1'


def same_host_url(base, href):
    candidate = urljoin(base, href)
    parts = urlsplit(candidate)
    if parts.scheme != 'https' or parts.hostname != 'line.twgbr.org' or parts.username or parts.password:
        return None
    return urlunsplit(parts._replace(fragment=''))


def inspect_page(raw, url):
    if not same_host_url(url, url):
        raise ValueError('Page is outside the inspected TWGBR host')
    soup = BeautifulSoup(raw, 'html.parser')
    for element in soup.select('script, style, template'):
        element.decompose()
    path = urlsplit(url).path
    bible = re.fullmatch(r'/recoveryversion/bible/(\d+)\.html', path)
    life = re.fullmatch(r'/life-study/(\d+)(?:_(\d+))?\.html', path)
    kind = 'bible_book' if bible else 'life_study_message' if life else 'index'
    audio = sorted({target for element in soup.select('audio[src], audio source[src]') if (target := same_host_url(url, element.get('src', '')))})
    links = sorted({target for element in soup.select('a[href]') if (target := same_host_url(url, element['href']))})
    book_links, message_links = {}, {}
    for link in links:
        found = re.fullmatch(r'/life-study/(\d+)(?:_(\d+))?\.html', urlsplit(link).path)
        if found:
            book, message = int(found[1]), int(found[2] or 1)
            if life and book == int(life[1]):
                message_links[message] = link
            elif not life and not found[2]:
                book_links[book] = link
    root = soup.select_one('#verses')
    if kind != 'index' and root is None:
        raise ValueError('Expected #verses document container missing; do not fall back to whole-page text')
    result = {
        'url': url, 'parser_version': PARSER_VERSION, 'kind': kind,
        'title': soup.title.get_text(' ', strip=True) if soup.title else None,
        'audio_urls': audio, 'book_index_links': book_links, 'message_index_links': message_links,
        'chapter_numbers': [], 'paragraph_count': 0, 'outline_heading_count': 0,
        'body_character_count': 0, 'selector_verified': False,
        'message_number': int(life[2] or 1) if life else None,
        'audio_number_matches_heading': False,
        'verbatim_alignment_verified': False, 'training_ready': False,
    }
    if root is not None:
        # Navigation and player text are not the body being inspected.
        for element in root.select('#chapternav, .button, audio, center'):
            element.decompose()
        headings = []
        for element in root.select('h3[id]'):
            match = re.fullmatch(r'C(\d+)([A-Za-z]+)', element['id'])
            if match:
                headings.append((int(match[1]), match[2]))
        result['chapter_numbers'] = sorted({number for number, _ in headings}) if bible else []
        result['paragraph_count'] = len(root.select('p.calibre2'))
        result['outline_heading_count'] = sum(bool(re.fullmatch(r'O\d+', name)) for element in root.select('div[class]') for name in element.get('class', []))
        result['body_character_count'] = len(root.get_text('\n', strip=True))
        result['selector_verified'] = bool(headings and result['paragraph_count'])
        if life and len(audio) == 1 and len(headings) == 1:
            media = re.fullmatch(r'([A-Za-z]+)-(\d+)\.mp3', Path(urlsplit(audio[0]).path).name)
            result['audio_number_matches_heading'] = bool(media and (int(media[2]), media[1]) == headings[0] and int(media[2]) == result['message_number'])
    return result


def inspect_reports(paths):
    results = []
    for report_path in paths:
        report = json.loads(Path(report_path).read_text(encoding='utf-8'))
        for record in report['success']:
            raw = Path(record['raw_path']).read_bytes()
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('Raw page checksum mismatch; stop before inspection')
            metadata = inspect_page(raw, record['final_url'])
            metadata.update(source_id=record['source_id'], raw_sha256=record['sha256'], rights_status=record['rights_status'], allowed_uses=record['allowed_uses'])
            results.append(metadata)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', action='append', required=True)
    parser.add_argument('--output', default='data/source-review/twgbr/structure-inventory.json')
    args = parser.parse_args()
    results = inspect_reports(args.report)
    if not results:
        raise SystemExit('No acquired review pages; no inventory produced')
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'parser_version': PARSER_VERSION, 'pages': results, 'training_ready': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    for item in results:
        print(json.dumps({key: item[key] for key in ['source_id', 'kind', 'paragraph_count', 'body_character_count', 'chapter_numbers', 'audio_urls', 'audio_number_matches_heading', 'verbatim_alignment_verified', 'training_ready']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
