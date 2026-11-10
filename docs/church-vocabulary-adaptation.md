# 教會專業詞彙調適：TWGBR 文字擷取與詞彙提示對照

- 任務：2026-11-10；狀態 **blocked（詞彙待人工審查；音訊訓練權利與人工逐字稿缺）**。
- 路由：church-data-acquisition（爬取）→ speech-evaluation（對照）；speech-finetuning 只做前置判斷，未訓練。
- 使用者指定範圍：TWGBR 恢復本聖經與生命讀經（line.twgbr.org）。使用者指示需要時可爬文字及音訊。
- 權利：頁面標示「CopyrightⒸ 臺灣福音書房」；**rights_status=pending**。本次音訊只作私人內部評估，所有列 training_ready=false，原文／原音／結果全在 Git 忽略的 data/、artifacts/、models/。

## 1. 文字爬取（text-v2）

```sh
.venv/bin/pip install -r requirements-data.txt
.venv/bin/python scripts/crawl_church_sources.py --config sources/church-crawl-text-v2.json \
  --output data/church-crawl/twgbr-text-v2
```

固定 132 個 seed（恢復本 01–66 卷、生命讀經 66 卷入口頁），`follow_links=false` 不遞迴；1 req/s、robots、單一 host、40MiB／150 requests／900 秒上限；音訊只建索引不下載。爬蟲頁數上限由 10 提高為 200（`MAX_PAGES`），預設 church-crawl.json 仍為 10 頁。

| 實測 | 值 |
| --- | --- |
| 頁面／文字文件 | 132／132，失敗 0 |
| HTTP requests／body | 133／6,483,322 bytes |
| CJK 字元（NFC 計數） | 1,254,382 |
| 音訊 URL 索引 | 63（只下載下節 3 個） |

## 2. 詞彙候選擷取

```sh
.venv/bin/python scripts/extract_church_terms.py --collection data/church-crawl/twgbr-text-v2 \
  --output data/church-vocabulary/<run> [--exclude-source <評估音訊對應頁>]
```

無監督新詞發現：2–6 字 n-gram 的頻率、文件頻率、內部凝固度（最小 PMI）、左右鄰字熵；去除幾乎總出現在較長候選內的片段、純數字（經節數字交給 reference scorer）與少量功能詞。wordfreq 一般中文 zipf 只作「一般常用詞」旗標與排序權重，不單獨刪詞。輸出：

- candidates.jsonl／review.csv：每列 review_status=pending_review、automatic_replacement=not_allowed、hotword_status=not_approved。review.csv 留 decision／category／note 欄給人工審查。
- orthographic-variants.json：恢復本用字與一般寫法（豫表／預表、大衞／大衛、輭弱／軟弱、主阿／主啊）。**這是輸出用字政策，不是辨識錯誤**；是否在字幕校正表統一，需使用者決定。
- report.json：輸入 URL 與文字 hash、參數、工具 hash、既有 approved-targets／glossary.js 詞的語料覆蓋。

結果中高分候選以聖經人名地名（耶和華、大衞、非利士人、尼布甲尼撒）、恢復本用語（申言者、神的經綸、召會生活、豫表、介言）、經文用語（燔祭、帳幕、聖別）為主；仍有「看哪、因為耶和華」等片語需人工剔除。

## 3. 評估音訊（內部評估樣本）

```sh
.venv/bin/python scripts/fetch_church_audio.py --config sources/church-audio-eval-v1.json \
  --output data/church-audio/twgbr-eval-v1
```

只接受文字爬取索引過的 URL、最多 5 檔、檢查 MP3 header，保存 SHA-256、來源頁與文字 hash。本次 3 檔：生命讀經 Gen-001、John-001、Eph-001（27,552,104 bytes；22,050Hz mono；約 38／41／35 分鐘）。

**重要事實**：抽聽辨識前 90 秒，音訊是講者導讀（「今天我們來看創世記生命讀經第一篇…李弟兄說…」），**不是網頁文字的逐字朗讀**。因此網頁全文不能當 CER reference，本次不報 CER。

## 4. 詞彙提示對照（無 reference）

```sh
.venv/bin/python scripts/compare_vocab_prompting.py --audio-root data/church-audio/twgbr-eval-v1 \
  --candidates data/church-vocabulary/twgbr-text-v2-leaveout-eval-v1/candidates.jsonl \
  --output artifacts/vocab-prompting/<new-run>
```

- 模型：Systran/faster-whisper-small 536b066…，model.bin SHA-256 3e305921…（與既有 baseline 相同），CPU int8／4 threads，zh、beam 5、temperature 0、無 VAD。
- 條件：baseline（無提示）／neutral_traditional（只給「以下是繁體中文的逐字稿。」）／church_hotwords（neutral＋詞彙）。neutral 控制組用來把「繁簡字形」效果與「詞彙」效果分開。
- 詞表規則固定：approved-targets（≥2字）在前，接 leave-out 擷取（排除 3 檔對應的生命讀經頁）中非一般常用的前 40 名，依 tokenizer 截到 200 tokens（實際 41 詞）。**未依評估音訊內容手動加詞**；本次抽聽看到的錯誤（如「生命讀經」「李弟兄」）不得回填詞表後仍稱為同一評估。
- 每檔前 600 秒。指標只有描述性：簡體字比例、詞彙命中次數（輸出轉繁後計數）、RTF；listening-review.csv 列出三條件不同的 30 秒窗格，留欄位給人工聽審。

### 實測結果（run1，每檔前 600 秒，machine_generated、無 reference）

| 檔案 | 條件 | CJK 字數 | 簡體字比例 | 最後段落結束 | RTF |
| --- | --- | --- | --- | --- | --- |
| Gen-001 | baseline | 1,950 | 34.0% | 600.1s | 0.306 |
| Gen-001 | neutral_traditional | 1,946 | 0.05% | 599.0s | 0.238 |
| Gen-001 | church_hotwords | **475** | 0% | 599.1s（13 段） | 0.088 |
| John-001 | baseline | 2,267 | 29.3% | 599.9s | 0.236 |
| John-001 | neutral_traditional | 2,300 | 0.04% | 600.0s | 0.232 |
| John-001 | church_hotwords | **306** | 0% | **132.8s 後無輸出** | 0.067 |
| Eph-001 | baseline | 1,731 | 0.23% | 601.0s | 0.182 |
| Eph-001 | neutral_traditional | 1,721 | 0.23% | 601.0s | 0.197 |
| Eph-001 | church_hotwords | **1,059** | 0.19% | 600.0s | 0.338 |

判讀：

- **41 詞 hotwords 提示判定退步，不採用**：三檔字數降到基線的 13–61%，John-001 在 133 秒後完全停止輸出，屬於長提示導致的漏字／跳段。詞彙命中數因此也下降（18→2、17→1、32→29），RTF 變快只是因為輸出變少。腳本已加 `speech_loss_suspected`（字數 <基線 80%）旗標。
- **中性繁體提示**讓 Gen／John 的簡體輸出從約 30% 降到 <0.1%，字數差 <2%。這只證明輸出字形改變，**不是準確率改善**；是否漏字或改錯，需以 listening-review.csv 聽審。
- 基線輸出可見的教會詞誤識（如「生命毒精／生命獨經」→生命讀經、「李地中」→李弟兄、「以服所書」→以弗所書、「詔會」→召會、「戒言」→介言）來自本評估音訊，只能作 **seen development cases**；若據此改詞表，這 3 檔不能再當未見測試。
- 未驗證：CER、詞彙正確率、誤改率、即時延遲。單一講員風格／低碼率 22kHz 錄音，不代表現場聚會麥克風。

後續候選（未執行）：短詞表（例如 10–15 個書卷／人名）或只用 initial_prompt 的版本，需新 run 目錄並先定好規則；仍以字數不退步為先決條件。

## 5. 是否需要 Whisper／LoRA 微調

目前不能啟動：(1) TWGBR 音訊訓練權利未確認；(2) 生命讀經音訊沒有逐字稿，網頁文字不是其 reference，需人工逐字稿或另取真正的朗讀音訊；(3) 尚無人工核對的 validation／sealed test。上述齊備前，應先以詞彙校正表＋提示詞改善，並以人工聽審結果決定。訓練仍走 [cloud-training.md](cloud-training.md) 的 Colab gate。

## 下一步

1. 使用者審查 data/church-vocabulary/twgbr-text-v2-run1/review.csv（全語料版）與 orthographic-variants.json，決定採用詞、類別及用字政策。
2. 聽審 artifacts/vocab-prompting/twgbr-eval-v1-run1/listening-review.csv 的差異窗格，標出正確條件；達一定數量後才可說提示是否改善。
3. 向臺灣福音書房確認 internal_evaluation／training 用途；確認前不擴大音訊下載。
4. 審查通過的詞再寫入 glossary.js 候選並跑 `npm run eval:glossary` 正反例回測；瀏覽器 SpeechRecognition 不能吃 hotwords，網站端只能靠校正表。
