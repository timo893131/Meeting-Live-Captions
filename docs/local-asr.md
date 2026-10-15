# 本機離線辨識基線

此流程與正式網站的 WebSpeech 分開。只在本機處理使用者獲准評估的錄音，不送到外部轉錄服務；模型下載僅下載公開權重，不能把錄音當 HTTP 請求內容。沒有模型微調或服務端上線變更。

## 已驗證及未完成

Python .venv 已安裝 requirements-asr.txt 的固定版本，faster-whisper 1.2.1、PyAV 16.0.1，pip check 通過。PyAV 19.0.1 與該版 faster-whisper 的 metadata_errors 呼叫不相容，實際解碼失敗後已固定為 16.0.1，並新增音訊解碼回歸測試。CLI 與合成引擎測試能檢查輸出保存及無 reference prompt 的契約；合成測試不代表真人辨識成功；另已完成首份使用者錄音的實際離線推論。

Hugging Face 主站已恢復連線。模型固定 Systran/faster-whisper-small commit 536b0662742c02347bc0e980a01041f333bce120，四個資產已下載到忽略的 models/whisper-small；model.bin 為 483,546,902 bytes，SHA-256 為 3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671，與固定版本的 HTTPS Hub LFS metadata 一致；三個小檔另核對 Git blob hash。Hub 下載轉址至 us.aws.cdn.hf.co，已追加此單一網域到環境草稿並保留原設定。當前下載實際成功；草稿保存與未來環境發布仍是不同步驟。

## 準備公開模型

在新環境下載時，先檢查 Hugging Face 的 Systran/faster-whisper-small 模型 repo，選定並記錄確切 commit。只取 config.json、model.bin、tokenizer.json 及 vocabulary.*，用 huggingface_hub.snapshot_download 的 revision 指定該 commit，local_dir 指向忽略的 models/whisper-small。下載應保持 TLS／Hub 原生檔案完整性檢查，不改 checksum、不走非核准鏡像。不將權重加入 Git；small 為多語約 244M 參數，先用 CPU int8 做一次基線，單一檔案不能證實現場條件下的準確率與速度。

```sh
.venv/bin/python -m pip install --cache-dir /workspace/.pip-cache -r requirements-asr.txt
.venv/bin/python scripts/transcribe_audio.py \
  --audio data/meeting-evaluation/week12day1/week12day1.mp3 \
  --model-dir models/whisper-small \
  --output artifacts/local-asr/week12day1-baseline \
  --threads 4
```

CLI 不會自動下載模型，只接收本機 CTranslate2 模型資料夾。輸出目錄必須不存在。語言 zh、轉錄任務、beam 5、temperature 0、CPU int8；不加入已知全文、詞彙提示或校正規則，避免答案洩漏。VAD 未啟用；Whisper 自身的靜音／機率判斷仍可能影響輸出，人工須檢查漏段與幻覺。

raw-asr.json 包含未校正文字、時間戳、音訊 hash、模型檔 hash、套件版本、參數和耗時；raw-asr.txt 是機器草稿。耗時含模型載入與轉錄，不含前置模型 hash，RTF 不能當成即時字幕延遲。首次執行錯誤可能留下新輸出目錄，診斷後使用新的 run 目錄，不覆寫人工註記。

## 文字稿核對

使用者提供的對應文字獨立保存在忽略的 data/meeting-evaluation/week12day1；原文不更動。reference-review.json 標記括號、方括號、省略號及可疑字串，均待聽音處理。不能一律刪括號：引用來源可能沒讀，也可能有讀；省略號可能省去了有讀出的句子。機器稿與既有出版文字都不是已核對的 gold reference。

下一步先看原音與機器稿，再逐段核對實際文字、聽得到的停頓與數字；繁簡／同音字形另訂顯示政策。此樣本是已見開發評估材料，不是封存測試集。完成核對才量測字元錯誤與專有詞位置；需要更多場次才能推論泛化效果。評估用途不等同訓練用途。

## 首份實錄執行結果

使用上述固定模型與 CPU int8、4 threads，在本環境完成約 401.77 秒錄音：159 個機器分段，載入與轉錄合計約 96.74 秒，RTF 約 0.241。此為單檔離線耗時，不能當作房間字幕延遲或其他硬體的速度保證。未使用提供的全文／hotwords 提示、未套用詞彙校正、未訓練。

私人產物位於忽略的 artifacts/local-asr/week12day1-baseline-av16：raw-asr.json、raw-asr.txt、raw-asr.srt，以及內嵌音訊的 audio-review.html。離線核對頁可重播片段、修改文字、逐段標記並下載核對 JSON；不會自動儲存，下載結果仍需完整性、來源、字形政策與時間對齊查核，不能單憑勾選宣稱 gold dataset ready。

機器稿與提供文字含明顯差異，且前後標題／出處不完全相同。provisional-review-notes.json 只作回聽清單；reference 尚未人工逐段核對，因此 CER、詞彙正確率及正式候選驗收均未執行。原音、出版文字、機器稿與核對頁都沒有加入 Git 或公開網站。
