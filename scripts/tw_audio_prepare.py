"""Local-only Taiwan Mandarin pilot preparation. Never establishes training readiness."""
import array
import hashlib
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import wave
from pathlib import Path

NORMALIZER = 'nfc-preserve-punctuation-case-tags-v1'
SAMPLE_RATE = 16000
MAX_RECORDS = 1000


def file_sha256(file):
    digest = hashlib.sha256()
    with Path(file).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def normalize_text(text):
    # Preserve Taiwan words, numbers, Latin case, punctuation and code-switch tags.
    return unicodedata.normalize('NFC', text.replace('\r\n', '\n').replace('\r', '\n'))


def _contained(root, path):
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root):
        raise ValueError('path_outside_root')
    return resolved


def _pcm_qc(file):
    with wave.open(str(file), 'rb') as source:
        if source.getnchannels() != 1 or source.getframerate() != SAMPLE_RATE or source.getsampwidth() != 2:
            raise ValueError('unexpected_working_format')
        pcm = source.readframes(source.getnframes())
    values = array.array('h')
    values.frombytes(pcm)
    if sys.byteorder != 'little':
        values.byteswap()
    if not values:
        raise ValueError('empty_decoded_audio')
    clipped = sum(abs(value) >= 32760 for value in values)
    silent_samples = 0
    longest = current = 0
    frame_samples = 320  # 20 ms; this measures amplitude, not speech activity.
    threshold = 10 ** (-45 / 20)
    for start in range(0, len(values), frame_samples):
        frame = values[start:start + frame_samples]
        rms = math.sqrt(sum(value * value for value in frame) / len(frame)) / 32768
        if rms <= threshold:
            silent_samples += len(frame)
            current += len(frame)
            longest = max(longest, current)
        else:
            current = 0
    return dict(duration=len(values) / SAMPLE_RATE,
                sample_rate_hz=SAMPLE_RATE, channels=1, pcm_sha256=hashlib.sha256(pcm).hexdigest(),
                clipping_sample_ratio=clipped / len(values), clipping_threshold_absolute=32760,
                silence_sample_ratio=silent_samples / len(values),
                longest_silent_run_seconds=longest / SAMPLE_RATE,
                silence_frame_ms=20, silence_threshold_dbfs=-45,
                decode_status='passed', background_music_check='unrun',
                transcript_audio_alignment_check='unrun', near_duplicate_audio_check='unrun')


def _prepare_one(record, root, processed, ffmpeg_version):
    row = dict(record)
    row.update(raw_audio_filepath=record.get('audio_filepath'), raw_text=record.get('text'), data_type='provider_claimed_pair_pending_review',
               normalized_text=normalize_text(record['text']) if isinstance(record.get('text'), str) else None,
               normalizer_version=NORMALIZER, language=record.get('language') or 'und', language_detection='unrun', split='unassigned', proposed_split='unassigned',
               local_reference_verified=False, training_ready=False, formal_evaluation_ready=False,
               candidate_for_provider_baseline=False, review_reasons=[], status='review')
    try:
        required = ['id', 'audio_filepath', 'text', 'source_url', 'recording_id', 'speaker_id', 'transcript_status', 'license_status', 'sha256']
        if any(key not in record for key in required):
            raise ValueError('missing_required_metadata')
        if not isinstance(record['id'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', record['id']):
            raise ValueError('unsafe_id')
        if not isinstance(record['audio_filepath'], str) or not record['audio_filepath'] or Path(record['audio_filepath']).is_absolute():
            raise ValueError('audio_path_must_be_relative')
        if not isinstance(record['text'], str) or not isinstance(record['source_url'], str) or not record['source_url']:
            raise ValueError('invalid_text_or_source')
        for field in ['recording_id', 'speaker_id']:
            if record[field] is not None and (not isinstance(record[field], str) or not record[field].strip()):
                raise ValueError('invalid_group_identifier')
        if not isinstance(record['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', record['sha256']):
            raise ValueError('invalid_sha256')
        raw = _contained(root, root / record['audio_filepath'])
        if not raw.is_file():
            raise ValueError('audio_not_file')
        actual = file_sha256(raw)
        if actual != record['sha256']:
            raise ValueError('raw_hash_mismatch')
        row['raw_sha256'] = actual
        destination = processed / (record['id'] + '.wav')
        if destination.exists() or destination.is_symlink():
            raise ValueError('output_exists_not_overwritten')
        probe = json.loads(subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_type,sample_rate,channels:format=duration',
             '-of', 'json', str(raw)], capture_output=True, check=True, text=True, timeout=30).stdout)
        audio_streams = [stream for stream in probe.get('streams', []) if stream.get('codec_type') == 'audio']
        if len(audio_streams) != 1:
            raise ValueError('expected_one_audio_stream')
        raw_duration = float(probe.get('format', {}).get('duration', 'nan'))
        if not math.isfinite(raw_duration) or raw_duration <= 0 or raw_duration > 120:
            raise ValueError('invalid_or_over_120s_pilot_audio_requires_manual_segmentation')
        row['raw_audio_metadata'] = dict(sample_rate_hz=audio_streams[0].get('sample_rate'),
                                         channels=audio_streams[0].get('channels'),
                                         duration=probe.get('format', {}).get('duration'))
        with tempfile.TemporaryDirectory(dir=processed) as temporary:
            working = Path(temporary) / 'working.wav'
            subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(raw), '-map', '0:a:0',
                            '-ac', '1', '-ar', str(SAMPLE_RATE), '-c:a', 'pcm_s16le', '-n', str(working)],
                           capture_output=True, check=True, timeout=60)
            qc = _pcm_qc(working)
            # Exclusive creation also protects against a concurrent writer after the preflight check.
            with destination.open('xb') as output, working.open('rb') as source:
                shutil.copyfileobj(source, output)
        row.update(audio_filepath=str(destination.relative_to(root)), processed_sha256=file_sha256(destination), sha256=file_sha256(destination),
                   pcm_sha256=qc['pcm_sha256'], duration=qc['duration'], segment_start=0.0,
                   segment_end=qc['duration'], qc=qc,
                   transform=dict(tool='ffmpeg', version=ffmpeg_version,
                                  parameters=dict(sample_rate_hz=SAMPLE_RATE, channels=1, codec='pcm_s16le')))
        reasons = row['review_reasons']
        if not 5 <= qc['duration'] <= 30:
            reasons.append('duration_outside_initial_5_30_seconds')
        if qc['duration'] > 30:
            reasons.append('full_clip_over_30s_needs_manual_aligned_segmentation')
        if qc['clipping_sample_ratio'] > 0.001:
            reasons.append('clipping_above_0.1_percent')
        if qc['silence_sample_ratio'] >= 0.95:
            reasons.append('mostly_silent_audio')
        if qc['longest_silent_run_seconds'] >= 2:
            reasons.append('silent_run_at_least_2_seconds')
        if record['license_status'] != 'approved':
            reasons.append('license_not_approved_quarantine')
        if not record['text'].strip():
            reasons.append('empty_transcript')
        if record['transcript_status'] == 'machine_generated':
            reasons.append('machine_transcript_not_reference')
        if record['speaker_id'] is None:
            reasons.append('speaker_unknown_isolation_unproven')
        if record['recording_id'] is None:
            reasons.append('recording_unknown_isolation_unproven')
        row['candidate_for_provider_baseline'] = (
            record['license_status'] == 'approved' and bool(record['text'].strip())
            and record['transcript_status'] in ['provider_reference', 'source_reference', 'human_verified']
            and qc['duration'] <= 30 and qc['silence_sample_ratio'] < 0.95
            and qc['clipping_sample_ratio'] <= 0.001)
        reasons.extend(['local_transcript_audio_review_pending', 'near_duplicate_audio_review_pending',
                        'background_music_check_unrun'])
    except (ValueError, OSError, subprocess.SubprocessError, json.JSONDecodeError, wave.Error) as error:
        row['status'] = 'rejected'
        # Never echo command stderr, transcript, absolute paths or arbitrary remote metadata.
        message = str(error)
        known = message if re.fullmatch(r'[a-z0-9_.]+', message) else type(error).__name__
        row['failure_reason'] = known
        row['review_reasons'].append(known)
        row['qc'] = dict(decode_status='failed_or_unrun', background_music_check='unrun',
                         transcript_audio_alignment_check='unrun', near_duplicate_audio_check='unrun')
    return row


def _deduplicate_and_split(rows):
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    group_keys = {}
    duplicate_keys = {}
    for index, row in enumerate(rows):
        if row['status'] == 'rejected':
            continue
        for kind in ['recording_id', 'speaker_id']:
            value = row.get(kind)
            if value is not None:
                key = (kind, value)
                if key in group_keys:
                    union(index, group_keys[key])
                else:
                    group_keys[key] = index
        duplicates = []
        for kind in ['raw_sha256', 'pcm_sha256', 'normalized_text']:
            value = row.get(kind)
            if value:
                key = (kind, value)
                if key in duplicate_keys:
                    previous = duplicate_keys[key]
                    duplicates.append(dict(kind=kind, duplicate_of=rows[previous]['id']))
                    union(index, previous)
                else:
                    duplicate_keys[key] = index
        if duplicates:
            row['duplicate_matches'] = duplicates
            row['duplicate_excluded'] = True
            row['candidate_for_provider_baseline'] = False
            row['review_reasons'].append('exact_duplicate_excluded_before_split')
    active = [i for i, row in enumerate(rows) if row.get('candidate_for_provider_baseline')]
    components = {}
    for i in active:
        components.setdefault(find(i), []).append(i)
    groups = sorted(components.values(), key=lambda group: min(str(rows[i]['id']) for i in group))
    assignments = {}
    if len(groups) >= 3:
        test_count = max(1, len(groups) // 10)
        validation_count = max(1, len(groups) // 10)
        for position, group in enumerate(groups):
            split = 'test' if position < test_count else 'validation' if position < test_count + validation_count else 'train'
            assignments[find(group[0])] = split
    for index, row in enumerate(rows):
        if row['status'] != 'rejected':
            component = find(index)
            members = sorted(str(rows[i]['id']) for i in range(len(rows)) if rows[i]['status'] != 'rejected' and find(i) == component)
            row['group_id'] = 'component-' + hashlib.sha256('\0'.join(members).encode()).hexdigest()[:16]
            # Quarantined and duplicate rows remain unassigned and excluded from active sets.
            if row.get('candidate_for_provider_baseline'):
                row['proposed_split'] = assignments.get(component, 'unassigned')
    return len(groups)


def prepare_records(records, root):
    """Convert a bounded pilot under root; return all rows plus truthful QC/split report.

    Input paths are relative to root. No downloads, model dependencies or speech recognition.
    Provider references remain locally unverified; these outputs are never training-ready.
    """
    if not isinstance(records, list) or not records or len(records) > MAX_RECORDS:
        raise ValueError('Expected 1..1000 pilot records')
    if any(not isinstance(record, dict) for record in records):
        raise ValueError('Expected object records')
    ids = [record.get('id') for record in records]
    if any(not isinstance(value, str) for value in ids) or len(set(ids)) != len(ids):
        raise ValueError('Duplicate or invalid input IDs')
    root = Path(root).resolve(strict=True)
    processed = root / 'processed'
    processed.mkdir(exist_ok=True)
    _contained(root, processed)
    version = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True, check=True, timeout=10).stdout.splitlines()[0]
    rows = [_prepare_one(record, root, processed, version) for record in records]
    group_count = _deduplicate_and_split(rows)
    active = [row for row in rows if row.get('candidate_for_provider_baseline')]
    report = dict(records=len(rows), decoded=sum(row['status'] != 'rejected' for row in rows),
                  rejected=sum(row['status'] == 'rejected' for row in rows),
                  duplicates_excluded=sum(bool(row.get('duplicate_excluded')) for row in rows),
                  provider_baseline_candidates=len(active),
                  decoded_input_seconds=sum(row.get('duration', 0) for row in rows if row['status'] != 'rejected'),
                  provider_baseline_candidate_seconds=sum(row['duration'] for row in active),
                  locally_human_verified_seconds=0, training_ready_seconds=0,
                  independent_components=group_count,
                  split_status='blocked_pending_near_duplicate_review',
                  proposed_split_status='tentative_grouped' if group_count >= 3 else 'insufficient_independent_groups',
                  speaker_isolation_guaranteed=bool(active) and all(row.get('speaker_id') is not None for row in active),
                  recording_isolation_guaranteed=bool(active) and all(row.get('recording_id') is not None for row in active),
                  exact_duplicate_checks=['raw_sha256', 'working_pcm_sha256', 'normalized_text'],
                  near_duplicate_audio_check='unrun_review_required',
                  background_music_check='unrun_review_required', transcript_audio_alignment_check='unrun_review_required',
                  training_ready=False, normalizer=NORMALIZER,
                  notes=['Provider labels are not local human verification.',
                         'Silence/clipping are measured amplitude heuristics, not speech or music classification.',
                         'No pause-based segmentation was implemented; no acoustic cutting or copying a whole transcript onto shorter chunks was performed.',
                         'Near-duplicate audio and actual alignment need review before formal training.',
                         'Only proposed_split is assigned; split stays unassigned until near-duplicate and alignment review. Unknown speakers cannot be guaranteed disjoint.'])
    return dict(records=rows, report=report)
