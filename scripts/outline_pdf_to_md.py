#!/usr/bin/env python3
"""Convert a message-outline PDF (綱要) to Markdown, one section per message, plus a quality report.

Why: the host pastes one message's outline before a meeting (spec-large-meeting.md M1). Outline PDFs usually
have a text layer, so reading that layer is exact; OCR is only a fallback for scanned pages and makes errors on
church terms. Markdown keeps the hierarchy (篇題、讀經、壹／一／1／a 要點) that the outline parser uses, is easy to
check by eye, and can be pasted as is.

Usage (needs PyMuPDF: pip install pymupdf==1.26.5):
  python scripts/outline_pdf_to_md.py outline.pdf --output out/
Writes out/<name>.md, out/<name>/NN.md (one file per message) and out/<name>.report.json.
Outlines are copyrighted: keep the output in private storage (Drive), not in Git.
"""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

# Recovery Version book abbreviations (longest first when matching). Single-chapter books take a verse directly.
BOOK_ABBREVIATIONS = ['創', '出', '利', '民', '申', '書', '士', '得', '撒上', '撒下', '王上', '王下', '代上', '代下',
                      '拉', '尼', '斯', '伯', '詩', '箴', '傳', '歌', '賽', '耶', '哀', '結', '但', '何', '珥', '摩',
                      '俄', '拿', '彌', '鴻', '哈', '番', '該', '亞', '瑪', '太', '可', '路', '約', '徒', '羅', '林前',
                      '林後', '加', '弗', '腓', '西', '帖前', '帖後', '提前', '提後', '多', '門', '來', '雅', '彼前',
                      '彼後', '約壹', '約貳', '約參', '猶', '啟']
SINGLE_CHAPTER = {'俄', '門', '約貳', '約參', '猶'}
CN_NUM = '一二三四五六七八九十百○〇'
_books = '|'.join(sorted(BOOK_ABBREVIATIONS, key=len, reverse=True))
_single = '|'.join(sorted(SINGLE_CHAPTER, key=len, reverse=True))
_verse = r'\d+(?:[上下])?(?:[～~\-－–]\d+(?:[上下])?)?'
# 弗一23、約十四6～7、林前十二12、詩二三1、門16；後面可接「，三17」「，18」之類的延續。
REF_RE = re.compile(rf'(?:(?:{_books})[{CN_NUM}]+{_verse}|(?:{_single}){_verse})'
                    rf'(?:[，,、](?:[{CN_NUM}]+)?{_verse})*')

LEVEL_MARKERS = [
    (1, re.compile(r'^([壹貳參叁肆伍陸柒捌玖拾]+)[\s、.．]')),
    (2, re.compile(r'^([一二三四五六七八九十]+)[\s、.．]')),
    (3, re.compile(r'^(\d{1,2})[\s、.．]')),
    (4, re.compile(r'^([a-z])[\s、.．)]')),
    (5, re.compile(r'^([（(]\d{1,2}[)）])')),
    (6, re.compile(r'^([（(][a-z][)）])')),
]
MESSAGE_RE = re.compile(r'^第\s*([一二三四五六七八九十百\d]+)\s*篇\s*(.*)$')
SCRIPTURE_RE = re.compile(r'^(讀經|读经)\s*[:：]\s*(.*)$')
TOC_LEADER_RE = re.compile(r'(?:[.．…·‧・]{3,}|\s{2,})\s*\d+\s*$')
PAGE_NUMBER_RE = re.compile(r'^[\s\-—–·]*(?:第\s*)?(?:\d+|[ivxlc]+|[IVXLC]+)\s*(?:頁)?[\s\-—–·]*$')
SENTENCE_END = '。！？；」』）)'


def normalize_char(ch):
    """Map look-alike code points that PDF fonts often emit to the normal character; returns (char, changed)."""
    code = ord(ch)
    if 0xFF10 <= code <= 0xFF19 or 0xFF21 <= code <= 0xFF3A or 0xFF41 <= code <= 0xFF5A:  # 全形數字與字母
        return chr(code - 0xFEE0), True
    if 0x2E80 <= code <= 0x2FDF or 0xF900 <= code <= 0xFAFF or 0x2F800 <= code <= 0x2FA1F:  # 部首字、相容漢字
        mapped = unicodedata.normalize('NFKC', ch)
        return mapped, mapped != ch
    if ch == '　':
        return ' ', True
    if ch in '∼〜˜':  # ∼ 〜 ˜：有些字型把經節範圍的「～」抽成這些字
        return '～', True
    return ch, False


def normalize_text(text, stats):
    out = []
    for ch in text:
        if 0xE000 <= ord(ch) <= 0xF8FF:
            stats['private_use_chars'] += 1  # 字型私用區：抽不出真正的字，需人工核對
        mapped, changed = normalize_char(ch)
        stats['normalized_chars'] += changed
        out.append(mapped)
    return re.sub(r'[ \t]+', ' ', ''.join(out)).strip()


def extract_pages(pdf_path):
    """Return [{'height', 'lines': [{'text', 'y', 'size'}]}] from the PDF text layer."""
    import pymupdf
    pages = []
    with pymupdf.open(pdf_path) as document:
        for page in document:
            lines = []
            for block in page.get_text('dict', sort=True)['blocks']:
                for line in block.get('lines', []):
                    spans = [s for s in line['spans'] if s['text'].strip()]
                    if not spans:
                        continue
                    text = ''.join(s['text'] for s in line['spans'])
                    size = max(s['size'] for s in spans)
                    lines.append({'text': text, 'y': line['bbox'][1], 'x': line['bbox'][0], 'size': round(size, 1)})
            pages.append({'height': page.rect.height, 'width': page.rect.width, 'lines': lines})
    return pages


def _shape(text):
    return re.sub(r'\d+', '#', text.replace(' ', ''))


def remove_running_lines(pages, stats):
    """Drop page numbers and headers/footers that repeat near the top or bottom of many pages."""
    edge = lambda page, line: line['y'] < page['height'] * 0.08 or line['y'] > page['height'] * 0.92
    counts = Counter()
    for page in pages:
        counts.update({_shape(line['text']) for line in page['lines'] if edge(page, line)})
    repeated = {shape for shape, n in counts.items() if len(pages) >= 3 and n >= max(3, len(pages) * 0.3)}
    for page in pages:
        kept = []
        for line in page['lines']:
            if edge(page, line) and (_shape(line['text']) in repeated or PAGE_NUMBER_RE.match(line['text'])):
                stats['running_lines_removed'] += 1
                continue
            kept.append(line)
        page['lines'] = kept


def line_level(text):
    for level, pattern in LEVEL_MARKERS:
        if pattern.match(text):
            return level
    return 0


def build_messages(pages, stats):
    """Group lines into messages → items. Wrapped lines are joined to the item they continue."""
    sizes = Counter(line['size'] for page in pages for line in page['lines'])
    body_size = sizes.most_common(1)[0][0] if sizes else 0
    front = {'number': None, 'title': '', 'scripture': [], 'items': []}
    messages = [front]
    current = None  # the item (dict) that a wrapped line continues

    def message():
        return messages[-1]

    for page_number, page in enumerate(pages, 1):
        for line in page['lines']:
            text = normalize_text(line['text'], stats)
            if not text:
                continue
            match = MESSAGE_RE.match(text)
            if match and not TOC_LEADER_RE.search(text):
                messages.append({'number': match.group(1), 'title': match.group(2).strip(), 'scripture': [],
                                 'items': [], 'page': page_number})
                current = None
                continue
            if match:
                stats['toc_lines_skipped'] += 1
                continue
            scripture = SCRIPTURE_RE.match(text)
            if scripture:
                message()['scripture'].append(scripture.group(2))
                current = {'kind': 'scripture'}
                continue
            level = line_level(text)
            if body_size:
                heading = line['size'] >= body_size * 1.15
            else:  # OCR 文字沒有字級：「第X篇」後第一行沒有標號的字就是篇題
                heading = message()['number'] is not None and not message()['title']
            if level:
                current = {'kind': 'item', 'level': level, 'text': text}
                message()['items'].append(current)
            elif heading and not message()['items'] and not message()['scripture']:
                message()['title'] = (message()['title'] + text) if message()['title'] else text
                current = None
            elif current and current['kind'] == 'scripture' and REF_RE.match(text):
                message()['scripture'][-1] += text
            elif current and current['kind'] == 'item':
                current['text'] += text  # 中文換行接續，不加空白
            else:
                current = {'kind': 'item', 'level': 0, 'text': text}
                message()['items'].append(current)
    if not front['items'] and not front['title']:
        messages.pop(0)
    return messages, body_size


def message_markdown(message):
    lines = []
    if message['number'] is None:
        lines.append('## （篇題前的內容）')
    else:
        lines.append(f"## 第{message['number']}篇　{message['title']}".rstrip())
    lines.append('')
    for scripture in message['scripture']:
        lines += [f'讀經：{scripture}', '']
    for item in message['items']:
        indent = '  ' * max(item['level'] - 1, 0)
        lines.append(f"{indent}- {item['text']}" if item['level'] else item['text'])
    return '\n'.join(lines).rstrip() + '\n'


def message_summary(message):
    text = ' '.join(message['scripture'] + [item['text'] for item in message['items']])
    return {
        'number': message['number'], 'title': message['title'], 'page': message.get('page'),
        'scripture_lines': len(message['scripture']), 'points': sum(1 for i in message['items'] if i['level']),
        'unmarked_lines': sum(1 for i in message['items'] if not i['level']),
        'verse_references': len(REF_RE.findall(text)), 'chars': len(text),
    }


def convert(pdf_path, output_dir, pages=None, checks=None):
    """pages: precomputed lines (e.g. from OCR) instead of the PDF text layer; checks(messages) → dict merged into the report."""
    pdf_path, output_dir = Path(pdf_path), Path(output_dir)
    stats = Counter(private_use_chars=0, normalized_chars=0, running_lines_removed=0, toc_lines_skipped=0)
    pages = extract_pages(pdf_path) if pages is None else pages
    empty = [n for n, page in enumerate(pages, 1) if sum(len(l['text'].strip()) for l in page['lines']) < 20]
    remove_running_lines(pages, stats)
    messages, body_size = build_messages(pages, stats)
    name = pdf_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir/name).mkdir(exist_ok=True)
    parts = [f'# {name}\n']
    for index, message in enumerate(messages):
        markdown = message_markdown(message)
        parts.append(markdown)
        (output_dir/name/f'{index:02d}.md').write_text(markdown, encoding='utf-8')
    (output_dir/f'{name}.md').write_text('\n'.join(parts), encoding='utf-8')
    warnings = []
    if empty:
        warnings.append(f'{len(empty)} 頁幾乎沒有文字層（掃描或圖片頁，需要 OCR 或人工）：{empty[:20]}')
    if stats['private_use_chars']:
        warnings.append(f"{stats['private_use_chars']} 個字型私用區字元：抽出的字不正確，需人工核對")
    if not any(m['number'] for m in messages):
        warnings.append('找不到「第X篇」：篇的分界要人工確認')
    for message in messages:
        if message['number'] and not message['scripture']:
            warnings.append(f"第{message['number']}篇沒有「讀經：」行")
    report = {
        'source': pdf_path.name, 'pages': len(pages), 'pages_without_text': empty, 'body_font_size': body_size,
        **dict(stats), 'messages': [message_summary(m) for m in messages], 'warnings': warnings,
    }
    if checks:
        extra = checks(messages)
        report['warnings'] += extra.pop('warnings', [])
        report.update(extra)
    (output_dir/f'{name}.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                                                 encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('pdf', nargs='+', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    for pdf in args.pdf:
        report = convert(pdf, args.output)
        print(json.dumps({k: report[k] for k in ('source', 'pages', 'warnings')}, ensure_ascii=False))
        for message in report['messages']:
            print(f"  第{message['number']}篇 {message['title'][:30]}：讀經 {message['scripture_lines']} 行、"
                  f"要點 {message['points']}、經節 {message['verse_references']}、未標號行 {message['unmarked_lines']}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
