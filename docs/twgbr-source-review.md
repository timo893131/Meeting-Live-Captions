# 指定來源盤點：TWGBR

## 範圍與實測結果

使用者指定恢復本聖經與生命讀經作為候選來源，並確認尚未取得模型訓練授權；本階段僅完成來源盤點與技術檢查。先前開發環境的網路代理拒絕已解除，現在可以存取指定網站。

| 頁面 | 已取得的證據 | 範圍 |
| --- | --- | --- |
| https://line.twgbr.org/recoveryversion/bible/01.html | 《創世記》恢復本；主內容有連續 1–50 章，257 個正文段落容器 | 合併多章的一頁；含綱目與正文 |
| https://line.twgbr.org/life-study/ | 索引提供編號 1–66 的書卷入口 | 已盤點連結，未下載全部書卷 |
| https://line.twgbr.org/life-study/1.html | 第一篇；48 個正文段落、約 6,865 字元，對應 Gen-001.mp3；同頁列出 1–120 篇入口 | 只抽查第一篇，未下載 120 篇 |
| https://line.twgbr.org/life-study/1_2.html | 第二篇；37 個正文段落、約 7,101 字元，對應 Gen-002.mp3 | 只抽查第二篇 |

段落數是 HTML `p.calibre2` 容器數，字元數是指定選擇器的可見文字長度，不代表音訊句數、詞彙數或已核對逐字稿。主內容為 `#verses`，移除導航、按鈕及播放器，保留綱目。只驗證目前創世記樣本，不宣稱所有書卷通用。

生命讀經頁面標示 `CopyrightⒸ 2016-2025 臺灣福音書房`。這是權利聲明線索，不是訓練、批量重製或發布授權。配置仍為 rights_status=pending、allowed_uses=[]，所有報告 training_ready=false。

## 音訊技術檢查

第二篇：`https://line.twgbr.org/life-study/mp3/ot/Gen-002.mp3`。

- HEAD 回應 200，MIME audio/mpeg，Content-Length 8,571,342 bytes，支援 byte ranges。
- 以 `bytes=0-131071` 抽查前 128 KiB，回應 206，Content-Range 與實際大小吻合。
- ffprobe 觀察到 MP3、22,050 Hz、單聲道、32,000 bit/s。
- 前段樣本與 SHA-256 存於忽略的本機資料位置；未下載完整音訊或提交 Git。

沒有驗證完整時長、全文音訊品質、語音轉寫或逐字對齊。低碼率及來源錄音環境對辨識的影響，需在允許用途確認後另外測量。

`Gen-001`／`Gen-002` 與標題篇號相符，只證明索引配對方式可辨識，不證明正文是錄音逐字稿。開頭／結尾、補充、引用與省略需人工核對及時間對齊，不能把整篇文字直接標成 gold reference。

## 工具與可重現步驟

配置：[sources/twgbr-review.json](../sources/twgbr-review.json)，包含原始來源與兩篇已檢查樣本，不遞迴抓取。解析工具版本固定於 requirements-data.txt；沒有安裝或執行 ASR／訓練引擎。

```sh
python -m venv .venv
.venv/bin/python -m pip install --cache-dir /workspace/.pip-cache -r requirements-data.txt
python scripts/review_sources.py --config sources/twgbr-review.json --output data/source-review/twgbr
.venv/bin/python scripts/inspect_twgbr.py --report data/source-review/twgbr/review-report.json
.venv/bin/python scripts/probe_audio.py --url https://line.twgbr.org/life-study/mp3/ot/Gen-002.mp3 --output data/source-review/twgbr-audio-probe
```

此雲端已有 ffprobe。其他環境需準備 FFmpeg／ffprobe，缺少時不會宣稱已驗證音訊。音訊工具要求合法 206／Content-Range；若 Range 被忽略，不讀取整個檔案，只探測前段，不播放、辨識或訓練。

本次盤點直接合併三份已取得的 review report，未為了合併重新下載頁面：

```sh
.venv/bin/python scripts/inspect_twgbr.py \
  --report data/source-review/twgbr/review-report.json \
  --report data/source-review/twgbr-book-1/review-report.json \
  --report data/source-review/twgbr-message-2/review-report.json
```

先查 robots.txt；本次回傳 404，表示未提供該檔，不表示授予使用權。預設最多 6 次請求嘗試（含 robots／重導）、每回應 1 MB、20 秒 timeout、同站至少間隔 1 秒、僅指定 HTTPS host；失敗、不明規則、過大／錯格式時停止該項並回傳失敗。

輸出位於 Git 忽略的 data/source-review：原始 HTML／音訊前段、SHA-256、檢查文字、來源／權利線索及結構／音訊報告。原文不以清洗結果覆寫，也不發布到字幕網站。

## 驗證與下一階段

```sh
.venv/bin/python -m unittest discover -s test -p 'test_source_review.py' -v
.venv/bin/python -m unittest discover -s test -p 'test_twgbr_inspection.py' -v
```

來源工具 10 項合成測試、結構／音訊工具 8 項合成測試，另實際讀取上述 4 頁並執行受限音訊探測。測試驗證網域、robots、編碼、雜湊、選擇器及 Range 防護，不代表語音準確率或人工逐字對齊。

接續工作：

1. 保留候選來源盤點，整理詞彙分類與評估規格；不批量爬取或訓練。
2. 分別確認 vocabulary、internal_evaluation、training、publication 的可允許用途與權利依據。
3. 用途允許後再挑少量代表篇章，人工核對聲音／文字、分段、對齊，保留原文／原音及版本。
4. 正確詞彙由來源與人工審查取得；常見誤識來自真實辨識結果，不憑空製造替換。加入一般中文負向案例，避免多義詞誤改。
5. 先評估詞彙／提示是否足夠；若仍需 ASR 微調，再確認音訊權利、train／validation／sealed test、baseline、硬體及預算。
