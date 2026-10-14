#!/usr/bin/env python3
"""Bounded audio metadata/prefix inspection; no full download, transcription or training."""
import argparse
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path
import urllib.request
from review_sources import Reviewer, ReviewError, validate_url


def probe_audio(reviewer, url, output, max_bytes=131072):
    if not 4096 <= max_bytes <= min(1048576, reviewer.limits['max_bytes_per_response']):
        raise ReviewError('Audio inspection byte budget is outside the bounded range')
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise ReviewError('ffprobe is unavailable; prepare this prerequisite before probing')
    url = validate_url(url, reviewer.hosts)
    if not reviewer.can_fetch(url):
        raise ReviewError('robots.txt disallows the audio path')
    headers = {'User-Agent': reviewer.config['user_agent'], 'Accept-Encoding': 'identity'}
    reviewer.before_request(url)
    with reviewer.opener.open(urllib.request.Request(url, method='HEAD', headers=headers), timeout=reviewer.limits['timeout_seconds']) as response:
        head = {'status': response.status, 'mime': response.headers.get('Content-Type'), 'content_length': response.headers.get('Content-Length'), 'accept_ranges': response.headers.get('Accept-Ranges')}
    reviewer.before_request(url)
    with reviewer.opener.open(urllib.request.Request(url, headers={**headers, 'Range': f'bytes=0-{max_bytes-1}'}), timeout=reviewer.limits['timeout_seconds']) as response:
        if response.status != 206:
            raise ReviewError('Byte range not honored; stop before reading a full response')
        final_url = validate_url(response.geturl(), reviewer.hosts)
        content_range = response.headers.get('Content-Range', '')
        match = re.fullmatch(r'bytes 0-(\d+)/(\d+)', content_range)
        if not match or int(match[1]) >= max_bytes:
            raise ReviewError('Unexpected audio Content-Range')
        if int(match[1]) + 1 >= int(match[2]):
            raise ReviewError('Range would cover the full recording; lower the byte budget')
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes or len(data) != int(match[1]) + 1:
            raise ReviewError('Audio prefix size does not match the permitted range')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    sample = output / (digest + '.audio-prefix')
    sample.write_bytes(data)
    command = [ffprobe, '-v', 'error', '-select_streams', 'a', '-show_entries', 'stream=codec_name,sample_rate,channels,bit_rate', '-of', 'json', str(sample)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if result.returncode:
        raise ReviewError('Audio prefix probe failed; do not claim a valid full recording')
    streams = json.loads(result.stdout).get('streams', [])
    if not streams:
        raise ReviewError('No audio stream found in the bounded prefix')
    report = {
        'source_url': url, 'final_url': final_url, 'head': head, 'content_range': content_range,
        'bytes_downloaded': len(data), 'sha256': digest, 'sample_path': str(sample),
        'streams': streams, 'request_attempts': reviewer.request_count,
        'probe_scope': 'initial_byte_range_only', 'full_audio_downloaded': False,
        'full_duration_verified': False, 'verbatim_alignment_verified': False,
        'rights_status': 'pending', 'review_only': True, 'training_ready': False,
    }
    (output / 'audio-probe.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='sources/twgbr-review.json')
    parser.add_argument('--url', required=True)
    parser.add_argument('--output', default='data/source-review/audio-probe')
    parser.add_argument('--max-bytes', type=int, default=131072)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    report = probe_audio(Reviewer(config, args.output), args.url, args.output, args.max_bytes)
    print(json.dumps({key: report[key] for key in ['bytes_downloaded', 'content_range', 'streams', 'full_audio_downloaded', 'verbatim_alignment_verified', 'training_ready']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
