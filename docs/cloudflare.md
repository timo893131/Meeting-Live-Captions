# Cloudflare 部署與試用

這個版本使用 **Workers + Static Assets + SQLite Durable Objects**，不是單獨的 Pages 靜態網站。每間房間有一個 Durable Object，集中處理 WebSocket 權限、字幕同步及最近字幕。使用 Hibernation WebSocket API，閒置時可讓物件休眠。

Cloudflare 官方目前提供 Workers Free 的 SQLite Durable Objects，但仍有請求、執行時間、讀寫與儲存額度。免費方案超額會導致操作失敗，不代表無限制的免費聚會平台。正式使用前請在 Cloudflare 後台核對目前方案與用量。

- [Durable Objects 免費方案與價格](https://developers.cloudflare.com/durable-objects/platform/pricing/)
- [WebSocket Hibernation](https://developers.cloudflare.com/durable-objects/best-practices/websockets/)

## 用 Cloudflare 後台部署（建議）

1. 登入你的 Cloudflare 帳號，在 Workers & Pages 中建立 **Worker**，選擇從 GitHub 匯入專案。
2. 授權存取 `timo893131/Meeting-Live-Captions`，選擇 `main`。
3. 根目錄使用儲存庫根目錄；build command 使用 `npm run build:assets`，deploy command 使用 `npx wrangler deploy`，Node.js 版本使用 22 或更新版本。
4. Worker 名稱保持 `meeting-live-captions`，與 `wrangler.jsonc` 一致。若此名稱已被你帳號內另一專案使用，先變更設定檔名稱，避免覆蓋既有 Worker。
5. 部署使用設定檔中的 SQLite Durable Object bindings 和 `v1` migration，不要改成 KV-backed Durable Objects。若帳號要求啟用功能，依後台的免費方案提示完成。
6. 部署成功後，開啟 Cloudflare 提供的實際 `workers.dev` HTTPS 網址。網址由你的帳號決定，本文件不預先假設。

不同後台版本的按鈕名稱可能不同。此方式由 Cloudflare 取得 GitHub 存取及部署權限，不需要將 Cloudflare token 傳到聊天。

## 在自己的電腦部署

```sh
git clone https://github.com/timo893131/Meeting-Live-Captions.git
cd Meeting-Live-Captions
npm ci
npx wrangler login
npm run deploy
```

OAuth 登入請在你的電腦完成。成功輸出才是實際部署的網址。Worker 版本由請求的網站 origin 產生 QR Code，不需要設定 `PUBLIC_URL`。

## 本機開發與驗證

```sh
npm ci
npm test
npm run check:cloudflare
npm run dev:cloudflare
```

另開終端執行：

```sh
npm run test:cloudflare
```

`test:cloudflare` 預設測試本機 8787 port。可設定 `CAPTION_TEST_URL` 指向實際部署網址，再執行同一測試。這會建立測試房間、傳送測試字幕，並刪除房間；只用在你自己的部署。

在目前 Codex 雲端環境中，Wrangler 設定／快取目錄需使用可寫位置：

```sh
export XDG_CONFIG_HOME=/workspace/.cloudflare/config
export XDG_CACHE_HOME=/workspace/.cloudflare/cache
export WRANGLER_SEND_METRICS=false
```

## 上線後的人工試用

1. 在桌面版 Chrome 開啟實際 HTTPS 網址。
2. 選個人模式、允許麥克風，說「耶穌基督、聖靈、以馬內利、腓立比書」；核對字詞及延遲。
3. 開啟詞彙設定，將實際誤識加成 `誤識文字=正確文字`，儲存後再次說相同內容。
4. 選廣播模式，在另一台裝置掃描 QR Code，確認不用密碼即可觀看。
5. 再用另一個瀏覽器輸入房間代碼與密碼，確認同樣可以加入，錯誤密碼不能加入。
6. 房主說話，確認暫定與確定字幕都會同步；房主結束房間，確認觀看端顯示已結束。

瀏覽器模擬测试使用模擬的辨識事件，驗證的是字幕程式流程，不是麥克風或辨識服務準確率。真正的語音測試仍需上述人工步驟。

## Cloudflare 版本的資料保留

為支援 Durable Object 休眠／重啟，房間驗證資訊與確定字幕會存入 Durable Object 的 SQLite-backed storage。最多保留最近 200 段，字幕總大小限制約 90 KB；長字幕可能使保留段數更少。這與 Node 版本只存記憶體的行為不同。

房主結束房間或 12 小時到期時，應用會刪除該房間儲存的資料。這是應用層刪除，不代表保證供應商備份即時清除。未確定字幕存在 WebSocket attachment；詞彙表仍只存在房主瀏覽器。伺服器不儲存音訊。

最多同時接受 200 個房間連線（含房主與尚未完成驗證的連線）。建立房間及驗證有基本限流；限流門檻考慮同一教會 Wi-Fi 共用對外 IP 的情境。大量公開流量仍應搭配 Cloudflare 的適當防護與用量監控。
