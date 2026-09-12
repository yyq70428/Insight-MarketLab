# 02 — 環境變數規格

## 通則

- 所有後端設定由單一設定層在載入時讀取。
- 程序環境值優先於根目錄環境檔，環境檔優先於內建預設值。
- 整數與浮點值無法解析時回退到預設值。
- 設定變更後必須重啟應用才生效。

## 設定清單

| 類別 | 名稱與預設 |
| --- | --- |
| 應用 | HOST 為 127.0.0.1；PORT 為 8000；CORS_ORIGINS 為所有來源 |
| 快取 | 即時報價 5 秒；盤中 K 線 15 秒；日線 60 秒；搜尋 300 秒；中繼資料 3600 秒；公司資料 86400 秒；新聞 300 秒；最多 256 個快取項目 |
| 分析 | MAX_HARMONIC_RESULTS 為 8；MAX_SR_ZONES 為 6 |
| 上游 | UPSTREAM_TIMEOUT 為 6 秒；UPSTREAM_USER_AGENT 為瀏覽器形式識別字串 |
| 新聞 | NEWS_MAX_PAGES_PER_ROUND 為 10；NEWS_MAX_ARTICLES 為 8；NEWS_TIMEOUT 為 8 秒 |
| 模型 | OPENAI_API_KEY 預設空；OPENAI_BASE_URL 指向 Responses 相容介面；OPENAI_MODEL 為 gpt-5.6-luna；OPENAI_TIMEOUT 為 90 秒 |
| 舊版報告 | AGENT_REPORT_TTL 為 3600 秒 |
| MongoDB | MONGODB_URI 預設空；MONGODB_DATABASE 為 marketlab |
| PostgreSQL | DATABASE_URL 預設空；容器環境另提供主機、使用者、密碼與資料庫名 |
| 新聞評審 | RAGAS_ENABLED 為 false；模型、基底與金鑰預設沿用主模型；RAGAS_TIMEOUT 為 120 秒 |
| 掃描 | SCAN_INTERVAL 為 900 秒；SCAN_CANDLE_INTERVAL 為日線；SCAN_FETCH_DELAY 為 0.4 秒 |
| 告警 | DISCORD_WEBHOOK_URL 預設空；ALERT_INTERVAL 為 300 秒；ALERT_COOLDOWN 為 86400 秒；ALERT_UNIVERSE 預設啟用；ALERT_NEAR_PCT 為 0 |
| Flow | FLOW_MAX_ROUNDS 為 20，目前為預留設定 |

## 上游位址設定

應提供 Yahoo Finance 搜尋、鉶亨關鍵字新聞、鉶亨分類歷史新聞、台灣證交所公司目錄、櫃買中心公司目錄與證交所代號查詢等位址設定。位址可由環境覆寫，但程式必須有當前正式來源的預設值。

## 機密規則

- 實際環境檔必須被版本控制忽略。
- 範例環境檔的所有金鑰、密碼、token 與 webhook 值必須留空。
- API 只能回傳服務是否已設定的布林值，不得回傳機密內容。
- 容器環境使用服務名稱連線；本機環境使用本機主機名稱連線。
