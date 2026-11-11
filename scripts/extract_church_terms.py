#!/usr/bin/env python3
"""Discover church vocabulary candidates from collected web text; output is pending human review.

Unsupervised Chinese term discovery (frequency, internal cohesion and boundary entropy) over
text_only documents from crawl_church_sources.py. Nothing here approves spelling variants,
automatic replacements, ASR hotwords or training use; every candidate stays pending_review.
"""
import argparse
import hashlib
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:  # General-Chinese frequency is optional context, never a filter on its own.
    import logging
    import jieba
    jieba.setLogLevel(logging.WARNING)
    import wordfreq
except ImportError:
    wordfreq = None

NUMERAL = re.compile(r'[〇零一二三四五六七八九十百千萬兩]+')
CJK = re.compile(r'[㐀-䶿一-鿿豈-﫿]+')
# Single characters that rarely start/end a domain term; cheap boundary cleanup only.
EDGE_STOP = set('的了是在我們你他她它祂這那就也都而與和及或但並把被給對從向於以為之其所著過來去上下中裏里有沒不要會能可一個些麼什')
# Mixed function words that look cohesive but are not vocabulary.
PHRASE_STOP = {'我們', '他們', '你們', '祂們', '這樣', '那樣', '因為', '所以', '如果', '就是', '不是', '還是',
               '這個', '那個', '甚麼', '什麼', '已經', '可以', '應當', '必須', '乃是', '這裏', '那裏', '這些',
               '那些', '一切', '回首頁', '自己', '現在', '然後', '因此', '雖然', '但是', '並且', '所有', '許多', '一樣',
               '一種', '一次', '之後', '以後', '以前', '之前', '的時候', '告訴', '看見', '說話', '知道'}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load_documents(roots, exclude=()):
    documents = []; exclude = set(exclude)
    for root in map(Path, roots):
        manifest = root/'manifests/pages.jsonl'
        for line in manifest.read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # Leave-out: pages paired with evaluation audio must not shape the term list.
            if not row.get('text_path') or row['source_url'] in exclude:
                continue
            path = (root/row['text_path']).resolve(strict=True)
            if not path.is_relative_to(root.resolve()):
                raise ValueError('Text path escapes collection root')
            data = path.read_bytes()
            if sha256(data) != row['text_sha256']:
                raise ValueError(f'Text hash mismatch: {row["source_url"]}')
            # NFC only for counting; the original text file is never rewritten.
            text = unicodedata.normalize('NFC', data.decode('utf-8'))
            kind = 'bible' if '/recoveryversion/' in row['source_url'] else 'life_study' if '/life-study/' in row['source_url'] else 'other'
            documents.append(dict(id=row['id'], source_url=row['source_url'], title=row.get('title'),
                                  kind=kind, text_sha256=row['text_sha256'], runs=CJK.findall(text)))
    if not documents:
        raise ValueError('No text documents in collection manifests')
    return documents


def count_ngrams(documents, max_n):
    counts = Counter(); doc_freq = Counter(); kind_freq = defaultdict(Counter)
    for doc in documents:
        seen = set()
        for run in doc['runs']:
            # Run edges are added as distinct boundary contexts in neighbours().
            for n in range(1, max_n+2):
                for i in range(len(run)-n+1):
                    gram = run[i:i+n]; counts[gram] += 1
                    if 2 <= n <= max_n:
                        seen.add(gram)
        for gram in seen:
            doc_freq[gram] += 1; kind_freq[gram][doc['kind']] += 1
    return counts, doc_freq, kind_freq


def entropy(counter):
    total = sum(counter.values())
    return -sum(c/total*math.log(c/total) for c in counter.values()) if total else 0.0


def neighbours(counts, documents, candidates, max_n):
    left = defaultdict(Counter); right = defaultdict(Counter)
    for gram, count in counts.items():
        if len(gram) < 3 or len(gram) > max_n+1:
            continue
        if gram[1:] in candidates:
            left[gram[1:]][gram[0]] += count
        if gram[:-1] in candidates:
            right[gram[:-1]][gram[-1]] += count
    # Run edges (punctuation, line starts) are distinct boundaries, not one repeated neighbour.
    for doc in documents:
        for run in doc['runs']:
            for n in range(2, min(max_n, len(run))+1):
                head, tail = run[:n], run[-n:]
                if head in candidates:
                    left[head][f'<edge{len(left[head])}>'] += 1
                if tail in candidates:
                    right[tail][f'<edge{len(right[tail])}>'] += 1
    return left, right


def cohesion(gram, counts, total):
    p = counts[gram]/total
    return min(math.log(p/((counts[gram[:i]]/total)*(counts[gram[i:]]/total))) for i in range(1, len(gram)))


# Recovery-Version house-style characters versus the forms general ASR usually writes.
HOUSE_STYLE = {'豫': '預', '衞': '衛', '輭': '軟', '裏': '裡', '祂': '他', '阿': '啊'}


def variant_report(ranked, documents):
    text = '\n'.join(''.join(d['runs']) for d in documents)
    rows = []
    for row in ranked:
        common = ''.join(HOUSE_STYLE.get(c, c) if c != '阿' or i == len(row['term'])-1 else c
                         for i, c in enumerate(row['term']))
        if common != row['term']:
            rows.append(dict(term=row['term'], common_form=common, term_frequency=row['frequency'],
                             common_form_frequency=text.count(common), review_status='pending_review',
                             note='House-style orthography; output policy is a user decision, not a recognition error.'))
    return rows


def known_terms(approved_path, glossary_path):
    known = {}
    if approved_path and Path(approved_path).exists():
        for group in json.loads(Path(approved_path).read_text(encoding='utf-8'))['targets']:
            for term in group['terms']:
                known.setdefault(term, set()).add('approved_target:'+group['category'])
    if glossary_path and Path(glossary_path).exists():
        for target in re.findall(r"\['[^']*',\s*'([^']+)'\]", Path(glossary_path).read_text(encoding='utf-8')):
            known.setdefault(target, set()).add('default_glossary_target')
    return known


def extract(documents, min_freq=8, min_docs=2, max_n=6, min_cohesion=2.0, min_entropy=1.0, limit=500,
            known=None):
    known = known or {}
    counts, doc_freq, kind_freq = count_ngrams(documents, max_n)
    total = sum(c for g, c in counts.items() if len(g) == 1)
    pool = {g for g, c in counts.items() if 2 <= len(g) <= max_n and c >= min_freq and doc_freq[g] >= min_docs
            and g[0] not in EDGE_STOP and g[-1] not in EDGE_STOP and g not in PHRASE_STOP
            # Verse/chapter numerals belong to the reference scorer, not the term list.
            and not NUMERAL.fullmatch(g)}
    left, right = neighbours(counts, documents, pool, max_n)
    scored = {}
    for gram in pool:
        coh = cohesion(gram, counts, total)
        le, re_ = entropy(left[gram]), entropy(right[gram])
        if coh < min_cohesion or min(le, re_) < min_entropy:
            continue
        scored[gram] = dict(term=gram, frequency=counts[gram], document_frequency=doc_freq[gram],
                            kind_document_frequency=dict(sorted(kind_freq[gram].items())),
                            cohesion=round(coh, 3), left_entropy=round(le, 3), right_entropy=round(re_, 3))
    # Drop fragments that almost always occur inside one longer accepted candidate.
    for gram in list(scored):
        for longer in scored:
            if len(longer) > len(gram) and gram in longer and counts[longer] >= 0.85*counts[gram]:
                scored.pop(gram, None); break
    for row in scored.values():
        base = math.log(row['frequency'])*min(row['left_entropy'], row['right_entropy'])*math.log1p(row['document_frequency'])
        row['general_zipf'] = general = wordfreq.zipf_frequency(row['term'], 'zh') if wordfreq else None
        if general is None:
            row['domain_specificity'] = None; row['score'] = round(base, 3)
        else:
            # Both on a log10 per-billion scale; characters stand in for words in the domain text.
            domain = math.log10(row['frequency']/total*1e9)
            row['domain_specificity'] = round(domain-general, 3)
            row['score'] = round(base*min(4.0, max(0.5, domain-general))/2, 3)
        row['general_common'] = bool(general is not None and general >= 5.0 and domain-general < 1.5)
        row['known_as'] = sorted(known.get(row['term'], []))
        row.update(review_status='pending_review', category=None, automatic_replacement='not_allowed',
                   hotword_status='not_approved', training_ready=False)
    ranked = sorted(scored.values(), key=lambda r: (-r['score'], r['term']))[:limit]
    coverage = {term: dict(frequency=counts.get(term, 0), document_frequency=doc_freq.get(term, 0),
                           sources=sorted(src)) for term, src in sorted(known.items())}
    return ranked, coverage, dict(characters=total, documents=len(documents),
                                  general_frequency='wordfreq zh (zipf)' if wordfreq else 'unavailable',
                                  documents_by_kind=dict(Counter(d['kind'] for d in documents)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--collection', action='append', required=True, help='crawl_church_sources output root')
    parser.add_argument('--output', required=True, help='New private directory, e.g. data/church-vocabulary/<run>')
    parser.add_argument('--approved', default='evaluation/glossary/approved-targets.json')
    parser.add_argument('--glossary', default='glossary.js')
    parser.add_argument('--min-freq', type=int, default=8)
    parser.add_argument('--min-docs', type=int, default=2)
    parser.add_argument('--limit', type=int, default=500)
    parser.add_argument('--exclude-source', action='append', default=[], help='Leave out a page URL (e.g. paired with evaluation audio)')
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists() and any(output.iterdir()):
        raise SystemExit('Output directory is not empty; use a new run directory')
    output.mkdir(parents=True, exist_ok=True)
    documents = load_documents(args.collection, args.exclude_source)
    ranked, coverage, stats = extract(documents, args.min_freq, args.min_docs, limit=args.limit,
                                      known=known_terms(args.approved, args.glossary))
    report = dict(created_at=datetime.now(timezone.utc).isoformat(), tool='extract_church_terms.py',
                  tool_sha256=sha256(Path(__file__).read_bytes()),
                  parameters=dict(min_freq=args.min_freq, min_docs=args.min_docs, max_n=6, limit=args.limit),
                  excluded_sources=sorted(args.exclude_source),
                  inputs=[dict(source_url=d['source_url'], text_sha256=d['text_sha256'], kind=d['kind']) for d in documents],
                  stats=stats, candidate_count=len(ranked), rights_status='pending',
                  use='vocabulary_candidate_review_only', training_ready=False,
                  known_term_coverage=coverage)
    (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    (output/'candidates.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in ranked), encoding='utf-8')
    variants = variant_report(ranked, documents)
    (output/'orthographic-variants.json').write_text(json.dumps(variants, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    with (output/'review.csv').open('w', encoding='utf-8-sig') as sheet:
        sheet.write('term,frequency,document_frequency,bible_docs,life_study_docs,general_zipf,general_common,score,known_as,decision,category,note\n')
        for r in ranked:
            k = r['kind_document_frequency']
            sheet.write(f"{r['term']},{r['frequency']},{r['document_frequency']},{k.get('bible', 0)},"
                        f"{k.get('life_study', 0)},{r['general_zipf']},{r['general_common']},{r['score']},{'|'.join(r['known_as'])},,,\n")
    print(json.dumps(dict(output=str(output), candidates=len(ranked), **stats), ensure_ascii=False))


if __name__ == '__main__':
    main()
