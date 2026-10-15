# 本機離線辨識基線

此流程與正式網站的 WebSpeech 分開。只在本機處理使用者獲准評估的錄音，不送到外部轉錄服務；模型下載僅下載公開權重，不能把錄音當 HTTP 請求內容。沒有模型微調或服務端上線變更。

## 已驗證及未完成

Python .venv 已安裝 requirements-asr.txt 的固定版本，faster-whisper 1.2.1，pip check 通過。CLI 與合成引擎測試能檢查輸出保存及無 reference prompt 的契約；合成測試不代表真人辨識成功。

目前環境的代理拒絕 Hugging Face 連線（tunnel 403），權重尚未下載，真實推論、時間戳對齊與 CER 均未完成。已保存環境草稿，保留既有網域並新增 huggingface.co、cas-bridge.xethub.hf.co、cas-server.xethub.hf.co、transfer.xethub.hf.co。需在環境設定檢閱、儲存，再發布環境；草稿儲存本身不會改變當前網路。

## 準備公開模型

網路設定生效後，先檢查 Hugging Face 的 Systran/faster-whisper-small 模型 repo，選定並記錄確切 commit。只取 config.json、model.bin、tokenizer.json 及 vocabulary.*，用 huggingface_hub.snapshot_download 的 revision 指定該 commit，local_dir 指向忽略的 models/whisper-small。下載應保持 TLS／Hub 原生檔案完整性檢查，不改 checksum、不走非核准鏡像。不將權重加入 Git；small 為多語約 244M 參數，先用 CPU int8 做一次基線，尚未證實此檔或現場條件的準確率與速度。

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
