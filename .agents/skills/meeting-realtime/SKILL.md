---
name: meeting-realtime
description: 實作或修復房間權限、WebSocket 字幕同步、重連、保留與 expiry；適用 Node 和 Cloudflare Durable Objects 的行為與契約。
---

# 房間與即時後端

## 輸入與定位

先確認故障／需求對應的角色、事件、runtime、重現條件與預期結果。按需讀 server.js、cloudflare/worker.js、public/app.js、test/app.test.js、scripts/smoke-cloudflare.mjs；不要全讀全部後端。

## 流程

1. 從現在實作確認事件：join、caption（final）、ready、interim、final、presence、closed。先記錄實際 payload 再更動，不能只靠文件猜。
2. 驗證 hostToken 可發字幕／關閉；password 或 invite 只可觀看。測試錯密碼、未驗證訊息、觀眾冒充廣播、舊房主連線及過大訊息。
3. 考慮快速重連、舊 socket 延遲事件、重複確定字幕、晚加入、房主離線及房間 expiry。若變更協定，交代相容性或明確移轉步驟。
4. 分別驗證 Node 記憶體與 Workers SQLite 儲存。Workers 的休眠重建、attachment、alarm 和刪除語意不能以 Node 測試替代。
5. 限流考慮整個教會 Wi-Fi 共用 IP；避免為單一連線問題降低所有權限／防護。保存範圍或期限改動需更新產品文件。
6. 排除環境網路與代理問題再判定應用缺陷；讀錯誤、對應一次診斷，不盲目重跑。不得記錄 hostToken、invite、密碼或私人字幕。

## 交付與驗收

- 完成最小修正、重要負向案例及影響的契約記錄。
- Node 修改跑 npm test；Workers 修改跑打包及已啟動的本機功能測試。共享流程修改需覆蓋兩者受影響的路徑。
- 公開端的測試使用獲准的 URL 和合成字幕，清理測試房間。不要對不明部署做壓力測試。
- 證據說明同步／權限／保存哪一項通過，不能僅憑 PID、port 或 health 判定房間可用。

按需參考：[工作流](../../../docs/workflow.md)、[Cloudflare](../../../docs/cloudflare.md)。
