#!/usr/bin/env python3
"""Evaluate caption accuracy on a sealed meeting test set (audio + near-verbatim reference text).

Input folder (e.g. Google Drive MEET/): NN.mp3 + NN.txt pairs. Optional NN.chrome.txt = captions exported
from the website ("下載字幕") while it listened to NN.mp3 with 同音校正 turned OFF; the corrections are
then applied here so raw and corrected Chrome results can both be scored.

For every recognizer output three variants are scored, the same way the website processes captions:
  raw       recognizer text
  glossary  + exact glossary replacements (glossary.js)
  phonetic  + same-sound church-term correction (public/phonetic.js)

Recognizer conditions (--conditions): full = whole file in one pass; fixed<N>/vad<N> = live-caption simulation
where audio is cut every N seconds (fixed) or at pauses with N seconds max (vad) and each chunk is recognized
without earlier context, as a Workers AI request per chunk would be; caption delay = chunk length + processing.
cfvad<N>/cffixed<N> = the same chunks sent to Cloudflare Workers AI (@cf/openai/whisper-large-v3-turbo) through the
REST API (env CF_ACCOUNT_ID, CF_API_TOKEN). Free plan: 10,000 neurons/day (~214 audio minutes); a run stops at
--cf-max-minutes or when Cloudflare reports the daily allocation is used up, and resumes with --reuse <run>.

Metrics: CER on normalized text (NFC, Simplified→Traditional for the hypothesis, punctuation/space removed),
church-term accuracy on reference term occurrences, and chars fixed/broken by each correction step.
This is a SEALED test: do not tune terms, prompts or rules from its errors; print aggregates only.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEUTRAL_PROMPT = '以下是繁體中文的逐字稿。'
LONG_DELETION = 20
CF_MODEL = '@cf/openai/whisper-large-v3-turbo'
CF_NEURONS_PER_AUDIO_MINUTE = 46.63  # Workers AI pricing page; free plan includes 10,000 neurons per day
KEEP = re.compile(r'[㐀-䶿一-鿿豈-﫿A-Za-z0-9]')


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def clean_reference(text):
    """Drop Markdown markers (#, *, >, `) that are formatting, not speech; keep every word."""
    lines = []
    for line in text.replace('\r\n', '\n').split('\n'):
        line = re.sub(r'^\s{0,3}(#{1,6}|>)\s*', '', line)
        lines.append(line.replace('**', '').replace('__', '').replace('`', ''))
    return '\n'.join(lines)


HYMN_STANZA = re.compile(r'^\s*(?:[一二三四五六七八九十]+[\u3000 ]|（副）)')


def without_hymn(text):
    """Speech-only reference: drop a trailing hymn (numbered stanzas 「一　…」 or 「（副）」, at least two lines)
    and everything after it. Returns the text unchanged when no hymn is found."""
    lines = text.split('\n')
    stanzas = [i for i, line in enumerate(lines) if HYMN_STANZA.match(line)]
    if len(stanzas) < 2:
        return text
    return '\n'.join(lines[:stanzas[0]])


def cut_after_reference_end(reference, hypothesis, tail=40):
    """Drop recognized text after the point matching the reference's last chars (e.g. the sung hymn)."""
    from rapidfuzz import fuzz
    if len(reference) < tail or not hypothesis:
        return hypothesis
    match = fuzz.partial_ratio_alignment(reference[-tail:], hypothesis)
    return hypothesis[:match.dest_end] if match and match.score >= 50 else hypothesis


def without_parentheses(text):
    """Variant without parenthesized citations such as （約四24）, which speakers may not read aloud."""
    return re.sub(r'[（(][^（）()]{0,40}[）)]', '', text)


def normalize(text, converter=None):
    text = unicodedata.normalize('NFC', text)
    if converter:
        text = converter.convert(text)
    return ''.join(KEEP.findall(text)).lower()


def church_terms():
    """Bible books + core church terms (public/church-terms.js string literals, not import paths)."""
    source = (ROOT/'public/church-terms.js').read_text(encoding='utf-8')
    return sorted({t for t in re.findall(r"'([^']+)'", source) if '/' not in t and '.' not in t}, key=len, reverse=True)


def bible_names():
    source = (ROOT/'public/bible-names.js').read_text(encoding='utf-8')
    return sorted(json.loads(re.search(r'BIBLE_NAMES = (\[.*\]);', source).group(1)), key=len, reverse=True)


def category_spans(reference, church, names):
    """Church-term spans, and name spans that do not overlap a church term (約翰 inside 約翰福音)."""
    church_spans = term_spans(reference, church)
    taken = set(k for s, e, _ in church_spans for k in range(s, e))
    name_spans = [span for span in term_spans(reference, names) if not taken & set(range(span[0], span[1]))]
    return dict(church=church_spans, names=name_spans)


def term_spans(reference, terms):
    """Non-overlapping occurrences of terms in the normalized reference (longest first)."""
    taken = [False]*len(reference); spans = []
    for term in terms:
        start = reference.find(term)
        while start != -1:
            end = start + len(term)
            if not any(taken[start:end]):
                spans.append((start, end, term))
                for k in range(start, end):
                    taken[k] = True
            start = reference.find(term, start + 1)
    return sorted(spans)


def score(reference, hypothesis, spans):
    from rapidfuzz.distance import Levenshtein
    ok = [False]*len(reference)
    for tag, i1, i2, _j1, _j2 in Levenshtein.opcodes(reference, hypothesis):
        if tag == 'equal':
            for k in range(i1, i2):
                ok[k] = True
    distance = Levenshtein.distance(reference, hypothesis)
    if isinstance(spans, list):
        spans = dict(church=spans, names=[])
    correct = sum(all(ok[s:e]) for s, e, _ in spans['church'])
    names_correct = sum(all(ok[s:e]) for s, e, _ in spans['names'])
    kinds = {'replace': 0, 'delete': 0, 'insert': 0}
    for op in Levenshtein.editops(reference, hypothesis):
        kinds[op.tag] += 1
    # Long runs of reference text with no recognized counterpart usually mean the speaker did not say that
    # part (or music/noise), not individual recognition errors.
    long_runs = [i2 - i1 for tag, i1, i2, _j1, _j2 in Levenshtein.opcodes(reference, hypothesis)
                 if tag == 'delete' and i2 - i1 >= LONG_DELETION]
    return dict(cer=round(distance/len(reference), 4) if reference else None, edit_distance=distance,
                substitutions=kinds['replace'], deletions=kinds['delete'], insertions=kinds['insert'],
                long_deletion_runs=len(long_runs), long_deletion_chars=sum(long_runs),
                reference_chars=len(reference), hypothesis_chars=len(hypothesis),
                term_occurrences=len(spans['church']), terms_correct=correct,
                **bag_counts(hypothesis, spans),
                term_accuracy=round(correct/len(spans['church']), 4) if spans['church'] else None,
                name_occurrences=len(spans['names']), names_correct=names_correct), ok


def bag_counts(hypothesis, spans):
    """Alignment-free term check for references that are not verbatim (e.g. a Life-Study message whose audio is
    the speaker's own reading with remarks): per term, min(times in reference, times in hypothesis); extra =
    times the hypothesis has a term beyond the reference (a hint of false corrections)."""
    out = {}
    for kind, prefix in (('church', 'terms'), ('names', 'names')):
        wanted = {}
        for _s, _e, term in spans[kind]:
            wanted[term] = wanted.get(term, 0) + 1
        found = {}
        for _s, _e, term in term_spans(hypothesis, sorted(wanted, key=len, reverse=True)):
            found[term] = found.get(term, 0) + 1
        out[f'{prefix}_bag_found'] = sum(min(n, found.get(t, 0)) for t, n in wanted.items())
        out[f'{prefix}_bag_extra'] = sum(max(0, found.get(t, 0) - n) for t, n in wanted.items())
    return out


def corrections(segments, glossary=None, term_set='all'):
    payload = json.dumps(dict(segments=segments, term_set=term_set, **({'glossary': glossary} if glossary is not None else {})))
    # NODE_BINARY lets Colab use a pinned Node from the nodejs-wheel-binaries package.
    result = subprocess.run([os.environ.get('NODE_BINARY', 'node'), str(ROOT/'scripts/apply-corrections.mjs')], input=payload, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def score_variants(name, segments, reference_variants, spans_by_variant, converter):
    out = corrections(segments)
    core = corrections(segments, term_set='core')
    # Chain: raw → glossary → same-sound (books + church terms) → same-sound (+ Bible names).
    texts = {'raw': ''.join(segments), 'glossary': ''.join(out['glossary']),
             'phonetic_core': ''.join(core['phonetic']), 'phonetic': ''.join(out['phonetic'])}
    result = dict(condition=name, segments=len(segments),
                  phonetic_changes=sum(len(c) for c in out['changes']), variants={})
    for ref_name, reference in reference_variants.items():
        previous = None
        for variant, text in texts.items():
            hypothesis = normalize(text, converter)
            if ref_name == 'speech_only':
                hypothesis = cut_after_reference_end(reference, hypothesis)
            metrics, ok = score(reference, hypothesis, spans_by_variant[ref_name])
            if previous is not None:
                metrics['chars_fixed_vs_previous'] = sum(1 for a, b in zip(previous, ok) if b and not a)
                metrics['chars_broken_vs_previous'] = sum(1 for a, b in zip(previous, ok) if a and not b)
            previous = ok
            result['variants'][f'{ref_name}/{variant}'] = metrics
    script = normalize(texts['raw'])
    result['raw_simplified_ratio'] = round(sum(converter.convert(c) != c for c in script)/len(script), 4) if script else None
    return result, out


def chrome_segments(path):
    """Website export lines: '<local time> <caption text>'; keep the caption text."""
    segments = []
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        match = re.match(r'^(?:上午|下午)?\s*\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AP]M)?\s+(.*)$', line)
        if line:
            segments.append(match.group(1) if match else line)
    return segments


def decode_audio(path):
    """16 kHz mono float32 via ffmpeg, so results do not depend on the installed PyAV version."""
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-f', 's16le', '-ac', '1', '-ar', '16000', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


RATE = 16000


def condition_name(condition):
    chunked = re.fullmatch(r'(cf)?(fixed|vad)(\d+)', condition)
    if chunked:
        return f'{"workers_ai" if chunked.group(1) else "whisper"}_live_{chunked.group(2)}_{chunked.group(3)}s'
    return {'full': 'whisper_no_prompt', 'full_prompt': 'whisper_traditional_prompt'}.get(condition, condition)



def vad_chunks(regions, total, max_samples):
    """Group speech regions [{start,end}] into chunks of at most max_samples, cutting only in pauses;
    a single longer region is split at fixed points. Returns [(start, end)] in samples."""
    chunks = []; current = None
    for region in regions:
        start, end = region['start'], min(region['end'], total)
        while end - start > max_samples:  # one long stretch of speech: forced cut
            if current:
                chunks.append(current); current = None
            chunks.append((start, start + max_samples)); start += max_samples
        if current and end - current[0] <= max_samples:
            current = (current[0], end)
        else:
            if current:
                chunks.append(current)
            current = (start, end)
    if current:
        chunks.append(current)
    return chunks


def fixed_chunks(total, max_samples):
    return [(start, min(start + max_samples, total)) for start in range(0, total, max_samples)]


def live_spans(samples, mode, seconds):
    """The live-caption chunks, identical for local Whisper and Workers AI so their results compare directly."""
    limit = int(seconds*RATE)
    if mode == 'vad':
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        regions = get_speech_timestamps(samples, VadOptions(min_silence_duration_ms=300, speech_pad_ms=100))
        return vad_chunks(regions, len(samples), limit)
    return fixed_chunks(len(samples), limit)


def live_timing(samples, spans, processing):
    lengths = sorted((end - start)/RATE for start, end in spans)
    delays = sorted((end - start)/RATE + p for (start, end), p in zip(spans, processing))
    pick = lambda values, q: round(values[min(len(values) - 1, int(q*len(values)))], 2) if values else None
    duration = len(samples)/RATE
    return dict(duration_seconds=round(duration, 1), elapsed_seconds=round(sum(processing), 1),
                       rtf=round(sum(processing)/duration, 3) if duration else None, chunks=len(spans),
                       chunk_seconds_median=pick(lengths, 0.5), chunk_seconds_max=pick(lengths, 1.0),
                       processing_seconds_p95=pick(sorted(processing), 0.95),
                       caption_delay_seconds_median=pick(delays, 0.5), caption_delay_seconds_p95=pick(delays, 0.95))


def transcribe_chunked(model, audio, mode, seconds):
    """Live-caption simulation: each chunk is recognized on its own (no earlier context), one caption per
    chunk. Delay = chunk length + processing time on THIS hardware (Workers AI timing differs)."""
    samples = decode_audio(audio); spans = live_spans(samples, mode, seconds)
    texts, processing = [], []
    for start, end in spans:
        began = time.monotonic()
        segments, _ = model.transcribe(samples[start:end], language='zh', task='transcribe', beam_size=5,
                                       temperature=0, vad_filter=False, condition_on_previous_text=False,
                                       without_timestamps=True)
        texts.append(''.join(s.text for s in segments).strip())
        processing.append(time.monotonic() - began)
    return texts, live_timing(samples, spans, processing)


class QuotaExhausted(Exception):
    """Daily free allocation (or this run's --cf-max-minutes budget) used up; resume later with --reuse."""


def wav_bytes(samples):
    import numpy as np
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1); out.setsampwidth(2); out.setframerate(RATE)
        out.writeframes((np.clip(samples, -1, 1)*32767).astype('<i2').tobytes())
    return buffer.getvalue()


def workers_ai_request(samples, account, token, attempts=6, opener=urllib.request.urlopen):
    """One chunk through the Workers AI REST API, with the same decoding settings as the local simulation."""
    body = json.dumps(dict(audio=base64.b64encode(wav_bytes(samples)).decode('ascii'), task='transcribe', language='zh',
                           vad_filter=False, condition_on_previous_text=False, beam_size=5)).encode()
    url = f'https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{CF_MODEL}'
    for attempt in range(attempts):
        request = urllib.request.Request(url, data=body, method='POST', headers={
            'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
        try:
            with opener(request, timeout=120) as response:
                return (json.loads(response.read()).get('result') or {}).get('text', '').strip()
        except urllib.error.HTTPError as error:
            try:
                errors = json.loads(error.read()).get('errors') or []
            except ValueError:
                errors = []
            codes = {e.get('code') for e in errors}
            detail = '; '.join(f"{e.get('code')} {e.get('message')}" for e in errors) or str(error)
            if 3036 in codes:
                raise QuotaExhausted(f'Cloudflare：今天的免費額度已用完（{detail}）') from error
            if error.code in (401, 403) or 5035 in codes:
                raise SystemExit(f'Workers AI 拒絕請求（HTTP {error.code}：{detail}）。請確認 CF_ACCOUNT_ID 與 '
                                 'CF_API_TOKEN（需要 Workers AI 權限）。') from error
            if error.code != 429 and error.code < 500:
                raise SystemExit(f'Workers AI 錯誤（HTTP {error.code}：{detail}）') from error
            last = detail
        except (urllib.error.URLError, TimeoutError) as error:
            last = str(error)
        time.sleep(min(60, 2**attempt))
    raise SystemExit(f'Workers AI 重試 {attempts} 次仍失敗：{last}')


def transcribe_workers_ai(audio, mode, seconds, partial_path, budget, request=None):
    """Send the live chunks to Workers AI one by one. Each finished chunk is saved to partial_path at once, so a
    run stopped by the daily allocation or the budget continues where it stopped (--reuse)."""
    request = request or workers_ai_request
    account, token = os.environ.get('CF_ACCOUNT_ID'), os.environ.get('CF_API_TOKEN')
    samples = decode_audio(audio); spans = live_spans(samples, mode, seconds)
    done = json.loads(partial_path.read_text(encoding='utf-8')) if partial_path.exists() else []
    if len(done) < len(spans) and not (account and token):
        raise SystemExit('缺少 CF_ACCOUNT_ID／CF_API_TOKEN 環境變數')
    for start, end in spans[len(done):]:
        minutes = (end - start)/RATE/60
        if budget['used'] + minutes > budget['max']:
            raise QuotaExhausted(f'已達本次上限 {budget["max"]} 音訊分鐘（--cf-max-minutes）')
        began = time.monotonic()
        text = request(samples[start:end], account, token)
        done.append(dict(text=text, processing=round(time.monotonic() - began, 3)))
        budget['used'] += minutes
        partial_path.write_text(json.dumps(done, ensure_ascii=False), encoding='utf-8')
    timing = live_timing(samples, spans, [d['processing'] for d in done])
    audio_minutes = sum(end - start for start, end in spans)/RATE/60
    timing.update(audio_minutes=round(audio_minutes, 1), neurons_estimate=round(audio_minutes*CF_NEURONS_PER_AUDIO_MINUTE),
                  processing_note='HTTPS round trip from the evaluation machine to Workers AI')
    return [d['text'] for d in done], timing


def transcribe(model, audio, prompt):
    samples = decode_audio(audio)
    started = time.monotonic()
    segments, info = model.transcribe(samples, language='zh', task='transcribe', beam_size=5, temperature=0,
                                      vad_filter=True, condition_on_previous_text=False, initial_prompt=prompt)
    texts = [s.text for s in segments]
    elapsed = time.monotonic() - started
    return texts, dict(duration_seconds=round(info.duration, 1), elapsed_seconds=round(elapsed, 1),
                       rtf=round(elapsed/info.duration, 3) if info.duration else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--meet', required=True, help='Folder with NN.mp3 + NN.txt (optional NN.chrome.txt)')
    parser.add_argument('--output', required=True, help='New run folder (must not exist)')
    parser.add_argument('--model-dir', help='Local faster-whisper model folder; omit to score Chrome exports only')
    parser.add_argument('--model-label', default='whisper-large-v3-turbo')
    parser.add_argument('--device', default='auto', choices=['auto', 'cuda', 'cpu'])
    parser.add_argument('--only', help='Comma-separated pair ids (e.g. 01) to evaluate')
    parser.add_argument('--reuse', action='append', default=[],
                        help='Earlier (possibly interrupted) run folder, may be given more than once (first match wins): '
                        'reuse its recognizer outputs, recognize only what is missing, and re-score everything')
    parser.add_argument('--loose-reference', action='store_true',
                        help='References are not verbatim (Life-Study): also report alignment-free term counts')
    parser.add_argument('--development', action='store_true', help='Development data (e.g. Bible readings), not a sealed test')
    parser.add_argument('--conditions', default='full,fixed15,vad15',
                        help='full (whole file), full_prompt (+Traditional prompt), fixed<N> / vad<N> (N-second live chunks), '
                        'cfvad<N> / cffixed<N> (the same chunks through Cloudflare Workers AI)')
    parser.add_argument('--cf-max-minutes', type=float, default=190,
                        help='Most audio minutes sent to Workers AI in this run (default 190 = about 8,900 of the 10,000 '
                        'free daily neurons)')
    args = parser.parse_args()
    from opencc import OpenCC
    converter = OpenCC('s2tw')
    meet = Path(args.meet); output = Path(args.output); output.mkdir(parents=True)
    pairs = sorted(p.stem for p in meet.glob('*.txt') if not p.stem.endswith('.chrome') and (meet/f'{p.stem}.mp3').exists())
    if args.only:
        pairs = [p for p in pairs if p in set(args.only.split(','))]
    if not pairs:
        raise SystemExit('No NN.mp3 + NN.txt pairs found')
    loaded = {}
    budget = dict(used=0.0, max=args.cf_max_minutes)

    def earlier_file(name):
        return next((Path(folder)/name for folder in args.reuse if (Path(folder)/name).exists()), None)

    def get_model():
        """Load the recognizer only when some output is not already available (--reuse / resumed runs)."""
        if 'model' not in loaded:
            if not args.model_dir:
                raise SystemExit('Recognizer output missing and no --model-dir given')
            from faster_whisper import WhisperModel
            import ctranslate2
            device = args.device if args.device != 'auto' else ('cuda' if ctranslate2.get_cuda_device_count() else 'cpu')
            model = WhisperModel(args.model_dir, device=device, compute_type='float16' if device == 'cuda' else 'int8',
                                 local_files_only=True)
            try:  # Fail fast (e.g. missing libcublas.so.12) before spending time on long audio.
                import numpy as np
                list(model.transcribe(np.zeros(16000, np.float32), language='zh')[0])
            except RuntimeError as error:
                raise SystemExit(f'模型無法在 {device} 上執行：{error}\n'
                                 '若是缺少 libcublas／libcudnn：請安裝 nvidia-cublas-cu12、nvidia-cudnn-cu12 並設定 LD_LIBRARY_PATH'
                                 '（Colab 筆記本第 3 格會自動處理）。') from error
            print(f'模型 {args.model_label}，裝置 {device}', flush=True)
            loaded['model'] = model
        return loaded['model']
    terms, names = church_terms(), bible_names()
    report = dict(created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'), sealed_test=not args.development,
                  model=args.model_label, model_bin_sha256=sha256_file(Path(args.model_dir)/'model.bin') if args.model_dir else None,
                  normalizer='NFC + OpenCC s2tw (hypothesis) + keep CJK/Latin/digits, lowercase',
                  code_files={p: sha256_file(ROOT/p) for p in ['glossary.js', 'public/phonetic.js', 'public/church-terms.js',
                                                              'public/pinyin-zh.js', 'scripts/evaluate_meet.py']},
                  workers_ai_model=CF_MODEL if 'cf' in args.conditions else None,
                  pairs=[])
    for pair in pairs:
        reference_text = clean_reference((meet/f'{pair}.txt').read_text(encoding='utf-8-sig'))
        references = {'full': normalize(reference_text), 'no_parentheses': normalize(without_parentheses(reference_text))}
        speech = without_hymn(reference_text)
        if speech != reference_text:  # sung hymn: also score the spoken part only (recognized hymn text not counted)
            references['speech_only'] = normalize(speech)
        spans = {name: category_spans(text, terms, names) for name, text in references.items()}
        entry = dict(id=pair, audio_sha256=sha256_file(meet/f'{pair}.mp3'), reference_sha256=sha256_file(meet/f'{pair}.txt'),
                     reference_chars=len(references['full']), term_occurrences=len(spans['full']['church']),
                     name_occurrences=len(spans['full']['names']), conditions=[])
        print(f'[{pair}] 參考文字 {entry["reference_chars"]} 字、教會專名 {entry["term_occurrences"]} 處、'
              f'人名地名 {entry["name_occurrences"]} 處', flush=True)
        if args.model_dir or args.reuse or re.search(r'\bcf', args.conditions):
            for condition in [c.strip() for c in args.conditions.split(',') if c.strip()]:
                chunked = re.fullmatch(r'(fixed|vad)(\d+)', condition)
                cloud = re.fullmatch(r'cf(fixed|vad)(\d+)', condition)
                cached = earlier_file(f'{pair}.{condition_name(condition)}.json')
                reused = bool(cached and cached.exists())
                if reused:
                    name = condition_name(condition)
                    texts = json.loads(cached.read_text(encoding='utf-8'))['raw']
                    saved = json.loads(cached.read_text(encoding='utf-8'))
                    timing = dict(saved.get('timing', {}))  # older outputs (before resume support) have no timing
                    prompt = saved.get('prompt')
                elif condition in ('full', 'full_prompt'):
                    prompt = NEUTRAL_PROMPT if condition == 'full_prompt' else None
                    name = 'whisper_traditional_prompt' if prompt else 'whisper_no_prompt'
                    texts, timing = transcribe(get_model(), meet/f'{pair}.mp3', prompt)
                elif chunked:
                    mode, seconds = chunked.group(1), int(chunked.group(2))
                    name, prompt = f'whisper_live_{mode}_{seconds}s', None
                    texts, timing = transcribe_chunked(get_model(), meet/f'{pair}.mp3', mode, seconds)
                elif cloud:
                    name, prompt = condition_name(condition), None
                    partial = output/f'{pair}.{name}.partial.json'
                    earlier = earlier_file(partial.name)
                    if earlier and earlier.exists() and not partial.exists():
                        partial.write_text(earlier.read_text(encoding='utf-8'), encoding='utf-8')
                    try:
                        texts, timing = transcribe_workers_ai(meet/f'{pair}.mp3', cloud.group(1), int(cloud.group(2)),
                                                              partial, budget)
                    except QuotaExhausted as stop:
                        print(f'\n已暫停：{stop}\n已完成的段落存在 {output}。台灣時間早上 8 點（UTC 0 點）額度重置後，'
                              f'把 --reuse "{output}" 加在最前面再執行一次就會從暫停處繼續。', flush=True)
                        raise SystemExit(3)
                else:
                    raise SystemExit(f'Unknown condition: {condition}')
                result, out = score_variants(name, texts, references, spans, converter)
                result.update(timing, prompt=prompt)
                if reused:
                    result['reused_from'] = str(cached.parent)
                entry['conditions'].append(result)
                (output/f'{pair}.{name}.json').write_text(json.dumps(dict(raw=texts, timing=timing, prompt=prompt, **out),
                                                                     ensure_ascii=False, indent=1), encoding='utf-8')
                if cloud and not reused:
                    source_note = f'，{timing["audio_minutes"]} 音訊分鐘、約 {timing["neurons_estimate"]} neurons'
                else:
                    source_note = ''
                delay = f'，字幕延遲中位數 {timing["caption_delay_seconds_median"]} 秒、P95 {timing["caption_delay_seconds_p95"]} 秒' if 'chunks' in timing else ''
                source = '沿用先前辨識結果' if reused else f'RTF {timing.get("rtf")}'
                print(f'  {name}: 完成（{source}{delay}{source_note}）', flush=True)
        chrome = meet/f'{pair}.chrome.txt'
        if chrome.exists():
            texts = chrome_segments(chrome)
            result, out = score_variants('chrome_export', texts, references, spans, converter)
            result['source_sha256'] = sha256_file(chrome)
            entry['conditions'].append(result)
            (output/f'{pair}.chrome_export.json').write_text(json.dumps(dict(raw=texts, **out), ensure_ascii=False, indent=1), encoding='utf-8')
            print('  chrome_export: 完成', flush=True)
        report['pairs'].append(entry)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    rows = ['| 測試 | 條件 | 版本 | CER | 專名正確 | 人名地名正確 | 修好字數 | 改壞字數 |', '| --- | --- | --- | --- | --- | --- | --- | --- |']
    for entry in report['pairs']:
        for cond in entry['conditions']:
            for key, m in cond['variants'].items():
                if key.startswith('full/'):
                    acc = f"{m['terms_correct']}/{m['term_occurrences']}" if m['term_occurrences'] else '—'
                    names_acc = f"{m['names_correct']}/{m['name_occurrences']}" if m['name_occurrences'] else '—'
                    rows.append(f"| {entry['id']} | {cond['condition']} | {key.split('/')[1]} | {m['cer']:.2%} | {acc} | {names_acc} | "
                                f"{m.get('chars_fixed_vs_previous', '—')} | {m.get('chars_broken_vs_previous', '—')} |")
    totals = {}
    for entry in report['pairs']:
        for cond in entry['conditions']:
            for key, m in cond['variants'].items():
                if key.startswith('full/'):
                    t = totals.setdefault((cond['condition'], key.split('/')[1]), dict(e=0, r=0, tc=0, to=0, nc=0, no=0, f=0, b=0))
                    t['e'] += m['edit_distance']; t['r'] += m['reference_chars']; t['tc'] += m['terms_correct']
                    t['to'] += m['term_occurrences']; t['nc'] += m['names_correct']; t['no'] += m['name_occurrences']
                    t['f'] += m.get('chars_fixed_vs_previous', 0); t['b'] += m.get('chars_broken_vs_previous', 0)
    rows += ['', f"合計（{len(report['pairs'])} 組）", '', '| 條件 | 版本 | CER | 專名正確 | 人名地名正確 | 修好字數 | 改壞字數 |',
             '| --- | --- | --- | --- | --- | --- | --- |']
    for (condition, variant), t in totals.items():
        rows.append(f"| {condition} | {variant} | {t['e']/t['r']:.2%} | {t['tc']}/{t['to']} | {t['nc']}/{t['no']} | "
                    f"{t['f'] if variant != 'raw' else '—'} | {t['b'] if variant != 'raw' else '—'} |")
    speech_rows = []
    for entry in report['pairs']:
        for cond in entry['conditions']:
            for key, m in cond['variants'].items():
                if key.startswith('speech_only/'):
                    speech_rows.append(f"| {entry['id']} | {cond['condition']} | {key.split('/')[1]} | {m['cer']:.2%} | "
                                       f"{m['terms_correct']}/{m['term_occurrences']} | {m['names_correct']}/{m['name_occurrences']} |")
    if speech_rows:
        rows += ['', '只算講道（不含詩歌；唱歌被辨識出的文字不計）', '', '| 測試 | 條件 | 版本 | CER | 專名正確 | 人名地名正確 |',
                 '| --- | --- | --- | --- | --- | --- |'] + speech_rows
    rows += ['', '錯誤分類（原始辨識，對照完整參考文字）', '',
             '| 測試 | 條件 | 替換 | 漏字 | 多字 | 長段漏字（≥20字） | 字幕延遲 中位數／P95 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for entry in report['pairs']:
        for cond in entry['conditions']:
            m = cond['variants']['full/raw']
            delay = (f"{cond['caption_delay_seconds_median']}／{cond['caption_delay_seconds_p95']} 秒"
                     if 'caption_delay_seconds_median' in cond else '—')
            rows.append(f"| {entry['id']} | {cond['condition']} | {m['substitutions']} | {m['deletions']} | {m['insertions']} | "
                        f"{m['long_deletion_runs']} 段／{m['long_deletion_chars']} 字 | {delay} |")
    if args.loose_reference:
        bag = {}
        for entry in report['pairs']:
            for cond in entry['conditions']:
                for key, m in cond['variants'].items():
                    if key.startswith('full/'):
                        t = bag.setdefault((cond['condition'], key.split('/')[1]), [0, 0, 0, 0, 0, 0])
                        for i, k in enumerate(['terms_bag_found', 'term_occurrences', 'terms_bag_extra',
                                               'names_bag_found', 'name_occurrences', 'names_bag_extra']):
                            t[i] += m[k]
        rows += ['', '專名比對（不需逐字對齊；參考文字不是逐字稿時以此為準，CER 僅供參考）', '',
                 '| 條件 | 版本 | 教會專名找到 | 多出 | 人名地名找到 | 多出 |', '| --- | --- | --- | --- | --- | --- |']
        for (condition, variant), t in bag.items():
            rows.append(f'| {condition} | {variant} | {t[0]}/{t[1]} | {t[2]} | {t[3]}/{t[4]} | {t[5]} |')
    summary = '\n'.join(rows)
    (output/'summary.md').write_text(summary+'\n', encoding='utf-8')
    print('\n'+summary)


if __name__ == '__main__':
    sys.exit(main())
