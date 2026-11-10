#!/usr/bin/env python3
"""Compare Whisper decoding with and without church-vocabulary hotwords on private evaluation audio.

No reference transcript is used or claimed: outputs are machine_generated, metrics are descriptive
(script ratio, term counts, disagreement windows) and the review pack needs human listening before
any accuracy statement. Hotwords come from extract_church_terms.py by a fixed rule, never from the
evaluation audio or its outputs.
"""
import argparse
import hashlib
import importlib.metadata
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

NEUTRAL = '以下是繁體中文的逐字稿。'
CJK = re.compile(r'[㐀-䶿一-鿿豈-﫿]')


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def select_terms(candidates_path, approved_path, top_k):
    """Fixed rule: approved targets (>=2 chars) first, then top_k non-general candidates by score."""
    terms = []
    for group in json.loads(Path(approved_path).read_text(encoding='utf-8'))['targets']:
        for term in group['terms']:
            if len(term) >= 2 and term not in terms:
                terms.append(term)
    added = 0
    for line in Path(candidates_path).read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if added >= top_k:
            break
        if not row['general_common'] and row['term'] not in terms:
            terms.append(row['term']); added += 1
    return terms


def fit_prompt(tokenizer, terms, max_tokens):
    # Whisper keeps only the last ~223 prompt tokens; drop the lowest-ranked terms rather than truncate silently.
    kept = list(terms)
    while kept and len(tokenizer.encode(' '+NEUTRAL+'、'.join(kept)).ids) > max_tokens:
        kept = kept[:-1]
    return kept


def script_stats(text, s2t):
    chars = CJK.findall(text)
    simplified = sum(1 for c in chars if s2t.convert(c) != c)
    return dict(cjk_chars=len(chars), simplified_only_chars=simplified,
                simplified_ratio=round(simplified/len(chars), 4) if chars else None)


def windows(segments, clip_seconds, width):
    grid = [[] for _ in range(int(clip_seconds//width)+1)]
    for seg in segments:
        grid[min(len(grid)-1, int(((seg['start']+seg['end'])/2)//width))].append(seg['text'].strip())
    return [''.join(parts) for parts in grid]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio-root', required=True, help='fetch_church_audio.py output root')
    parser.add_argument('--candidates', required=True, help='candidates.jsonl from a leave-out extraction run')
    parser.add_argument('--approved', default='evaluation/glossary/approved-targets.json')
    parser.add_argument('--model-dir', default='models/whisper-small')
    parser.add_argument('--output', required=True, help='New private directory under artifacts/')
    parser.add_argument('--clip-seconds', type=int, default=600)
    parser.add_argument('--top-k', type=int, default=40)
    parser.add_argument('--max-prompt-tokens', type=int, default=200)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    from faster_whisper import WhisperModel
    from opencc import OpenCC
    s2t = OpenCC('s2t')
    root = Path(args.audio_root).resolve(strict=True)
    rows = [json.loads(l) for l in (root/'manifests/audio.jsonl').read_text(encoding='utf-8').splitlines() if l.strip()]
    if not rows or any(r['training_ready'] or r['allowed_use'] != 'internal_evaluation_pending_rights' for r in rows):
        raise SystemExit('Audio manifest must be pending-rights internal evaluation rows only')
    output = Path(args.output); output.mkdir(parents=True)  # never overwrite an earlier run
    model_dir = Path(args.model_dir).resolve(strict=True)
    model = WhisperModel(str(model_dir), device='cpu', compute_type='int8', cpu_threads=args.threads,
                         num_workers=1, local_files_only=True)
    terms = fit_prompt(model.hf_tokenizer, select_terms(args.candidates, args.approved, args.top_k), args.max_prompt_tokens)
    conditions = {'baseline': None, 'neutral_traditional': NEUTRAL, 'church_hotwords': NEUTRAL+'、'.join(terms)}
    settings = dict(language='zh', task='transcribe', beam_size=5, temperature=0, vad_filter=False,
                    condition_on_previous_text=True, initial_prompt=None)
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), status='machine_generated_no_reference',
                  reference_used=False, human_verified=False, training_run=False,
                  model_file_sha256=sha256_file(model_dir/'model.bin'), settings=settings,
                  term_rule=dict(top_k=args.top_k, exclude_general_common=True, plus='approved_targets_len>=2',
                                 max_prompt_tokens=args.max_prompt_tokens,
                                 candidates_sha256=sha256_file(args.candidates)),
                  hotword_terms=terms, conditions=conditions, clip_seconds=args.clip_seconds,
                  packages={n: importlib.metadata.version(n) for n in ['faster-whisper', 'ctranslate2', 'av']},
                  files=[])
    review = ['file,window_start,window_end,baseline,neutral_traditional,church_hotwords,correct_condition,note\n']
    for row in rows:
        clip = output/f"{row['id']}-{args.clip_seconds}s.wav"
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(root/row['audio_path']), '-t', str(args.clip_seconds),
                        '-ar', '16000', '-ac', '1', '-c:a', 'pcm_s16le', str(clip)], check=True)
        entry = dict(id=row['id'], source_url=row['source_url'], source_sha256=row['sha256'],
                     clip_sha256=sha256_file(clip), results={})
        grids = {}
        for name, hotwords in conditions.items():
            started = time.monotonic()
            segments, info = model.transcribe(str(clip), hotwords=hotwords, **settings)
            segs = [dict(start=round(s.start, 2), end=round(s.end, 2), text=s.text,
                         avg_logprob=round(s.avg_logprob, 4)) for s in segments]
            elapsed = time.monotonic()-started
            text = ''.join(s['text'] for s in segs)
            normalized = s2t.convert(text)  # script-normalized copy for term counting only
            entry['results'][name] = dict(elapsed_seconds=round(elapsed, 1), rtf=round(elapsed/info.duration, 3),
                                          segments=len(segs), **script_stats(text, s2t),
                                          term_hits_script_normalized={t: normalized.count(t) for t in terms if normalized.count(t)},
                                          text=text, segment_rows=segs)
            grids[name] = windows(segs, args.clip_seconds, 30)
            print(json.dumps(dict(file=row['id'], condition=name, rtf=entry['results'][name]['rtf'])), flush=True)
        base_chars = entry['results']['baseline']['cjk_chars']
        for result in entry['results'].values():
            # Long prompts can make Whisper skip speech; fewer characters is a regression flag, not brevity.
            result['speech_loss_suspected'] = bool(base_chars and result['cjk_chars'] < 0.8*base_chars)
        for i, parts in enumerate(zip(*grids.values())):
            if len(set(parts)) > 1:
                cells = ['"'+p.replace('"', '""')+'"' for p in parts]
                review.append(f"{row['id']},{i*30},{(i+1)*30},{','.join(cells)},,\n")
        report['files'].append(entry)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output/'listening-review.csv').write_text(''.join(review), encoding='utf-8-sig')
    summary = {f['id']: {k: dict(rtf=v['rtf'], simplified_ratio=v['simplified_ratio'],
                                 term_hits=sum(v['term_hits_script_normalized'].values()),
                                 speech_loss_suspected=v['speech_loss_suspected'])
                         for k, v in f['results'].items()} for f in report['files']}
    (output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(output=str(output), hotword_terms=len(terms), summary=summary), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
