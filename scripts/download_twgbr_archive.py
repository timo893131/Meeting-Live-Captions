#!/usr/bin/env python3
"""TWGBR 恢復本聖經＋生命讀經 私人離線下載程式（文字＋音訊）。

範圍（固定，不追蹤其他連結）：
  * 恢復本經文：https://line.twgbr.org/recoveryversion/bible/01–66.html（每卷一頁含全部章）
  * 恢復本音訊：上述頁面播放器載入的 https://plan.bible365.today/plan/mp3/bible/<卷>/<章>-<書名>.mp3
  * 生命讀經：https://line.twgbr.org/life-study/1–66.html 及其連到的每篇 <n>_<k>.html
  * 生命讀經音訊：每篇頁面 <audio> 的 MP3

66 卷每卷各有自己的資料夾，資料夾一律使用標準書名（01-創世記 … 66-啟示錄）。撒母耳記、列王紀、
歷代志的上下卷在網站上內容相同，兩卷都會保存；相同的 MP3 只下載一次，第二卷用本機複製。

只供個人離線研讀、不公開：內容 CopyrightⒸ 臺灣福音書房，不轉散布，未經授權不用於模型訓練。
預設每秒最多 1 個請求、單一連線；可中斷續抓（完成的檔案記在 manifest.jsonl，含 SHA-256）。

需求：Python 3.10+、beautifulsoup4（pip install beautifulsoup4）。

範例：
  python download_twgbr_archive.py --output twgbr-archive              # 全部（約 27GB）
  python download_twgbr_archive.py --output twgbr-archive --no-audio   # 只抓文字與原始網頁
  python download_twgbr_archive.py --output twgbr-archive --books 1-5,40 --zip twgbr.zip
"""
import argparse
import hashlib
import json
import re
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

SITE = 'https://line.twgbr.org'
BIBLE_AUDIO = 'https://plan.bible365.today/plan/mp3/bible'
HOSTS = {'line.twgbr.org', 'plan.bible365.today'}
UA = 'MeetingLiveCaptions-PrivateArchive/1.1 (personal offline study; 1 req/s)'
BOOKS = ['創世記', '出埃及記', '利未記', '民數記', '申命記', '約書亞記', '士師記', '路得記', '撒母耳記上',
         '撒母耳記下', '列王紀上', '列王紀下', '歷代志上', '歷代志下', '以斯拉記', '尼希米記', '以斯帖記',
         '約伯記', '詩篇', '箴言', '傳道書', '雅歌', '以賽亞書', '耶利米書', '耶利米哀歌', '以西結書',
         '但以理書', '何西阿書', '約珥書', '阿摩司書', '俄巴底亞書', '約拿書', '彌迦書', '那鴻書', '哈巴谷書',
         '西番雅書', '哈該書', '撒迦利亞書', '瑪拉基書', '馬太福音', '馬可福音', '路加福音', '約翰福音',
         '使徒行傳', '羅馬書', '哥林多前書', '哥林多後書', '加拉太書', '以弗所書', '腓立比書', '歌羅西書',
         '帖撒羅尼迦前書', '帖撒羅尼迦後書', '提摩太前書', '提摩太後書', '提多書', '腓利門書', '希伯來書',
         '雅各書', '彼得前書', '彼得後書', '約翰壹書', '約翰貳書', '約翰參書', '猶大書', '啟示錄']
SHARED_LIFE_STUDY = {10: 9, 12: 11, 14: 13}  # 下卷 → 上卷（網站上同一套生命讀經）
NAV = {'简', '繁', '回目錄', '回首頁', '上一篇', '下一篇', '上一卷', '下一卷'}


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def folder(n):
    return f'{n:02d}-{BOOKS[n-1]}'


class CertificateProblem(Exception):
    """HTTPS 憑證驗證失敗：每個請求都會一樣失敗，立刻停止並說明處理方式。"""


CERT_HELP = '''
HTTPS 憑證驗證失敗（CERTIFICATE_VERIFY_FAILED）。常見原因是公司網路或防毒軟體會檢查 HTTPS，
用自己的憑證重新簽署連線；瀏覽器信任它，但 Python 預設不認得。請擇一處理（不要關閉憑證驗證）：

  1) 安裝 truststore，讓程式改用 Windows／macOS 的系統憑證庫（瀏覽器能開網站時通常就能解決）：
       python -m pip install truststore
     然後重新執行同一個指令。

  2) 若仍失敗：在瀏覽器開 https://line.twgbr.org ，檢視網站憑證 → 憑證路徑最上層的根憑證 →
     匯出成「Base-64 編碼 X.509 (.CER)」，例如存成 company-root.cer，再執行：
       python download_twgbr_archive.py --output twgbr-archive --ca-bundle company-root.cer
     （注意 plan.bible365.today 的音訊也要能通過同一張憑證；公司 IT 也可提供這個根憑證。）

已完成的檔案都有記錄，修好後重新執行會續抓。
'''


def ssl_context(ca_bundle=None):
    """回傳 (context, 說明)。優先：--ca-bundle → truststore（系統憑證庫）→ Python 預設。"""
    if ca_bundle:
        context = ssl.create_default_context()
        context.load_verify_locations(cafile=ca_bundle)  # 加入，不取代預設信任清單
        return context, f'Python 預設＋{ca_bundle}'
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT), 'truststore（系統憑證庫）'
    except ImportError:
        return ssl.create_default_context(), 'Python 預設（未安裝 truststore）'


class Archive:
    def __init__(self, root, interval=1.0, retries=2, timeout=60, max_bytes=80*1048576, context=None):
        self.context = context
        self.root = Path(root); self.root.mkdir(parents=True, exist_ok=True)
        self.interval, self.retries, self.timeout, self.max_bytes = interval, retries, timeout, max_bytes
        self.manifest_path = self.root/'manifest.jsonl'
        self.done = {}
        if self.manifest_path.exists():
            for line in self.manifest_path.read_text(encoding='utf-8').splitlines():
                if line.strip():
                    row = json.loads(line); self.done[row['path']] = row
        self.errors = []; self.last = 0.0; self.requests = 0; self.downloaded_bytes = 0
        self.verbose = True; self.added = 0
        self.by_url = {}
        for row in self.done.values():
            self.by_url.setdefault((row['url'], row['kind']), []).append(row['path'])
        self.book_stats = {}

    # ---- network -------------------------------------------------------------------------
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
                with urllib.request.urlopen(request, timeout=self.timeout, context=self.context) as response:
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
            except ssl.SSLCertVerificationError as error:
                raise CertificateProblem(str(error)) from error
            except (urllib.error.URLError, TimeoutError, IOError) as error:
                if isinstance(getattr(error, 'reason', None), ssl.SSLCertVerificationError):
                    raise CertificateProblem(str(error.reason)) from error
                if attempt < self.retries:
                    time.sleep(5*(attempt+1)); continue
                raise

    # ---- local files ---------------------------------------------------------------------
    def record(self, rel, url, data_len, digest, kind, **meta):
        row = dict(path=rel, url=url, kind=kind, bytes=data_len, sha256=digest, fetched_at=now(), **meta)
        with self.manifest_path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False)+'\n')
        self.done[rel] = row; self.added += 1
        self.by_url.setdefault((url, kind), []).append(rel)
        return row

    def save(self, rel, url, data, kind, **meta):
        path = self.root/rel; path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name+'.part'); temporary.write_bytes(data); temporary.replace(path)
        return self.record(rel, url, len(data), sha256(data), kind, **meta)

    def have(self, rel):
        row = self.done.get(rel); path = self.root/rel
        return bool(row and path.exists() and path.stat().st_size == row['bytes'])

    def local_copy(self, url, kind):
        """A finished file already downloaded from the same URL (shared Samuel/Kings/Chronicles audio)."""
        for path in self.by_url.get((url, kind), []):
            if self.have(path):
                return self.done[path]
        return None

    def get(self, rel, url, kind, **meta):
        """Return bytes for html kinds (from disk if complete); download only what is missing."""
        if self.have(rel):
            return (self.root/rel).read_bytes() if kind.endswith('html') else True
        if kind.endswith('audio'):
            source = self.local_copy(url, kind)
            if source:
                path = self.root/rel; path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.root/source['path'], path)
                self.record(rel, url, source['bytes'], source['sha256'], kind, copied_from=source['path'], **meta)
                self.say(f'  = {rel}（與 {source["path"]} 相同，本機複製）')
                return True
        try:
            data = self.fetch(url)
        except CertificateProblem:
            raise
        except Exception as error:
            self.errors.append(dict(path=rel, url=url, kind=kind, error=f'{type(error).__name__}: {error}'[:300], at=now()))
            print(f'  ! {rel}: {self.errors[-1]["error"]}', flush=True)
            return None
        if kind.endswith('audio') and data[:3] != b'ID3' and data[:1] != b'\xff':
            self.errors.append(dict(path=rel, url=url, kind=kind, error='Response is not MP3 audio', at=now()))
            print(f'  ! {rel}: 不是 MP3 音訊', flush=True)
            return None
        self.save(rel, url, data, kind, **meta)
        self.say(f'  + {rel} ({len(data):,} bytes)')
        return data if kind.endswith('html') else True

    def say(self, message):
        if self.verbose:
            print(message, flush=True)

    def book_done(self, label, started_added, started_errors):
        if not self.verbose:
            print(f'    新增 {self.added-started_added} 個檔案、失敗 {len(self.errors)-started_errors} 項；'
                  f'累計下載 {self.downloaded_bytes/1048576:,.0f} MiB', flush=True)

    def stat(self, n, key, value):
        self.book_stats.setdefault(n, {})[key] = value


def main_text(html):
    """#verses 主內容 → 純文字：去掉導覽列，經節號碼與經文合成一行。回傳 (文字, 第一個 h3 標題)。"""
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
        if merged and merged[-1].isdigit():
            merged[-1] = f'{merged[-1]} {line}'
        else:
            merged.append(line)
    return '\n'.join(merged), (first.get_text(' ', strip=True) if first else None)


def text_file(archive, rel, html, url, kind, **meta):
    if archive.have(rel):
        return True
    text, _ = main_text(html)
    if not text:
        archive.errors.append(dict(path=rel, url=url, kind=kind, error='No #verses main text', at=now()))
        return False
    archive.save(rel, url, (text+'\n').encode('utf-8'), kind, derived_from='html', **meta)
    return True


def bible(archive, books, want_text, want_audio, chapter_limit):
    for n in books:
        mark = (archive.added, len(archive.errors))
        try:
            name = BOOKS[n-1]; base = folder(n)
            url = f'{SITE}/recoveryversion/bible/{n:02d}.html'
            print(f'[恢復本] {base}', flush=True)
            html = archive.get(f'recovery-version/html/{base}.html', url, 'bible_html', book=n, book_name=name)
            if not html:
                continue
            page = html.decode('utf-8', errors='replace')
            prefix = re.search(r"bookMP4Prefix:\s*['\"]([^'\"]+)", page)
            chapters = chapter_count(page)
            archive.stat(n, 'chapters', chapters)
            if want_text:
                text_file(archive, f'recovery-version/text/{base}.txt', html, url, 'bible_text', book=n, book_name=name)
            if want_audio:
                if not chapters or not prefix:
                    archive.errors.append(dict(path=base, url=url, kind='bible_audio', error='Player metadata not found', at=now()))
                    continue
                for c in range(1, min(chapters, chapter_limit or 10**6)+1):
                    archive.get(f'recovery-version/audio/{base}/{c:03d}.mp3', bible_audio_url(n, c, chapters, prefix.group(1)),
                                'bible_audio', book=n, book_name=name, chapter=c)
        finally:
            archive.book_done(n, *mark)


def chapter_count(page):
    """以經文中的章標題（<h3 id="C…">）計算章數；播放器設定有誤（約翰參書寫 5 章，實際 1 章），只作備用。"""
    headings = BeautifulSoup(page, 'html.parser').select('#verses h3[id^="C"]')
    if headings:
        return len(headings)
    found = re.search(r"numChapters:\s*['\"]?(\d+)", page)  # 有些卷沒有引號（如啟示錄）
    return int(found.group(1)) if found else None


def bible_audio_url(book, chapter, chapters, prefix):
    """章號兩位數（01-Genesis）；超過 99 章的詩篇用三位數（001-Psalms）。書名空白編碼（1%20Samuel）。"""
    width = 3 if chapters >= 100 else 2
    return f'{BIBLE_AUDIO}/{book:02d}/{chapter:0{width}d}-{urllib.parse.quote(prefix)}.mp3'


def message_links(html, n, url):
    soup = BeautifulSoup(html, 'html.parser')
    pattern = re.compile(rf'/life-study/{n}(?:_(\d+))?\.html$')
    messages = {}
    for link in soup.find_all('a', href=True):
        target = urllib.parse.urljoin(url, link['href']).split('#')[0]
        parts = urllib.parse.urlsplit(target); match = pattern.search(parts.path)
        # 網站上偶有 <n>_0.html 的壞連結（404），不是實際篇章。
        if match and parts.hostname == 'line.twgbr.org' and match.group(1) != '0':
            messages[int(match.group(1) or 1)] = target
    messages.setdefault(1, url)
    return messages


def life_study(archive, books, want_text, want_audio, message_limit):
    for n in books:
        mark = (archive.added, len(archive.errors))
        try:
            name = BOOKS[n-1]; base = folder(n); url = f'{SITE}/life-study/{n}.html'
            html = archive.get(f'life-study/index/{base}.html', url, 'life_study_index_html', book=n, book_name=name)
            if not html:
                continue
            messages = message_links(html, n, url)
            archive.stat(n, 'messages', len(messages))
            note = f'（與 {folder(SHARED_LIFE_STUDY[n])} 為同一套信息）' if n in SHARED_LIFE_STUDY else ''
            print(f'[生命讀經] {base}：{len(messages)} 篇{note}', flush=True)
            for k in sorted(messages)[:message_limit or None]:
                murl = messages[k]; stem = f'{base}/{k:03d}'
                mhtml = archive.get(f'life-study/html/{stem}.html', murl, 'life_study_html', book=n, book_name=name, message=k)
                if not mhtml:
                    continue
                if want_text:
                    text_file(archive, f'life-study/text/{stem}.txt', mhtml, murl, 'life_study_text', book=n,
                              book_name=name, message=k, message_title=main_text(mhtml)[1])
                if want_audio:
                    msoup = BeautifulSoup(mhtml, 'html.parser')
                    sources = [urllib.parse.urljoin(murl, tag.get('src')) for tag in msoup.select('audio source[src], audio[src]')]
                    sources = [s for s in dict.fromkeys(sources) if s.lower().endswith('.mp3')]
                    if not sources:
                        archive.errors.append(dict(path=f'life-study/audio/{stem}', url=murl, kind='life_study_audio',
                                                   error='No MP3 on page', at=now()))
                    for i, source in enumerate(sources):
                        suffix = '' if i == 0 else f'-{i+1}'
                        archive.get(f'life-study/audio/{stem}{suffix}.mp3', source, 'life_study_audio', book=n,
                                    book_name=name, message=k, page_url=murl)
        finally:
            archive.book_done(n, *mark)


def compact(books):
    spans, start = [], None
    for i, b in enumerate(books):
        start = b if start is None else start
        if i+1 == len(books) or books[i+1] != b+1:
            spans.append(str(start) if start == b else f'{start}-{b}'); start = None
    return ','.join(spans)


def write_readme(archive, args):
    rows = list(archive.done.values())
    def count(kind, n=None):
        picked = [r for r in rows if r['kind'] == kind and (n is None or r.get('book') == n)]
        return len(picked), sum(r['bytes'] for r in picked)
    lines = ['# TWGBR 私人離線資料（恢復本聖經＋生命讀經）', '',
             f'- 最後更新：{now()}（UTC）；程式：download_twgbr_archive.py',
             f'- 本次參數：collections={args.collections}、books={compact(args.books)}、文字={"否" if args.no_text else "是"}、'
             f'音訊={"否" if args.no_audio else "是"}' + (f'、每卷上限 {args.limit_per_book}' if args.limit_per_book else ''),
             '- 權利：內容 CopyrightⒸ 臺灣福音書房。**僅供個人離線研讀／內部使用，不公開、不轉散布；未經授權不用於模型訓練。**', '',
             '## 抓取範圍', '',
             '| 系列 | 來源 | 內容 |', '| --- | --- | --- |',
             f'| 恢復本聖經 | {SITE}/recoveryversion/bible/01–66.html | 每卷一頁（含全部章節經文）；文字取 #verses 主內容 |',
             f'| 恢復本經文音訊 | {BIBLE_AUDIO}/<卷>/<章>-<書名>.mp3 | 恢復本頁面播放器載入的每章 MP3 |',
             f'| 生命讀經 | {SITE}/life-study/1–66.html 及其連到的每篇信息頁 | 每篇一頁 |',
             f'| 生命讀經音訊 | 每篇信息頁 <audio> 的 MP3（{SITE}/life-study/mp3/…） | 一篇一檔；是講者導讀，**不是網頁文字的逐字朗讀** |',
             '', '不追蹤其他連結、不抓其他網站。預設每秒最多 1 個請求、單一連線。',
             '撒母耳記、列王紀、歷代志的上下卷在網站上是同一套生命讀經，兩卷資料夾都保存（內容相同；相同 MP3 只下載一次，另一卷為本機複製）。', '',
             '## 資料夾結構', '', '```text',
             'README.md                              本說明（每次執行後重寫）',
             'manifest.jsonl                         每個完成檔案：path、url、kind、bytes、sha256、fetched_at、卷／章／篇',
             'errors.jsonl                           本次失敗項目（重新執行會自動補抓）',
             'recovery-version/',
             '  html/01-創世記.html                   原始網頁（未修改）',
             '  text/01-創世記.txt                    主內容純文字（章標題、綱目、經文；經節號碼在行首）',
             '  audio/01-創世記/001.mp3               第 1 章音訊（三位數章號）',
             'life-study/',
             '  index/01-創世記.html                  各卷入口頁（＝第一篇）原始網頁',
             '  html/01-創世記/001.html               第 1 篇原始網頁',
             '  text/01-創世記/001.txt                第 1 篇主內容純文字',
             '  audio/01-創世記/001.mp3               第 1 篇音訊',
             '```', '', '資料夾一律為「兩位數卷號-標準書名」：01-創世記 … 66-啟示錄。', '',
             '## 總數', '', '| 類別 | 檔案數 | 大小 |', '| --- | --- | --- |']
    labels = [('bible_html', '恢復本原始網頁'), ('bible_text', '恢復本純文字'), ('bible_audio', '恢復本經文音訊'),
              ('life_study_index_html', '生命讀經入口頁'), ('life_study_html', '生命讀經原始網頁'),
              ('life_study_text', '生命讀經純文字'), ('life_study_audio', '生命讀經音訊')]
    for kind, label in labels:
        c, size = count(kind)
        lines.append(f'| {label} | {c:,} | {size/1048576:,.1f} MiB |')
    lines += ['', '## 逐卷清單', '', '「已存／應有」：應有數取自網站（恢復本章數取自頁面播放器設定，生命讀經篇數取自入口頁連結）。', '',
              '| 卷 | 恢復本文字 | 經文音訊（已存／章數） | 生命讀經文字（已存／篇數） | 生命讀經音訊 |',
              '| --- | --- | --- | --- | --- |']
    for n in range(1, 67):
        stats = archive.book_stats.get(n, {})
        ch = stats.get('chapters', '?'); ms = stats.get('messages', '?')
        lines.append(f'| {folder(n)} | {"✓" if count("bible_text", n)[0] else "—"} | {count("bible_audio", n)[0]}／{ch} | '
                     f'{count("life_study_text", n)[0]}／{ms} | {count("life_study_audio", n)[0]} |')
    lines += ['', f'本次失敗：{len(archive.errors)} 項（見 errors.jsonl）。本次 HTTP 請求 {archive.requests:,} 次、下載 {archive.downloaded_bytes/1048576:,.1f} MiB。'
              '「?」表示這次沒有處理該卷（例如用 --books 只抓部分書卷）。', '',
              '## 使用與續抓', '', '```bash', 'pip install beautifulsoup4',
              'python download_twgbr_archive.py --output <資料夾>', '```', '',
              '中斷後用同一個 --output 重跑即可，已完成且大小相符的檔案會略過。加 --zip <檔名>.zip 可產生壓縮檔（檔名以 UTF-8 標記，Windows 解壓不會變亂碼）。',
              '純文字是 HTML 的衍生檔，原始網頁另存未修改；sha256 可檢查檔案完整性。全部音訊約 27GB（經文 1,189 章、生命讀經 1,984 個不重複音訊），請確認磁碟空間。', '']
    (archive.root/'README.md').write_text('\n'.join(lines), encoding='utf-8')
    (archive.root/'errors.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False)+'\n' for e in archive.errors), encoding='utf-8')


def make_zip(root, target):
    """Python zipfile 會為中文檔名設定 UTF-8 旗標，Windows／macOS 解壓不會出現亂碼。"""
    root = Path(root); target = Path(target).resolve()
    with zipfile.ZipFile(target, 'w') as bundle:
        for path in sorted(root.rglob('*')):
            if path.is_file() and path.resolve() != target and not path.name.endswith('.part'):
                method = zipfile.ZIP_STORED if path.suffix.lower() == '.mp3' else zipfile.ZIP_DEFLATED
                bundle.write(path, Path(root.name)/path.relative_to(root), compress_type=method)
    return target


def parse_books(value):
    books = set()
    for part in value.split(','):
        a, _, b = part.strip().partition('-')
        books.update(range(int(a), int(b or a)+1))
    if not books or min(books) < 1 or max(books) > 66:
        raise argparse.ArgumentTypeError('books 必須在 1–66 之間，例如 1-66 或 1,40-43')
    return sorted(books)


def main():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')  # 舊版 Windows 主控台遇到中文不中斷
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', default='twgbr-archive', help='輸出資料夾（預設 twgbr-archive）')
    parser.add_argument('--collections', default='bible,life-study', help='bible、life-study 或兩者（逗號分隔）')
    parser.add_argument('--books', type=parse_books, default=parse_books('1-66'), help='卷號，例如 1-66 或 8,57')
    parser.add_argument('--no-text', action='store_true', help='不產生純文字（原始網頁仍會保存）')
    parser.add_argument('--no-audio', action='store_true', help='不下載 MP3')
    parser.add_argument('--quiet', action='store_true', help='不逐檔顯示，只顯示每卷摘要與錯誤（適合 Colab）')
    parser.add_argument('--limit-per-book', type=int, default=0, help='試跑：每卷最多幾章／幾篇')
    parser.add_argument('--interval', type=float, default=1.0, help='請求間隔秒數（最低 0.5）')
    parser.add_argument('--retries', type=int, default=2)
    parser.add_argument('--timeout', type=int, default=60)
    parser.add_argument('--max-file-mb', type=int, default=80)
    parser.add_argument('--ca-bundle', help='額外信任的根憑證檔（PEM／Base-64 .cer），用於公司網路的 HTTPS 檢查')
    parser.add_argument('--zip', help='完成後把輸出資料夾打包成此 zip 檔（UTF-8 檔名）')
    args = parser.parse_args()
    if args.interval < 0.5:
        parser.error('--interval 至少 0.5 秒')
    collections = {c.strip() for c in args.collections.split(',')}
    if not collections <= {'bible', 'life-study'}:
        parser.error('--collections 只接受 bible 和／或 life-study')
    try:
        context, trust = ssl_context(args.ca_bundle)
    except (OSError, ssl.SSLError) as error:
        parser.error(f'--ca-bundle 無法讀取：{error}')
    print(f'HTTPS 憑證來源：{trust}', flush=True)
    archive = Archive(args.output, args.interval, args.retries, args.timeout, args.max_file_mb*1048576, context)
    archive.verbose = not args.quiet
    try:
        if 'bible' in collections:
            bible(archive, args.books, not args.no_text, not args.no_audio, args.limit_per_book)
        if 'life-study' in collections:
            life_study(archive, args.books, not args.no_text, not args.no_audio, args.limit_per_book)
    except KeyboardInterrupt:
        print('中斷；已完成的檔案已記錄，重新執行會續抓。', file=sys.stderr)
    except CertificateProblem as error:
        write_readme(archive, args)
        print(f'\n停止：{error}\n{CERT_HELP}', file=sys.stderr)
        return 2
    finally:
        write_readme(archive, args)
    print(f'完成：{len(archive.done):,} 個檔案已記錄，本次失敗 {len(archive.errors)} 項；說明見 {archive.root/"README.md"}')
    if args.zip:
        print(f'壓縮檔：{make_zip(archive.root, args.zip)}')
    return 1 if archive.errors else 0


if __name__ == '__main__':
    sys.exit(main())
