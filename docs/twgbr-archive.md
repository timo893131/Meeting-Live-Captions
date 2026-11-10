# TWGBR 私人離線下載程式

`scripts/download_twgbr_archive.py` 把使用者指定的兩個系列整理成一個資料夾：恢復本聖經（文字＋每章音訊）與生命讀經（每篇文字＋音訊）。使用者說明為個人／內部使用、不對外發布。內容 CopyrightⒸ 臺灣福音書房；不轉散布，未經授權不用於模型訓練。

## 範圍（寫死在程式內，不追蹤其他連結）

| 系列 | 來源 |
| --- | --- |
| 恢復本經文 | https://line.twgbr.org/recoveryversion/bible/01–66.html（每卷一頁含全部章） |
| 恢復本音訊 | 頁面播放器載入的 https://plan.bible365.today/plan/mp3/bible/<卷>/<章>-<書名>.mp3 |
| 生命讀經 | https://line.twgbr.org/life-study/1–66.html 及其連到的每篇 `<n>_<k>.html` |
| 生命讀經音訊 | 每篇頁面 `<audio>` 的 MP3（line.twgbr.org/life-study/mp3/…） |

撒母耳記、列王紀、歷代志上下卷網址不同但內容與音訊相同，只存一次（存在上卷資料夾）。

## 使用

只需要 Python 3.10+ 與 beautifulsoup4，可以在自己的電腦執行：

```bash
pip install beautifulsoup4
```

```bash
python scripts/download_twgbr_archive.py --output twgbr-archive
```

常用選項：`--no-audio`（只抓文字＋原始網頁）、`--collections bible` 或 `life-study`、`--books 1-5,40`、`--limit-per-book 2`（試跑）、`--interval 1`（每次請求間隔秒數，最低 0.5）。中斷後用同一個 `--output` 再跑一次即可續抓；已完成且大小相符的檔案不再下載。

預估：全部音訊約 27GB（經文 1,189 章，每章約 4–8MB；生命讀經約 2,000 篇，每篇約 2–10MB），以每秒 1 個請求計算，全部約需數小時，視網速而定。

## 輸出

每次執行結束會在輸出資料夾重寫 README.md，內容包括抓取範圍、資料夾結構、各類檔案數量與大小、失敗數。另外有：

- manifest.jsonl：每個完成檔案的 path、url、kind、bytes、sha256、fetched_at，以及卷、章或篇。
- errors.jsonl：本次失敗項目，重新執行時會自動補抓。

純文字是從原始 HTML 的 `#verses` 主內容衍生出來的：移除導覽列，經節號碼與經文合成一行；原始網頁另外保存、不修改。

生命讀經音訊是講者導讀，不是網頁文字的逐字朗讀，不能直接當作逐字稿配對。

## 驗證

```bash
python -m unittest test.test_twgbr_archive
```

測試用的是合成網頁，沒有連網，涵蓋：只允許兩個主機、經文格式整理、續抓不重下、上下卷去重、非 MP3 回應記為錯誤、README 與 manifest 的產生。
