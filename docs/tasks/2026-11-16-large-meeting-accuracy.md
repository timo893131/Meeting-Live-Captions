# 工作卡：大型聚會最高準確度（綱要校正＋微調 Whisper）

- 任務 ID／日期：2026-11-16-large-meeting-accuracy
- 狀態：in progress（M0 同音放寬第 3 輪仍 unrun；M1、M2 已上線；M3 試跑第 1 次完成、已修正，待重跑試跑）
- 規格：[../spec-large-meeting.md](../spec-large-meeting.md)（目標、使用者決策、里程碑、契約、驗收門檻、風險）
- 主分類：speech-finetuning；次分類依里程碑：meeting-ui-ux、meeting-realtime、speech-data-preparation、speech-evaluation、meeting-verification-release。
- 基準：main 1e04c38（正式網站）；開發分支 `claude/peaceful-keller-kbipya`（PR #16）；MEET 網站條件 CER 14.49%、專名 93/124。
- 費用：零；Colab 免費 GPU、Modal Starter 免費額度（須設上限）、Cloudflare 免費方案。

## 決策與進度

| 里程碑 | 狀態 | 下一步 |
| --- | --- | --- |
| M0 收尾（同音放寬第 3 輪、PR #16） | 2026-11-16：Drive 最新結果 `20261114-135356-near` 是**第 2 輪**（早於第 3 輪 commit 121384b；正確全文多改 664 處）。第 3 輪 unrun。`test_colab_notebook` 既存失敗已修（套用 b316493）。 | 使用者說已跑，但 2026-11-16 Drive 上找不到新的 `*-near` 結果（最新仍是第 2 輪）→ 請使用者確認第 4、5 格是否有錯誤 |
| M1 綱要輸入與本場詞表 | 實作完成（b926ac6）：`public/outline.js`、設定「本場綱要」、`evaluate_meet.py --outline`；綱要轉換見 [../outline-conversion.md](../outline-conversion.md) | **已上線**（PR #17 合併 28c75a7，2026-11-16 正式網址驗證通過） | M2 |
| M2 經文對齊 | 第一步已上線（PR #21）；第二步開發集第 3 輪通過「不改壞」標準（使用者 2026-11-17 決定），PR #22 合併；2026-11-18 正式網址驗證通過 | M3 |
| M3 訓練資料 | 程式完成（cd0acf9）；2026-11-18 試跑第 1 次（每種來源 5 個錄音）後修正（089e2c2）：改以讀音對齊與計 CER、詩篇 2–150 篇沒有經文（標題是「篇」）、重切時刪除舊片段 | 使用者重跑試跑（轉寫結果沿用，只重切）→ 讀報告、抽聽 → 全部執行 |
| M4 微調 | 未開始 | — |
| M5 Modal 部署 | 未開始 | 使用者申請 Modal |
| M6 MEET 驗收與彩排 | 未開始 | — |

## 驗證證據

| 檢查 | 方式 | 結果 | 版本／日期 |
| --- | --- | --- | --- |
| 同音放寬第 3 輪 | `notebooks/phonetic_near_check.ipynb` dev | unrun | 121384b |
| 綱要轉換 | `test.test_outline_pdf_to_md`（含 PyMuPDF 產生的真 PDF） | passed | 1903508 |
| 範例綱要轉換（文字層） | Colab `outline_to_markdown.ipynb` | passed（執行成功；87 頁無文字層） | 1903508 |
| 綱要 OCR | `test.test_outline_ocr`（假 OCR／假 Drive 服務；真 PDF 轉圖） | passed | 253ab13 |
| M1 單元／UI 測試 | `npm test`（56）、`ui-smoke`（18，含綱要不經 WebSocket）、Python 49 | passed | b926ac6 |
| M1 開發集（第 1 輪） | Colab `outline_check.ipynb` | failed：專名 805→815（門檻 +31）、改壞 23／修好 53；原文誤改 0；本場新詞 195→214/244、多出 0。主因：near 蓋掉聲調容錯（汴亞敏）＋全形數字 | b926ac6 |
| M1 開發集（第 2 輪） | 同上（run 20261116-064428-outline） | 教會專名 805→815（**未達 +31 門檻**）、多出 63→63；人名地名 368→369、多出 89→97；修好 36／改壞 2（達 ≤1/5）；CER 47.00%→46.95%；本場新詞 229→248/287、多出 0；正確原文誤改 0 | b291e7f |
| M1 正式網址 | health、靜態檔與 main 28c75a7 一致、`smoke-cloudflare`（房間／密碼／邀請／廣播／刪除）、瀏覽器：房主貼綱要＋觀眾加入＋模擬 Chrome 語音「以沙／彼烈」→「以撒／彼列」兩端一致、綱要不經 WebSocket、觀眾看不到設定、桌面與手機無橫向捲動；測試房間已刪除（200） | passed | 28c75a7 |
| 綱要選檔（PR #18–#20） | 正式網址 fdce04b：靜態檔（含 pdf.js、tesseract.js、chi_tra）與 main 一致；瀏覽器實測文字型 PDF 0.7 秒、掃描型 PDF（測試檔 2 頁）瀏覽器 OCR 3.5 秒，皆分 2 篇、篇題與經節正確、無外部連線、無頁面錯誤；`smoke-cloudflare` passed。真實 TS26TRN 掃描檔的瀏覽器辨識速度／準確度 unrun（使用者決定不量測） | passed | fdce04b |
| M2 經文 API（正式網址） | e5d9c28：health `verses:true`；`smoke-cloudflare`（`CAPTION_TEST_VERSE=弗1:23`）2 passed：房主可讀、無房間／無權杖／觀眾邀請／錯誤經節／已結束房間拒絕、`no-store`；抽查 創1:1、詩23:1、詩119:105、詩150:6、俄1:21、門1:25、猶1:24-25、約壹5:12、啟22:21、弗1:22-23、瑪4:6 共 13 節全有；測試房間已刪除 | passed | e5d9c28 |
| M2 經文對齊開發集（第 1 輪） | `verse_align_check.ipynb` | 恢復本朗讀 20 章 CER 12.55%→5.55%（修好 1221／改壞 2）；生命讀經講解：經文對齊修好約 40／改壞約 37 → **未過**（講員插話、改寫經文被換掉） | 8ad5dd9 |
| M2 經文對齊開發集（第 2 輪） | 同上（只重新計分） | 恢復本朗讀：換 667 段、變差 0（CER 12.55%→5.60%）；生命讀經：換 66 段，變好 20／一樣 41／變差 5（92.4%，門檻 99%）→ 未過；變差的都是講員讀舊譯本措辭 | 6da6fd7 |
| M2 經文對齊開發集（第 3 輪） | 同上 | 恢復本朗讀：換 667 段、變差 0、CER 12.55%→6.06%（修好 1132／改壞 2）；生命讀經：換 66 段、變好 22／一樣 42／變差 2（97%；同音舊措辭）、經文對齊修好 27／改壞 3；使用者決定以不改壞標準上線 | a85cf7c |
| M2 經文對齊（正式網址） | 3c62028：靜態檔（`/`、app.js、verse-align.js、outline.js、phonetic.js、bible-abbreviations.js、style.css）與 main 一致；`smoke-cloudflare`（`CAPTION_TEST_VERSE=弗1:23`）2 passed；瀏覽器（Playwright，模擬 Chrome 語音，非真人收音）：房主貼綱要（讀經 弗一22～23）→ 載入經文 2 節；朗讀弗一23 無標點且含同音錯字 2 處（祂→他、豐→風）→ 房主與觀眾（邀請連結）都顯示恢復本原文＋「（弗一23）」；一般句子不變、不加經節；觀眾看不到綱要與設定；桌面 1280／手機 390 無橫向捲動；無頁面錯誤；測試房間已刪除（200） | passed | 3c62028 |
| M3 資料管線（合成資料） | `.venv/bin/python -m unittest test.test_twgbr_training_data test.test_cloud_training_data test.test_colab_notebook`：對齊／切段（含講員插話不進標籤、短停頓只在標點處切）、計畫排除開發集與多音檔、manifest 通過 gate、gate 拒絕錯誤權利依據／超過門檻／封存 test 用原文標籤、續跑不重做、筆記本未執行且固定版本 | passed（21） | cd0acf9 |
| M3 試跑第 1 次 | Colab `twgbr_training_data.ipynb`（TRIAL，各 5 個錄音） | 執行成功：恢復本音訊 0.47 小時→片段 0.24 小時（原文覆蓋 55.5%，對齊 CER 平均 5.7%）；生命讀經 2.0→1.21 小時（覆蓋 60.9%，CER 6.1%）；退回 29 段（CER）；排除：開發集 20＋16、詩篇 149 章（**錯誤：沒有經文**）、生命讀經篇數上限 1,848 | cd0acf9 |
| M3 讀音對齊（本機重算試跑的轉寫結果） | 士師記 6 章：覆蓋 71%→98%、退回 5→0、對齊 CER（讀音）0–1%；出埃及記生命讀經 29 篇：覆蓋 79%→85%；標籤是原文（民書記→民數記、進池→浸池）；`unittest` 13＋gate 4＋notebook 4 passed | passed（本機重算；Colab 重跑 unrun） | 089e2c2 |
| 範例綱要 OCR | Colab `outline_ocr.ipynb` | **passed**：12 篇與篇題全對、無警告；經文 911 節 OCR 錯字率 0.27%（含印刷用字差異 1.06%） | 5eb91f6 |
| Colab 筆記本測試 | `test.test_colab_notebook` | passed（6） | 2026-11-16 |

## 交接

- 已完成：規格、使用者決策紀錄、免費部署選項查核（Modal Starter US$30／月額度；Workers AI 不能放自訂 Whisper；Colab／ZeroGPU／Oracle 不適合即時服務）。
- 未解：spec 第 8 節第 3 項（Modal）M5 前再確認；第 2 項 R2 已同意（第 1 項綱要範例已提供，等轉換結果）。
- 2026-11-16 使用者：大型聚會一天約 8 小時，平常聚會 2–3 小時；**先把準確度與穩定度做到最好**，時數／額度之後再考慮（可能提高預算）。注意 Workers AI 免費額度約 3.5 小時／天。
- token／wall time／費用：unavailable。
