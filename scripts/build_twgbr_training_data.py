#!/usr/bin/env python3
"""M3 training data from the private TWGBR archive: whole recordings -> Whisper word timestamps -> alignment
with the published text -> 5-30 s clips (16 kHz mono PCM16 WAV) labelled with the published text.

Sources (docs/spec-large-meeting.md M3; rights: owner_internal_decision, section 2 -- internal use only,
never published, never committed to Git):
  * Recovery Version chapter readings (audio + chapter text; near-verbatim): keep clips with CER <= 10 %.
  * Life-Study messages (audio = reading plus the speaker's remarks): keep clips with CER <= 15 %, i.e. only
    the parts read from the text.
Excluded: the development sets (bible-dev-v1 chapters, life-study-dev-v1 messages), Life-Study books that
share another book's messages, messages with several audio files. MEET is not in the archive.
Split by recording (chapter / message): about 2 % validation, never sharing a recording with train.

Labels are the publisher's text, not a human transcript: rows say transcript_status=source_text_aligned
with the clip's alignment CER, and the training gate (scripts/cloud_training_data.py) accepts them only
under that explicit category.

Steps (resumable; the Colab notebook notebooks/twgbr_training_data.ipynb runs them in order):
  plan        list recordings, exclusions and splits                          -> <output>/plan.json
  transcribe  Whisper large-v3-turbo word timestamps (GPU), stops at --max-minutes -> <output>/cache/<id>.json
  segment     align, cut, write clips, manifests and the data report         -> <output>/manifests, reports
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))

PIPELINE = 'twgbr-v1-align-1'
RATE = 16000
KEEP = re.compile(r'[㐀-䶿一-鿿豈-﫿A-Za-z0-9]')
PUNCTUATION = '，。；：！？、「」『』（）《》〈〉…—．,.;:!?()"\'“”‘’ 　\t'
NEUTRAL_PROMPT = '以下是繁體中文的逐字稿。'
RIGHTS = dict(license_status='owner_internal_decision', rights_evidence_ref='docs/spec-large-meeting.md#2')
POLICY = dict(min_seconds=5.0, max_seconds=30.0, min_gap=0.25, min_gap_punctuation=0.08, anchor=2, min_chars=8, min_cps=1.5, max_cps=9.0,
              max_cer={'bible': 0.10, 'life_study': 0.15}, validation_per=50)
KINDS = {'bible': ('rv', 'twgbr-recovery-version-reading'), 'life_study': ('ls', 'twgbr-life-study-message')}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def write_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    os.replace(temporary, path)


def normalize(text, converter=None):
    text = unicodedata.normalize('NFC', text)
    if converter:
        text = converter.convert(text)
    return ''.join(KEEP.findall(text)).lower()


def split_of(recording_id, per=POLICY['validation_per']):
    """About 1/per of the recordings go to validation, decided by the id alone (stable across runs)."""
    return 'validation' if int(sha256_bytes(('split:' + recording_id).encode())[:8], 16) % per == 0 else 'train'


# ---------------------------------------------------------------- plan

def dev_exclusions(archive_root):
    """Chapters / messages of the development sets: from their manifests, plus the deterministic picks of
    the dev-set builders (so the exclusion holds even when a dev set was never built on this Drive)."""
    import build_bible_dev_set as bible_dev
    import build_life_study_dev_set as life_dev
    import download_twgbr_archive as archive
    bible, life = set(), set()
    def manifests(name):
        return {archive_root/name/'manifest.json', *archive_root.parent.glob(f'*/{name}/manifest.json')}
    for path in manifests('bible-dev-v1'):
        if path.exists():
            bible |= {(row['book'], row['chapter']) for row in json.loads(path.read_text(encoding='utf-8'))}
    for path in manifests('life-study-dev-v1'):
        if path.exists():
            life |= {(row['book'], row['message']) for row in json.loads(path.read_text(encoding='utf-8'))}
    chapters = {}
    for n in range(1, 67):
        html = archive_root/f'recovery-version/html/{archive.folder(n)}.html'
        if html.exists():
            chapters[n] = archive.chapter_count(html.read_text(encoding='utf-8'))
    if len(chapters) == 66 and all(chapters.values()):
        bible |= set(bible_dev.pick_chapters(chapters, 20))
    found = life_dev.available(archive_root)
    if found:
        life |= set(life_dev.pick(found, 16))
    return bible, life


def plan(archive_root, life_study_messages):
    import build_bible_dev_set as bible_dev
    import download_twgbr_archive as archive
    bible_dev_set, life_dev_set = dev_exclusions(archive_root)
    recordings, excluded = [], []
    for n in range(1, 67):
        name, base = archive.BOOKS[n-1], archive.folder(n)
        text_path = archive_root/f'recovery-version/text/{base}.txt'
        audio_dir = archive_root/f'recovery-version/audio/{base}'
        if text_path.exists() and audio_dir.is_dir():
            book_text = text_path.read_text(encoding='utf-8')
            for audio in sorted(audio_dir.glob('[0-9][0-9][0-9].mp3')):
                chapter = int(audio.stem)
                rid = f'rv-{n:02d}-{chapter:03d}'
                if (n, chapter) in bible_dev_set:
                    excluded.append(dict(id=rid, reason='bible_dev_set')); continue
                text = bible_dev.chapter_text(book_text, name, chapter)
                if not text.strip():
                    excluded.append(dict(id=rid, reason='no_chapter_text')); continue
                recordings.append(dict(id=rid, kind='bible', book=n, book_name=name, chapter=chapter,
                                       audio=str(audio.relative_to(archive_root)), text_sha256=sha256_bytes(text.encode())))
        if n in archive.SHARED_LIFE_STUDY:
            continue  # same messages as the first book of the pair
        texts, audio_dir = archive_root/f'life-study/text/{base}', archive_root/f'life-study/audio/{base}'
        if not texts.is_dir() or not audio_dir.is_dir():
            continue
        for text_file in sorted(texts.glob('[0-9][0-9][0-9].txt')):
            message = int(text_file.stem)
            rid = f'ls-{n:02d}-{message:03d}'
            audio = audio_dir/f'{message:03d}.mp3'
            if (n, message) in life_dev_set:
                excluded.append(dict(id=rid, reason='life_study_dev_set')); continue
            if not audio.exists():
                excluded.append(dict(id=rid, reason='no_audio')); continue
            if (audio_dir/f'{message:03d}-2.mp3').exists():
                excluded.append(dict(id=rid, reason='several_audio_files')); continue
            recordings.append(dict(id=rid, kind='life_study', book=n, book_name=name, message=message,
                                   audio=str(audio.relative_to(archive_root)),
                                   text_sha256=sha256_file(text_file)))
    for row in recordings:
        row['split'] = split_of(row['id'])
        row['order'] = sha256_bytes(('order:' + row['id']).encode())
    bible = sorted((r for r in recordings if r['kind'] == 'bible'), key=lambda r: r['order'])
    life = sorted((r for r in recordings if r['kind'] == 'life_study'), key=lambda r: r['order'])
    for row in life[life_study_messages:]:
        excluded.append(dict(id=row['id'], reason='life_study_message_limit'))
    selected = bible + life[:life_study_messages]
    return dict(pipeline=PIPELINE, created_at=now(), archive=str(archive_root), life_study_messages=life_study_messages,
                recordings=selected, excluded=excluded,
                counts=dict(bible=len(bible), life_study=min(len(life), life_study_messages),
                            validation=sum(r['split'] == 'validation' for r in selected), excluded=len(excluded)))


def reference_text(archive_root, row):
    import build_bible_dev_set as bible_dev
    import download_twgbr_archive as archive
    if row['kind'] == 'bible':
        book_text = (archive_root/f'recovery-version/text/{archive.folder(row["book"])}.txt').read_text(encoding='utf-8')
        return bible_dev.chapter_text(book_text, row['book_name'], row['chapter'])
    return (archive_root/f'life-study/text/{archive.folder(row["book"])}/{row["message"]:03d}.txt').read_text(encoding='utf-8')


# ---------------------------------------------------------------- transcribe

def decode_audio(path):
    """16 kHz mono float32 via ffmpeg (as evaluate_meet.py)."""
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-f', 's16le', '-ac', '1', '-ar', str(RATE), '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def transcribe(plan_data, archive_root, output, model_dir, model_label, max_minutes, decode=decode_audio, model=None,
               max_recordings=None):
    if model is None:
        from faster_whisper import WhisperModel
        model = WhisperModel(model_dir, device='cuda', compute_type='float16')
    started, done, skipped = time.monotonic(), 0, 0
    pending = [r for r in plan_data['recordings'] if not (output/'cache'/f'{r["id"]}.json').exists()]
    if max_recordings is not None:  # a trial run: a few of each source, in plan order
        cached = {r['id'] for r in plan_data['recordings'] if (output/'cache'/f'{r["id"]}.json').exists()}
        per_kind = {}
        for r in plan_data['recordings']:
            if r['id'] in cached:
                per_kind[r['kind']] = per_kind.get(r['kind'], 0) + 1
        chosen = []
        for r in pending:
            if per_kind.get(r['kind'], 0) < max_recordings:
                per_kind[r['kind']] = per_kind.get(r['kind'], 0) + 1; chosen.append(r)
        pending = chosen
    print(f'待辨識 {len(pending)} 個錄音（已完成 {len(plan_data["recordings"]) - len(pending)} 個）', flush=True)
    for row in pending:
        if time.monotonic() - started > max_minutes*60:
            skipped = len(pending) - done
            print(f'已達本次時間上限 {max_minutes} 分鐘：剩 {skipped} 個，下次重跑會接著做', flush=True)
            break
        audio = archive_root/row['audio']
        samples = decode(audio)
        tick = time.monotonic()
        segments, info = model.transcribe(samples, language='zh', task='transcribe', beam_size=5, temperature=0,
                                          vad_filter=True, condition_on_previous_text=False, word_timestamps=True,
                                          initial_prompt=NEUTRAL_PROMPT)
        words = [[round(w.start, 3), round(w.end, 3), w.word] for s in segments for w in (s.words or [])]
        elapsed = time.monotonic() - tick
        cache = dict(id=row['id'], audio_sha256=sha256_file(audio), audio_seconds=round(len(samples)/RATE, 3),
                     model=model_label, elapsed_seconds=round(elapsed, 1), created_at=now(), words=words)
        write_atomic(output/'cache'/f'{row["id"]}.json', json.dumps(cache, ensure_ascii=False))
        done += 1
        print(f'{row["id"]} {cache["audio_seconds"]/60:.1f} 分鐘音訊，{elapsed:.0f} 秒，{len(words)} 詞', flush=True)
    return dict(transcribed=done, remaining=skipped)


# ---------------------------------------------------------------- align and cut (pure functions)

def hypothesis_chars(words, converter=None):
    """[(char, start, end)] for the kept characters of Whisper's words; a word's time is spread over its chars."""
    chars = []
    for start, end, word in words:
        kept = normalize(word, converter)
        if not kept:
            continue
        step = max(0.0, end - start)/len(kept)
        for i, char in enumerate(kept):
            chars.append((char, start + i*step, start + (i + 1)*step))
    return chars


def reference_chars(text):
    """Normalized reference and, for each kept char, its position in the original text."""
    text = unicodedata.normalize('NFC', text)
    kept, positions = [], []
    for i, char in enumerate(text):
        if KEEP.match(char):
            kept.append(char.lower()); positions.append(i)
    return ''.join(kept), positions


def align(hypothesis, reference):
    """For each hypothesis char, the reference index it equals (-1 when substituted or inserted)."""
    from rapidfuzz.distance import Levenshtein
    match = [-1]*len(hypothesis)
    for tag, h0, h1, r0, _ in Levenshtein.opcodes(hypothesis, reference):
        if tag == 'equal':
            for k in range(h1 - h0):
                match[h0 + k] = r0 + k
    return match


def cut_points(chars, match, min_gap=POLICY['min_gap'], anchor=POLICY['anchor'], breaks=(), min_gap_punctuation=None):
    """Boundaries b (between chars b-1 and b) with `anchor` matched chars on each side and a pause, so the
    audio cut and the text cut fall at the same place. The pause may be shorter (min_gap_punctuation) where
    the text has punctuation after reference char match[b-1] (`breaks`). The recording's ends count when anchored."""
    points = []
    for b in range(len(chars) + 1):
        left, right = match[max(0, b - anchor):b], match[b:b + anchor]
        if b and (len(left) < anchor or min(left) < 0):
            continue
        if b < len(chars) and (len(right) < anchor or min(right) < 0):
            continue
        if 0 < b < len(chars):
            gap = chars[b][1] - chars[b-1][2]
            needed = min_gap_punctuation if min_gap_punctuation is not None and match[b-1] in breaks else min_gap
            if match[b] != match[b-1] + 1 or gap < needed:
                continue
        points.append(b)
    return points


def punctuation_breaks(text, positions):
    """Reference indices r whose char is followed by punctuation or a line break in the original text."""
    marks = set('，。；：！？、」』）\n')
    return {r for r in range(len(positions)) if marks & set(text[positions[r] + 1:positions[r + 1] if r + 1 < len(positions) else len(text)])}


def boundary_time(chars, b, total):
    if b == 0:
        return max(0.0, chars[0][1] - 0.3)
    if b == len(chars):
        return min(total, chars[-1][2] + 0.3)
    return (chars[b-1][2] + chars[b][1])/2


def label_text(text, positions, r0, r1):
    """Original text of reference chars r0..r1-1, with the punctuation that follows the last char; a line
    break inside becomes 。 (outline headings have none), other whitespace is dropped."""
    end = positions[r1] if r1 < len(positions) else len(text)
    piece = text[positions[r0]:end]
    piece = re.sub(r'(?<=[^，。；：！？、」』）\s])\s*\n\s*', '。', piece.rstrip())
    piece = re.sub(r'\s+', '', piece)
    return piece.lstrip(PUNCTUATION)


def make_clips(chars, match, reference, text, positions, total_seconds, max_cer, policy=POLICY):
    """Greedy 5-30 s clips between cut points; keep those whose alignment CER <= max_cer. Returns (clips, rejected)."""
    from rapidfuzz.distance import Levenshtein
    points = cut_points(chars, match, policy['min_gap'], policy['anchor'], punctuation_breaks(text, positions),
                        policy['min_gap_punctuation'])
    times = {b: boundary_time(chars, b, total_seconds) for b in points}
    hypothesis = ''.join(c for c, _, _ in chars)
    clips, rejected, i = [], {}, 0
    while i < len(points) - 1:
        s = points[i]
        best = None
        for j in range(i + 1, len(points)):
            length = times[points[j]] - times[s]
            if length > policy['max_seconds']:
                break
            if length >= policy['min_seconds']:
                best = j
        if best is None:
            i += 1; continue
        e = points[best]
        r0, r1 = match[s], match[e-1] + 1
        seconds = times[e] - times[s]
        cer = Levenshtein.distance(hypothesis[s:e], reference[r0:r1])/max(1, r1 - r0)
        cps = (r1 - r0)/seconds
        reason = ('too_few_chars' if r1 - r0 < policy['min_chars'] else 'speech_rate' if not policy['min_cps'] <= cps <= policy['max_cps']
                  else 'alignment_cer' if cer > max_cer else None)
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
        else:
            clips.append(dict(start=round(times[s], 3), end=round(times[e], 3), text=label_text(text, positions, r0, r1),
                              whisper=hypothesis[s:e], alignment_cer=round(cer, 4), reference_span=[r0, r1]))
        i = best
    return clips, rejected


# ---------------------------------------------------------------- segment

def write_wav(path, samples):
    import numpy as np
    pcm = (np.clip(samples, -1.0, 1.0)*32767).astype('<i2').tobytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    with wave.open(str(temporary), 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE); out.writeframes(pcm)
    os.replace(temporary, path)
    return len(pcm)//2


def segment_recording(row, archive_root, output, converter, decode=decode_audio, policy=POLICY):
    cache_path = output/'cache'/f'{row["id"]}.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8'))
    text = reference_text(archive_root, row)
    stamp = sha256_bytes(json.dumps([PIPELINE, policy, sha256_file(cache_path), sha256_bytes(text.encode())], sort_keys=True).encode())
    rows_path = output/'rows'/f'{row["id"]}.json'
    if rows_path.exists():
        saved = json.loads(rows_path.read_text(encoding='utf-8'))
        if saved.get('stamp') == stamp:
            return saved
    reference, positions = reference_chars(text)
    chars = hypothesis_chars(cache['words'], converter)
    match = align(''.join(c for c, _, _ in chars), reference)
    max_cer = policy['max_cer'][row['kind']]
    clips, rejected = make_clips(chars, match, reference, text, positions, cache['audio_seconds'], max_cer, policy)
    samples = decode(archive_root/row['audio']) if clips else None
    prefix, source = KINDS[row['kind']]
    rows = []
    for n, clip in enumerate(clips, 1):
        clip_id = f'{row["id"]}-{n:03d}'
        relative = f'audio/{row["id"]}/{clip_id}.wav'
        frames = write_wav(output/relative, samples[int(clip['start']*RATE):int(clip['end']*RATE)])
        rows.append(dict(id=clip_id, audio_filepath=relative, text=clip['text'], duration=round(frames/RATE, 3),
                         sha256=sha256_file(output/relative), split=row['split'], recording_id=row['id'], speaker_id=None,
                         source=source, book=row['book'], book_name=row['book_name'],
                         **({'chapter': row['chapter']} if row['kind'] == 'bible' else {'message': row['message']}),
                         source_start=clip['start'], source_end=clip['end'], whisper_text=clip['whisper'],
                         alignment_cer=clip['alignment_cer'], alignment_max_cer=max_cer,
                         transcript_status='source_text_aligned', local_reference_verified=False,
                         near_duplicate_review='exact_text_checked', **RIGHTS,
                         allowed_uses=['training', 'internal_evaluation'], training_ready=row['split'] == 'train',
                         evaluation_ready=row['split'] == 'validation', source_audio_sha256=cache['audio_sha256'],
                         source_text_sha256=sha256_bytes(text.encode()), pipeline=PIPELINE))
    kept_chars = sum(c['reference_span'][1] - c['reference_span'][0] for c in clips)
    result = dict(id=row['id'], stamp=stamp, rows=rows, rejected=rejected, audio_seconds=cache['audio_seconds'],
                  reference_chars=len(reference), kept_reference_chars=kept_chars,
                  matched_chars=sum(m >= 0 for m in match), hypothesis_chars=len(chars))
    write_atomic(rows_path, json.dumps(result, ensure_ascii=False))
    return result


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q*len(values)))] if values else None


def segment(plan_data, archive_root, output, converter, decode=decode_audio, policy=POLICY):
    results = []
    for row in plan_data['recordings']:
        if (output/'cache'/f'{row["id"]}.json').exists():
            result = segment_recording(row, archive_root, output, converter, decode, policy)
            results.append((row, result))
            print(f'{row["id"]} 保留 {len(result["rows"])} 段，退回 {sum(result["rejected"].values())} 段', flush=True)
    splits = {'train': [], 'validation': []}
    for row, result in results:
        splits[row['split']].extend(result['rows'])
    train_texts = {clip['text'] for clip in splits['train']}
    dropped = [clip['id'] for clip in splits['validation'] if clip['text'] in train_texts]
    splits['validation'] = [clip for clip in splits['validation'] if clip['text'] not in train_texts]
    hashes = {}
    for name, rows in splits.items():
        body = ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows)
        write_atomic(output/'manifests'/f'{name}.jsonl', body)
        hashes[name] = sha256_bytes(body.encode())
    rejected = {}
    for _, result in results:
        for reason, count in result['rejected'].items():
            rejected[reason] = rejected.get(reason, 0) + count
    by = {}
    for kind in KINDS:
        done = [(row, result) for row, result in results if row['kind'] == kind]
        clips = [clip for _, result in done for clip in result['rows'] if clip['id'] not in dropped]
        cers = [clip['alignment_cer'] for clip in clips]
        by[kind] = dict(recordings_planned=sum(r['kind'] == kind for r in plan_data['recordings']), recordings_transcribed=len(done),
                        audio_hours=round(sum(result['audio_seconds'] for _, result in done)/3600, 2),
                        clip_hours=round(sum(clip['duration'] for clip in clips)/3600, 2), clips=len(clips),
                        train_clips=sum(clip['split'] == 'train' for clip in clips),
                        validation_clips=sum(clip['split'] == 'validation' for clip in clips),
                        reference_coverage=round(sum(r['kept_reference_chars'] for _, r in done)/max(1, sum(r['reference_chars'] for _, r in done)), 3),
                        recordings_without_clips=sorted(row['id'] for row, result in done if not result['rows']),
                        alignment_cer=dict(mean=round(sum(cers)/len(cers), 4) if cers else None, p50=percentile(cers, 0.5),
                                           p90=percentile(cers, 0.9), zero=sum(c == 0 for c in cers)),
                        max_cer=policy['max_cer'][kind])
    report = dict(pipeline=PIPELINE, created_at=now(), policy=policy, rights=RIGHTS, manifest_sha256=hashes, by_source=by,
                  rejected_clips=rejected, validation_dropped_same_text_as_train=len(dropped),
                  excluded_recordings=_count(plan_data['excluded']),
                  splits={name: dict(clips=len(rows), hours=round(sum(r['duration'] for r in rows)/3600, 2),
                                     recordings=len({r['recording_id'] for r in rows})) for name, rows in splits.items()},
                  speaker_ids='unknown (null): speaker isolation between splits is not proven; split is by recording',
                  labels='publisher text aligned to Whisper large-v3-turbo; not human verified',
                  test_sets='not built here: development sets and sealed MEET stay outside these manifests')
    write_atomic(output/'reports'/'data-report.json', json.dumps(report, ensure_ascii=False, indent=1) + '\n')
    write_atomic(output/'reports'/'data-report.md', markdown_report(report))
    return report


def _count(rows):
    counts = {}
    for row in rows:
        counts[row['reason']] = counts.get(row['reason'], 0) + 1
    return counts


def markdown_report(report):
    names = {'bible': '恢復本朗讀', 'life_study': '生命讀經'}
    lines = [f'# TWGBR 訓練資料報告（{report["pipeline"]}，{report["created_at"]}）', '',
             '權利：owner_internal_decision（使用者 2026-11-16 內部使用決定，docs/spec-large-meeting.md 第 2 節）；只限內部，不公開散布。',
             '標籤：出版文字與 Whisper large-v3-turbo 對齊後的原文，不是人工逐字稿。', '',
             '| 來源 | 已辨識／計畫錄音 | 音訊時數 | 保留片段 | 片段時數 | train／validation 段 | 原文覆蓋 | 對齊 CER 平均／P50／P90 | 門檻 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for kind, s in report['by_source'].items():
        c = s['alignment_cer']
        lines.append(f'| {names[kind]} | {s["recordings_transcribed"]}／{s["recordings_planned"]} | {s["audio_hours"]} | {s["clips"]} | {s["clip_hours"]} | '
                     f'{s["train_clips"]}／{s["validation_clips"]} | {s["reference_coverage"]:.1%} | {c["mean"]}／{c["p50"]}／{c["p90"]} | ≤{s["max_cer"]:.0%} |')
    lines += ['', f'分割：train {report["splits"]["train"]["clips"]} 段 {report["splits"]["train"]["hours"]} 小時（{report["splits"]["train"]["recordings"]} 個錄音）；'
              f'validation {report["splits"]["validation"]["clips"]} 段 {report["splits"]["validation"]["hours"]} 小時（{report["splits"]["validation"]["recordings"]} 個錄音）。'
              f'validation 與 train 文字完全相同而移除：{report["validation_dropped_same_text_as_train"]} 段。',
              f'退回片段：{json.dumps(report["rejected_clips"], ensure_ascii=False)}',
              f'排除錄音：{json.dumps(report["excluded_recordings"], ensure_ascii=False)}',
              f'講員：{report["speaker_ids"]}', f'測試集：{report["test_sets"]}',
              f'manifest SHA-256：{json.dumps(report["manifest_sha256"])}', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('step', choices=['plan', 'transcribe', 'segment'])
    parser.add_argument('--archive', required=True, help='twgbr-archive folder (recovery-version/, life-study/)')
    parser.add_argument('--output', required=True, help='e.g. MyDrive/meeting-live-captions/data/twgbr-v1')
    parser.add_argument('--life-study-messages', type=int, default=120, help='how many Life-Study messages to use')
    parser.add_argument('--model-dir', help='faster-whisper model folder (transcribe)')
    parser.add_argument('--model-label', default='whisper-large-v3-turbo')
    parser.add_argument('--max-minutes', type=float, default=150, help='transcribe time budget for this run')
    parser.add_argument('--trial', type=int, help='transcribe: only the first N recordings of each source (trial run)')
    args = parser.parse_args()
    archive_root, output = Path(args.archive), Path(args.output)
    plan_path = output/'plan.json'
    if args.step == 'plan':
        data = plan(archive_root, args.life_study_messages)
        if plan_path.exists():
            old = json.loads(plan_path.read_text(encoding='utf-8'))
            if [r['id'] for r in old['recordings']] == [r['id'] for r in data['recordings']]:
                print('計畫與上次相同，沿用', plan_path); data = old
        write_atomic(plan_path, json.dumps(data, ensure_ascii=False, indent=1) + '\n')
        print(json.dumps(data['counts'], ensure_ascii=False))
        return
    data = json.loads(plan_path.read_text(encoding='utf-8'))
    if args.step == 'transcribe':
        if not args.model_dir:
            raise SystemExit('--model-dir is required')
        print(json.dumps(transcribe(data, archive_root, output, args.model_dir, args.model_label, args.max_minutes,
                                    max_recordings=args.trial), ensure_ascii=False))
    else:
        from opencc import OpenCC
        report = segment(data, archive_root, output, OpenCC('s2tw'))
        print(markdown_report(report))


if __name__ == '__main__':
    main()
