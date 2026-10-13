---
name: speech-finetuning
description: 在授權資料、固定評估與算力預算具備時規劃或執行 Whisper／LoRA 微調、checkpoint 選擇、模型匯出與量化驗證；不在一般 Workers 訓練。
---

# 語音模型微調

## 前置條件

需要明確的訓練需求、具有 training 權利的音訊＋人工稿、隔離的 train／validation／sealed-test、baseline、GPU／執行位置、時數／費用與保存預算。現有瀏覽器 ASR 的模型不可由本專案微調。

若只有訓練規劃要求，交付設計與可執行步驟，不啟動訓練。若要求實際訓練，缺少關鍵資料、授權或算力時先完成配置與可做的資料驗證，再指出具體前置條件。

## 流程

1. 判斷不足是否能由音源、詞彙提示或校正解決；記錄微調要改善的 cohort／錯誤類型，不為換模型而換模型。
2. 檢查基礎模型授權、精確 revision／hash、繁中支援、工具鏈與硬體相容性；Whisper 使用多語版本，不誤用 .en。
3. 在訓練前固定 manifest、normalizer、tokenizer、seed、LR、batch／gradient accumulation、precision、steps、eval interval、checkpoint 與 resume 策略。
4. 先用小批資料驗證資料管線、標籤、梯度、顯存與可恢復性；結果只稱 pipeline smoke，不視為品質改善。
5. 依預算執行訓練，記錄當前／最佳 checkpoint。依 validation 選模型，封存 test 不可作 early stopping 或 prompt 調整。
6. LoRA 減少可訓練參數，仍需載入基礎模型；匯出時先確認合併流程及部署格式相容。轉 CTranslate2／int8 後重新比較品質、延遲與記憶體。
7. speech-evaluation 完成教會／一般中文／靜音／噪音回測，並記錄失敗案例。候選未達門檻則不替換 baseline。
8. 通過後先在單一房主／小規模部署，維持字幕事件契約及既有辨識 fallback；保留上一個可用版本與回退命令。

## 交付與驗收

- training config、來源與資料版本、費用／算力記錄、checkpoint／輸出 hash、模型卡、匯出版本與評估報告。
- GPU 訓練與模型推論不放入一般 Cloudflare Workers／Durable Objects；模型權重與錄音不上 Git。
- loss 下降、訓練完成或 checkpoint 存在都不等於字幕品質提升；不得用編造的數字／音訊補足成果。

按需參考：[模型方案](../../../docs/architecture-and-speech.md)、[訓練工作流](../../../docs/workflow.md)、[模型卡](../../../docs/templates/model-card.md)。
