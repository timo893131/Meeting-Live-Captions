#!/usr/bin/env python3
"""Context-correction experiment: cut audio into the website's live chunks, and score the results.

  prepare  NN.mp3 → NN.chunks.json + NN.chunks.s16 (pause cut, ≤10 s: the same chunks as evaluate_meet.py vad10/cfvad10).
           --window-start/--window-seconds keep only the chunks inside one stretch of each recording (Life-Study
           development set: a few minutes per message, so the free Workers AI allocation is enough).
  score    read a run of scripts/context-experiment.mjs and compare the conditions with the website (base).

References: MEET (sealed test, near verbatim) is scored on the whole text: CER, church terms at aligned positions.
Life-Study (development, --development) is not verbatim; within a window the matching part of the message is
located from the base captions (6-character anchors) and the same region is used for every condition. The
primary measure there is the alignment-free term count (found / extra), as in evaluate_meet.py --loose-reference.
A sealed test prints totals only; it must not be used to choose models, prompts or rules.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import evaluate_meet as ev  # noqa: E402

GATES = dict(found_gain_ratio=0.03, extra_increase_ratio=0.005, extra_increase_min=2, broken_per_fixed=0.2,
             llm_neurons_per_hour=1000, llm_latency_p95=3.0)


def prepare(args):
    data, out = Path(args.data), Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    pairs = sorted(p.stem for p in data.glob('*.txt') if not p.stem.endswith('.chrome') and (data/f'{p.stem}.mp3').exists())
    if args.only:
        pairs = [p for p in pairs if p in set(args.only.split(','))]
    if not pairs:
        raise SystemExit(f'{data} 沒有 NN.mp3 + NN.txt')
    for pair in pairs:
        samples = ev.decode_audio(data/f'{pair}.mp3')
        spans = ev.live_spans(samples, 'vad', 10)
        if args.window_seconds:
            lo, hi = int(args.window_start*ev.RATE), int((args.window_start + args.window_seconds)*ev.RATE)
            chosen = [(k, s, e) for k, (s, e) in enumerate(spans) if s >= lo and e <= hi]
            duration = min(hi, len(samples))/ev.RATE - min(lo, len(samples))/ev.RATE
        else:
            chosen = [(k, s, e) for k, (s, e) in enumerate(spans)]
            duration = len(samples)/ev.RATE
        import numpy as np
        pcm = b''.join((np.clip(samples[s:e], -1, 1)*32767).astype('<i2').tobytes() for _, s, e in chosen)
        (out/f'{pair}.chunks.s16').write_bytes(pcm)
        meta = dict(pair=pair, audio_sha256=ev.sha256_file(data/f'{pair}.mp3'), total_chunks=len(spans),
                    window=[args.window_start, args.window_seconds] if args.window_seconds else None,
                    duration_seconds=round(duration, 1),
                    chunks=[dict(full_index=k, start=round(s/ev.RATE, 2), samples=e - s, seconds=round((e - s)/ev.RATE, 3))
                            for k, s, e in chosen],
                    pcm_sha256=hashlib.sha256(pcm).hexdigest())
        (out/f'{pair}.chunks.json').write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding='utf-8')
        print(f'[{pair}] {len(chosen)}/{len(spans)} 段、{duration/60:.1f} 分鐘', flush=True)


def reference_region(reference, hypothesis, n=6, margin=30):
    """(start, end) of the reference stretch that the hypothesis covers, from n-grams that occur once in the
    reference; outliers further than twice the hypothesis length from the median anchor are ignored."""
    positions = {}
    for i in range(len(reference) - n + 1):
        positions.setdefault(reference[i:i + n], []).append(i)
    hits = sorted(positions[g][0] for j in range(len(hypothesis) - n + 1)
                  if len(positions.get(g := hypothesis[j:j + n], ())) == 1)
    if len(hits) < 3:
        return None
    median = hits[len(hits)//2]
    kept = [h for h in hits if abs(h - median) <= 2*len(hypothesis)]
    return max(0, kept[0] - margin), min(len(reference), kept[-1] + n + margin)


def pick(values, q):
    values = sorted(v for v in values if v is not None)
    return round(values[min(len(values) - 1, int(q*len(values)))], 2) if values else None


def load_stream(run, name):
    path = Path(run)/f'{name}.json'
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding='utf-8'))
    return data if data.get('complete') else None


def condition_texts(run, pair):
    """{condition: dict(segments, records, kind, model)} for everything finished in the run."""
    out = {}
    for kind in ('base', 'prompt'):
        stream = load_stream(run, f'{pair}.whisper_{kind}')
        if stream:
            out[kind] = dict(segments=[r['site'] for r in stream['records']], records=stream['records'], kind='whisper')
    for path in sorted(Path(run).glob(f'{pair}.llm_*__*.json')):
        if path.name.endswith('.partial.json'):
            continue
        stream = json.loads(path.read_text(encoding='utf-8'))
        if not stream.get('complete'):
            continue
        model = stream['model']; source = 'llm' if stream['source'] == 'base' else 'prompt_llm'
        records = stream['records']
        out[f'{source}|{model}'] = dict(segments=[r['final'] for r in records], records=records, kind='llm', model=model)
        out[f'{source}|{model}|unguarded'] = dict(segments=[r['final_unguarded'] for r in records], records=records,
                                                  kind='llm_unguarded', model=model)
    return out


def prompt_echo(records):
    """Captions that repeat ≥8 characters of the previous caption that was in Whisper's prompt."""
    count = 0
    for r in records:
        prompt, text = r.get('prompt') or '', ev.normalize(r.get('site') or '')
        tail = ev.normalize(prompt.split('。')[-1])
        if len(tail) >= 8 and any(tail[i:i + 8] in text for i in range(len(tail) - 7)):
            count += 1
    return count


def score(args):
    run, data, prepared = Path(args.run), Path(args.data), Path(args.prepared)
    terms, names = ev.church_terms(), ev.bible_names()
    metas = {p.name.replace('.chunks.json', ''): json.loads(p.read_text(encoding='utf-8')) for p in sorted(prepared.glob('*.chunks.json'))}
    totals, stats, pairs_report = {}, {}, []
    hours = 0.0
    for pair, meta in metas.items():
        conditions = condition_texts(run, pair)
        if 'base' not in conditions:
            continue
        hours += meta['duration_seconds']/3600
        full = ev.normalize(ev.clean_reference((data/f'{pair}.txt').read_text(encoding='utf-8-sig')))
        base_text = ev.normalize(''.join(conditions['base']['segments']))
        region = (0, len(full))
        if args.development and meta.get('window'):
            region = reference_region(full, base_text)
            if region is None:
                print(f'[{pair}] 找不到對應的參考文字段落，略過', flush=True)
                continue
        reference = full[region[0]:region[1]]
        spans = ev.category_spans(reference, terms, names)
        entry = dict(id=pair, reference_region=list(region), reference_chars=len(reference),
                     term_occurrences=len(spans['church']), name_occurrences=len(spans['names']), conditions={})
        base_ok = None
        for name in ['base', 'prompt'] + sorted(k for k in conditions if k not in ('base', 'prompt')):
            if name not in conditions:
                continue
            c = conditions[name]
            metrics, ok = ev.score(reference, ev.normalize(''.join(c['segments'])), spans)
            if base_ok is None:
                base_ok = ok
            else:
                metrics['chars_fixed_vs_base'] = sum(1 for a, b in zip(base_ok, ok) if b and not a)
                metrics['chars_broken_vs_base'] = sum(1 for a, b in zip(base_ok, ok) if a and not b)
            metrics['changed_segments_vs_base'] = sum(a != b for a, b in zip(conditions['base']['segments'], c['segments']))
            entry['conditions'][name] = metrics
            t = totals.setdefault(name, {})
            for key in ('edit_distance', 'reference_chars', 'terms_correct', 'term_occurrences', 'terms_bag_found', 'terms_bag_extra',
                        'names_correct', 'name_occurrences', 'names_bag_found', 'names_bag_extra', 'chars_fixed_vs_base',
                        'chars_broken_vs_base', 'changed_segments_vs_base'):
                t[key] = t.get(key, 0) + metrics.get(key, 0)
            s = stats.setdefault(name, dict(kind=c['kind'], latency=[], neurons=0.0, calls=0, segments=0, tokens_in=0, tokens_out=0,
                                            proposed=0, accepted=0, rejected={}, parse_errors=0, echo=0, estimated_tokens=0))
            s['segments'] += len(c['records'])
            if c['kind'] == 'whisper':
                s['latency'] += [r.get('latency') for r in c['records']]
                s['neurons'] += sum(r.get('neurons') or r['seconds']/60*46.63 for r in c['records'])
                s['echo'] += prompt_echo(c['records']) if name == 'prompt' else 0
            elif c['kind'] == 'llm':
                for r in c['records']:
                    if not r['called']:
                        continue
                    s['calls'] += 1; s['latency'].append(r['latency']); s['neurons'] += r['neurons']
                    s['tokens_in'] += r['tokens_in']; s['tokens_out'] += r['tokens_out']
                    s['estimated_tokens'] += bool(r.get('tokens_estimated'))
                    s['parse_errors'] += bool(r['parse_error']); s['proposed'] += len(r['edits']); s['accepted'] += len(r['accepted'])
                    for item in r['rejected']:
                        s['rejected'][item['reason']] = s['rejected'].get(item['reason'], 0) + 1
        pairs_report.append(entry)
    if not pairs_report:
        raise SystemExit('沒有可計分的結果（base 尚未完成？）')
    report = dict(run=str(run), sealed_test=not args.development, audio_hours=round(hours, 3), gates=GATES, pairs=pairs_report,
                  totals=totals, stats={k: {**v, 'latency': None} for k, v in stats.items()})
    lines = summary(report, totals, stats, hours, args.development)
    if args.development:
        lines += review_lines(run, metas)
    (run/'context-report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (run/'context-summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))


def label(name):
    parts = name.split('|')
    text = {'base': '網站（基準）', 'prompt': 'A：Whisper 提示', 'llm': 'B：語言模型', 'prompt_llm': 'A＋B'}[parts[0]]
    if len(parts) > 1:
        text += f'（{parts[1].replace("@cf/", "")}' + ('，未經安全檢查' if len(parts) > 2 else '') + '）'
    return text


def summary(report, totals, stats, hours, development):
    base = totals['base']
    lines = [f"資料：{'生命讀經開發集（參考文字不是逐字稿）' if development else 'MEET 封存測試（只驗收，不調整）'}；"
             f"{len(report['pairs'])} 份、音訊 {hours*60:.1f} 分鐘", '',
             '| 條件 | 教會專名找到 | 多出 | 人名地名找到 | 多出 | 專名正確（對齊） | CER | 修好／改壞字數 | 改動段數 |',
             '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for name, t in totals.items():
        fixed = '—' if name == 'base' else f"{t['chars_fixed_vs_base']}／{t['chars_broken_vs_base']}"
        lines.append(f"| {label(name)} | {t['terms_bag_found']}/{t['term_occurrences']} | {t['terms_bag_extra']} | "
                     f"{t['names_bag_found']}/{t['name_occurrences']} | {t['names_bag_extra']} | {t['terms_correct']}/{t['term_occurrences']} | "
                     f"{t['edit_distance']/t['reference_chars']:.2%} | {fixed} | {'—' if name == 'base' else t['changed_segments_vs_base']} |")
    lines += ['', '| 條件 | 呼叫次數／段數 | neurons／小時 | 延遲 中位數／P95 | 提議／採用修改 | 安全檢查擋下 | 其他 |',
              '| --- | --- | --- | --- | --- | --- | --- |']
    for name, s in stats.items():
        if s['kind'] == 'llm_unguarded':
            continue
        per_hour = round(s['neurons']/hours) if hours else None
        latency = f"{pick(s['latency'], 0.5)}／{pick(s['latency'], 0.95)} 秒" if any(v is not None for v in s['latency']) else '沿用先前結果'
        if s['kind'] == 'whisper':
            calls = f"{s['segments']}/{s['segments']}"
            other = f"提示被照抄 {s['echo']} 段" if name == 'prompt' else ''
            lines.append(f"| {label(name)} | {calls} | {per_hour}（Whisper） | {latency} | — | — | {other} |")
        else:
            rejected = '、'.join(f'{k} {v}' for k, v in sorted(s['rejected'].items())) or '0'
            other = f"JSON 錯誤 {s['parse_errors']}" + (f"；token 為估計 {s['estimated_tokens']} 次" if s['estimated_tokens'] else '')
            lines.append(f"| {label(name)} | {s['calls']}/{s['segments']} | {per_hour}（另加 Whisper） | {latency} | "
                         f"{s['proposed']}／{s['accepted']} | {rejected} | {other} |")
    lines += ['', '門檻（對照網站基準；開發集的專名增加依參考專名數等比例換算 +30/920）：']
    occurrences = base['term_occurrences'] or 1
    for name, t in totals.items():
        if name == 'base' or name.endswith('|unguarded'):
            continue
        s = stats[name]
        extra = t['terms_bag_extra'] - base['terms_bag_extra']
        allow_extra = max(GATES['extra_increase_min'], GATES['extra_increase_ratio']*occurrences)
        if development:   # not verbatim: alignment-free count, the agreed +30/920 scaled to this sample
            gain = t['terms_bag_found'] - base['terms_bag_found']
            need_gain = max(1, round(GATES['found_gain_ratio']*occurrences))
        else:             # sealed test: aligned church terms must increase
            gain, need_gain = t['terms_correct'] - base['terms_correct'], 1
        checks = [(f'專名 {gain:+d}（需 ≥{need_gain}）', gain >= need_gain),
                  (f'多出 {extra:+d}（≤{allow_extra:.0f}）', extra <= allow_extra),
                  (f"改壞 {t['chars_broken_vs_base']} ≤ 修好 {t['chars_fixed_vs_base']}/5", t['chars_broken_vs_base'] <= GATES['broken_per_fixed']*t['chars_fixed_vs_base'])]
        if s['kind'] == 'llm':
            per_hour = s['neurons']/hours if hours else 0
            p95 = pick(s['latency'], 0.95) or 0
            checks += [(f'語言模型 {per_hour:.0f} neurons／小時（≤1000）', per_hour <= GATES['llm_neurons_per_hour']),
                       (f'延遲 P95 {p95} 秒（≤3）', p95 <= GATES['llm_latency_p95'])]
        if not development:
            checks.append((f"CER {t['edit_distance']/t['reference_chars']:.2%}（基準 {base['edit_distance']/base['reference_chars']:.2%}，可差 ≤0.1 點）",
                           t['edit_distance']/t['reference_chars'] <= base['edit_distance']/base['reference_chars'] + 0.001))
        verdict = '通過' if all(ok for _, ok in checks) else '未通過'
        lines.append(f"- {label(name)}：**{verdict}**；" + '；'.join(f"{text}{'' if ok else ' ✗'}" for text, ok in checks))
    return lines


def review_lines(run, metas):
    """Development only: every accepted / rejected model edit, for reading (never for the sealed test)."""
    lines = ['', '語言模型修改明細（開發集；請人工看是否合理）', '', '| 份 | 條件 | 段 | 原字幕 | 修改 | 結果 |', '| --- | --- | --- | --- | --- | --- |']
    for pair in metas:
        for name, c in condition_texts(run, pair).items():
            if c['kind'] != 'llm':
                continue
            for r in c['records']:
                for edit in r.get('accepted', []):
                    lines.append(f"| {pair} | {label(name)} | {r['i']} | {r['site']} | {edit['from']}→{edit['to']} | 採用 |")
                for edit in r.get('rejected', []):
                    lines.append(f"| {pair} | {label(name)} | {r['i']} | {r['site']} | {edit['from']}→{edit['to']} | 擋下（{edit['reason']}） |")
    return lines


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--data', required=True); p.add_argument('--output', required=True); p.add_argument('--only')
    p.add_argument('--window-start', type=float, default=0); p.add_argument('--window-seconds', type=float, default=0)
    s = sub.add_parser('score')
    s.add_argument('--data', required=True); s.add_argument('--prepared', required=True); s.add_argument('--run', required=True)
    s.add_argument('--development', action='store_true', help='Life-Study development set (not verbatim; shows edit details)')
    args = parser.parse_args()
    prepare(args) if args.command == 'prepare' else score(args)


if __name__ == '__main__':
    main()
