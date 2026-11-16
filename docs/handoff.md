# 交接摘要（2026-11-16）

新對話先讀本檔，再讀 **[spec-large-meeting.md](spec-large-meeting.md)**（目前要做的開發），然後依 AGENTS.md 路由。
本檔只寫現況、決策與下一步，不重述歷史。

## 使用者與工作方式

- 繁體中文溝通。服務教會聚會（地方召會；恢復本、生命讀經用語）。
- **零費用、全部雲端、沒有自己的伺服器或 GPU**：網站用 Cloudflare 免費方案；GPU 工作用 Google Colab（免費 T4）；資料在使用者 Google Drive（`twgbr-archive/`）。即時微調模型的部署選 Modal 免費額度（見 spec）。
- 發布：開發分支 → PR → 使用者審核合併 → main 自動部署 → 用正式網址驗證（health、房間、瀏覽器實測）。不 force-push。
- 介面維持原本的**淺藍風格**。
- 使用者在 Colab 跑筆記本後，會說「直接讀」：用 Google Drive 工具讀 `eval-runs/<最新>/summary.md` 等結果。

## 正式網站

https://meeting-live-captions.livecap-worker.workers.dev（Worker `meeting-live-captions`，main 自動部署）

| 功能 | 現況 |
| --- | --- |
| 辨識 | 預設 Workers AI Whisper large-v3-turbo（`POST /api/transcribe`）：瀏覽器停頓切段（5 秒後遇 0.3 秒停頓、或 1.5 秒停頓、最長 9 秒）；Worker 轉繁體、濾幻聽。Chrome `SpeechRecognition` 當灰字預覽；額度用完／連續失敗改用 Chrome。 |
| 額度 | 每天 10,000 neurons ≈ 214 音訊分鐘，UTC 0 點（台灣 08:00）重置；`SpeechLimit` 每 IP 每天 4 小時、每分鐘 40 段。 |
| 校正 | 同音教會專名校正 `public/phonetic.js`（書卷、教會專名、人名地名、一律校正詞）；詞彙校正表預設空白。 |
| 本場綱要 | 設定裏貼上當堂綱要（只存在房主瀏覽器）：綱要用到的內建專名本場接受相近讀音，綱要中的新詞加入同音校正（`public/outline.js`，M1，2026-11-16 上線）。綱要 PDF／掃描檔用 `notebooks/outline_ocr.ipynb` 轉成每篇 Markdown（[outline-conversion.md](outline-conversion.md)）。 |
| 房間 | 個人／廣播／加入（密碼、邀請連結、QR）；Workers 版字幕存 Durable Object，結束或 12 小時刪除；Node 版只存記憶體。 |

## 量測基準

| 資料 | 用途 | 網站現況 |
| --- | --- | --- |
| MEET 3 場（Drive `twgbr-archive/MEET/`） | **封存測試**：只驗收一次，不訓練、不依它調整 | CER 14.49%、教會專名 93/124、延遲中位數 10.3／P95 13.1 秒 |
| 生命讀經開發集 16 篇（`life-study-dev-v1/`） | 找詞、調規則；音訊是導讀不是逐字 → 用「專名找到／多出」 | 教會專名 805/1037（多出 63）、人名地名 368/428（多出 89） |
| 恢復本開發集（`bible-dev-v1`，`scripts/build_bible_dev_set.py`） | 章朗讀＋經文，接近逐字 | — |
| 恢復本＋生命讀經正確全文 | 校正規則誤改檢查（`scripts/term-precision.mjs`） | 網站現況 359 處 |

細節見 [meet-evaluation.md](meet-evaluation.md)。

## 資料與權利

- TWGBR（恢復本經文＋音訊、生命讀經文字＋音訊）在 Drive `twgbr-archive/`。版權臺灣福音書房。
- **2026-11-16 使用者決定**：只在內部使用，取消「不用於訓練」限制，可用於微調；未取得出版者授權。音訊、文字、模型權重都不進 Git、不公開。
- MEET 仍封存。

## 最近完成（PR #16，待使用者審核）

- 上下文校正實驗（Whisper 提示／Workers AI 語言模型）：**未通過、不採用**，見 [context-correction-experiment.md](context-correction-experiment.md)。
- 同音放寬 `phoneticCorrect(..., {near:true})`（預設關閉）：第 1、2 輪未通過；第 3 輪只對書卷與教會用語放寬（排除 `NEAR_SKIP`、`NEAR_PROTECT`），離線估計開發集多改 54 處（約 1 處錯）、正確全文多改約 12 處，**等 Colab `notebooks/phonetic_near_check.ipynb`（COMMIT 121384b）結果**。

## 下一步

1. 依 [spec-large-meeting.md](spec-large-meeting.md) 執行：M0 收尾 → M1 綱要輸入 → M2 經文對齊 → M3 訓練資料 → M4 微調 → M5 Modal 部署 → M6 MEET 驗收與彩排。進度記在 [tasks/2026-11-16-large-meeting-accuracy.md](tasks/2026-11-16-large-meeting-accuracy.md)。
2. 開工前向使用者確認 spec 第 8 節（R2 存經文、Modal 帳號、聚會規模）。綱要範例已在 Drive（`ex_TS26TRN_zht.pdf`），轉換方法與工具見 [outline-conversion.md](outline-conversion.md)。
3. 收音：現場用混音器直接接線，仍是最便宜、效果最大的改善。

## 主要程式與筆記本

| 用途 | 檔案 |
| --- | --- |
| 前端 | `public/app.js`、`speech-chunker.js`、`phonetic.js`、`church-terms.js`、`always-corrected.js`、`bible-names.js`、`pinyin-zh.js`（產生檔）、`context-correct.js`（實驗，未載入） |
| Worker | `cloudflare/worker.js`、`cloudflare/transcript.js`、`wrangler.jsonc` |
| 讀音表 | `scripts/build-pinyin-table.py`（改 church-terms 後重建） |
| 評估 | `scripts/evaluate_meet.py`（`--reuse`、`--development`、`--loose-reference`、`--phonetic-near`）、`scripts/term-precision.mjs`、`scripts/context_experiment.py`／`context-experiment.mjs` |
| 資料 | `scripts/download_twgbr_archive.py`、`build_life_study_dev_set.py`、`build_bible_dev_set.py`、`cloud_training_data.py` |
| 訓練 | `scripts/train_cloud_whisper.py`、`notebooks/cloud_whisper_lora.ipynb`（舊版：whisper-small、20 步 smoke，M4 改寫） |
| Colab | `evaluate_meet_captions.ipynb`、`evaluate_workers_ai.ipynb`、`phonetic_near_check.ipynb`、`context_correction_experiment.ipynb`、`life_study_terms.ipynb`、`download_twgbr_archive.ipynb` |

筆記本以 `COMMIT = '<sha>'` 釘住程式版本；改程式後更新 COMMIT（筆記本產生器放在對話 scratchpad，不在 repo；直接改 .ipynb 的 COMMIT 字串即可）。

## 驗證方式（此雲端環境）

- `npm test`；`CHROMIUM_PATH=/opt/pw-browsers/chromium node --test scripts/ui-smoke.mjs`；`npm run check:cloudflare`。
- Python：`.venv/bin/python -m unittest test.test_evaluate_meet test.test_context_experiment`（`.venv` 需 rapidfuzz==3.14.1、opencc-python-reimplemented==0.1.7、numpy；讀音表另需 pypinyin==0.55.0、jieba==0.42.1）。
- Node fetch 不走代理：正式站 API 測試用 `NODE_USE_ENV_PROXY=1 NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt`；Playwright 用 `proxy: {server: process.env.HTTPS_PROXY}`。
- 已知：網站缺 favicon。
