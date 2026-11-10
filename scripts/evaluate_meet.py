#!/usr/bin/env python3
"""Evaluate caption accuracy on a sealed meeting test set (audio + near-verbatim reference text).

Input folder (e.g. Google Drive MEET/): NN.mp3 + NN.txt pairs. Optional NN.chrome.txt = captions exported
from the website ("下載字幕") while it listened to NN.mp3 with 同音校正 turned OFF; the corrections are
then applied here so raw and corrected Chrome results can both be scored.

For every recognizer output three variants are scored, the same way the website processes captions:
  raw       recognizer text
  glossary  + exact glossary replacements (glossary.js)
  phonetic  + same-sound church-term correction (public/phonetic.js)

Metrics: CER on normalized text (NFC, Simplified→Traditional for the hypothesis, punctuation/space removed),
church-term accuracy on reference term occurrences, and chars fixed/broken by each correction step.
This is a SEALED test: do not tune terms, prompts or rules from its errors; print aggregates only.
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
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEUTRAL_PROMPT = '以下是繁體中文的逐字稿。'
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


def without_parentheses(text):
    """Variant without parenthesized citations such as （約四24）, which speakers may not read aloud."""
    return re.sub(r'[（(][^（）()]{0,40}[）)]', '', text)


def normalize(text, converter=None):
    text = unicodedata.normalize('NFC', text)
    if converter:
        text = converter.convert(text)
    return ''.join(KEEP.findall(text)).lower()


def church_terms():
    source = (ROOT/'public/church-terms.js').read_text(encoding='utf-8')
    return sorted(set(re.findall(r"'([^']+)'", source)), key=len, reverse=True)


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
    correct = sum(all(ok[s:e]) for s, e, _ in spans)
    return dict(cer=round(distance/len(reference), 4) if reference else None, edit_distance=distance,
                reference_chars=len(reference), hypothesis_chars=len(hypothesis),
                term_occurrences=len(spans), terms_correct=correct,
                term_accuracy=round(correct/len(spans), 4) if spans else None), ok


def corrections(segments, glossary=None):
    payload = json.dumps(dict(segments=segments, **({'glossary': glossary} if glossary is not None else {})))
    # NODE_BINARY lets Colab use a pinned Node from the nodejs-wheel-binaries package.
    result = subprocess.run([os.environ.get('NODE_BINARY', 'node'), str(ROOT/'scripts/apply-corrections.mjs')], input=payload, text=True,
                            capture_output=True, check=True)
    return json.loads(result.stdout)


def score_variants(name, segments, reference_variants, spans_by_variant, converter):
    out = corrections(segments)
    texts = {'raw': ''.join(segments), 'glossary': ''.join(out['glossary']), 'phonetic': ''.join(out['phonetic'])}
    result = dict(condition=name, segments=len(segments),
                  phonetic_changes=sum(len(c) for c in out['changes']), variants={})
    for ref_name, reference in reference_variants.items():
        previous = None
        for variant, text in texts.items():
            metrics, ok = score(reference, normalize(text, converter), spans_by_variant[ref_name])
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
    args = parser.parse_args()
    from opencc import OpenCC
    converter = OpenCC('s2tw')
    meet = Path(args.meet); output = Path(args.output); output.mkdir(parents=True)
    pairs = sorted(p.stem for p in meet.glob('*.txt') if not p.stem.endswith('.chrome') and (meet/f'{p.stem}.mp3').exists())
    if args.only:
        pairs = [p for p in pairs if p in set(args.only.split(','))]
    if not pairs:
        raise SystemExit('No NN.mp3 + NN.txt pairs found')
    model = None
    if args.model_dir:
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
    terms = church_terms()
    report = dict(created_at=datetime.now(timezone.utc).isoformat(timespec='seconds'), sealed_test=True,
                  model=args.model_label, model_bin_sha256=sha256_file(Path(args.model_dir)/'model.bin') if args.model_dir else None,
                  normalizer='NFC + OpenCC s2tw (hypothesis) + keep CJK/Latin/digits, lowercase',
                  code_files={p: sha256_file(ROOT/p) for p in ['glossary.js', 'public/phonetic.js', 'public/church-terms.js',
                                                              'public/pinyin-zh.js', 'scripts/evaluate_meet.py']},
                  pairs=[])
    for pair in pairs:
        reference_text = clean_reference((meet/f'{pair}.txt').read_text(encoding='utf-8-sig'))
        references = {'full': normalize(reference_text), 'no_parentheses': normalize(without_parentheses(reference_text))}
        spans = {name: term_spans(text, terms) for name, text in references.items()}
        entry = dict(id=pair, audio_sha256=sha256_file(meet/f'{pair}.mp3'), reference_sha256=sha256_file(meet/f'{pair}.txt'),
                     reference_chars=len(references['full']), term_occurrences=len(spans['full']), conditions=[])
        print(f'[{pair}] 參考文字 {entry["reference_chars"]} 字、教會專名 {entry["term_occurrences"]} 處', flush=True)
        if model:
            for name, prompt in [('whisper_no_prompt', None), ('whisper_traditional_prompt', NEUTRAL_PROMPT)]:
                texts, timing = transcribe(model, meet/f'{pair}.mp3', prompt)
                result, out = score_variants(name, texts, references, spans, converter)
                result.update(timing, prompt=prompt)
                entry['conditions'].append(result)
                (output/f'{pair}.{name}.json').write_text(json.dumps(dict(raw=texts, **out), ensure_ascii=False, indent=1), encoding='utf-8')
                print(f'  {name}: 完成（RTF {timing["rtf"]}）', flush=True)
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
    rows = ['| 測試 | 條件 | 版本 | CER | 專名正確 | 修好字數 | 改壞字數 |', '| --- | --- | --- | --- | --- | --- | --- |']
    for entry in report['pairs']:
        for cond in entry['conditions']:
            for key, m in cond['variants'].items():
                if key.startswith('full/'):
                    acc = f"{m['terms_correct']}/{m['term_occurrences']}" if m['term_occurrences'] else '—'
                    rows.append(f"| {entry['id']} | {cond['condition']} | {key.split('/')[1]} | {m['cer']:.2%} | {acc} | "
                                f"{m.get('chars_fixed_vs_previous', '—')} | {m.get('chars_broken_vs_previous', '—')} |")
    summary = '\n'.join(rows)
    (output/'summary.md').write_text(summary+'\n', encoding='utf-8')
    print('\n'+summary)


if __name__ == '__main__':
    sys.exit(main())
