# 詞彙分類與離線回測 v1

## 本階段範圍

新增八類詞彙分類與 21 個人工合成開發案例，不從 TWGBR 複製語料，未使用真人音訊或辨識紀錄；不代表真實 ASR 準確率。正式 glossary.js 與網頁行為未更改，候選只供離線比較。

分類見 [taxonomy.json](../evaluation/glossary/taxonomy.json)：聖經書卷、人物、地名、屬靈／神學用語、教會生活、經文數字、本地姓名／教會名稱、多義詞／專名邊界。這是標註設計，並非由來源自動擷取的完整詞典；不會把合法譯名或神學近義詞一律改成某個版本。

## 執行

```sh
npm run eval:glossary
npm run eval:glossary:candidate
node --test test/glossary-evaluation.test.js
```

- eval:glossary 執行原始合成輸入與目前 defaultGlossary 的比較，沒有候選時 candidate gate 為 unrun，但案例已執行。
- eval:glossary:candidate 加入固定的縮小前綴實驗；目前**預期退出碼為 1**，因 bible_books cohort 退步。這是候選不通過，不是安裝或執行失敗。
- 報告位於忽略的 artifacts/glossary-evaluation/<run_id>/report.json，保存每案輸出、S/D/I/N、分組指標、fixture／詞彙／評估程式 hash、code commit 與 workingTreeDirty。
- 可傳 --output 指定新的報告路徑；已存在檔案不覆寫。沒有 token／費用 metadata 時記 unavailable，不編造節省率。

本版只接受標示 authored_synthetic_development 的資料，最多 500 案，每段最多 500 個正規化 Unicode code points。未建立真人資料接入、sealed test、模型推論、音訊延遲或訓練流程。

## 指標與座標

正規化版本 `nfc-strip-punctuation-space-v1`：Unicode NFC 後移除標點及空白；不轉繁簡、不修數字、不替換詞彙。中英文大小寫及符號保留與否由此固定規則決定，不為候選臨時改算法。

- CER = (替換 S＋刪除 D＋插入 I)／reference code-point 數 N；以總計計算，N=0 為 null，仍保留插入數。
- 詞彙正確率 = 正確的已標註出現位置／全部標註位置。terms 的 start／end 是正規化 reference 的 Unicode code-point 半開區間；驗證其文字與座標一致且不重疊。
- 用編輯距離對齊後逐位置評分，不以全文 contains 判定。例如第一個「耶穌」錯、第二個正確，第一個不會因後面有正確詞就算對。
- 誤改率 = 原先正確而被改錯的標註位置／原先正確的標註位置，分母為零時 null。它不是所有自然語言錯誤的完整統計。
- 對齊使用固定 tie-breaking；重複字詞有多個同成本對齊時仍需人工檢查，不把機器字元對齊當成人工語意標註。

## 實測結果：僅此合成開發集

21 案含 148 個 reference 字元、27 個標註出現位置；其中 16 個位置在原始輸入已正確。空文字案不提供語音靜音證據。

| 版本 | 字元錯誤／N | 正確標註位置 | 新誤改／原先正確位置 |
| --- | --- | --- | --- |
| 原始合成輸入 | 11／148 | 16／27 | 0／16 |
| 正式 defaultGlossary | 2／148 | 25／27 | 1／16 |
| 前綴實驗候選 | 2／148 | 25／27 | 0／16 |

整體分數一樣仍可能有分組退步：

- defaultGlossary 的「創世紀→創世記」可修正經文用語，也會誤改合成的港劇名稱例句。
- 候選只在「讀創世紀」「創世紀第」前綴替換，避開專名誤改，卻漏掉「今天講創世紀」的經文案例。
- 兩者都沒有修正合成的經節數字誤識，詞彙表不能憑常見經節推定使用者講的數字。

事先定義的 fixture gate：任一 cohort 的 CER、詞彙正確率不能退步，亦不可增加誤改。候選 bible_books cohort 退步，所以 gate failed，保留正式版本。

案例與候選均在開發時可見，不是未見測試集；候選改善某些案例不代表通過生產驗收，也不能宣稱真人辨識提升到 25／27 或某百分比。

## 下一步與資料接軌

1. 人工審閱分類及正向／負向案例，補足多義詞、譯名、數字與教會常用搭配。
2. 有權使用的真實辨識輸入／人工稿到位後，另建立資料 manifest、場次／講員分組與封存測試流程；不能把本版的合成 fixture 改標籤冒充真人資料。
3. 用 validation 評估上下文規則／詞彙提示，不只堆疊能通過已知案例的前綴；正式採用需真實代表性資料與固定驗收。
4. TWGBR 仍只有來源盤點／技術檢查授權範圍；未取得模型訓練授權，不擴大抓取或開始微調。
