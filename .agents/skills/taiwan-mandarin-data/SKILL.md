---
name: taiwan-mandarin-data
description: 台灣華語語音資料 Agent：有限來源盤點、授權隔離、10–20段語料試抓、原音與文字保存、QC及可追溯基線；不自動擴量或訓練。
---

# 台灣華語語音資料 Agent

先讀 AGENTS.md。使用者已要求此 Agent 時可委派獨立來源盤點；一般小任務不自動多代理。其他對話與舊 artifact 不保證可存取；/workspace/web-spider 若存在先讀 README，否則沿用本 repo 工具。

主要設定 sources/taiwan-mandarin-pilot.json；流程及狀態見 docs/tasks/2026-11-02-taiwan-mandarin-pilot.md。讀需要的 acquisition、preparation 或 evaluation Skill，避免一次載入所有文件。

1. 先確認資料卡／服務規則，公開不是訓練授權。crawler固定15段、100MiB body、單檔12MiB、60 HTTP requests、1 req/s、最多1 retry、600秒，沒有自動擴量。
2. `python scripts/tw_speech_pilot.py --prepare` 做官方 metadata review、card license gate、小樣本下載及原音hash；HTTP cache為完整檔級續抓。未知host／robots拒絕／403不得繞過；變更網路設定後才重試受阻操作。
3. `tw_audio_prepare.prepare_records(records,root)` 另存16k mono WAV，保留原文、NFC文與語碼標記。QC是實測幅度／解碼檢查，不是語音、噪音或音樂辨識。超長來源不得任意切後複製全文；未實作的近似音訊去重、音樂、字音一致性與停頓分段必須標unrun。
4. 原錄音及已知講員連通分組、原音／PCM／文字精確去重後只產生proposed_split；近似去重與對齊待審時split維持unassigned。講員未知時不聲稱完全隔離，所有資料目前training_ready=false。
5. `python scripts/tw_speech_baseline.py --output <new-private-dir>` 預設只收本地核對reference。`--reference-policy provider_provisional` 僅限明確的供應者原稿試比；不能把機器稿當reference。輸出不宣稱sealed gold、不自動發布；離線RTF不是即時延遲。
6. 每次回報來源、音訊時數、可用配對／待審時數、失敗、QC、產物及下一步。空資料與受阻來源不能寫成15段成功；synthetic tests不能充當ASR測試。

正式站仍為WebSpeech，無自有可微調權重。Whisper/CTranslate2只是本機推論；小規模LoRA需原始PyTorch訓練權重、合法標籤、隔離資料與實測GPU資源。此Agent不自行啟動訓練。

來源預設已改官方Hub Parquet匯出（tw_parquet_source.py），避開Viewer 500。需取得不可變commit，再以該版本dataset info的?blobs=true檔案metadata篩選指定語言／split（不用nested tree查詢），再於既有byte/request budget內做精確206 Range讀取；不整包下載、不執行遠端dataset腳本。區塊可多載未選列，只有選中音訊計時selected_audio_hours；downloaded_hours=null，不把未知當0。部分讀取不宣稱完整Parquet hash已驗，詳細規則見cloud-training.md最新段落。此路徑尚未有實際FLEURS成功下載證據。
