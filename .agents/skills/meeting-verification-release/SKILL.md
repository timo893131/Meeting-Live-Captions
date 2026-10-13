---
name: meeting-verification-release
description: 依修改風險安排功能驗證、語音回測、Cloudflare 打包與發布、公開網站驗證及回退；區分建置、部署、合成字幕與真人語音證據。
---

# 驗證與發布

## 輸入與規模

檢查 diff、任務驗收、runtime、repo／branch 與部署對象，讀相關主 Skill 的結果摘要。沿用既有授權，純文件與小文案不跑整套應用／模型測試。

## 檢查矩陣

| 影響 | 必要的代表性驗證 |
| --- | --- |
| 文檔／Skills | 路徑、名稱、frontmatter、相互一致性、git diff --check |
| 靜態 UI | 選定桌面／手機畫面、鍵盤／長字幕／錯誤狀態 |
| 個人字幕／詞彙 | npm test 與受影響瀏覽器流程；詞彙候選回測 |
| Node 房間 | npm test、權限／晚加入／關閉等受影響案例 |
| Workers 房間 | npm run check:cloudflare、本機服務＋npm run test:cloudflare |
| 模型／音訊管線 | 固定 manifest／baseline、相關品質與延遲回測 |
| 正式發布 | 成功部署證據、實際 URL 的核心功能與清理、回退版本 |

## 流程

1. 先跑能捕捉此變更失敗的最小檢查。失败时讀根因，區分程式、工具／網路、資料與外部服務，不用跳過案例換綠燈。
2. 保存命令退出狀態、測試數與日期／版本；passed、failed、skipped、unrun 分開。重跑要有新修改或診斷。
3. 上線前確認真實部署 repo 和 branch。官方一鍵部署會複製 repo，原專案 push 不一定更新那個副本；記錄映射，不猜自動發布成功。
4. 依已授權範圍發布，取得 Cloudflare 實際 HTTPS URL。確認現有權限，瀏覽器登入不等於 CLI 授權；不用聊天傳遞秘密。
5. 公開 smoke 使用合成字幕：首頁／health、錯密碼、host／viewer 權限、邀請、暫定／確定字幕、history、QR、close；清理房間。只對核准目標執行。
6. 若環境必須用代理，沿用平台代理並配置相應 HTTP／WSS agent；不輸出代理憑證，不關閉 TLS，不把 DNS／代理失敗當網站失敗。
7. 真實收音另外用支援的瀏覽器和獲准音源驗證；記錄瀏覽器、語言、環境與人工結果，不與合成 smoke 混為一談。
8. 失敗則依事先記錄的版本與 Cloudflare deployment 歷史回退；若含資料 schema／migration 變更，先判斷舊版相容，不盲目回退。

## 交付

最終只報重要變更、版本、實際執行結果、限制及必要下一步。無帳號權限／公開 URL 時可以完成本機驗證與打包，但不可宣稱已上線。

按需參考：[發布狀態與矩陣](../../../docs/workflow.md)、[Cloudflare 部署](../../../docs/cloudflare.md)、[工作卡](../../../docs/templates/task-card.md)。
