# 評估報告：<候選／run_id>

未取得實際數據的欄位標 unavailable／unrun，不以範例當成果。

- 目標與假設：
- baseline／candidate；唯一主要變因：
- 資料 manifest 版本／SHA-256、來源授權、split／封存狀態：
- 樣本數、音訊時數、詞彙出現次數／cohorts：
- 人工 reference 狀態、normalizer／metric 版本：
- 模型 revision／詞彙 hash、browser／provider、工具與硬體：
- 評估前已約定的品質／誤改／延遲／資源門檻：
- 命令、開始／結束時間、退出狀態、產物位置：

## 比較

| cohort／指標與分母 | baseline | candidate | 差異 | 判定／限制 |
| --- | --- | --- | --- | --- |
| <如 CER，N=...> | unavailable | unavailable | unavailable | <尚未量測> |

CER 記錄 S/D/I/N 與正規化規則；詞彙對齊 reference 出現位置。暫定、確定與觀眾同步延遲分開，記錄測量起訖與時鐘。無 reference 或有效樣本時不能報零錯誤。

## 錯誤與限制

- 改善／退步類型與去識別案例：
- 一般中文誤改、經文數字、靜音／噪音、長句問題：
- 演算法結果與人工抽查；樣本量及重複測量限制：
- test 是否用於調參；若有需揭露並更換封存集：
- token／算力／時間／費用及 metadata 來源：

## 決策

採用／保留 baseline／繼續實驗：<由門檻及證據決定>。

候選發布範圍、上一版與回退：<實際可執行步驟>。
