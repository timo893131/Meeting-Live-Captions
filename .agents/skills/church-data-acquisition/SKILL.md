---
name: church-data-acquisition
description: 蒐集或爬取聖經詞彙、講道文字、授權音檔與教會用語；先確認來源、用途授權、同意、保存及可追溯性。
---

# 資料來源與爬取

## 輸入

來源 URL／上傳資料、所需資料類型、預計用途（詞彙整理／內部評估／訓練／發布）、規模、存放位置。若用途未指定，先整理來源清單及權利資訊，不擅自大量下載或當作訓練資料。

## 流程

1. 查核來源版本、譯本、權利聲明、robots／服務條款、API／匯出方式和相關授權；公開可讀與獲准訓練分開判斷。
2. 先處理受權利允許的少量樣本，驗證解析後再擴大。優先官方 API／公開匯出；不繞過登入、付費牆、速率限制或其他存取控制。
3. 爬取需限制 domains、requests、bytes、並行數與重試；尊重 Retry-After、使用可識別的 User-Agent，保存來源與取得時間。
4. 原文／音檔不可被正規化覆寫。保存 SHA-256、mime、資料長度及 parser 版本，用 stable ID 去重，支持中斷後續抓。
5. 對錄音確認講員／參與者同意與可用範圍，移除不需要的個資。不得將禱告代求、私人見證或敏感對談直接進入公開資料集。
6. 授權／同意不明時標 pending 並排除後續受限用途；可以繼續做來源登錄、解析器與其他已允許的資料工作。

## 交付與驗收

- source register、取得／失敗／去重數、manifest、來源及權利依據。秘密與私人資料留在核准的本機／外部儲存，不提交 Git。
- 以代表性樣本核對來源、解析及完整性；空結果不得報告蒐集成功。
- HTTP 200、robots allow 或頁面有聖經文字，不是訓練授權證據。
- 完成後交給 speech-data-preparation；若只有詞彙文字，不稱之為 ASR 音訊訓練集。

按需參考：[資料規則](../../../docs/workflow.md)、[來源登錄](../../../docs/templates/source-register.example.csv)、[manifest 範例](../../../docs/templates/audio-segment.example.json)、[schema](../../../docs/schemas/audio-segment.schema.json)。

指定 TWGBR 資源時，按需讀 [來源檢查](../../../docs/twgbr-source-review.md)，使用 `python scripts/review_sources.py` 先做有限 seed 檢查；此工具不會遞迴爬取或核准訓練權利。

對已取得的 TWGBR review report，可用 `scripts/inspect_twgbr.py` 離線盤點；`scripts/probe_audio.py` 只讀取有限 byte range。依 `requirements-data.txt` 準備工具。篇號／檔名吻合不等於逐字對齊；任務只要求盤點或尚無訓練授權時，不擴大到模型訓練。
