---
name: speech-data-preparation
description: 轉換授權音訊與逐字稿、分段、標註、正規化、去重及隔離資料 split；生成可重現的 ASR 評估或訓練資料。
---

# 音訊與文字準備

## 輸入與前置條件

先取得來源 manifest、用途授權、原始資料 hash、目標引擎需求及逐字稿／標註狀態。沒有音訊的聖經文字只能作詞彙或提示資料，不能補造對應聲音。

## 流程

1. 探測現有格式、sample rate、channels、codec、duration；依模型／辨識引擎需求決定轉換，不能無條件假設全部是 16 kHz mono。
2. 原始檔唯讀保留，轉換成新版本。記錄工具與版本、參數、input/output hash；不覆寫原音、不把重採樣當降噪。
3. 依說話分段，保留對齊 timestamp、session／speaker/group ID。保留評估所需靜音、重疊說話與噪音案例，不為提高分數全部丟掉。
4. 人工核對聽得到的逐字稿；保留原稿與 normalized reference。不把模型自產稿標成 gold；不強行補成預期經文。
5. 固定繁簡、數字、空白及標點規則，版本化 normalizer；語意／專有名詞錯誤不能靠正規化隱藏。
6. 以場次、講員或來源群組制定 split；同音檔衍生片段／增強版本必須同一 split。跨群組重複音訊及文本需另外檢查並報告。
7. 驗證 schema、路徑、hash、duration／timestamp、空稿、重複、用途授權及 split；無法使用的資料需記錄原因，不能默默刪除。

## 交付與驗收

- 版本化 manifest、轉換設定、資料量／時數、品質與排除報告、split 清單及洩漏檢查。
- 每段需要可追溯來源、實際權利和人工稿狀態；pending 資料不得供訓練或 gold 回測。
- 訓練用文字正規化與顯示用繁體轉換分開；保存可比較的原始辨識輸出。
- 對少量與完整選定資料驗證一致性；缺失 metadata 以 null／pending 表示，不能編造 hash 或時間。

按需參考：[manifest schema](../../../docs/schemas/audio-segment.schema.json)、[資料與評估契約](../../../docs/workflow.md)。

本機接入檢查：`node scripts/check-audio-manifest.mjs --manifest <file.jsonl> --root <approved-data-root> --purpose internal_evaluation`。全資料 split 審計改用 `--purpose split_audit`；需新講員隔離時加 `--speaker-disjoint true`。詳細邊界見 [接入說明](../../../docs/audio-manifest-check.md)，通過不能代替授權查核或人工聽稿。
