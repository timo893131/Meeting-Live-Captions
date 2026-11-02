"""Bounded Taiwan Mandarin pilot: provenance first, no training or auto scale-up."""
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
from pathlib import Path

UA = 'MeetingLiveCaptions-TaiwanSpeechPilot/1.0 (+https://github.com/timo893131/Meeting-Live-Captions)'


def now():
    return datetime.now(timezone.utc).isoformat()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def preserve_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('Existing original differs; use a new versioned root')
        return
    with path.open('xb') as out:
        out.write(data)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class BoundedFetcher:
    """Atomic per-file resume; counters and verified cache persist across restarts."""
    def __init__(self, root, config):
        self.root = Path(root)
        self.limits = config['limits']
        self.hosts = set(config['allowed_hosts'])
        self.cache = self.root/'raw/http'
        self.cache.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root/'reports/fetch-state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(requests=0, body_bytes=0, cache={})
        self.started = time.monotonic()
        self.last = 0.0
        self.robots = {}
        self.opener = urllib.request.build_opener(NoRedirect)

    def check_url(self, url):
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname not in self.hosts or parsed.username or parsed.password or parsed.port not in (None, 443):
            raise ValueError('Unapproved HTTPS download host: '+str(parsed.hostname))

    def save(self):
        atomic_json(self.state_path, self.state)

    def request(self, url):
        self.check_url(url)
        if self.state['body_bytes'] >= self.limits['max_total_body_bytes']:
            raise RuntimeError('Cumulative body-byte budget exhausted')
        if self.state['requests'] >= self.limits['max_requests']:
            raise RuntimeError('Cumulative HTTP request budget exhausted')
        if time.monotonic()-self.started >= self.limits['max_wall_seconds']:
            raise RuntimeError('Wall-time budget exhausted')
        remaining = self.limits['interval_seconds']-(time.monotonic()-self.last)
        if remaining > 0:
            time.sleep(remaining)
        self.state['requests'] += 1
        self.last = time.monotonic()
        self.save()
        return self.opener.open(urllib.request.Request(url, headers={'User-Agent': UA}), timeout=self.limits['timeout_seconds'])

    def robots_allowed(self, url):
        parsed = urllib.parse.urlsplit(url)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        if origin not in self.robots:
            robot_url = origin+'/robots.txt'
            body = self.get(robot_url, robots=False, allow_404=True, max_bytes=262144)
            policy = urllib.robotparser.RobotFileParser(robot_url)
            policy.parse(body.decode('utf8', errors='replace').splitlines())
            self.robots[origin] = policy
        if not self.robots[origin].can_fetch(UA, url):
            raise RuntimeError('robots.txt disallows this URL')

    def get(self, url, robots=True, allow_404=False, max_bytes=None):
        self.check_url(url)
        if robots:
            self.robots_allowed(url)
        key = sha256(url.encode())
        cached = self.state['cache'].get(key)
        if cached:
            file = self.cache/key
            data = file.read_bytes()
            if sha256(data) != cached['sha256']:
                raise RuntimeError('Cached download hash mismatch')
            return data
        limit = min(max_bytes or self.limits['max_file_bytes'], self.limits['max_file_bytes'])
        current = url
        for redirect in range(self.limits['max_redirects']+1):
            response = None
            for attempt in range(self.limits['max_retries']+1):
                try:
                    response = self.request(current)
                    break
                except urllib.error.HTTPError as error:
                    if error.code in (301, 302, 303, 307, 308):
                        location = error.headers.get('Location')
                        if not location:
                            raise RuntimeError('Redirect has no Location')
                        current = urllib.parse.urljoin(current, location)
                        self.check_url(current)
                        if robots:
                            self.robots_allowed(current)
                        break
                    if error.code == 404 and allow_404:
                        response = None
                        self.state['cache'][key] = dict(url=url, status=404, sha256=sha256(b''), fetched_at=now())
                        (self.cache/key).write_bytes(b'')
                        self.save()
                        return b''
                    if error.code in (429, 500, 502, 503, 504) and attempt < self.limits['max_retries']:
                        retry = error.headers.get('Retry-After', '1')
                        if not retry.isdigit() or int(retry) > 10:
                            raise RuntimeError('Retry-After requires a later run') from error
                        time.sleep(max(1, int(retry)))
                        continue
                    raise
                except urllib.error.URLError:
                    # CONNECT access denial must not trigger repeated retries.
                    raise
            if response is None:
                continue
            with response:
                length = response.headers.get('Content-Length')
                if length and int(length) > limit:
                    raise RuntimeError('File exceeds configured byte limit')
                chunks = []
                size = 0
                while True:
                    if time.monotonic()-self.started >= self.limits['max_wall_seconds']:
                        raise RuntimeError('Wall-time budget exhausted')
                    remaining = min(limit-size, self.limits['max_total_body_bytes']-self.state['body_bytes'])
                    if remaining <= 0:
                        raise RuntimeError('Download body-byte budget exhausted')
                    block = response.read(min(65536, remaining))
                    if not block:
                        break
                    size += len(block)
                    self.state['body_bytes'] += len(block)
                    self.save()
                    if size > limit or self.state['body_bytes'] > self.limits['max_total_body_bytes']:
                        raise RuntimeError('Download body-byte budget exhausted')
                    chunks.append(block)
                    if length and size == int(length):
                        break
                data = b''.join(chunks)
                if length and size != int(length):
                    raise RuntimeError('Truncated HTTP response')
            file = self.cache/key
            temporary = file.with_suffix('.part')
            temporary.write_bytes(data)
            temporary.replace(file)
            self.state['cache'][key] = dict(url=url, final_host=urllib.parse.urlsplit(current).hostname, sha256=sha256(data), fetched_at=now(), size=size)
            self.save()
            return data
        raise RuntimeError('Redirect limit exceeded')


def check_license(card, expected):
    # Fail closed instead of inferring a license from public availability.
    frontmatter = card.split('---', 2)
    if len(frontmatter) != 3 or frontmatter[0].strip():
        raise ValueError('Dataset card has no supported YAML frontmatter')
    if not re.search(r'^license:\s*'+re.escape(expected)+r'\s*$', frontmatter[1], re.M):
        raise ValueError('Expected dataset license was not verified')


def collect(root, config, fetcher):
    source = config['source']
    card_bytes = fetcher.get(source['card_url'], max_bytes=1048576)
    check_license(card_bytes.decode('utf8'), source['expected_license'])
    preserve_bytes(root/'raw/dataset-card.md', card_bytes)
    metadata = fetcher.get(source['rows_url'], max_bytes=4194304)
    document = json.loads(metadata)
    rows = document.get('rows')
    if not isinstance(rows, list) or not rows:
        raise ValueError('No provider rows returned')
    if len(rows) > config['limits']['samples']:
        raise ValueError('Provider returned more than pilot sample budget')
    preserve_bytes(root/'raw/provider-rows.json', metadata)
    records = []
    failures = []
    seen_indexes = set()
    for entry in rows:
        row = entry.get('row', {})
        index = entry.get('row_idx')
        if not isinstance(index, int) or index in seen_indexes:
            failures.append(dict(row=None, reason='No stable provider row index'))
            continue
        seen_indexes.add(index)
        sample_id = f'fleurs-cmn-hant-tw-validation-{index}'
        try:
            audio = row.get('audio')
            if not isinstance(audio, list) or len(audio) != 1 or not isinstance(audio[0].get('src'), str):
                raise ValueError('Unsupported provider audio schema')
            text = row.get('raw_transcription') or row.get('transcription')
            if not isinstance(text, str) or not text.strip():
                raise ValueError('No provider text; audio must remain unpaired')
            payload = fetcher.get(audio[0]['src'])
            audio_path = root/'raw'/f'{sample_id}.audio'
            if audio_path.exists() and sha256(audio_path.read_bytes()) != sha256(payload):
                raise ValueError('Existing original audio differs; refuse overwrite')
            if not audio_path.exists():
                with audio_path.open('xb') as out:
                    out.write(payload)
            records.append(dict(id=sample_id, audio_filepath=str(audio_path.relative_to(root)), text=text, language=source['language'], duration=None, source_url=source['dataset_url'], recording_id=f'fleurs:{row.get("path") or index}', recording_identity_scope='provider_file_or_row_only_original_session_unknown', speaker_id=row.get('speaker_id') or None, segment_start=0, segment_end=None, transcript_status=source['reference_status'], license_status='approved', license=source['expected_license'], attribution=source['attribution'], license_evidence_sha256=sha256(card_bytes), provider_rows_sha256=sha256(metadata), sha256=sha256(payload), split='unassigned', provider_split='validation', dataset_role='pipeline_development_only', downloaded_at=fetcher.state['cache'][sha256(audio[0]['src'].encode())]['fetched_at'], language_spans=[], language_annotation_status='not_reviewed', local_reference_verified=False, training_ready=False))
        except Exception as error:
            failures.append(dict(id=sample_id, reason=type(error).__name__+': '+str(error).split('?')[0][:200]))
            if isinstance(row.get('raw_transcription') or row.get('transcription'), str):
                atomic_json(root/'text_only'/f'{sample_id}.json', dict(text=row.get('raw_transcription') or row.get('transcription'), source_url=source['dataset_url'], status='text_only_no_downloaded_audio', training_ready=False))
    preserve_bytes(root/'manifests/downloaded.jsonl', ''.join(json.dumps(record, ensure_ascii=False)+'\n' for record in records).encode())
    return records, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='sources/taiwan-mandarin-pilot.json')
    parser.add_argument('--root', default='data/taiwan-mandarin-pilot')
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    root = Path(args.root).resolve()
    config = json.loads(Path(args.config).read_text())
    if not 10 <= config['limits']['samples'] <= 20 or config.get('training_enabled') is not False or config.get('automatic_scale_up') is not False:
        raise ValueError('Pilot must contain 10–20 samples, training disabled, no auto expansion')
    for directory in ['raw', 'processed', 'manifests', 'text_only', 'review', 'reports']:
        (root/directory).mkdir(parents=True, exist_ok=True)
    fetcher = BoundedFetcher(root, config)
    report = dict(started_at=now(), config_sha256=sha256(Path(args.config).read_bytes()), sources_attempted=2, audio_sources_attempted=1, audio_downloaded=0, downloaded_hours=0, usable_paired_hours=0, pending_review_hours=0, trained=False, baseline_status='unrun', realtime_status='unrun', failures=[], status='in_progress')
    try:
        review_source = config['other_sources_review_only'][0]
        try:
            metadata = fetcher.get(review_source['metadata_url'], max_bytes=1048576)
            preserve_bytes(root/'raw/common-voice-release-metadata.json', metadata)
            report['source_review'] = dict(url=review_source['metadata_url'], sha256=sha256(metadata), license_status='pending_release_data_card', audio_downloaded=False)
        except Exception as review_error:
            report['source_review'] = dict(status='blocked_or_failed', reason=type(review_error).__name__)
        records, failures = collect(root, config, fetcher)
        report.update(audio_downloaded=len(records), failures=failures, downloaded_hours=None if records else 0, pending_review_hours=None if records else 0)
        if args.prepare and records:
            from tw_audio_prepare import prepare_records
            prepared_path = root/'manifests/prepared.jsonl'
            if prepared_path.exists():
                prepared = [json.loads(line) for line in prepared_path.read_text().splitlines() if line.strip()]
                if {r['id']:r['sha256'] for r in records} != {r['id']:r.get('raw_sha256') for r in prepared}:
                    raise ValueError('Existing prepared manifest differs from original downloads')
                for row in prepared:
                    if row.get('processed_sha256'):
                        file = (root/row['audio_filepath']).resolve(strict=True)
                        if not file.is_relative_to(root) or sha256(file.read_bytes()) != row['sha256']:
                            raise ValueError('Existing working audio hash mismatch')
                result = dict(records=prepared, report=dict(status='reused_verified_existing_manifest', records=len(prepared)))
            else:
                result = prepare_records(records, root)
                preserve_bytes(prepared_path, ''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in result['records']).encode())
            report['preparation'] = result['report']
            seconds = sum(row.get('duration') or 0 for row in result['records'])
            report['measured_decoded_hours'] = seconds/3600
            complete_durations = all(isinstance(row.get('duration'), (int, float)) for row in result['records'])
            report['downloaded_hours'] = seconds/3600 if complete_durations else None
            report['pending_review_hours'] = seconds/3600 if complete_durations else None
            report['pilot_sample_target_met'] = 10 <= len(records) <= 20
            report['quality_gate'] = 'pending_reference_and_near_duplicate_review'
        report['status'] = 'downloaded_pending_reference_review' if records else 'no_audio_collected'
    except Exception as error:
        report['status'] = 'blocked_or_failed'
        report['failures'].append(dict(type=type(error).__name__, reason=str(error).split('?')[0][:250]))
    report.update(finished_at=now(), http_requests_cumulative=fetcher.state['requests'], http_body_bytes_cumulative=fetcher.state['body_bytes'])
    atomic_json(root/'reports/collection-report.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['status'] in ('blocked_or_failed', 'no_audio_collected'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
