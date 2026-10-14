# 指定來源檢查：TWGBR

## 指定資源與目前狀態

| source_id | 使用者提供的網址 | 已確認事項 | 未確認事項 |
| --- | --- | --- | --- |
| twgbr-recoveryversion-seed | https://line.twgbr.org/recoveryversion/bible/01.html | URL 已登錄 | 頁面結構、實際書卷／版本、文字權利、可允許用途 |
| twgbr-life-study-seed | https://line.twgbr.org/life-study/ | URL 已登錄 | 索引／文件結構、是否提供音訊、文字及音訊權利 |

首次直接連線遭執行環境代理拒絕（CONNECT 403），請求未到達來源網站。工具實際執行時也無法取得 robots.txt，兩個來源尚未取得任何頁面。這不是來源網站禁止爬取或部署失敗的證據。

已保留既有自訂網路規則，僅在 Codex 雲端環境草稿追加 `line.twgbr.org`。草稿保存不等於執行環境已套用；需在環境設定檢閱、儲存並發布後確認連線。不要改 Cloudflare 網站設定來處理這個開發環境的出口問題。

## 可以重跑的檢查

配置：[sources/twgbr-review.json](../sources/twgbr-review.json)。工具僅使用 Python 標準函式庫，無額外 pip 安裝。

```sh
python scripts/review_sources.py --config sources/twgbr-review.json --output data/source-review/twgbr
python -m unittest discover -s test -p 'test_source_review.py' -v
```

來源檢查僅取得使用者指定的兩個 seed，不遞迴追蹤連結、下載全文庫或抓音訊。先查 robots.txt；若無法確認規則、不允許 seed、回應過大或格式不適合，就記錄失敗。404 表示未提供 robots，不表示授予任何資料使用權。

預設最多 6 次來源請求嘗試（含 robots 與重導），同一網域至少間隔 1 秒，每次回應最多 1 MB，20 秒 timeout，僅 HTTPS 及指定網域；外站重導會被拒絕，允許的重導也共用速率與請求預算。支援可解析的 Crawl-delay；必要等待超過此次有限檢查範圍時延期，不忽略規則。程式沒有盲目重試或繞過代理／網站存取控制。

輸出位於 Git 忽略的 data/source-review/twgbr：

- 原始 HTML 與 SHA-256，同內容採相同檔名，原文不以正規化結果覆寫。
- 檢查用可見文字、編碼、頁面標題、同站連結及可能的權利聲明線索。
- robots 的原文／hash 或不可用狀態、各來源結果與請求數。
- review-report.json；有來源失敗時程式退出碼為 1，不能當作成功爬取。

解析器以合成 HTML 測試；尚未驗證真實站點的主內容選擇器。它會保留選單及 footer 供檢查，文字檔不是乾淨的聖經正文或已核准語料。HTTP／HTML charset 支援 Big5 等可解碼格式；不悄悄用替代字元把損壞內容當有效中文。

## 連線可用後的下一步

1. 實際取得 robots 與兩個 seed，確認所列書卷、資料版本、網站權利聲明及官方可用的匯出方式。
2. 依真實 HTML 選擇主內容，排除導航／廣告／重複頁；抽查篇章、章節與文字完整性。
3. 明確登錄 vocabulary、internal_evaluation、training、publication 等用途的權利依據，不由公開可讀或網址名稱推定授權。
4. 若來源可供詞彙用途，整理書卷／人物／地名、屬靈概念與教會常用搭配；保存 canonical、來源與人工審查狀態。
5. 常見誤識需由實際辨識記錄或測試取得，不從正確文本憑空製造「模型常錯」的替換。一般中文的負向案例也需納入，避免錯改「交通」等多義詞。
6. 與既有 glossary 比較、人工核對、離線回測，再採用通過的校正；來源文章不直接變成可發布的產品內容。
7. 若要微調自有 ASR，確認可訓練的音訊、對應人工逐字稿與資料切分；文字庫本身不能替代這些資料。模型、算力及訓練預算另依 speech-finetuning 工作流執行。

目前兩個來源在配置中均為 rights_status=pending、allowed_uses=[]。來源工具始終標 review_only=true、training_ready=false，不會因爬取成功而宣稱訓練資料已就緒；用途核准與資料準備是另外的階段。
