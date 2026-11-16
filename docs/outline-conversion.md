# 綱要轉換：PDF → Markdown → 本場詞表

2026-11-16。M1（[spec-large-meeting.md](spec-large-meeting.md)）的前置：聚會前房主貼上當堂綱要，字幕依綱要的專名與經節校正。
這份文件回答「怎樣轉換最有效率又準確」。

## 結論

1. **有文字層就直接讀，不做 OCR。** 訓練綱要的 PDF 通常由排版軟體輸出、帶文字層，直接抽字就和原稿一字不差，而且一份幾秒鐘就能跑完。
   OCR（Google 文件「用 Google 文件開啟」、Tesseract）會把恢復本專名認錯（例如「祂」「裏」「豫表」），錯字一旦加進本場詞表，就會把字幕改錯。
   只有報告列出「沒有文字層」的頁（掃描或圖片），才對那幾頁補做 OCR 或人工輸入。
2. **要先轉成 Markdown，但只是中間格式。** Markdown 保留綱要的層次：`## 第X篇 篇題`、`讀經：` 行，以及 `壹／一／1／a` 依層級縮排的要點。這正是 `parseOutline` 要用的
   `{title, points, refs, terms}`，人眼也容易核對、可以比較差異；而且是純文字，房主可以直接整篇複製貼上。
   網站的「本場綱要」框接受 Markdown，也接受從 PDF 直接複製的純文字（`parseOutline` 會略過 `#`、`-` 等標記）。
3. **一份 PDF 轉一次（Colab 批次），每篇存一個檔。** 聚會前只貼當堂那一篇，不必整份貼上；貼越多，本場詞表就越大，也越容易誤改。
4. **輸出只放在雲端硬碟。** 綱要有著作權，不進 Git、不放公開靜態檔，和恢復本文字一樣處理。

## 工具

| 檔案 | 用途 |
| --- | --- |
| `scripts/outline_pdf_to_md.py` | PyMuPDF 抽文字層 → 清理 → 分篇 → `<檔名>.md`、`<檔名>/NN.md`（每篇一檔）、`<檔名>.report.json` |
| `notebooks/outline_to_markdown.ipynb` | Colab（CPU）：有文字層的 PDF；在 MyDrive 找到 PDF，結果寫在 PDF 旁的 `<檔名>-md/` |
| `scripts/outline_ocr.py`、`notebooks/outline_ocr.ipynb` | 掃描 PDF：Google 雲端硬碟 OCR → 同一套轉換＋自動檢查 |
| `test/test_outline_pdf_to_md.py` | 合成頁面＋真的 PDF（用 PyMuPDF 產生）測試 |

## 已處理的 PDF 問題

| 問題 | 處理 |
| --- | --- |
| 頁首、頁尾、頁碼（含羅馬數字） | 頁面上下 8% 之內、在 ≥30% 頁面重複出現的行（數字視為相同）刪除 |
| 目錄頁的「第一篇 ……1」 | 有點線或結尾帶頁碼的篇題行略過，不當成新的一篇 |
| 中文換行把一句切成兩行 | 沒有層級標號的行接回上一個要點（不加空白）；跨頁也接 |
| 康熙部首（⼀ U+2F00）、相容漢字 | NFKC 轉成一般漢字（否則「⼀個」不會被當成「一個」） |
| 全形數字／字母、全形空白 | 轉半形（經節「２３」→「23」）；中文標點保留全形 |
| 經節範圍「～」被抽成「∼」「〜」 | 統一為「～」（實測 PyMuPDF CJK 字型就會這樣，否則一段經節會被拆成兩段） |
| 字型私用區字元（U+E000–F8FF） | 無法還原，報告計數並警告，需人工核對 |
| 掃描頁 | 報告列出頁碼，不自動 OCR |

## 報告怎麼看

`report.json` 每篇有 `scripture_lines`（讀經行）、`points`（有標號的要點數）、`verse_references`（經節數）、`unmarked_lines`（沒有標號的行）。
正常的一篇：有 1 行讀經、數十個要點、未標號行很少。若未標號行很多，可能是雙欄排版、詩歌或附錄，要人工看。`warnings` 不是空的就要先處理。

## 範例 PDF 現況（2026-11-16）

`ex_TS26TRN_zht.pdf`（62 MB）用 `outline_to_markdown.ipynb` 轉換的結果：**87 頁都沒有文字層，整份都是掃描或圖片頁**，所以要走 OCR。

## 掃描 PDF：Google 雲端硬碟 OCR

| 選項 | 判斷 |
| --- | --- |
| **Google 雲端硬碟 OCR**（採用） | 免費，用使用者自己的帳號，不必安裝；印刷體繁體中文品質好。每頁轉成 < 2 MB 的 JPEG（Drive OCR 的上限），以 `ocrLanguage=zh`（Drive v3 只接受 ISO 639-1，`zh-TW` 會回 400；只是語言提示，繁體字照原樣輸出）建暫存 Google 文件，匯出文字後刪除 |
| Tesseract `chi_tra` | 免費，但中文印刷體錯字明顯較多 |
| PaddleOCR／RapidOCR | 品質好，但模型在執行時才下載，版本相依多；Drive OCR 不夠好時再當第二引擎比較 |
| 付費 OCR API、視覺語言模型 | 不符合零費用 |
| **原稿文字檔（Word／網頁）** | 如果拿得到，最準也最快，完全不必 OCR |

沒有人工打字的參考稿，所以 `scripts/outline_ocr.py` 用兩項自動檢查估計 OCR 品質：
1. 經節章數不存在（例如「弗七3」，以弗所書只有 6 章）：多半是數字或國字認錯。
2. 和內建教會專名／聖經人名只差一個字（例如「神的經論」對「神的經綸」）：可能認錯字。

這兩份清單在 `report.json` 的 `invalid_references`、`term_suspects`。房主貼上綱要前應該先修好，因為錯字會進本場詞表。

執行：`notebooks/outline_ocr.ipynb`（CPU），輸出在 PDF 旁的 `<檔名>-ocr/`（每頁快取）與 `<檔名>-md/`。
