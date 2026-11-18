"""Cloud training data gate, standard library only; never launches training."""
import argparse
import hashlib
import json
import math
import wave
from pathlib import Path

OWNER_DECISION_EVIDENCE = 'docs/spec-large-meeting.md#2'
MAX_SOURCE_ALIGNED_CER = 0.15


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            h.update(block)
    return h.hexdigest()


def inspect_manifests(config, root_override=None):
    policy = config['data']
    root = Path(root_override or policy['root']).resolve(strict=True)
    rows, errors, hashes = {}, [], {}
    seen_ids, seen_groups = set(), {}
    count = 0
    unknown_speakers = 0
    categories = {}
    for split in ['train', 'validation', 'test']:
        manifest = (root/policy[split+'_manifest']).resolve(strict=True)
        if not manifest.is_relative_to(root):
            raise ValueError('Manifest outside approved data root')
        hashes[split] = digest(manifest)
        selected = []
        with manifest.open() as stream:
            for line_no, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                count += 1
                if count > policy['max_total_records']:
                    raise ValueError('Record budget exceeded')
                row = json.loads(line)
                label = f'{split} row {line_no}'
                if not isinstance(row,dict):
                    errors.append(dict(location=label,reasons=['record_must_be_object']))
                    continue
                reasons = []
                if not isinstance(row.get('id'), str) or not row['id'].strip() or row['id'] in seen_ids:
                    reasons.append('missing_or_duplicate_id')
                else:
                    seen_ids.add(row['id'])
                if row.get('split') != split:
                    reasons.append('split_mismatch')
                required_use = 'training' if split == 'train' else 'internal_evaluation'
                license_status = row.get('license_status')
                evidence = row.get('rights_evidence_ref')
                # owner_internal_decision: the user's recorded decision to use TWGBR internally (no publisher licence);
                # accepted only with that exact evidence reference, never relabelled as approved.
                rights_ok = (license_status == 'approved' and isinstance(evidence, str) and evidence.strip()) or \
                    (license_status == 'owner_internal_decision' and evidence == OWNER_DECISION_EVIDENCE)
                if not rights_ok or required_use not in (row.get('allowed_uses') if isinstance(row.get('allowed_uses'),list) else []):
                    reasons.append('purpose_rights_evidence_required')
                ready_field = 'training_ready' if split == 'train' else 'evaluation_ready'
                status = row.get('transcript_status')
                if status == 'human_verified':
                    labels_ok = row.get('local_reference_verified') is True and row.get('near_duplicate_review') == 'passed'
                elif status == 'source_text_aligned' and split != 'test':
                    # Publisher text kept only where it aligned with the audio; the sealed test needs human labels.
                    cer, limit = row.get('alignment_cer'), row.get('alignment_max_cer')
                    labels_ok = all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (cer, limit)) and \
                        0 <= cer <= limit <= MAX_SOURCE_ALIGNED_CER and row.get('near_duplicate_review') in ('passed', 'exact_text_checked')
                else:
                    labels_ok = False
                if row.get('example_only') is True or row.get(ready_field) is not True or not labels_ok:
                    reasons.append('labels_or_duplicate_review_incomplete')
                text = row.get('text')
                if not isinstance(text, str) or not text.strip():
                    reasons.append('reference_text_required')
                if row.get('language_spans') or any(tag in (text if isinstance(text,str) else '') for tag in ['[EN]', '[TAI]', '[台語]', '[英文]', '[lang=']):
                    reasons.append('annotation_aware_training_adapter_required')
                if not isinstance(row.get('recording_id'), str) or not row['recording_id'].strip():
                    reasons.append('recording_id_required')
                speaker = row.get('speaker_id')
                if not isinstance(speaker, str) or not speaker.strip():
                    unknown_speakers += 1
                    if policy['require_known_speakers']:
                        reasons.append('speaker_id_required_by_policy')
                audio = None
                try:
                    if not isinstance(row.get('audio_filepath'), str) or Path(row['audio_filepath']).is_absolute():
                        raise ValueError('relative_audio_path_required')
                    audio = (root/row['audio_filepath']).resolve(strict=True)
                    if not audio.is_relative_to(root):
                        raise ValueError('audio_outside_root')
                    actual_hash = digest(audio)
                    if actual_hash != row.get('sha256'):
                        raise ValueError('audio_hash_mismatch')
                    with wave.open(str(audio), 'rb') as wav:
                        if wav.getnchannels() != 1 or wav.getframerate() != 16000 or wav.getsampwidth() != 2 or wav.getcomptype() != 'NONE':
                            raise ValueError('expected_16khz_mono_pcm16_wav')
                        duration = wav.getnframes()/16000
                        payload = wav.readframes(wav.getnframes())
                        if len(payload) != wav.getnframes()*2:
                            raise ValueError('truncated_audio')
                    if not policy['min_seconds'] <= duration <= policy['max_seconds']:
                        raise ValueError('clip_duration_outside_policy')
                    if not isinstance(row.get('duration'), (int, float)) or not math.isfinite(row['duration']) or abs(row['duration']-duration)>0.02:
                        raise ValueError('duration_metadata_mismatch')
                    row['_pcm_sha256'] = hashlib.sha256(payload).hexdigest()
                    row['_resolved_audio'] = str(audio)
                except (OSError, ValueError, wave.Error, EOFError) as error:
                    reasons.append(str(error) if isinstance(error, ValueError) else 'audio_missing_or_invalid')
                # Read sealed test metadata for leakage audit only; never return its text/audio to training.
                groups = [('recording', row.get('recording_id')), ('speaker', speaker), ('audio_hash', row.get('sha256')), ('pcm_hash', row.get('_pcm_sha256')), ('reference_hash', hashlib.sha256(text.encode()).hexdigest() if isinstance(text,str) and text else None)]
                for kind, value in groups:
                    if not isinstance(value, str) or not value:
                        continue
                    key = (kind, value)
                    if key in seen_groups and seen_groups[key] != split:
                        reasons.append('cross_split_'+kind)
                    seen_groups[key] = split
                if reasons:
                    errors.append(dict(location=label, reasons=sorted(set(reasons))))
                else:
                    selected.append(row)
                    categories[(split, license_status, status)] = categories.get((split, license_status, status), 0) + 1
        if not selected:
            errors.append(dict(location=split, reasons=['no_eligible_rows']))
        rows[split] = selected
    result = dict(status='failed' if errors else 'passed', manifest_sha256=hashes,
                  counts={split:len(items) for split,items in rows.items()},
                  unknown_speakers=unknown_speakers, speaker_isolation_verified_by_declared_ids=unknown_speakers==0,
                  rights_and_label_categories=[dict(split=k[0], license_status=k[1], transcript_status=k[2], rows=v) for k, v in sorted(categories.items())],
                  errors=errors, test_consumption='metadata_leakage_audit_only', training_started=False)
    return result, {split:items for split,items in rows.items() if split != 'test'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='training/cloud-whisper-lora.json')
    parser.add_argument('--root')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    root = Path(args.root or config['data']['root']).resolve()
    missing = [config['data'][split+'_manifest'] for split in ['train','validation','test'] if not (root/config['data'][split+'_manifest']).is_file()]
    try:
        if missing:
            report = dict(status='blocked', reason='missing_manifests', data_root=str(root), missing_files=missing,
                          next_step='Prepare reviewed and grouped training/evaluation manifests; a downloaded pilot alone is not training-ready.', training_started=False)
        else:
            report, _ = inspect_manifests(config, args.root)
    except (OSError, ValueError) as error:
        report = dict(status='blocked', reason=type(error).__name__, training_started=False)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
