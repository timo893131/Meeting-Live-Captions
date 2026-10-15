---
name: speech-evaluation
description: 用固定資料與基準評估教會詞彙校正、語音模型、提示與歷史聚會回測；比較 CER、詞彙誤改、延遲及資源成本，避免測試洩漏。
---

# 詞彙與 ASR 評估

## 最小輸入

baseline／candidate 版本、具授權的固定資料 manifest、reference 來源、normalizer、cohorts、runtime／硬體及驗收門檻。詞彙離線評估只需既有原始辨識文字，不必每次重新跑音訊模型。

## 流程

1. 先記錄 baseline 與候選唯一變因（詞彙表、prompt、模型、quantization 或分段策略）；保留 raw 和 corrected 輸出。
2. 評估集按講員／場次／噪音及詞彙類型分組，涵蓋一般中文與非教會上下文，包含容易被詞彙表誤改的句子。
3. 中文以 CER 為主要整體指標，記錄計算規則、S/D/I/N；如報 WER，固定中文斷詞器版本。零 reference／空樣本的指標標 undefined，不當零錯誤。
4. 專有名詞以人工標註的出現位置對齊，計算正確率及誤改；不能只檢查候選全文是否出現該詞。需核對經文書卷、姓名與數字。
5. 即時情境分別測暫定字幕、確定字幕、同步到觀眾的延遲；說明起訖點、時鐘與測量方式。離線 RTF 不能當作字幕端到端延遲。
6. 每次保留執行版本、browser／provider（可知範圍）、硬體、設定、seed、成本與原始結果。WebSpeech 供應商版本未知就寫 unknown。
7. 驗收先訂門檻；開發只看 train／validation，選定候選後才看封存 test。若依 test 結果調整，需揭露並換新的封存測試集。

## 交付與判定

- 用 eval-run.example.json 與 evaluation-report.md 保存可比較的摘要；數據與私人例句留在忽略的 artifacts/。
- 報告各 cohort、樣本數、baseline／candidate、差異與限制；少量樣本不宣稱普遍提升。
- 門檻沒有滿足就保留 baseline，先定位錯誤類型；模型訓練只在可測不足且前置條件齊全時接續。
- 小詞彙規則修正跑對應案例；版本發布需要完整固定回測。模擬字幕／使用者好評不等同實測 CER。

按需參考：[指标定義](../../../docs/workflow.md)、[詞彙候選](../../../docs/templates/glossary-candidate.example.json)、[評估報告](../../../docs/templates/evaluation-report.md)、[run metadata](../../../docs/templates/eval-run.example.json)。

現有文字回測工具與限制見 [詞彙回測](../../../docs/glossary-evaluation.md)：`npm run eval:glossary` 比較 21 個人工合成開發案例；`npm run eval:glossary:candidate` 的前綴實驗目前預期失敗，不能因整體分數不變就忽略分組退步。資料及規則位於 evaluation/glossary/，不是 TWGBR 語料或真人 ASR 基準。
