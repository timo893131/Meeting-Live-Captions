# 工作卡：大型聚會最高準確度（綱要校正＋微調 Whisper）

- 任務 ID／日期：2026-11-16-large-meeting-accuracy
- 狀態：in progress（M0 等 Colab 結果；M1 前置：綱要轉換工具完成）
- 規格：[../spec-large-meeting.md](../spec-large-meeting.md)（目標、使用者決策、里程碑、契約、驗收門檻、風險）
- 主分類：speech-finetuning；次分類依里程碑：meeting-ui-ux、meeting-realtime、speech-data-preparation、speech-evaluation、meeting-verification-release。
- 基準：main 1e04c38（正式網站）；開發分支 `claude/peaceful-keller-kbipya`（PR #16）；MEET 網站條件 CER 14.49%、專名 93/124。
- 費用：零；Colab 免費 GPU、Modal Starter 免費額度（須設上限）、Cloudflare 免費方案。

## 決策與進度

| 里程碑 | 狀態 | 下一步 |
| --- | --- | --- |
| M0 收尾（同音放寬第 3 輪、PR #16） | 2026-11-16：Drive 最新結果 `20261114-135356-near` 是**第 2 輪**（早於第 3 輪 commit 121384b；正確全文多改 664 處）。第 3 輪 unrun。`test_colab_notebook` 既存失敗已修（套用 b316493）。 | 使用者說已跑，但 2026-11-16 Drive 上找不到新的 `*-near` 結果（最新仍是第 2 輪）→ 請使用者確認第 4、5 格是否有錯誤 |
| M1 綱要輸入與本場詞表 | 前置完成：`scripts/outline_pdf_to_md.py`＋`notebooks/outline_to_markdown.ipynb`，方法見 [../outline-conversion.md](../outline-conversion.md)。範例 `ex_TS26TRN_zht.pdf` 87 頁全是圖片（無文字層）→ 新增 `scripts/outline_ocr.py`＋`notebooks/outline_ocr.ipynb`（Google 雲端硬碟 OCR＋自動檢查）。 | 綱要轉換完成（outline-conversion.md）→ 開始 `public/outline.js`＋房主「本場綱要」輸入 |
| M2 經文對齊 | 未開始；2026-11-16 使用者**同意**恢復本經文存 Cloudflare R2 私人 bucket、只給房主讀取 | M1 之後 |
| M3 訓練資料 | 未開始 | — |
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
| 範例綱要 OCR | Colab `outline_ocr.ipynb` | **passed**：12 篇與篇題全對、無警告；經文 911 節 OCR 錯字率 0.27%（含印刷用字差異 1.06%） | 5eb91f6 |
| Colab 筆記本測試 | `test.test_colab_notebook` | passed（6） | 2026-11-16 |

## 交接

- 已完成：規格、使用者決策紀錄、免費部署選項查核（Modal Starter US$30／月額度；Workers AI 不能放自訂 Whisper；Colab／ZeroGPU／Oracle 不適合即時服務）。
- 未解：spec 第 8 節第 3 項（Modal）M5 前再確認；第 2 項 R2 已同意（第 1 項綱要範例已提供，等轉換結果）。
- 2026-11-16 使用者：大型聚會一天約 8 小時，平常聚會 2–3 小時；**先把準確度與穩定度做到最好**，時數／額度之後再考慮（可能提高預算）。注意 Workers AI 免費額度約 3.5 小時／天。
- token／wall time／費用：unavailable。
