#!/usr/bin/env python3
"""Private offline archive of TWGBR Recovery Version Bible and Life-Study (text + audio).

Scope (fixed): https://line.twgbr.org/recoveryversion/bible/01-66.html, the Life-Study book
pages https://line.twgbr.org/life-study/1-66.html and every message page they link to, the
Life-Study MP3 linked on each message page, and the per-chapter Bible MP3s that the Recovery
Version page player loads from plan.bible365.today. Nothing else is followed.

Personal, non-public use only: content is CopyrightⒸ 臺灣福音書房; not for redistribution or
model training without permission. Polite by default (1 request/second, one connection),
resumable (finished files are recorded in manifest.jsonl with SHA-256 and skipped next run).

Requires Python 3.10+ and beautifulsoup4 (pip install beautifulsoup4).
"""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

SITE = 'https://line.twgbr.org'
BIBLE_AUDIO = 'https://plan.bible365.today/plan/mp3/bible'
HOSTS = {'line.twgbr.org', 'plan.bible365.today'}
UA = 'MeetingLiveCaptions-PrivateArchive/1.0 (personal offline study; 1 req/s)'
BOOKS = ['創世記', '出埃及記', '利未記', '民數記', '申命記', '約書亞記', '士師記', '路得記', '撒母耳記上',
         '撒母耳記下', '列王紀上', '列王紀下', '歷代志上', '歷代志下', '以斯拉記', '尼希米記', '以斯帖記',
         '約伯記', '詩篇', '箴言', '傳道書', '雅歌', '以賽亞書', '耶利米書', '耶利米哀歌', '以西結書',
         '但以理書', '何西阿書', '約珥書', '阿摩司書', '俄巴底亞書', '約拿書', '彌迦書', '那鴻書', '哈巴谷書',
         '西番雅書', '哈該書', '撒迦利亞書', '瑪拉基書', '馬太福音', '馬可福音', '路加福音', '約翰福音',
         '使徒行傳', '羅馬書', '哥林多前書', '哥林多後書', '加拉太書', '以弗所書', '腓立比書', '歌羅西書',
         '帖撒羅尼迦前書', '帖撒羅尼迦後書', '提摩太前書', '提摩太後書', '提多書', '腓利門書', '希伯來書',
         '雅各書', '彼得前書', '彼得後書', '約翰壹書', '約翰貳書', '約翰參書', '猶大書', '啟示錄']


NAV = {'简', '繁', '回目錄', '回首頁', '上一篇', '下一篇', '上一卷', '下一卷'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe(name):
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_')[:60]


class Archive:
    def __init__(self, root, interval, retries, timeout, max_bytes):
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.interval, self.retries, self.timeout, self.max_bytes = interval, retries, timeout, max_bytes
        self.manifest_path = self.root/'manifest.jsonl'
        self.done = {}
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    row = json.loads(line); self.done[row['path']] = row
        self.errors = []; self.last = 0.0; self.requests = 0; self.downloaded_bytes = 0

    def fetch(self, url):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != 'https' or parts.hostname not in HOSTS:
            raise ValueError('URL outside archive scope: '+url)
        for attempt in range(self.retries+1):
            wait = self.interval-(time.monotonic()-self.last)
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic(); self.requests += 1
            try:
                request = urllib.request.Request(url, headers={'User-Agent': UA})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    final = urllib.parse.urlsplit(response.geturl()).hostname
                    if final not in HOSTS:
                        raise ValueError('Redirected outside archive scope: '+response.geturl())
                    length = response.headers.get('Content-Length')
                    if length and int(length) > self.max_bytes:
                        raise ValueError(f'File larger than --max-file-mb: {length} bytes')
                    data = response.read(self.max_bytes+1)
                    if len(data) > self.max_bytes:
                        raise ValueError('File larger than --max-file-mb')
                    if length and len(data) != int(length):
                        raise IOError('Truncated response')
                    self.downloaded_bytes += len(data)
                    return data
            except urllib.error.HTTPError as error:
                if error.code in (429, 500, 502, 503, 504) and attempt < self.retries:
                    retry = error.headers.get('Retry-After', '')
                    time.sleep(min(120, int(retry)) if retry.isdigit() else 5*(attempt+1))
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, IOError):
                if attempt < self.retries:
                    time.sleep(5*(attempt+1)); continue
                raise

    def save(self, rel, url, data, kind, **meta):
        path = self.root/rel; path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name+'.part'); temporary.write_bytes(data); temporary.replace(path)
        row = dict(path=rel, url=url, kind=kind, bytes=len(data), sha256=sha256(data), fetched_at=now(), **meta)
        with self.manifest_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
        self.done[rel] = row
        return row

    def have(self, rel):
        row = self.done.get(rel); path = self.root/rel
        return bool(row and path.exists() and path.stat().st_size == row['bytes'])

    def get(self, rel, url, kind, **meta):
        """Return bytes for rel, downloading only if it is not already complete."""
        if self.have(rel):
            return (self.root/rel).read_bytes() if kind.endswith('html') else None
        try:
            data = self.fetch(url)
        except Exception as error:
            self.errors.append(dict(path=rel, url=url, kind=kind, error=f'{type(error).__name__}: {error}'[:300], at=now()))
            print(f'  ! {rel}: {self.errors[-1]["error"]}', flush=True)
            return None
        if kind.endswith('audio') and not data[:3] == b'ID3' and data[:1] != b'\xff':
            self.errors.append(dict(path=rel, url=url, kind=kind, error='Response is not MP3 audio', at=now()))
            return None
        self.save(rel, url, data, kind, **meta)
        print(f'  + {rel} ({len(data):,} bytes)', flush=True)
        return data


def main_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    body = soup.select_one('#verses')
    if body is None:
        return None, None
    for node in body.select('script,style,template,#chapternav,button,audio,center'):
        node.decompose()
    first = body.find('h3')
    lines = [line for line in body.get_text('\n', strip=True).splitlines() if line not in NAV]
    merged = []
    for line in lines:
        # 經節號碼與經文合成一行：「1 當士師秉政的時候…」
        if merged and merged[-1].isdigit():
            merged[-1] = f'{merged[-1]} {line}'
        else:
            merged.append(line)
    return '\n'.join(merged), (first.get_text(' ', strip=True) if first else None)


def text_file(archive, rel, html, url, kind, **meta):
    if html is None or archive.have(rel):
        return
    text, _ = main_text(html)
    if not text:
        archive.errors.append(dict(path=rel, url=url, kind=kind, error='No #verses main text', at=now())); return
    archive.save(rel, url, (text+'\n').encode('utf-8'), kind, derived_from='html', **meta)


def bible(archive, books, want_text, want_audio, chapter_limit):
    for n in books:
        name = BOOKS[n-1]; folder = f'{n:02d}-{name}'
        url = f'{SITE}/recoveryversion/bible/{n:02d}.html'
        print(f'[恢復本] {folder}', flush=True)
        html = archive.get(f'recovery-version/html/{folder}.html', url, 'bible_html', book=n, book_name=name)
        if html is None:
            html_path = archive.root/f'recovery-version/html/{folder}.html'
            html = html_path.read_bytes() if html_path.exists() else None
        if html is None:
            continue
        if want_text:
            text_file(archive, f'recovery-version/text/{folder}.txt', html, url, 'bible_text', book=n, book_name=name)
        if want_audio:
            page = html.decode('utf-8', errors='replace')
            chapters = re.search(r"numChapters:\s*'(\d+)'", page); prefix = re.search(r"bookMP4Prefix:\s*'([^']+)'", page)
            if not chapters or not prefix:
                archive.errors.append(dict(path=folder, url=url, kind='bible_audio', error='Player metadata not found', at=now())); continue
            for c in range(1, min(int(chapters.group(1)), chapter_limit or 10**6)+1):
                audio_url = f'{BIBLE_AUDIO}/{n:02d}/{c:02d}-{prefix.group(1)}.mp3'
                archive.get(f'recovery-version/audio/{folder}/{c:03d}.mp3', audio_url, 'bible_audio',
                            book=n, book_name=name, chapter=c)


def life_study(archive, books, want_text, want_audio, message_limit):
    seen = set()
    for n in books:
        url = f'{SITE}/life-study/{n}.html'
        cached = archive.root/f'life-study/index/{n:02d}.html'
        html = archive.get(f'life-study/index/{n:02d}.html', url, 'life_study_index_html', book=n)
        html = html or (cached.read_bytes() if cached.exists() else None)
        if html is None:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        title = (soup.title.get_text(strip=True) if soup.title else '').split(' - ')[0] or BOOKS[n-1]
        pattern = re.compile(rf'/life-study/{n}(?:_(\d+))?\.html$')
        messages = {}
        for link in soup.find_all('a', href=True):
            target = urllib.parse.urljoin(url, link['href']).split('#')[0]
            match = pattern.search(urllib.parse.urlsplit(target).path)
            # 網站上偶有 <n>_0.html 的壞連結（404），不是實際篇章。
            if match and urllib.parse.urlsplit(target).hostname == 'line.twgbr.org' and match.group(1) != '0':
                messages[int(match.group(1) or 1)] = target
        messages.setdefault(1, url)
        # 撒母耳記、列王紀、歷代志上下卷網址不同但內容相同；以入口頁主內容判斷，只存一次。
        key = sha256((main_text(html)[0] or url).encode('utf-8'))
        if key in seen:
            print(f'[生命讀經] {n:02d} 與前一卷內容相同，略過', flush=True); continue
        seen.add(key)
        folder = f'{n:02d}-{safe(title)}'
        print(f'[生命讀經] {folder}：{len(messages)} 篇', flush=True)
        for k in sorted(messages)[:message_limit or None]:
            murl = messages[k]; base = f'life-study/{{}}/{folder}/{k:03d}'
            mhtml = archive.get(base.format('html')+'.html', murl, 'life_study_html', book=n, message=k)
            if mhtml is None and (archive.root/(base.format('html')+'.html')).exists():
                mhtml = (archive.root/(base.format('html')+'.html')).read_bytes()
            if mhtml is None:
                continue
            if want_text:
                text_file(archive, base.format('text')+'.txt', mhtml, murl, 'life_study_text', book=n, message=k,
                          message_title=main_text(mhtml)[1])
            if want_audio:
                msoup = BeautifulSoup(mhtml, 'html.parser')
                sources = [urllib.parse.urljoin(murl, tag.get('src')) for tag in msoup.select('audio source[src], audio[src]')]
                sources = [s for s in dict.fromkeys(sources) if s.endswith('.mp3')]
                if not sources:
                    archive.errors.append(dict(path=base.format('audio'), url=murl, kind='life_study_audio', error='No MP3 on page', at=now()))
                for i, source in enumerate(sources):
                    suffix = '' if i == 0 else f'-{i+1}'
                    archive.get(base.format('audio')+f'{suffix}.mp3', source, 'life_study_audio', book=n, message=k, page_url=murl)


def write_readme(archive, args):
    rows = list(archive.done.values())
    def stat(kind):
        picked = [r for r in rows if r['kind'] == kind]
        return len(picked), sum(r['bytes'] for r in picked)
    lines = ['# TWGBR 私人離線資料（恢復本聖經＋生命讀經）', '',
             f'- 最後更新：{now()}（UTC）；程式：scripts/download_twgbr_archive.py',
             f'- 本次參數：collections={args.collections}、books={compact(args.books)}、text={not args.no_text}、audio={not args.no_audio}'
             + (f'、每卷上限 {args.limit_per_book}' if args.limit_per_book else ''),
             '- 權利：內容 CopyrightⒸ 臺灣福音書房。**僅供個人離線研讀／內部使用，不公開、不轉散布；未經授權不用於模型訓練。**', '',
             '## 抓取範圍', '',
             '| 系列 | 來源 | 內容 |', '| --- | --- | --- |',
             f'| 恢復本聖經 | {SITE}/recoveryversion/bible/01–66.html | 每卷一頁（含全部章節經文）；文字取 #verses 主內容 |',
             f'| 恢復本經文音訊 | {BIBLE_AUDIO}/<卷>/<章>-<書名>.mp3 | 恢復本頁面播放器載入的每章 MP3 |',
             f'| 生命讀經 | {SITE}/life-study/1–66.html 及其連到的每篇信息頁 | 每篇一頁；撒母耳記、列王紀、歷代志上下卷共用同一套信息，只存一次 |',
             f'| 生命讀經音訊 | 每篇信息頁 <audio> 的 MP3（{SITE}/life-study/mp3/…） | 一篇一檔；是講者導讀／轉述，**不是網頁文字的逐字朗讀** |',
             '', '不追蹤其他連結、不抓其他網站。網站 robots.txt 不存在（404）；預設每秒最多 1 個請求、單一連線。', '',
             '## 資料夾結構', '', '```text',
             'README.md                     本說明（每次執行後重寫）',
             'manifest.jsonl                每個完成檔案：path、url、kind、bytes、sha256、fetched_at、卷／章／篇',
             'errors.jsonl                  本次失敗項目（重新執行會自動補抓）',
             'recovery-version/',
             '  html/01-創世記.html          原始網頁（未修改）',
             '  text/01-創世記.txt           主內容純文字（章標題＋經文）',
             '  audio/01-創世記/001.mp3      第 1 章音訊（三位數章號）',
             'life-study/',
             '  index/01.html               各卷入口頁（＝第一篇）原始網頁',
             '  html/01-創世記/001.html      第 1 篇原始網頁',
             '  text/01-創世記/001.txt       第 1 篇主內容純文字',
             '  audio/01-創世記/001.mp3      第 1 篇音訊', '```', '',
             '## 目前數量', '', '| 類別 | 檔案數 | 大小 |', '| --- | --- | --- |']
    labels = [('bible_html', '恢復本原始網頁'), ('bible_text', '恢復本純文字'), ('bible_audio', '恢復本經文音訊'),
              ('life_study_index_html', '生命讀經入口頁'), ('life_study_html', '生命讀經原始網頁'),
              ('life_study_text', '生命讀經純文字'), ('life_study_audio', '生命讀經音訊')]
    for kind, label in labels:
        count, size = stat(kind)
        lines.append(f'| {label} | {count:,} | {size/1048576:,.1f} MiB |')
    lines += ['', f'本次失敗：{len(archive.errors)} 項（見 errors.jsonl）。HTTP 請求 {archive.requests:,} 次、下載 {archive.downloaded_bytes/1048576:,.1f} MiB。', '',
              '## 使用與續抓', '', '```bash', 'pip install beautifulsoup4',
              'python scripts/download_twgbr_archive.py --output <資料夾>', '```', '',
              '中斷後用同一個 --output 重跑即可，已完成且大小相符的檔案會略過。純文字是 HTML 的衍生檔，原始網頁另存未修改；',
              'sha256 可用來檢查檔案是否完整。全部音訊約 27GB（經文約 1,189 章、生命讀經約 2,000 篇），請確認磁碟空間。', '']
    (archive.root/'README.md').write_text('\n'.join(lines), encoding='utf-8')
    (archive.root/'errors.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False)+'\n' for e in archive.errors), encoding='utf-8')


def compact(books):
    spans, start = [], None
    for i, b in enumerate(books):
        start = b if start is None else start
        if i+1 == len(books) or books[i+1] != b+1:
            spans.append(str(start) if start == b else f'{start}-{b}'); start = None
    return ','.join(spans)


def parse_books(value):
    books = set()
    for part in value.split(','):
        a, _, b = part.partition('-')
        books.update(range(int(a), int(b or a)+1))
    if not books or min(books) < 1 or max(books) > 66:
        raise argparse.ArgumentTypeError('books must be within 1-66, e.g. 1-66 or 1,40-43')
    return sorted(books)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', default='data/twgbr-archive', help='Archive folder (default: data/twgbr-archive)')
    parser.add_argument('--collections', default='bible,life-study', help='bible, life-study or both')
    parser.add_argument('--books', type=parse_books, default=parse_books('1-66'), help='Book numbers, e.g. 1-66 or 8,57')
    parser.add_argument('--no-text', action='store_true', help='Skip text extraction (raw HTML is still saved)')
    parser.add_argument('--no-audio', action='store_true', help='Skip MP3 downloads')
    parser.add_argument('--limit-per-book', type=int, default=0, help='Test run: max chapters/messages per book')
    parser.add_argument('--interval', type=float, default=1.0, help='Seconds between requests (minimum 0.5)')
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--max-file-mb', type=int, default=80)
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error('--interval must be at least 0.5 seconds')
    collections = {c.strip() for c in args.collections.split(',')}
    if not collections <= {'bible', 'life-study'}:
        parser.error('--collections accepts bible and/or life-study')
    archive = Archive(args.output, args.interval, args.retries, args.timeout, args.max_file_mb*1048576)
    try:
        if 'bible' in collections:
            bible(archive, args.books, not args.no_text, not args.no_audio, args.limit_per_book)
        if 'life-study' in collections:
            life_study(archive, args.books, not args.no_text, not args.no_audio, args.limit_per_book)
    except KeyboardInterrupt:
        print('中斷；已完成的檔案已記錄，重新執行會續抓。', file=sys.stderr)
    finally:
        write_readme(archive, args)
    print(f'完成：{len(archive.done):,} 個檔案已記錄，本次失敗 {len(archive.errors)} 項；說明見 {archive.root/"README.md"}')
    return 1 if archive.errors else 0


if __name__ == '__main__':
    sys.exit(main())
