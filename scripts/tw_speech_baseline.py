"""Offline Taiwan Mandarin ASR pilot. Does not measure live microphone latency."""
import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def eligible(records, policy):
    if policy not in ['verified_only', 'provider_provisional']:
        raise ValueError('Unknown reference policy')
    output = []
    excluded = []
    for row in records:
        reason = None
        if row.get('license_status') != 'approved' or not row.get('candidate_for_provider_baseline'):
            reason = 'rights_or_audio_quality_not_eligible'
        elif row.get('transcript_status') not in ['provider_reference', 'source_reference', 'human_verified'] or not isinstance(row.get('text'), str) or not row['text'].strip():
            reason = 'missing_or_unsupported_reference_status'
        elif policy == 'verified_only' and (row.get('local_reference_verified') is not True or row.get('transcript_status') != 'human_verified'):
            reason = 'local_reference_not_verified'
        elif row.get('language_spans') or re.search(r'\[(?:/?(?:EN|TAI|台語|英文)|/?lang[=:])', row.get('text', ''), re.I):
            reason = 'language_annotation_aware_scoring_required'
        if reason:
            excluded.append(dict(id=row.get('id'), reason=reason))
        else:
            output.append(row)
    return output, excluded


def score(rows, project):
    # Reuse the repository's fixed code-point alignment and normalizer, no new CER algorithm.
    js = """import fs from 'node:fs';import {normalize,align,NORMALIZER,METRIC_VERSION} from './scripts/glossary-metrics.mjs';
const rows=JSON.parse(fs.readFileSync(0,'utf8'));let S=0,D=0,I=0,N=0;
const scores=rows.map(row=>{const a=align(normalize(row.reference),normalize(row.hypothesis));S+=a.substitutions;D+=a.deletions;I+=a.insertions;N+=a.referenceCharacters;delete a.positions;return {id:row.id,...a};});
process.stdout.write(JSON.stringify({normalizer:NORMALIZER,metric_version:METRIC_VERSION,substitutions:S,deletions:D,insertions:I,reference_characters:N,cer:N?(S+D+I)/N:null,rows:scores}));"""
    result = subprocess.run(['node', '--input-type=module', '-e', js], input=json.dumps(rows), text=True, capture_output=True, check=True, cwd=project, timeout=30)
    return json.loads(result.stdout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', default='data/taiwan-mandarin-pilot')
    parser.add_argument('--model-dir', default='models/whisper-small')
    parser.add_argument('--output', required=True, help='New private report directory')
    parser.add_argument('--reference-policy', choices=['verified_only', 'provider_provisional'], default='verified_only')
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    root = Path(args.root).resolve()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir()
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), status='unrun', reference_policy=args.reference_policy, audio_count=0, sources=0, downloaded_hours=0, usable_paired_hours=0, pending_review_hours=0, trained=False, model_version='Systran/faster-whisper-small@536b0662742c02347bc0e980a01041f333bce120', model_loaded=False, reference_comparison=None, formal_gold_evaluation=False, realtime=dict(status='unrun', reason='No real microphone or normal-speed playback experiment performed', first_text_ms=None, final_ms=None, p50_ms=None, p95_ms=None, revisions=None), wer=dict(status='unrun', reason='No versioned Chinese word segmenter selected'), failures=[])
    try:
        manifest = root/'manifests/prepared.jsonl'
        if not manifest.exists():
            raise ValueError('No prepared real-audio manifest; collection and preparation must complete first')
        records = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
        report.update(manifest_sha256=file_hash(manifest), audio_count=len(records), sources=len({r.get('source_url') for r in records}), downloaded_hours=sum(r.get('duration') or 0 for r in records)/3600, pending_review_hours=sum((r.get('duration') or 0) for r in records if not r.get('local_reference_verified'))/3600)
        if len(records)>20:
            raise ValueError('Pilot baseline accepts at most 20 records')
        selected, excluded = eligible(records, args.reference_policy)
        report['excluded'] = excluded
        if not selected:
            raise ValueError('No eligible audio/reference rows for selected reference policy')
        model_dir = Path(args.model_dir).resolve()
        model = model_dir/'model.bin'
        if not model.exists():
            raise ValueError('Local model weights absent; download fixed revision and verify hash first')
        if file_hash(model) != '3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671':
            raise ValueError('Model hash differs from pinned baseline')
        from faster_whisper import WhisperModel
        report['runtime'] = dict(platform=platform.platform(), python=platform.python_version(), packages={name: importlib.metadata.version(name) for name in ['faster-whisper', 'ctranslate2', 'av']})
        started = time.monotonic()
        recognizer = WhisperModel(str(model_dir), device='cpu', compute_type='int8', cpu_threads=4, num_workers=1, local_files_only=True)
        report['model_load_seconds'] = time.monotonic()-started
        report['model_loaded'] = True
        report['settings'] = dict(language='zh', task='transcribe', beam_size=5, temperature=0, vad_filter=False, initial_prompt=None, hotwords=None, condition_on_previous_text=True)
        report['model_file_sha256'] = {str(file.relative_to(model_dir)): file_hash(file) for file in model_dir.glob('*') if file.is_file()}
        pairs = []
        inference_started = time.monotonic()
        for row in selected:
            if time.monotonic()-inference_started>600:
                raise RuntimeError('Pilot inference wall-time budget exhausted')
            audio = (root/row['audio_filepath']).resolve(strict=True)
            if not audio.is_relative_to(root) or file_hash(audio) != row['sha256']:
                raise ValueError('Working audio path or hash mismatch')
            started = time.monotonic()
            segments, info = recognizer.transcribe(str(audio), **report['settings'])
            segments = [dict(start=s.start, end=s.end, text=s.text) for s in segments]
            elapsed = time.monotonic()-started
            pairs.append(dict(id=row['id'], reference=row['text'], hypothesis=''.join(s['text'] for s in segments), segments=segments, offline_seconds=elapsed, audio_seconds=info.duration, offline_rtf=elapsed/info.duration if info.duration else None))
        report['transcriptions'] = pairs
        report['reference_comparison'] = score(pairs, project)
        report['status'] = 'completed_provisional_provider_comparison' if args.reference_policy == 'provider_provisional' else 'completed_local_verified_reference_comparison'
        report['formal_gold_evaluation'] = False
        report['reference_locally_verified'] = args.reference_policy == 'verified_only'
        report['holdout_evaluation_status'] = 'unrun_no_sealed_split_contract'
        report['usable_paired_hours'] = sum(r['duration'] for r in selected if r.get('local_reference_verified'))/3600
    except Exception as error:
        report['status'] = 'blocked_or_failed'
        report['failures'].append(dict(type=type(error).__name__, reason=str(error).split('?')[0][:250]))
    (output/'baseline-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k: report[k] for k in ['status', 'audio_count', 'sources', 'downloaded_hours', 'usable_paired_hours', 'pending_review_hours', 'trained', 'failures']}, ensure_ascii=False, indent=2))
    if report['status'] == 'blocked_or_failed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
