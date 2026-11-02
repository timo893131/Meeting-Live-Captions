# 台灣華語語音資料 Agent：小樣本流程與基線

- 任務：2026-11-02；狀態 **blocked（資料與模型網路存取）**。
- 目標：先以10–20段跑通資料流程及實錄基線，再規劃擴量／微調；不直接大型訓練。
- 路由：taiwan-mandarin-data，必要時接 acquisition／preparation／evaluation。已委派一個獨立來源查核子任務，範圍及後續QC實作皆有隔離；無對外發訊。
- 設定：[taiwan-mandarin-pilot.json](../../sources/taiwan-mandarin-pilot.json)。下列時數均為本次實際資料，不沿用舊對話的數值。

## 目前專案與模型

| 項目 | 實查結果 |
| --- | --- |
| 正式網站 | public/app.js 的 SpeechRecognition（zh-TW）；瀏覽器供應者模型，無本專案可訓練權重；詞彙功能是文字校正 |
| 本機離線方案 | faster-whisper 1.2.1／CTranslate2 4.8.3，預定固定 Systran/faster-whisper-small revision 536b0662742c02347bc0e980a01041f333bce120，CPU int8 |
| 權重現況 | 此工作區沒有已驗證模型檔；HF 連線403，本次未載入模型；舊任務的推論結果不是本次基線 |
| 相容性 | PyAV固定16.0.1，沿用已處理的metadata_errors相容性；pip check通過 |
| 微調支援 | Whisper原始PyTorch/Hugging Face權重可用於微調；CTranslate2 int8推論權重不能直接用本工具反向傳播。WebSpeech也不能由此專案微調 |
| 實際資源 | 5個CPU affinity、cgroup配額4核；memory.max 34,359,738,368 bytes（32GiB）；未發現nvidia-smi或可用NVIDIA GPU；無訓練runtime |
| 輸入 | 本地ffmpeg／ffprobe可用；工作副本16kHz、mono、PCM16 WAV。Whisper官方audio.py確認16kHz與30秒480,000 samples；small的80-bin log-mel／token labels需在取得原始訓練config後再次核對 |
| 現有爬蟲 | /workspace/web-spider不存在；不假設其他對話檔案可直接存取，使用本repo新CLI |

推論輸入是本機音檔，由decoder轉為16k浮點波形；訓練時還需feature extractor與tokenizer，不能只把JSONL丟入CTranslate2。generic JSONL保留使用者要求欄位，見 [schema](../schemas/taiwan-speech-record.schema.json)。原有church audio-segment schema仍保留；兩種格式不可不經映射混用。

模型介面依據為本次可讀取的官方 [Whisper audio.py](https://github.com/openai/whisper/blob/main/whisper/audio.py) 與 [faster-whisper README](https://github.com/SYSTRAN/faster-whisper)。原始證據及SHA-256保存在忽略的 raw/model-docs，不把音訊／逐字稿／權重加入Git。

## 來源盤點

| 來源 | 已查到的事實 | 本次狀態 |
| --- | --- | --- |
| Google FLEURS cmn_hant_tw | 預定先查[官方資料卡](https://huggingface.co/datasets/google/fleurs)與datasets-server rows API，取15段 | 403，尚未確認本次資料卡的授權與schema；設定中的cc-by-4.0只是待核對的預期值，不能視為已核准 |
| Common Voice SCS zh-TW v27 | [官方metadata](https://raw.githubusercontent.com/common-voice/cv-dataset/main/datasets/scripted-speech/cv-corpus-27.0-2026-09-11.json)已讀取：140,996 clips／131.70h；validated 85,570 clips／約79.92h；2,336 contributors；全包3,173,160,333 bytes | 超過100MiB pilot，未下載音訊；特定release資料卡／平台存取條件待核對。repo軟體MPL2不是音訊授權 |
| Common Voice自然語音／語碼混合 | [SPS官方說明](https://github.com/common-voice/cv-dataset/tree/main/datasets/spontaneous-speech)及metadata查到v5沒有zh-TW；code-switching尚alpha未發行 | 不冒稱已有台灣自然對話／中英台夾雜資料 |

Common Voice現在的官方下載入口是 [Mozilla Data Collective](https://mozilladatacollective.com/)。`client_id`可作講員群組依據，但須檢查不同release的同人／同片重複。zh-TW metadata也有香港口音與未標口音，locale不能當成已核對的台灣口音標籤。

validated僅是供應者投票驗證，不代表已由我們聽音核對。文章、朗讀prompt、機器稿與人工逐字稿分開保存。FLEURS預期是朗讀資料，只可跑通流程，不能覆蓋真實對話、噪音、教會現場與語碼混合的全部情境。

## 有限擷取與輸出

```sh
cd /workspace/Meeting-Live-Captions
.venv/bin/python scripts/tw_speech_pilot.py --prepare
```

預設root為忽略的 data/taiwan-mandarin-pilot，建立 raw/、processed/、manifests/、text_only/、review/、reports/。原始音訊、原文、HTTP來源、取得時間、授權卡及hash都保留。

上限為15段、1頁rows metadata、60個累積HTTP requests、100MiB HTTP body、單檔12MiB、1 req/s、最多1次重試、20秒單次timeout、600秒批次檢查。API/HTTP匯出優先，檢查robots，拒絕未知host與跳出白名單的redirect；遵守Retry-After，長退避等待交給下次執行，403不反覆重試。完整檔級cache支援中斷續抓並驗hash；未完成單檔從頭抓，沒有假稱byte-range續傳。cache壞損、原音不同或既有人工manifest不吻合會停止，不靜默覆寫。

授權卡必須明確命中預期license才下載音訊；未知授權保留review／source metadata，沒有正式訓練用途。下載後每列有id、audio_filepath、text、language、duration、source_url、recording_id、speaker_id、segment_start/end、transcript_status、license_status、sha256、split；download階段duration可null，探測後補實值，未知不編造。供應者的validation來源split與pipeline_development_only用途另記；已查看的小樣本不能被稱為未見封存test。

配對級別是 provider_claimed_pair_pending_review。raw text與NFC文字分別保存，不轉繁簡、不改數字／台灣用語，英文／台語標記保留；language_spans沒有標註時明示not_reviewed。無法下載的供應者文字只存text_only，不當ASR音訊配對。

## QC、去重與切分

原音hash先核對，再另存16k mono副本；超過120秒拒絕自動處理。5–30秒為初始片長參考，30秒以上放review，不切成短音後複製全文；目前沒有停頓切段或字級對齊器。來源已是單句clip時可先保留完整片段。原音／副本hash與ffmpeg版本／參數保存。

已實作實測解碼、時長、削波（abs>=32760）、20ms-frame RMS靜音（-45dBFS）與長靜音檢查。這些是幅度heuristics，不是聲音品質分數或語音／音樂分類。背景音樂、字音一致性、近似音訊去重尚unrun；不得把無檢測當passed。

先做原音hash、工作PCM hash、NFC文字精確去重，再用原錄音與已知speaker連通分組產生proposed_split。**近似去重與reference未審前，split一律unassigned、training_ready=false**；不建立正式train/validation/test。未知講員不聲稱完全隔離；供應者clip／row ID也不等同已知原始場次。

## 基準測試入口與本次結果

```sh
.venv/bin/python scripts/tw_speech_baseline.py \
  --root data/taiwan-mandarin-pilot \
  --output artifacts/taiwan-mandarin-pilot/<new-run>
```

預設verified_only，沒有本地核對reference就排除。若只做供應者原稿的探索性試比，可顯式加 `--reference-policy provider_provisional`，報告會標provisional；機器稿始終不能當reference。最多20筆，保持固定模型SHA、CPU int8／4threads、zh／beam5／temperature0，全文與hotwords不加入prompt。產生raw hypothesis、逐段時間戳、模型／音訊／manifest hash、版本、離線秒數與RTF。

CER重用現有NFC／去標點空白版本與字元S/D/I/N，不轉繁簡、不修數字。含語碼標記需annotation-aware scorer，現階段排除評分但原文保留；WER因未指定固定中文斷詞器，標unrun。provider試比或本地已核對reference皆不自動宣稱sealed-test gold，資料隔離與覆蓋必須另外驗收。

**本次真實基準未完成**：來源／模型下載仍被proxy CONNECT 403攔下；實際collect退出1，baseline preflight退出1，沒有模型載入、實錄轉錄、CER或即時延遲數值。不是一次成功的ASR基準，也沒有拿過去教會錄音的97秒結果冒充。

| 本次資料狀態 | 實際值 |
| --- | --- |
| 來源盤點 | 2個主要系列；CV metadata可讀，FLEURS受阻 |
| 已下載音訊 | 0段／0h |
| 已配對且可正式使用 | 0h |
| 待校對音訊 | 0h（沒有下載音訊） |
| 已本地校對 | 0h |
| 已訓練 | 0 |
| QC結果 | 沒有實錄可量測；工具的合成測試另列，不算語料 |
| 真實麥克風／正常速度播放 | unrun；初次文字、最終延遲、P50/P95、反覆修訂、漏字皆無實測值 |

## 驗證與環境阻礙

13項新合成測試通過，包括15個明確標為synthetic的音訊fixture從假HTTP API到格式轉換／去重／隔離流程，及爬取預算、續抓、防覆寫、跨host、robots、Retry-After、授權卡、reference篩選、固定CER；另外3項既有local ASR契約／解碼測試通過，pip check通過。它們都不是台灣華語準確率或即時測試。

```sh
.venv/bin/python -m unittest discover -s test -p 'test_tw_*.py'
.venv/bin/python -m unittest discover -s test -p test_local_asr.py
```

保存的環境草稿保留原網域，增補 datasets-server.huggingface.co、storage.googleapis.com、mozilladatacollective.com；既有huggingface.co／下載CDN也保留。需到環境設定檢閱、儲存並發布後再測受阻操作。草稿保存不是runtime已生效的證據；若回傳新的官方audio host，需另確認再加入，不能開放任意redirect。

## 擴量與微調方案（未啟動）

1. 網路可用後先確認FLEURS授權卡／schema，再抓15段，取得本地核對reference及近似去重結果。先行規則：解碼／hash全通過、無未解授權／重複／配對錯誤；沒有通過就不擴量。
2. 通過後另開新版本root，階段二上限建議1GiB、60分鐘擷取、最多500段／約2–5小時，取較先到的上限；未自動啟用，當前CLI仍限定10–20段；擴量需另一版收集設定／分頁流程。蒐集自然對話、噪音、專名、中英台夾雜，分開來源與標註，不能以乾淨朗讀代替覆蓋。目標時數是規劃，不是保證可取得。
3. 真實即時基線須在實際麥克風或正常速度播放的端到端流程，以單調時鐘記錄語音起點、first interim、final、viewer到達、修訂次數與漏字，再統計P50/P95。跨裝置需要時鐘／量測方法；不使用離線RTF或CPU逐檔耗時充當這些延遲。
4. 微調選原始多語Whisper small，先確認固定模型card／config與訓練授權。使用16k mono波形→feature extractor→小模型80-bin log-mel及token labels；保留UTF-8繁中原稿、語碼annotation與正規化版本，驗證token長度及30秒上限，不自動截斷長音。
5. 準備train/validation/未見test及來源／講員隔離，GPU位置與時間預算確定後才試LoRA。建議先用約16GiB GPU作20–50步pipeline smoke，實測顯存、梯度與checkpoint resume，再決定後續步數；不是資源或改善保證。本機無此GPU，不安裝大型訓練套件或啟動訓練。
6. 固定baseline與未參訓test比較CER、一般中文／專名／語碼混合／噪音，並在同硬體同正常速度條件比較即時延遲。保留原模型、設定與checkpoint；轉回CTranslate2／int8後再測。品質或延遲退步就保留baseline。

本工作沒有改動既有教會資料權利；TWGBR仍限已允許的盤點／技術檢查，不加入本次訓練。token／費用未提供metadata，記unavailable；不宣稱節省率。
