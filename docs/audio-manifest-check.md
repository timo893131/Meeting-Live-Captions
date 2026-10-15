# 真實錄音回測資料接入檢查

本工具只做本機資料檢查，不抓取網站、不上傳、不轉錄、不訓練。需要 Node 22+ 與 ffprobe；雲端環境已提供 ffprobe。測試會產生一秒鐘的空白 WAV，不能代表真人辨識或聽寫已驗證。

## 準備

1. 依 [manifest 範例](templates/audio-segment.example.json) 建立 JSONL，每段一列；範例本身故意未獲授權且沒有音檔，不能直接通過。
2. 將錄音存入核准位置，raw_path／processed_path 使用相對於 --root 的路徑；不可用絕對路徑或解析後跳出 root 的路徑／符號連結。工具核對解析後位置，仍應使用可信且執行期間不變的本機目錄。
3. 填入實際來源版本、授權證據位置與允許用途。approved 由資料管理者依實際文件填寫，不是按鈕或工具可代為取得的授權。講員同意需有依據，不能只因聚會公開就省略。
4. 逐字稿由人工聽寫／核對。允許空白稿表示已核對的靜音；機器自產稿不可標成 human_verified。以現有 normalizer 處理，保留原文。
5. audio.duration_seconds、sample_rate_hz、channels 描述原始檔；start/end 是原始檔座標的片段區間。轉換檔另存 hash 及 transform，不覆寫原檔。

```sh
node scripts/check-audio-manifest.mjs \
  --manifest data/manifests/validation.jsonl \
  --root data \
  --purpose internal_evaluation \
  --speaker-disjoint true
```

internal_evaluation 只接受 validation／sealed_test，training 只接受 train。檢查完整資料集時，使用 --purpose split_audit，可混合 train／validation／sealed_test，按每列 split 核對 training 或 internal_evaluation 權利，檢查跨 train 的洩漏；這個模式只作審計，不會執行訓練或評估。未指定 speaker-disjoint 時仍檢查場次／群組／原始音檔 hash 與完全相同的非空正規化文字；對新講員的評估應指定 true。

## 檢查結果

- 結構、權利、用途、同意、保存期限、來源、人工稿、正規化、時間界線、ID 與 split；任一失敗即退出 1。
- metadata 通過後才讀取音檔，以串流核對 SHA-256，使用 ffprobe 確認單一音軌；原音 sample rate／聲道須一致，duration 容差 0.1 秒。
- processed 檔案只檢查路徑、hash、音軌及轉換紀錄存在；尚不驗證轉換參數、轉換後片段時間或字音對齊。
- 不會覆寫報告。預設產物位於忽略的 artifacts/manifest-check/<run_id>/report.json，包含輸入 hash、政策、列號與錯誤，不輸出逐字稿。格式錯誤或無法讀取時退出 1，不保證產生報告。

通過不代表內容可訓練：工具不驗證授權文件真偽、不代替人工聽稿、不辨識重新編碼／裁切的近似重複音訊，也不做語意對齊。多位講員目前每列只可填一個 speaker_id，重疊發言需額外標註與審計。大型資料的 hash／重複檢查需另規劃資源。

TWGBR 目前只完成盤點與技術檢查，沒有訓練授權；不要將其資料改標為 approved 以通過本工具。
