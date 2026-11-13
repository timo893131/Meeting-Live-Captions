# 交接摘要（2026-11-12）

新對話先讀本檔，再依 AGENTS.md 路由。這份摘要寫的是目前決策、證據、已上線內容、未解問題與下一步，不重述完整歷史。

## 使用者與工作方式

- 繁體中文溝通。服務教會聚會（地方召會；恢復本、生命讀經用語）。
- 限制：**全部雲端、零費用、沒有自己的伺服器或 GPU**。部署用 Cloudflare 免費方案；GPU 工作用 Google Colab（T4），資料放使用者的 Google Drive。
- 發布流程：開發分支 → **開 PR → 使用者審核合併 → main 自動部署** → 我用正式網址驗證（health、檔案與 main 一致、房間 smoke、瀏覽器實測）。不 force-push；未經要求不建立 PR 以外的發布動作。
- 介面風格：使用者偏好**原本的淺藍設計**。Hallmark（Wayfind／Dose）改版試過後撤回，只保留小幅可用性修正。

## 正式網站

https://meeting-live-captions.livecap-worker.workers.dev（Worker `meeting-live-captions`，main 自動部署）

| 功能 | 現況 |
| --- | --- |
| 辨識 | 預設 **Whisper large-v3-turbo on Workers AI**（`POST /api/transcribe`）。瀏覽器在停頓處切段（滿 5 秒遇 0.3 秒停頓、或 1.5 秒停頓、最長 9 秒），WAV 送 Worker；Worker 轉繁體（opencc-js cn→tw）、濾掉幻聽字句（優優獨播劇場、字幕志願者…）。Chrome `SpeechRecognition` 同時當灰字預覽；額度用完／失敗自動改用 Chrome。設定可改選「Chrome 即時辨識」。 |
| 額度 | 免費每天 10,000 neurons ≈ 214 音訊分鐘（約 3.5 小時），UTC 0 點重置；`SpeechLimit` DO 限制每 IP 每天 4 小時、每分鐘 40 段。 |
| 校正 | 同音教會專名校正（`public/phonetic.js`）：內建書卷、教會專名、生命讀經新增 25 詞、279→278 人名地名（拿掉腓力斯）、一律校正的一般詞 11 個（照會→召會、征戰→爭戰、西安→錫安、實話→實化…，使用者確認）。設定可查看內建清單（唯讀）；**詞彙校正表預設空白**，只放使用者自己的詞。 |
| 音檔測試 | 個人模式「用音檔測試辨識」依辨識方式：Whisper 整檔切段並行送出（30 分鐘約幾分鐘）；Chrome 以正常速度播放給辨識。 |
| 房間 | 個人／廣播／加入（密碼、邀請連結、QR）；Workers 版字幕存 Durable Object，結束或 12 小時刪除。 |

## 量測結果（重點）

MEET 是**封存測試**（3 場聚會錄音＋近逐字稿，在 Drive `twgbr-archive/MEET/`）：只驗收，不依其錯誤調詞或規則。細節見 [meet-evaluation.md](meet-evaluation.md)。

| 條件（MEET 3 場） | CER 校正後 | 教會專名正確 | 延遲 中位數／P95 |
| --- | --- | --- | --- |
| **Workers AI 停頓切段 ≤10 秒（網站）＋新詞表** | **14.49%** | **93/124（75%）** | 10.3／13.1 秒 |
| Workers AI ≤30 秒 | 14.10% | 102/124 | 31／35 秒 |
| Colab Whisper 整檔（上限參考） | 13.75% | 99/124 | — |
| Chrome（只有 01） | 31.7% | 22/64 | — |

- 01 結尾約 22:48 後是唱詩歌；`speech_only` 分數排除詩歌。
- 03 在所有 Whisper 條件都有同樣的長段漏字與多字，疑似參考文字與錄音不一致；新詞表在 03 多改壞約 8 字（依封存規則未逐句檢視）。
- 生命讀經開發集（16 篇，Drive `twgbr-archive/life-study-dev-v1/`）：音訊是帶讀加講解，**不是逐字稿**，用不需對齊的專名比對；新詞表 400→684/920。

## 資料與權利

- TWGBR（恢復本經文＋音訊、生命讀經文字＋音訊）已由使用者用 Colab 下載到 Drive `twgbr-archive/`。版權臺灣福音書房：**私人／內部使用，未取得訓練授權**；只用於詞彙清單、開發評估。
- 不把音檔、逐字稿、模型權重提交 Git。

## 主要程式與筆記本

| 用途 | 檔案 |
| --- | --- |
| 前端 | `public/app.js`、`public/speech-chunker.js`、`public/phonetic.js`、`public/church-terms.js`、`public/always-corrected.js`、`public/bible-names.js`、`public/pinyin-zh.js`（產生檔） |
| Worker | `cloudflare/worker.js`、`cloudflare/transcript.js`、`wrangler.jsonc`（AI binding、DO migrations v1/v2） |
| 讀音表 | `scripts/build-pinyin-table.py`（`MISSPELLINGS`＝一律校正；改 church-terms 後要重建） |
| 評估 | `scripts/evaluate_meet.py`（full／vad／cfvad 條件、`--reuse`、`--loose-reference`、先轉繁體再校正，與網站一致） |
| 找詞 | `scripts/build_life_study_dev_set.py`、`scripts/mine-same-sound-terms.mjs` |
| Colab | `notebooks/evaluate_meet_captions.ipynb`（MEET；`REUSE` 只重新計分）、`evaluate_workers_ai.ipynb`（CF 權杖放 Colab 密鑰）、`life_study_terms.ipynb`、`download_twgbr_archive.ipynb` |

Colab 筆記本以 `COMMIT = '<sha>'` 釘住程式版本；改評估程式後要更新筆記本的 COMMIT。

## 驗證方式（此雲端環境）

- `npm test`；`CHROMIUM_PATH=/opt/pw-browsers/chromium node --test scripts/ui-smoke.mjs`；`npm run check:cloudflare`；`python3 -m unittest test.test_evaluate_meet`（需 `pip install rapidfuzz==3.14.1 opencc-python-reimplemented==0.1.7 numpy`；讀音表需 `pypinyin==0.55.0 jieba==0.42.1`）。
- Node 的 fetch 不走代理：正式站 API 測試用 `NODE_USE_ENV_PROXY=1 NODE_EXTRA_CA_CERTS=/root/.ccr/ca-bundle.crt`；Playwright 用 `proxy: {server: process.env.HTTPS_PROXY}`。
- `test.test_colab_notebook` 有 1 個既存失敗（cloud_whisper_lora 筆記本），與近期工作無關。
- 網站缺 favicon（主控台 404），不影響使用。

## 下一步（建議順序，等使用者決定）

1. **收音**：現場改用混音器直接接線（最便宜、效果最大）。
2. **上下文校正實驗**（2026-11-13 試跑完成，**未通過**，見 [context-correction-experiment.md](context-correction-experiment.md)）：Whisper 提示使專名變少；Gemma 4 回覆全空；Qwen3 便宜快速但照單接受錯誤提示，改壞多於修好。接著做「同音校正放寬聲調／台灣混音、但不拆一般詞」（`{near: true}`，預設關閉；`notebooks/phonetic_near_check.ipynb`，見 meet-evaluation.md），等使用者在 Colab 跑開發集與誤改檢查。
3. （已併入第 2 項的條件 A）
4. **微調暫不做**：Workers AI 不能放自訂 Whisper（要自費 GPU 或瀏覽器端模型）；沒有授權的逐字訓練資料。若要準備：聚會字幕下載後請同工對照錄音修正（取得講員同意即為自有逐字稿）；向臺灣福音書房詢問訓練授權。
5. 擴充專名：用 Drive 上未用過的生命讀經篇章再建一批開發資料跑 `life_study_terms.ipynb`。
