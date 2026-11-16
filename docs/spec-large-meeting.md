# 開發規格：大型聚會最高準確度字幕

版本 2026-11-16。給新對話執行用；狀態與進度記在 [tasks/2026-11-16-large-meeting-accuracy.md](tasks/2026-11-16-large-meeting-accuracy.md)。
先讀 [handoff.md](handoff.md)，再讀本檔；每個里程碑開始時依 AGENTS.md 載入對應 Skill。

## 1. 目標

一個月以上後有大型聚會（內部使用）。要讓現場即時字幕盡可能準確，且**不花錢**：

1. **綱要校正**：房主在聚會前貼上當堂的信息綱要，字幕依綱要的專名與引用經節即時校正。
2. **微調模型**：用恢復本與生命讀經的音訊＋文字微調 Whisper，使教會用語、書卷、人名地名與讀經更準。
3. **免費雲端部署**：微調模型在雲端即時辨識，失敗時自動回到現有 Workers AI Whisper。

不在範圍：改版介面風格（維持淺藍）、公開散布模型、為觀看者另做辨識。

## 2. 使用者決策（2026-11-16，已確認）

| 項目 | 決定 |
| --- | --- |
| 資料 | 只在內部使用。**取消「TWGBR 不用於訓練」限制**：恢復本、生命讀經的文字＋音訊都可用於微調。未取得臺灣福音書房授權，屬使用者自行決定；權重、音訊、文字不進 Git、不公開，只存使用者 Drive／私人儲存。 |
| 費用 | 零費用。訓練用 Colab 免費 GPU；上線用免費額度（建議 Modal Starter 每月 US$30 額度），須設花費上限。 |
| 設備 | 現場沒有專用電腦或 GPU，部署在雲端。 |
| 文字稿 | 聚會前只有**綱要／大綱**（標題、要點、經節），不是逐字講稿。 |
| 封存測試 | MEET 三場仍封存：不訓練、不依它調整，最後驗收一次。 |
| 時程 | 一個月以上；兩部分都完整做，含 MEET 驗收與現場彩排。 |

## 3. 現況基準（不可退步）

- 網站：Workers AI Whisper large-v3-turbo，停頓切段 ≤10 秒 → 繁體轉換、濾幻聽 → 同音教會專名校正（`public/phonetic.js`）。
- MEET（網站條件）：CER 14.49%，教會專名 93/124，延遲中位數 10.3 秒／P95 13.1 秒。
- 生命讀經開發集 16 篇（`twgbr-archive/life-study-dev-v1/`）：音訊是導讀不是逐字，用「專名找到／多出」計分；目前網站 805/1037、多出 63。
- 恢復本開發集：`scripts/build_bible_dev_set.py` 產生的 `bible-dev-v1`（章朗讀＋經文，接近逐字）。
- 進行中：同音放寬 `{near:true}` 第 3 輪（預設關閉，見 meet-evaluation.md），等 Colab 結果決定是否上線。PR #16 待使用者審核。

## 4. 里程碑

每個里程碑：開發分支 → 測試 → PR → 使用者合併 → 正式網址驗證。Colab 筆記本以 `COMMIT` 釘版本。

### M0 收尾（0.5 天）
- 讀 `phonetic_near_check` 第 3 輪結果（Drive `life-study-dev-v1/eval-runs/*-near/summary.md`、`near-precision.md`）。通過開發集門檻且正確全文多改 ≤ 約 20 處 → 跑 MEET 一次 → 使用者決定是否在 `public/app.js` 開啟 `near:true`。
- 處理既存失敗 `test.test_colab_notebook`（cloud_whisper_lora 筆記本），M4 會改寫該筆記本。

### M1 綱要輸入與本場詞表（約 1 週）—— Skill：meeting-ui-ux＋speech-evaluation
- 房主（個人模式與廣播房主）設定新增「本場綱要」文字框；只存在房主瀏覽器（localStorage），不送伺服器、不給觀看者。
- `public/outline.js`（新）：
  - `parseOutline(text)` → `{title, points[], refs[], terms[]}`。
  - 經節引用：中文簡寫書卷＋中文或阿拉伯數字章節，支援 `弗一23`、`約十四6～7`、`太十六18，二八19`、`詩二三1`、`林前十二12` 及「讀經：」行；書卷簡稱表放在 `public/church-terms.js` 旁。
  - 專名：綱要中出現的既有專名（優先），以及不在一般詞表（`COMMON`）的 2–6 字詞（重複出現或在標題／要點中），加入本場同音校正詞表（嚴格同音，不用 near）。
- 校正順序：固定替換 → 本場詞表＋內建詞表的同音校正（本場詞較長優先）。
- 量測：用生命讀經開發集模擬綱要＝每篇的標題＋篇中小標＋引用經節（從參考文字抽，**不含正文**），比較「有／無綱要」。門檻沿用：專名找到 +3% 參考專名數、多出 ≤ max(2, 0.5%)、改壞 ≤ 修好/5。
- 驗收決定（2026-11-16，使用者）：教會專名 +3% 對綱要不適用（每篇綱要的內建專名平均約 8 個）；M1 改以「改壞 ≤ 修好/5、正確原文誤改 0、專名多出不增加」上線。第 2 輪開發集全部達成（修好 36／改壞 2、誤改 0、本場新詞 229→248/287）。
- 實作（2026-11-16）：本場詞分兩種——綱要用到的內建專名與經節書卷（本場接受相近讀音，NEAR_SKIP 除外）、一般詞典沒有且出現 ≥2 次的新詞（嚴格同音）。另加「正確原文誤改」檢查與「本場新詞找到／多出」。
- 介面驗收：手機／桌面、鍵盤、長綱要（5,000 字）、空綱要、格式錯誤不當機。

### M2 經文對齊（約 1 週）—— Skill：meeting-realtime＋speech-evaluation
- 講員讀經時（多半照恢復本逐字讀），把字幕對齊到綱要引用經節的原文。
- 經文來源：恢復本全文**不放在公開靜態檔**。建議存在 Cloudflare R2（免費 10 GB，私人 bucket），Worker 新增 `GET /api/verses?refs=…`，只有房主憑證可取；Node 版不支援（文件註明）。待使用者確認此做法。
- `public/verse-align.js`（新）：以無聲調拼音（含台灣混音）在「最近 2–3 段字幕」與「本場經節」間做滑動比對；相似度 ≥ 門檻（以開發集決定）才把該段替換為經文原文對應片段，並在字幕旁標記經節（如「弗一23」）。不確定就不換。
- 量測：恢復本開發集（朗讀，正例）＋生命讀經開發集（講解，含大量非讀經，負例）。驗收：替換準確率 ≥99%（替換後與參考一致或更好）、改壞 ≤ 修好/10；讀經段落 CER 明顯下降。
- 可選實驗：把綱要專名作 Whisper `initial_prompt`（`/api/transcribe?prompt=`）。上次以「最近字幕」當提示失敗（專名 −6），此項必須在開發集獨立量測，未通過不採用；額度每次 ≤6,000 neurons。

### M3 訓練資料（約 1 週，Colab）—— Skill：speech-data-preparation
- 恢復本：每章音訊＋經文。以 Whisper（Colab GPU）產生時間戳 → 與經文對齊 → 切成 5–30 秒、16 kHz mono；標籤用**經文原文**（繁體、保留標點），只留對齊 CER ≤10% 的段落；章首書卷介紹等不在文字中的部分丟棄。
- 生命讀經：音訊是導讀加講解；對齊後只留與文字 CER ≤15% 的連續段落（實際照稿讀的部分），標籤用原文。
- 分割（依來源群組，避免洩漏）：
  - 排除：`life-study-dev-v1` 的 16 篇及其來源篇章、`bible-dev-v1` 的章、MEET 三場。
  - validation：另選約 2% 的書卷章節／篇章（整篇保留，不與 train 共用來源）。
- manifest 沿用 `docs/cloud-training.md` 格式；`scripts/cloud_training_data.py` 的權利檢查新增明確類別 `license_status: "owner_internal_decision"`、`rights_evidence_ref: "docs/spec-large-meeting.md#2"`，**不可**標成 `approved`，也不移除檢查。
- 產出：Drive `meeting-live-captions/data/twgbr-v1/`（音訊、manifests、資料報告：時數、段數、對齊分布、hash）。預估可用數十小時以上，以實際報告為準。

### M4 微調（約 1–2 週，Colab 免費 T4）—— Skill：speech-finetuning
- 基礎模型：`openai/whisper-large-v3-turbo`（固定 revision）＋LoRA（q/k/v/out 與 fc，rank 32 起）；FP16、gradient checkpointing、batch 4 × accumulation 8 起；checkpoint 每 200 步存 Drive、可續跑（Colab 會斷線）。T4 跑不動時改 medium，再不行 small。
- 改寫 `scripts/train_cloud_whisper.py`／`notebooks/cloud_whisper_lora.ipynb`（目前預設 whisper-small、20 步 smoke）。
- 依 validation 選 checkpoint；測試：
  - 生命讀經開發集：專名找到／多出、CER（參考）。
  - 恢復本開發集：CER、專名。
  - 一般華語回歸：`sources/taiwan-mandarin-pilot.json` 的公開語料小樣本，CER 不可變差 >1 個百分點。
  - 幻聽：靜音／詩歌片段不得產生大量文字。
- 匯出：合併 LoRA → CTranslate2（float16 與 int8_float16 各一）→ 重新跑同一組開發測試確認品質與速度。權重只存 Drive 與部署平台的私人空間，寫模型卡（`docs/templates/model-card.md`），不進 Git。

### M5 雲端部署（約 1 週）—— Skill：meeting-verification-release
- **主要：Modal**（Starter 免費額度）。`deploy/modal_asr.py`（新）：faster-whisper 載入 M4 模型，`POST /transcribe` 收 16 kHz WAV、回 `{text, segments}`，Bearer 權杖驗證；T4 或 L4；不用時縮到 0；聚會期間由房主按「準備辨識」預熱（冷啟動約 30–60 秒，需實測）。
- **Worker**：`POST /api/transcribe` 增加引擎選擇；設定 `CUSTOM_ASR_URL`（變數）與 `CUSTOM_ASR_TOKEN`（Wrangler secret）時可用「教會模型」。逾時（約 6 秒）或錯誤 → 同一段自動改用 Workers AI，前端事件契約不變；`/api/health` 回報可用引擎。後處理（繁體轉換、濾幻聽、同音校正）照舊。
- 前端：設定的辨識方式加「教會模型（微調）」；預設值等 M6 通過後再改。
- 額度保護：Modal 設花費上限；記錄每小時實際費用；超過額度自動停用並回到 Workers AI。
- 備案（零費用、須實測）：房主瀏覽器以 transformers.js＋WebGPU 執行轉成 ONNX 的模型；只做速度測試，不在 M5 上線。
- 不採用：Colab 當即時服務（免費層會中斷、不適合當網路服務）、HF ZeroGPU（每天約 5 分鐘）、Oracle 免費 CPU。

### M6 驗收與彩排
- 開發集通過 → **MEET 跑一次**（`evaluate_meet.py` 新增教會模型條件）。門檻：CER 低於 14.49%、教會專名 >93/124、延遲 P95 不比現況差。未通過就不改預設，不依 MEET 結果調整。
- 正式網址：health、房間（房主＋2 觀看者）、引擎切換、Modal 關閉時自動回退、綱要輸入；清除測試房間。
- 彩排：聚會前用一場真實錄音（1 小時，用音檔測試）走完整流程，記錄延遲與費用。
- 聚會當天的操作說明寫在 `docs/large-meeting-runbook.md`（預熱、綱要貼上、回退、額度檢查）。

## 5. 介面與資料契約

| 介面 | 規格 |
| --- | --- |
| `POST /api/transcribe?lang=zh&engine=workers-ai\|custom[&prompt=]` | 輸入 16 kHz WAV ≤10 秒；回應 `{text, engine, fallback?}`；錯誤碼沿用現況（額度用完 3036 → 前端改 Chrome）。 |
| `GET /api/verses?refs=弗1:23,約14:6-7` | 只限房主憑證；回 `{refs:[{ref, text}]}`；R2 讀取；不快取到公開 CDN。 |
| Modal `POST /transcribe` | Bearer 權杖；輸入同上；回 `{text, segments:[{start,end,text}], model}`。 |
| 綱要 | 只存房主瀏覽器；不經 WebSocket 傳給觀看者。 |

## 6. 驗證命令

`npm test`；`npm run check:cloudflare`（Wrangler 需 `XDG_CONFIG_HOME=/workspace/.cloudflare/config XDG_CACHE_HOME=/workspace/.cloudflare/cache`）；`npm run dev:cloudflare` 後 `npm run test:cloudflare`；
`CHROMIUM_PATH=/opt/pw-browsers/chromium node --test scripts/ui-smoke.mjs`；`python -m unittest discover test`（需 `.venv`：rapidfuzz、opencc-python-reimplemented、numpy）。
Colab 實際訓練、Modal 部署、正式網址驗證都要在交付時分別標 passed／failed／unrun。

## 7. 風險

| 風險 | 處理 |
| --- | --- |
| 恢復本朗讀風格與現場講道不同，模型過度偏向讀經 | 混入生命讀經照稿段落；一般華語回歸測試；開發集同時看講解類音訊。 |
| Colab 免費 GPU 斷線／配額不足 | 每 200 步存 checkpoint；可退到較小模型；分多天訓練。 |
| Modal 冷啟動或額度用完 | 預熱按鈕；6 秒逾時回退 Workers AI；花費上限。 |
| 經文對齊誤換（講員只是提到、不是讀經） | 高門檻＋需連續多段相符；不確定不換；負例（講解）量測。 |
| 著作權 | 使用者已決定內部使用；權重與文字不散布、不進 Git；R2 私人。 |

## 8. 開工前要向使用者確認

1. 提供一份綱要範例（貼上或 Drive 路徑），確定格式。
2. 恢復本經文存在 Cloudflare R2 私人 bucket、只給房主讀取：是否同意。
3. 申請 Modal 帳號（M5 前）：確認註冊是否需要信用卡，並設定花費上限。
4. 聚會規模：天數、每天小時數、同時觀看人數（估算額度）。
