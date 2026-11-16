# 工作卡：大型聚會最高準確度（綱要校正＋微調 Whisper）

- 任務 ID／日期：2026-11-16-large-meeting-accuracy
- 狀態：ready（規格完成，等新對話開工）
- 規格：[../spec-large-meeting.md](../spec-large-meeting.md)（目標、使用者決策、里程碑、契約、驗收門檻、風險）
- 主分類：speech-finetuning；次分類依里程碑：meeting-ui-ux、meeting-realtime、speech-data-preparation、speech-evaluation、meeting-verification-release。
- 基準：main 1e04c38（正式網站）；開發分支 `claude/peaceful-keller-kbipya`（PR #16）；MEET 網站條件 CER 14.49%、專名 93/124。
- 費用：零；Colab 免費 GPU、Modal Starter 免費額度（須設上限）、Cloudflare 免費方案。

## 決策與進度

| 里程碑 | 狀態 | 下一步 |
| --- | --- | --- |
| M0 收尾（同音放寬第 3 輪、PR #16） | 等使用者跑 Colab | 讀 near-check 結果 → 決定 MEET 驗收 |
| M1 綱要輸入與本場詞表 | 未開始 | 等綱要範例 |
| M2 經文對齊 | 未開始 | 等使用者同意 R2 存經文 |
| M3 訓練資料 | 未開始 | — |
| M4 微調 | 未開始 | — |
| M5 Modal 部署 | 未開始 | 使用者申請 Modal |
| M6 MEET 驗收與彩排 | 未開始 | — |

## 驗證證據

| 檢查 | 方式 | 結果 | 版本／日期 |
| --- | --- | --- | --- |
| 同音放寬第 3 輪 | `notebooks/phonetic_near_check.ipynb` dev | unrun | 121384b |

## 交接

- 已完成：規格、使用者決策紀錄、免費部署選項查核（Modal Starter US$30／月額度；Workers AI 不能放自訂 Whisper；Colab／ZeroGPU／Oracle 不適合即時服務）。
- 未解：spec 第 8 節四項待使用者確認。
- token／wall time／費用：unavailable。
