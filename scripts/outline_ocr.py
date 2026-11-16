#!/usr/bin/env python3
"""OCR a scanned outline PDF (no text layer) with Google Drive's built-in OCR, then write Markdown like
outline_pdf_to_md.py, plus automatic OCR checks.

Why Google Drive OCR: free with the user's own Google account, strong on printed Traditional Chinese, nothing to
install. Each page is rendered to a JPEG (< 2 MB, Drive's OCR limit), uploaded as a Google Doc with OCR, exported
as text, and the temporary Doc is deleted. Page text is cached, so a rerun only OCRs missing pages.

Checks without a hand-typed reference:
- verse references whose book chapter does not exist (OCR misread digits/numerals);
- words one character away from a known church term or Bible name (likely misread characters);
- pages whose OCR text is nearly empty.

Colab: notebooks/outline_ocr.ipynb. Outlines are copyrighted: output stays in Drive, never in Git.
"""
import io
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import outline_pdf_to_md as outline  # noqa: E402

ROOT = Path(__file__).parents[1]
CHAPTERS = dict(zip(outline.BOOK_ABBREVIATIONS, [
    50, 40, 27, 36, 34, 24, 21, 4, 31, 24, 22, 25, 29, 36, 10, 13, 10, 42, 150, 31, 12, 8, 66, 52, 5, 48, 12, 14,
    3, 9, 1, 4, 7, 3, 3, 3, 2, 14, 4,  # 舊約 39 卷
    28, 16, 24, 21, 28, 16, 16, 13, 6, 6, 4, 4, 5, 3, 6, 4, 3, 1, 13, 5, 5, 3, 5, 1, 1, 1, 22]))  # 新約 27 卷
DIGITS = {c: i for i, c in enumerate('○一二三四五六七八九')} | {'〇': 0}
_books = '|'.join(sorted(outline.BOOK_ABBREVIATIONS, key=len, reverse=True))
PIECE_RE = re.compile(rf'(?:({_books}))?([{outline.CN_NUM}]+)?(\d+)')
MAX_IMAGE_BYTES = 1_900_000


def chinese_number(text):
    """一二三 style chapter numbers: 二三 = 23, 十四 = 14, 二十 = 20, 一百一十九 = 119, 一一九 = 119."""
    if not any(c in text for c in '十百'):
        value = 0
        for c in text:
            value = value * 10 + DIGITS[c]
        return value
    value, current = 0, 0
    for c in text:
        if c == '百':
            value += (current or 1) * 100
            current = 0
        elif c == '十':
            value += (current or 1) * 10
            current = 0
        else:
            current = current * 10 + DIGITS[c]
    return value + current


def parse_references(text):
    """Yield (matched text, book, chapter, verse) for each verse in each reference run."""
    for match in outline.REF_RE.finditer(text):
        book = chapter = None
        for piece in re.split(r'[，,、]', match.group(0)):
            parsed = PIECE_RE.match(piece)
            if not parsed:
                continue
            book = parsed.group(1) or book
            if parsed.group(2):
                chapter = chinese_number(parsed.group(2))
            elif book in outline.SINGLE_CHAPTER:
                chapter = 1
            if book and chapter:
                yield piece, book, chapter, int(parsed.group(3))


def known_terms():
    source = (ROOT/'public/church-terms.js').read_text(encoding='utf-8')
    names = json.loads(re.search(r'BIBLE_NAMES = (\[.*\]);', (ROOT/'public/bible-names.js').read_text(
        encoding='utf-8')).group(1))
    return sorted(set(re.findall(r"'([^']+)'", source)) - {'./bible-names.js'} | set(names))


def near_term_suspects(text, terms):
    """Substrings that differ from a known term (≥3 chars) in exactly one character and are not terms themselves."""
    term_set = set(terms)
    by_length = {}
    for term in terms:
        if len(term) >= 3:
            by_length.setdefault(len(term), []).append(term)
    found = {}
    for length, group in by_length.items():
        for start in range(len(text) - length + 1):
            piece = text[start:start + length]
            if piece in term_set or not all('一' <= c <= '鿿' for c in piece):
                continue
            for term in group:
                if sum(a != b for a, b in zip(piece, term)) == 1:
                    found.setdefault((piece, term), text[max(0, start - 6):start + length + 6])
                    break
    return [{'ocr': piece, 'term': term, 'context': context} for (piece, term), context in found.items()]


def check_messages(messages, terms=None):
    terms = known_terms() if terms is None else terms
    bad_refs, suspects = [], []
    for message in messages:
        label = f"第{message['number']}篇" if message['number'] else '篇題前'
        texts = message['scripture'] + [item['text'] for item in message['items']]
        for text in texts:
            for piece, book, chapter, verse in parse_references(text):
                if chapter > CHAPTERS[book] or chapter < 1 or not 1 <= verse <= 176:
                    bad_refs.append({'message': label, 'reference': piece, 'book': book, 'chapter': chapter,
                                     'verse': verse})
            suspects += [{'message': label, **s} for s in near_term_suspects(text, terms)]
    warnings = []
    if bad_refs:
        warnings.append(f'{len(bad_refs)} 個經節的章數不存在（多半是 OCR 認錯數字），見 invalid_references')
    if suspects:
        warnings.append(f'{len(suspects)} 處和教會專名／聖經人名只差一個字，可能是 OCR 認錯，見 term_suspects')
    return {'invalid_references': bad_refs, 'term_suspects': suspects, 'warnings': warnings}


def render_pages(pdf_path, dpi=300):
    """Yield (page number, JPEG bytes) small enough for Drive OCR."""
    import pymupdf
    with pymupdf.open(pdf_path) as document:
        for number, page in enumerate(document, 1):
            for scale_dpi, quality in ((dpi, 90), (dpi, 75), (int(dpi * 0.8), 75), (int(dpi * 0.6), 70)):
                pixmap = page.get_pixmap(dpi=scale_dpi, colorspace=pymupdf.csGRAY)
                data = pixmap.tobytes('jpeg', jpg_quality=quality)
                if len(data) <= MAX_IMAGE_BYTES:
                    break
            yield number, data


def google_ocr(service, image_bytes, language='zh-TW', retries=3):
    """Upload as a Google Doc with OCR, export plain text, delete the temporary Doc."""
    from googleapiclient.http import MediaIoBaseUpload
    for attempt in range(retries):
        try:
            media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg', resumable=False)
            created = service.files().create(
                body={'name': 'outline-ocr-temporary', 'mimeType': 'application/vnd.google-apps.document'},
                media_body=media, ocrLanguage=language, fields='id').execute()
            try:
                data = service.files().export(fileId=created['id'], mimeType='text/plain').execute()
            finally:
                service.files().delete(fileId=created['id']).execute()
            return data.decode('utf-8-sig') if isinstance(data, bytes) else data
        except Exception:  # Drive 偶爾回 429/5xx：稍等再試
            if attempt == retries - 1:
                raise
            time.sleep(5 * (attempt + 1))


def ocr_text_to_page(text):
    """OCR text → the page structure outline_pdf_to_md expects (line order as y; no font size)."""
    text = text.lstrip('﻿').replace('\r', '')
    lines = [line for line in text.split('\n') if line.strip() and not set(line.strip()) <= {'_'}]
    # 頁高 100：第一行 y=0、最後一行 y=100，一定落在頁首／頁尾區（上下 8%），可被當成重複的頁首頁尾刪除
    step = 100 / (len(lines) - 1) if len(lines) > 1 else 0
    return {'height': 100, 'width': 1, 'lines': [
        {'text': line, 'y': index * step, 'x': 0, 'size': 0} for index, line in enumerate(lines)]}


def run(pdf_path, cache_dir, output_dir, service, language='zh-TW', log=print):
    pdf_path, cache_dir = Path(pdf_path), Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    pages = []
    for number, image in render_pages(pdf_path):
        cached = cache_dir/f'{number:03d}.txt'
        if not cached.exists():
            cached.write_text(google_ocr(service, image, language), encoding='utf-8')
            log(f'第 {number} 頁 OCR 完成（{len(image) // 1000} KB）')
        pages.append(ocr_text_to_page(cached.read_text(encoding='utf-8')))
    report = outline.convert(pdf_path, output_dir, pages=pages, checks=check_messages)
    report['ocr'] = {'engine': 'google-drive', 'language': language, 'cache': str(cache_dir)}
    (Path(output_dir)/f'{pdf_path.stem}.report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report
