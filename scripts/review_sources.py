#!/usr/bin/env python3
"""Bounded source review, not a recursive crawler or approved training corpus."""
import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


class ReviewError(Exception):
    pass


def validate_url(url, allowed_hosts):
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != 'https' or parts.hostname not in allowed_hosts or parts.username or parts.password or parts.port not in (None, 443):
        raise ReviewError('URL outside the permitted HTTPS hosts')
    return urllib.parse.urlunsplit(parts._replace(fragment=''))


class ScopedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts, before_redirect=None):
        super().__init__()
        self.allowed_hosts = allowed_hosts
        self.before_redirect = before_redirect

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_url(newurl, self.allowed_hosts)
        if self.before_redirect:
            self.before_redirect(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PageReview(HTMLParser):
    """Visible text is for inspection; site-specific document selectors are unverified."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ignored = 0
        self.in_title = False
        self.title = []
        self.text = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style', 'template'):
            self.ignored += 1
        if tag == 'title':
            self.in_title = True
        if not self.ignored:
            if tag in ('p', 'br', 'div', 'li', 'h1', 'h2', 'h3', 'tr', 'section', 'footer'):
                self.text.append('\n')
            if tag == 'a':
                href = dict(attrs).get('href')
                if href:
                    self.links.append(href)

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'template'):
            self.ignored = max(0, self.ignored - 1)
        if tag == 'title':
            self.in_title = False
        if not self.ignored and tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'tr', 'section', 'footer'):
            self.text.append('\n')

    def handle_data(self, data):
        if self.ignored:
            return
        if self.in_title:
            self.title.append(data)
        else:
            self.text.append(data)

    def summary(self, base_url, allowed_hosts):
        lines = [' '.join(line.split()) for line in ''.join(self.text).splitlines()]
        lines = [line for line in lines if line]
        links = set()
        for href in self.links:
            try:
                links.add(validate_url(urllib.parse.urljoin(base_url, href), allowed_hosts))
            except (ReviewError, ValueError):
                pass
        return {
            'title': ' '.join(''.join(self.title).split()),
            'visible_text': '\n'.join(lines),
            'same_host_links': sorted(links),
            'rights_clues': [line for line in lines if re.search(r'版權|著作權|授權|使用條款|copyright|permission|terms of use', line, re.I)],
            'parser': 'source-review-visible-html-v1',
            'document_selector_verified': False,
        }


class Reviewer:
    def __init__(self, config, output):
        if config.get('phase') != 'source_review_only':
            raise ReviewError('This tool only supports source review; it cannot approve training rights')
        self.config = config
        self.hosts = set(config['allowed_hosts'])
        self.limits = dict(config['limits'])
        if not (1 <= self.limits['max_seed_pages'] <= 10 and 1 <= self.limits['max_requests'] <= 20 and 1 <= self.limits['max_bytes_per_response'] <= 2000000 and 1 <= self.limits['timeout_seconds'] <= 60 and 1 <= self.limits['minimum_interval_seconds'] <= 30):
            raise ReviewError('Limits outside the bounded source-review range')
        self.output = Path(output)
        self.opener = urllib.request.build_opener(ScopedRedirect(self.hosts, self.before_request))
        self.last_request = {}
        self.robots = {}
        self.robots_evidence = {}
        self.request_count = 0

    def before_request(self, url):
        url = validate_url(url, self.hosts)
        if self.request_count >= self.limits['max_requests']:
            raise ReviewError('Request budget exhausted; no further request made')
        host = urllib.parse.urlsplit(url).hostname
        delay = self.limits['minimum_interval_seconds'] - (time.monotonic() - self.last_request.get(host, 0))
        if delay > 30:
            raise ReviewError('Required crawl wait exceeds this bounded review; defer the request')
        if delay > 0:
            time.sleep(delay)
        self.last_request[host] = time.monotonic()
        self.request_count += 1

    def fetch(self, url):
        url = validate_url(url, self.hosts)
        self.before_request(url)
        req = urllib.request.Request(url, headers={'User-Agent': self.config['user_agent']})
        with self.opener.open(req, timeout=self.limits['timeout_seconds']) as response:
            final_url = validate_url(response.geturl(), self.hosts)
            data = response.read(self.limits['max_bytes_per_response'] + 1)
            if len(data) > self.limits['max_bytes_per_response']:
                raise ReviewError('Response exceeds the configured byte limit')
            charset = response.headers.get_content_charset()
            if not charset:
                declared = re.search(br'charset\s*=\s*[\"\']?([a-zA-Z0-9_-]+)', data[:8192], re.I)
                charset = declared.group(1).decode('ascii') if declared else ('utf-8-sig' if data.startswith(b'\xef\xbb\xbf') else 'utf-8')
            return data, response.headers.get_content_type(), charset, final_url

    def can_fetch(self, url):
        parts = urllib.parse.urlsplit(url)
        origin = parts.scheme + '://' + parts.netloc
        if origin not in self.robots:
            robot_url = origin + '/robots.txt'
            rules = urllib.robotparser.RobotFileParser(robot_url)
            try:
                data, mime, _, _ = self.fetch(robot_url)
                if mime not in ('text/plain', 'application/octet-stream') or data.lstrip().lower().startswith((b'<html', b'<!doctype html')):
                    raise ReviewError('robots.txt is not a usable text response')
                digest = hashlib.sha256(data).hexdigest()
                self.output.mkdir(parents=True, exist_ok=True)
                robot_path = self.output / ('robots-' + digest + '.txt')
                robot_path.write_bytes(data)
                self.robots_evidence[origin] = {'state': 'checked', 'url': robot_url, 'sha256': digest, 'path': str(robot_path)}
                rules.parse(data.decode('utf-8', errors='replace').splitlines())
                # Preserve Crawl-delay, when declared, as a stricter minimum.
                delay = rules.crawl_delay(self.config['user_agent'])
                if delay is not None:
                    self.limits['minimum_interval_seconds'] = max(self.limits['minimum_interval_seconds'], delay)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    rules.allow_all = True
                    self.robots_evidence[origin] = {'state': 'absent_404', 'url': robot_url, 'sha256': None, 'path': None}
                else:
                    self.robots[origin] = None
                    self.robots_evidence[origin] = {'state': 'unavailable', 'url': robot_url, 'http_status': error.code}
                    raise ReviewError(f'robots.txt unavailable (HTTP {error.code}); no seed pages fetched') from error
            except (urllib.error.URLError, TimeoutError, ReviewError) as error:
                self.robots[origin] = None
                self.robots_evidence[origin] = {'state': 'unavailable', 'url': robot_url}
                raise ReviewError('robots.txt could not be checked; no seed pages fetched') from error
            self.robots[origin] = rules
        rules = self.robots[origin]
        if rules is None:
            raise ReviewError('robots.txt could not be checked; no seed pages fetched')
        return rules.can_fetch(self.config['user_agent'], url)

    def review(self, source):
        url = validate_url(source['seed_url'], self.hosts)
        if not self.can_fetch(url):
            raise ReviewError('robots.txt disallows this seed page')
        data, mime, charset, final_url = self.fetch(url)
        if mime not in ('text/html', 'application/xhtml+xml'):
            raise ReviewError('Seed is not an HTML page; select an appropriate parser first')
        digest = hashlib.sha256(data).hexdigest()
        parser = PageReview()
        parser.feed(data.decode(charset, errors='strict'))
        summary = parser.summary(final_url, self.hosts)
        if not summary['visible_text']:
            raise ReviewError('No visible text; inspect dynamic loading instead of claiming acquisition success')
        folder = self.output / source['source_id']
        folder.mkdir(parents=True, exist_ok=True)
        raw = folder / (digest + '.html')
        text = folder / (digest + '.txt')
        raw.write_bytes(data)
        text.write_text(summary.pop('visible_text'), encoding='utf-8')
        record = {
            'source_id': source['source_id'], 'seed_url': url, 'final_url': final_url,
            'retrieved_at': datetime.now(timezone.utc).isoformat(),
            'sha256': digest, 'mime': mime, 'charset': charset, 'bytes': len(data),
            'raw_path': str(raw), 'review_text_path': str(text),
            'rights_status': source['rights_status'], 'allowed_uses': source['allowed_uses'],
            'review_only': True, 'training_ready': False, **summary,
        }
        (folder / (digest + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        return record

    def run(self):
        sources = self.config['sources']
        if len(sources) > self.limits['max_seed_pages']:
            raise ReviewError('Configured seeds exceed max_seed_pages; no requests made')
        for source in sources:
            if not re.fullmatch(r'[a-zA-Z0-9_-]+', source['source_id']):
                raise ReviewError('Unsafe source_id; no requests made')
            validate_url(source['seed_url'], self.hosts)
        report = {'phase': 'source_review_only', 'success': [], 'failed': [], 'request_count': 0, 'training_ready': False}
        for source in sources:
            try:
                report['success'].append(self.review(source))
            except (ReviewError, urllib.error.URLError, TimeoutError, LookupError, ValueError) as error:
                report['failed'].append({'source_id': source['source_id'], 'error': str(error)})
        report['request_count'] = self.request_count
        report['robots_evidence'] = self.robots_evidence
        self.output.mkdir(parents=True, exist_ok=True)
        (self.output / 'review-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument('--config', default='sources/twgbr-review.json')
    args.add_argument('--output', default='data/source-review/twgbr')
    options = args.parse_args()
    config = json.loads(Path(options.config).read_text(encoding='utf-8'))
    report = Reviewer(config, options.output).run()
    print(json.dumps({'pages_acquired': len(report['success']), 'pages_failed': len(report['failed']), 'request_count': report['request_count'], 'report': str(Path(options.output) / 'review-report.json'), 'training_ready': False}, ensure_ascii=False))
    raise SystemExit(1 if report['failed'] else 0)


if __name__ == '__main__':
    main()
