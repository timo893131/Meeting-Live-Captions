#!/usr/bin/env python3
"""OCR a scanned outline PDF (no text layer) with Google Drive's built-in OCR, then write Markdown like
outline_pdf_to_md.py, plus automatic OCR checks.

Why Google Drive OCR: free with the user's own Google account, strong on printed Traditional Chinese, nothing to
install. Each page is rendered to a JPEG (< 2 MB, Drive's OCR limit), uploaded as a Google Doc with OCR, exported
as text, and the temporary Doc is deleted. Page text is cached, so a rerun only OCRs missing pages.

Checks without a hand-typed reference:
- verse references whose book chapter does not exist (OCR misread digits/numerals);
- outlines printed with their verses (綱要附經文): the OCR text of each quoted verse against the Recovery
  Version text (from the TWGBR archive on Drive) gives a real character error rate;
- pages whose OCR text is nearly empty.
(A "one character away from a church term" check was tried on the sample and dropped: 254 flags, nearly all
correct text such as 亞伯拉罕／亞伯蘭.)

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
_books = '|'.join(sorted(outline.BOOK_ABBREVIATIONS, key=len, reverse=True))
PIECE_RE = re.compile(rf'(?:({_books}))?([{outline.CN_NUM}]+)?(\d+)')
MAX_IMAGE_BYTES = 1_900_000
QUOTE_KEY_RE = re.compile(rf'^({_books})(\d+):(\d+)(?:[～~\-－–](\d+))?$')


chinese_number = outline.chinese_number


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


def bible_books():
    source = (ROOT/'public/church-terms.js').read_text(encoding='utf-8')
    return re.findall(r"'([^']+)'", re.search(r'BIBLE_BOOKS = \[(.*?)\]', source, re.S).group(1))


def load_recovery_version(text_dir):
    """{(abbreviation, chapter, verse): text} from <archive>/recovery-version/text/NN-書名.txt (TWGBR download)."""
    verses = {}
    for number, (abbreviation, book) in enumerate(zip(outline.BOOK_ABBREVIATIONS, bible_books()), 1):
        path = Path(text_dir)/f'{number:02d}-{book}.txt'
        if not path.exists():
            continue
        chapter = 1
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            heading = re.match(r'^\S+ 第 (\d+) 章$', line)
            if heading:
                chapter = int(heading.group(1))
                continue
            verse = re.match(r'^(\d+)\s+(.+)$', line)
            if verse:
                verses.setdefault((abbreviation, chapter, int(verse.group(1))), verse.group(2))
    return verses


def hanzi(text):
    return ''.join(c for c in text if '\u4e00' <= c <= '\u9fff' or '\u3400' <= c <= '\u4dbf')


def fitting_distance(piece, reference):
    """Edits to turn piece into some substring of reference (piece may be a cut-off part of a verse)."""
    previous = [0] * (len(reference) + 1)
    for i, a in enumerate(piece, 1):
        current = [i] + [0] * len(reference)
        for j, b in enumerate(reference, 1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b))
        previous = current
    return min(previous)


def quote_keys(ref):
    """'林後6:14～16' → [('林後', 6, 14), ('林後', 6, 15), ('林後', 6, 16)]."""
    match = QUOTE_KEY_RE.match(ref)
    if not match:
        return []
    book, chapter, first = match.group(1), int(match.group(2)), int(match.group(3))
    last = int(match.group(4) or first)
    return [(book, chapter, verse) for verse in range(first, min(last, first + 40) + 1)]


def check_messages(messages, verses=None):
    """Impossible chapters always; with Recovery Version text: OCR error rate on quoted verses, and lines of
    verse text that OCR split away from their reference are moved out of the outline points."""
    bad_refs = []
    for message in messages:
        label = f"第{message['number']}篇" if message['number'] else '篇題前'
        for text in message['scripture'] + [item['text'] for item in message['items']]:
            for piece, book, chapter, verse in parse_references(text):
                if chapter > CHAPTERS[book] or chapter < 1 or not 1 <= verse <= 176:
                    bad_refs.append({'message': label, 'reference': piece, 'book': book, 'chapter': chapter,
                                     'verse': verse})
    result = {'invalid_references': bad_refs, 'warnings': []}
    if bad_refs:
        result['warnings'].append(f'{len(bad_refs)} 個經節的章數不存在（多半是 OCR 認錯數字），見 invalid_references')
    if verses is None:
        return result
    checked, errors, chars, worst, unknown, moved = 0, 0, 0, [], [], 0
    for message in messages:
        label = f"第{message['number']}篇" if message['number'] else '篇題前'
        candidates = []
        for quote in message.get('quotes', []):
            keys = quote_keys(quote['ref'])
            texts = [hanzi(verses[k]) for k in keys if k in verses]
            if keys and not texts:
                unknown.append({'message': label, 'ref': quote['ref']})
            candidates += texts
            ocr = hanzi(quote['text'])
            if len(keys) == 1 and texts and len(ocr) >= 4:
                distance = fitting_distance(ocr, texts[0])
                checked, errors, chars = checked + 1, errors + distance, chars + len(ocr)
                if distance:
                    worst.append({'message': label, 'ref': quote['ref'], 'errors': distance, 'ocr': quote['text'],
                                  'recovery_version': verses[keys[0]]})
        kept, message['verse_text'] = [], []
        for item in message['items']:
            text = hanzi(item['text'])
            if not item['level'] and len(text) >= 6 and any(
                    len(set(text) & set(c)) >= 0.7 * len(set(text)) and fitting_distance(text, c) <= 0.15 * len(text)
                    for c in candidates):
                message['verse_text'].append(item['text'])
                moved += 1
            else:
                kept.append(item)
        message['items'] = kept
    worst.sort(key=lambda w: -w['errors'])
    result['verse_check'] = {
        'quotes_checked': checked, 'ocr_chars': chars, 'errors': errors,
        'cer': round(errors / chars, 4) if chars else None, 'verse_text_lines_moved': moved,
        'unknown_refs': unknown[:50], 'worst': worst[:40],
    }
    if unknown:
        result['warnings'].append(f'{len(unknown)} 個引用經文在恢復本找不到（可能 OCR 認錯章節），見 verse_check.unknown_refs')
    return result


def page_count(pdf_path):
    import pymupdf
    with pymupdf.open(pdf_path) as document:
        return document.page_count


def render_pages(pdf_path, only=None, dpi=300):
    """Yield (page number, JPEG bytes) small enough for Drive OCR; only: page numbers to render (default all)."""
    import pymupdf
    with pymupdf.open(pdf_path) as document:
        for number, page in enumerate(document, 1):
            if only is not None and number not in only:
                continue
            for scale_dpi, quality in ((dpi, 90), (dpi, 75), (int(dpi * 0.8), 75), (int(dpi * 0.6), 70)):
                pixmap = page.get_pixmap(dpi=scale_dpi, colorspace=pymupdf.csGRAY)
                data = pixmap.tobytes('jpeg', jpg_quality=quality)
                if len(data) <= MAX_IMAGE_BYTES:
                    break
            yield number, data


def google_ocr(service, image_bytes, language=None, retries=3):
    """Upload as a Google Doc with OCR, export plain text, delete the temporary Doc.

    language: optional OCR hint. None lets Drive detect the language (it keeps the characters on the page, so
    Traditional Chinese stays Traditional)."""
    from googleapiclient.http import MediaIoBaseUpload
    for attempt in range(retries):
        try:
            media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype='image/jpeg', resumable=False)
            options = {'ocrLanguage': language} if language else {}
            created = service.files().create(
                body={'name': 'outline-ocr-temporary', 'mimeType': 'application/vnd.google-apps.document'},
                media_body=media, fields='id', **options).execute()
            try:
                data = service.files().export(fileId=created['id'], mimeType='text/plain').execute()
            finally:
                service.files().delete(fileId=created['id']).execute()
            return data.decode('utf-8-sig') if isinstance(data, bytes) else data
        except Exception as error:  # Drive 偶爾回 429/5xx：稍等再試；其他錯誤（例如 400 參數錯）直接報錯
            status = getattr(getattr(error, 'resp', None), 'status', None)
            if attempt == retries - 1 or (status is not None and status != 429 and status < 500):
                raise
            time.sleep(5 * (attempt + 1))


def ocr_text_to_page(text):
    """OCR text → the page structure outline_pdf_to_md expects (line order as y; no font size)."""
    text = text.lstrip('﻿').replace('\r', '')
    lines = [line for line in text.split('\n') if line.strip() and not set(line.strip()) <= {'_'}]
    # 頁高 100：前兩行 y=0、最後兩行 y=100，落在頁首／頁尾區（上下 8%），重複的頁首頁尾與頁碼會被刪除；
    # OCR 常把頁碼和版權行（2026 Living Stream Ministry）排成最後兩行。
    def y(index):
        return 0 if index < 2 else 100 if index >= len(lines) - 2 else 50
    return {'height': 100, 'width': 1, 'lines': [
        {'text': line, 'y': y(index), 'x': 0, 'size': 0} for index, line in enumerate(lines)]}


def rejected_language(error):
    """Drive answers 400 'Invalid Value' at location ocrLanguage for hints it does not accept (seen: zh-TW, zh)."""
    status = getattr(getattr(error, 'resp', None), 'status', None)
    return status == 400 and b'ocrLanguage' in (getattr(error, 'content', b'') or b'')


def run(pdf_path, cache_dir, output_dir, service, language=None, log=print, recovery_version_dir=None):
    pdf_path, cache_dir = Path(pdf_path), Path(cache_dir)
    verses = load_recovery_version(recovery_version_dir) if recovery_version_dir else None
    if verses is not None:
        log(f'恢復本經文 {len(verses)} 節（用來檢查 OCR 準確度）')
    cache_dir.mkdir(parents=True, exist_ok=True)
    cached_page = lambda number: cache_dir/f'{number:03d}.txt'
    count = page_count(pdf_path)
    missing = {n for n in range(1, count + 1) if not cached_page(n).exists()}
    log(f'{count} 頁，已有 OCR 快取 {count - len(missing)} 頁，要 OCR {len(missing)} 頁')
    for number, image in render_pages(pdf_path, only=missing):
        cached = cached_page(number)
        try:
            text = google_ocr(service, image, language)
        except Exception as error:
            if not (language and rejected_language(error)):
                raise
            log(f'Drive 不接受語言提示 {language!r}，改用自動偵測語言')
            language = None
            text = google_ocr(service, image, language)
        cached.write_text(text, encoding='utf-8')
        log(f'第 {number} 頁 OCR 完成（{len(image) // 1000} KB）')
    pages = [ocr_text_to_page(cached_page(n).read_text(encoding='utf-8')) for n in range(1, count + 1)]
    report = outline.convert(pdf_path, output_dir, pages=pages, checks=lambda m: check_messages(m, verses))
    report['ocr'] = {'engine': 'google-drive', 'language': language or 'auto', 'cache': str(cache_dir)}
    (Path(output_dir)/f'{pdf_path.stem}.report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report
