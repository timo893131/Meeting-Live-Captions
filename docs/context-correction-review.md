# 上下文詞彙候選：人工核對工作流

目標：把單一已見錄音中的辨識問題轉成可逐筆審閱的建議，而不是新增全域替換或微調模型。分類為 EVALUATE，使用 speech-evaluation Skill；沒有變更正式產品、glossary.js 或 WebSpeech。

## 範圍與限制

- 目前只有一份可供評估的聚會錄音，尚無經人工逐段確認的 gold reference；本輪只建立五組文字建議規則，並用人工合成正向／反向例句檢查程式。
- 規則見 [context-review-rules.json](../evaluation/glossary/context-review-rules.json)。每次建議需在原始 ASR 同一片段中符合指定的 before／after 字串；同一 context 兩者皆指定時須同時成立，多個 context 擇一。沒有繁簡轉換、標點清理、模糊比對或跨段推定，故切分／空白不同會漏掉建議。
- 保留 rawText，記錄原始字元位置、ruleId、source、suggested 與 pending 決定；suggestedText 是全部候選套用時的預覽，不能當已核准逐字稿。位置使用 Unicode code points，重疊候選直接拒絕，不自行選規則。替換不串接處理。
- 「婚姻」「演習」等一般詞未建立替換規則；「高揚的妻」缺少足夠上下文，也不提出建議。有限反例通過不能證明所有情境安全；其餘命中亦需回聽。
- 使用者之前核准的是目標詞／概念。本次新增的「禁食、羔羊、施浸、童女、召會」只是待審的錯誤假說，未因程式命中就升格為已核准詞彙或訓練標籤。
- 這些規則是看過此開發樣本後擬定，沒有獨立測試證據。Whisper raw ASR 與候選預覽分開，不套用現行 defaultGlossary，也不宣稱與網站 WebSpeech 直接比較。

## 執行與交付

```sh
node scripts/propose-context-corrections.mjs \
  --asr artifacts/local-asr/<run>/raw-asr.json \
  --rules evaluation/glossary/context-review-rules.json \
  --output artifacts/context-review/<new-run>

python3 scripts/build-context-review.py \
  --suggestions artifacts/context-review/<new-run>/suggestions.json \
  --audio data/meeting-evaluation/week12day1/week12day1.mp3 \
  --output artifacts/context-review/<new-run>/review.html
```

輸出 suggestions.json、review.tsv 與內嵌原音的 review.html。JSON 是無損主檔，TSV 字串採 JSON quoting，僅供檢視。所有輸出都放在 Git 忽略目錄；目錄／檔案已存在即退出，不覆寫人工工作。報告記錄輸入、規則與提議程式 SHA-256；核對頁另驗證音檔 hash、原文字元座標及預覽一致性。

下載後以瀏覽器開啟 HTML：先播放，再選「採用此處／拒絕此處」；預設全部待確認。填核對者代號後下載 JSON，回傳核對結果才有後續匯入依據。此頁只列出有建議的片段，不是完整逐字稿工具，採用一筆也不表示核准全域規則；決策檔可經下述 CLI 驗證後套用至此錄音的字幕；不會自動發布或更新產品規則。變更不會自動儲存，也不會送到網站。即使所有建議已決定，goldReferenceAvailable、accuracyMeasured、productionEligible 仍為 false。

驗證：`npm test` 檢查規則、一般語境、重複詞、Unicode、衝突與不跨段，以及 CLI 報告保存；`python3 -m unittest discover -s test -p test_context_review.py` 檢查輸入座標、音檔一致性及 HTML／JSON escaping。另以合成互動測試核對實際頁面的採用／拒絕、身份欄位、下載與手機版面，不把 UI 測試當作真人聽音。

## 環境與下一步

本次工作區未帶回先前忽略的私人產物，因此從原附件恢復音檔，依相同固定模型 revision／權重 hash 及 PyAV 16.0.1 重跑原始 ASR。舊檔連結不保證跨環境保留；新產物應下載到核准的私人儲存位置，不能靠 Git 保存私人資料。模型設定見 [local-asr.md](local-asr.md)。

人工決策到位後，再擴充負向案例並設計下一版規則；仍需整份人工 reference、其他場次及固定門檻才能正式回測。修改數只表示建議量，不代表修對數或準確率提升。這批資料只供已允許的評估，沒有開始訓練，也未擴大 TWGBR 抓取。

2026-10-19 實際執行：恢復後 ASR 仍為 159 段，五組規則提出 9 筆、分布於 9 段的 pending 建議；其餘片段沒有自動擴大替換。Node 20 項測試、Python 2 項核對頁測試，以及實際核對頁的播放定位、身份必填、採用／拒絕匯出與手機寬度檢查通過。互動測試使用的決策僅供驗證，沒有當成人工審閱結果匯入；整份人工逐字稿核對、正式準確率與生產驗收仍未完成。

## 匯入已回傳的決策

```sh
node scripts/apply-context-decisions.mjs \
  --asr artifacts/local-asr/<run>/raw-asr.json \
  --rules evaluation/glossary/context-review-rules.json \
  --proposals artifacts/context-review/<run>/suggestions.json \
  --decisions <private-review-file.json> \
  --output artifacts/context-review/<new-applied-run>
```

匯入器先用原始 ASR 和同一規則重建候選，核對音檔、ASR、規則 hash 與每個字元座標／建議內容。每一個有建議的片段及項目都需回傳；未決定時保留 pending，不能省略。重複、篡改、版本不符或缺少核對者的決策會被拒絕。只套用 accepted 出現位置，rejected／pending 保留原字；同段多筆以原始 Unicode 座標一次套用，不串接改寫。

新輸出目錄包含 corrected-transcript.txt、corrected-subtitles.srt、reviewed-corrections.json 與原樣保存的 review-decisions.json。紀錄保留原文、校正後文字、時間戳、核對者、逐筆決策及來源／決策／程式 hash；既有目錄拒絕覆寫，原始 ASR 不變。

這是「已確認出現位置的部分校正」，不是完整 human_verified reference，也不會推定整體 CER 或生產可用。首次回傳的 9 筆全部 accepted，驗證版本吻合後已套用至 9 段；全檔 159 段的原文／時間戳均保留，其他 150 段內容未改。這些私人決策和字幕未加入 Git；正式產品與規則核准範圍維持原樣。仍需整份文字核對和獨立場次，才能做完整準確率與泛化驗收。

驗證：`npm test` 新增決策匯入測試，涵蓋混合採用／拒絕／待定、Unicode 長度變更、來源／版本失配、篡改／重複／漏項、時間戳進位與防覆寫。
