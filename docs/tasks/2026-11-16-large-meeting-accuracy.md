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
| M0 收尾（同音放寬第 3 輪、PR #16） | 2026-11-16：Drive 最新結果 `20261114-135356-near` 是**第 2 輪**（早於第 3 輪 commit 121384b；正確全文多改 664 處）。第 3 輪 unrun。`test_colab_notebook` 既存失敗已修（套用 b316493）。 | 使用者跑 `phonetic_near_check.ipynb`（COMMIT 121384b）→ 我讀結果 |
| M1 綱要輸入與本場詞表 | 前置完成：`scripts/outline_pdf_to_md.py`＋`notebooks/outline_to_markdown.ipynb`，方法見 [../outline-conversion.md](../outline-conversion.md)。範例 `ex_TS26TRN_zht.pdf`（62 MB）無法在此環境讀取。 | 使用者跑 `outline_to_markdown.ipynb` → 我讀 Markdown／報告，調整標號規則 → `public/outline.js` |
| M2 經文對齊 | 未開始 | 等使用者同意 R2 存經文 |
| M3 訓練資料 | 未開始 | — |
| M4 微調 | 未開始 | — |
| M5 Modal 部署 | 未開始 | 使用者申請 Modal |
| M6 MEET 驗收與彩排 | 未開始 | — |

## 驗證證據

| 檢查 | 方式 | 結果 | 版本／日期 |
| --- | --- | --- | --- |
| 同音放寬第 3 輪 | `notebooks/phonetic_near_check.ipynb` dev | unrun | 121384b |
| 綱要轉換 | `test.test_outline_pdf_to_md`（含 PyMuPDF 產生的真 PDF） | passed | 1903508 |
| 範例綱要轉換 | Colab `outline_to_markdown.ipynb` | unrun | — |
| Colab 筆記本測試 | `test.test_colab_notebook` | passed（6） | 2026-11-16 |

## 交接

- 已完成：規格、使用者決策紀錄、免費部署選項查核（Modal Starter US$30／月額度；Workers AI 不能放自訂 Whisper；Colab／ZeroGPU／Oracle 不適合即時服務）。
- 未解：spec 第 8 節第 2、3 項待使用者確認（第 1 項綱要範例已提供，等轉換結果）。
- 2026-11-16 使用者：大型聚會一天約 8 小時，平常聚會 2–3 小時；**先把準確度與穩定度做到最好**，時數／額度之後再考慮（可能提高預算）。注意 Workers AI 免費額度約 3.5 小時／天。
- token／wall time／費用：unavailable。
