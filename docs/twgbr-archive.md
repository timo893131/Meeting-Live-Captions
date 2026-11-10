# TWGBR 私人離線下載程式

`scripts/download_twgbr_archive.py` 把使用者指定的兩個系列整理成一個資料夾：恢復本聖經（文字＋每章音訊）與生命讀經（每篇文字＋音訊）。使用者說明為個人／內部使用、不對外發布。內容 CopyrightⒸ 臺灣福音書房；不轉散布，未經授權不用於模型訓練。

## 範圍（寫死在程式內，不追蹤其他連結）

| 系列 | 來源 |
| --- | --- |
| 恢復本經文 | https://line.twgbr.org/recoveryversion/bible/01–66.html（每卷一頁含全部章） |
| 恢復本音訊 | 頁面播放器載入的 https://plan.bible365.today/plan/mp3/bible/<卷>/<章>-<書名>.mp3 |
| 生命讀經 | https://line.twgbr.org/life-study/1–66.html 及其連到的每篇 `<n>_<k>.html` |
| 生命讀經音訊 | 每篇頁面 `<audio>` 的 MP3（line.twgbr.org/life-study/mp3/…） |

66 卷每卷都有自己的資料夾，一律使用標準書名（01-創世記 … 66-啟示錄）。撒母耳記、列王紀、歷代志的上下卷在網站上是同一套生命讀經，兩卷都會保存；相同的 MP3 只下載一次，另一卷用本機複製。

經文音訊網址規則已對照網站實測：章號用兩位數（`01-Genesis.mp3`），詩篇 150 章用三位數（`001-Psalms.mp3`）；書名中的空白要編碼（`01-1%20Samuel.mp3`）；章數以經文中的章標題計算（約翰參書頁面播放器寫 5 章，實際 1 章）。

## 使用

只需要 Python 3.10+ 與 beautifulsoup4，可以在自己的電腦執行：

```bash
pip install beautifulsoup4
```

```bash
python scripts/download_twgbr_archive.py --output twgbr-archive
```

常用選項：`--zip twgbr.zip`（完成後打包；中文檔名有 UTF-8 標記，Windows 解壓不會變亂碼）、`--no-audio`（只抓文字＋原始網頁）、`--collections bible` 或 `life-study`、`--books 1-5,40`、`--limit-per-book 2`（試跑）、`--interval 1`（每次請求間隔秒數，最低 0.5）。中斷後用同一個 `--output` 再跑一次即可續抓；已完成且大小相符的檔案不再下載。

預估：全部音訊約 27GB（經文 1,189 章，每章約 4–8MB；生命讀經 1,984 個不重複音訊，每篇約 2–10MB），以每秒 1 個請求計算，全部約需數小時，視網速而定。

## 用 Google Colab 下載到 Google Drive（不用自己的電腦）

開啟 [notebooks/download_twgbr_archive.ipynb](../notebooks/download_twgbr_archive.ipynb)（Colab：檔案 → 開啟筆記本 → GitHub），由上而下逐格執行。資料直接存到「我的雲端硬碟/twgbr-archive」。筆記本會取得固定 commit 的程式並核對 SHA-256，再用 `--quiet` 執行；第 5 格逐卷檢查是否完成，並把檔案同步到 Drive。Colab 斷線時，重新從第 1 格執行即可續抓。

## 公司網路／HTTPS 檢查（CERTIFICATE_VERIFY_FAILED）

若出現 `self-signed certificate in certificate chain`，代表網路會重新簽署 HTTPS（常見於公司網路或防毒軟體）。程式會在第一次失敗時停止並顯示說明。處理方式（不關閉憑證驗證）：

```bash
python -m pip install truststore
```

安裝後程式會自動改用作業系統的憑證庫，與瀏覽器相同。若仍失敗，從瀏覽器匯出網站憑證路徑最上層的根憑證（Base-64 .cer），再加上 `--ca-bundle company-root.cer`。

## 輸出

每次執行結束會在輸出資料夾重寫 README.md，內容包括抓取範圍、資料夾結構、各類總數、66 卷逐卷清單（已存數／網站應有數）與失敗數。另外有：

- manifest.jsonl：每個完成檔案的 path、url、kind、bytes、sha256、fetched_at，以及卷、章或篇。
- errors.jsonl：本次失敗項目，重新執行時會自動補抓。

純文字是從原始 HTML 的 `#verses` 主內容衍生出來的：移除導覽列，經節號碼與經文合成一行；原始網頁另外保存、不修改。

生命讀經音訊是講者導讀，不是網頁文字的逐字朗讀，不能直接當作逐字稿配對。

## 驗證

```bash
python -m unittest test.test_twgbr_archive
```

測試用的是合成網頁，沒有連網，涵蓋：只允許兩個主機、經文格式整理、續抓不重下、上下卷都保存且共用音訊只下載一次、經文音訊網址規則、沒有引號的章數、zip 的 UTF-8 檔名、非 MP3 回應記為錯誤、README 與 manifest 的產生。
