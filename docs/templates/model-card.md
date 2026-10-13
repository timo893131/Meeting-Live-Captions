# 模型卡：<模型 ID／版本>

尚未訓練或測量時，明確寫 planned／unrun。不要將模型卡模板當作已有模型。

## 用途

- 狀態、負責人、建立日期：
- 支援語言／場景／模型限制：
- 基礎模型、精確 revision／hash、授權：
- 評估改善目標與不適用場景：

## 資料與訓練

- train／validation／sealed test manifest、hash、split 方法：
- 資料權利／同意、保存與刪除要求（不填私人內容）：
- 人工 reference 與 normalizer：
- 全微調／LoRA 配置、seed、precision、steps、checkpoint 選擇：
- GPU／記憶體、時數、費用／預算與工具版本：
- 訓練／resume 命令或版本化 config：

## 匯出與回測

- checkpoint、adapter／merged／CTranslate2 產物、hash、量化：
- 評估報告與 baseline；教會、一般中文、靜音／噪音的結果：
- CER／詞彙／誤改、p50／p95 字幕延遲、RTF／記憶體：
- test 是否曾被用於調整，以及相關限制：
- 部署相容性、預計主機與字幕事件契約：

## 上線與回退

- 核准用途、試用範圍與實際部署版本：
- fallback、上一版、回退命令／格式相容性：
- 未解限制、失敗情境、監測與回報方式：
