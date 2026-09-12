# 04 — HTTP API 規格

## 通用規則

- 所有回應使用 JSON，頁面與靜態資產除外。
- 代號、週期、日期、range、權重與數量必須有長度、枚舉或數值範圍驗證。
- 上游不可用回傳 404，輸入錯誤回傳 400 或 422，狀態衝突回傳 409，資料庫或模型不可用回傳 503。
- 錯誤訊息可以告知使用者如何修正，但不得回傳供應商原始例外、金鑰或請求內容。

## 市場與分析

| 方法與路徑 | 輸入 | 主要輸出 |
| --- | --- | --- |
| GET /api/search | 搜尋文字 | 代號、名稱、交易所、類型 |
| GET /api/quote | 代號 | 現價、漲跌、開高低、成交量、幣別與時間 |
| GET /api/candles | 代號、週期、範圍、可選錨點 | 標準化 K 線、標的中繼資料與資料政策 |
| GET /api/analysis | 與 K 線相同 | 諧波型態、ZigZag、支撐壓力與最新價 |
| GET /api/profile | 代號 | 公司資料與近期事件 |
| GET /api/news | 代號與來源 | 一般新聞清單 |
| GET /api/news-tw | 台股代號與分頁 | 鉶亨新聞、總頁數與總筆數 |
| GET /api/patterns | 無 | 掃描結果、進度與更新時間 |

## 舊版單次 Agent

| 方法與路徑 | 用途 |
| --- | --- |
| GET /api/technical-agent | 以錨點前 K 線與四項權重建立暫存技術報告 |
| GET /api/adaptive-agent | 使用錨點前歷史樣本計算技術權重候選 |
| GET /api/agent-config | 回傳模型是否已設定、模型名、新聞來源與報告存活期 |
| GET /api/news-identity | 辨識新聞搜尋所需的標的名稱與別名 |
| POST /api/news-agent | 擷取錨點新聞、驗證日期並產生暫存新聞報告 |
| POST /api/execution-agent | 校驗兩份暫存報告的標的、週期與錨點一致後做決策與驗證 |

## 持久化 Flow

| 方法與路徑 | 用途 |
| --- | --- |
| GET /api/flow/config | 回傳資料庫、模型、評審、引擎與可用 Agent 資訊 |
| GET /api/flow/policies | 回傳四種 Agent 的預設參數與驗證結構 |
| POST /api/flow/sessions | 建立錨點 session；可選擇建立後自動執行完整 Flow |
| GET /api/flow/sessions | 依 scope、代號或狀態分頁列出 session |
| GET /api/flow/sessions/{sessionId} | 回傳 session、所有 Agent run、新聞評審、事件與相關版本 |
| POST /api/flow/sessions/{sessionId}/stages/{agent} | 執行指定階段；只有決策階段允許本次覆寫 |
| POST /api/flow/sessions/{sessionId}/run | 為已建立 session 新增一筆完整 Flow job |
| POST /api/flow/sessions/{sessionId}/next | 依交易日數建立下一輪相連 session |
| GET /api/flow/jobs/{jobId} | 讀取單次 Flow job 狀態與錯誤 |

## 區間序列回測

POST /api/flow/batches 接受標的、開始日、結束日、1 至 7 個交易日的最長持有期、0.1 至 20 的觀望波動百分比門檻與可選 Agent 參數。日期區間最多 94 個日曆日。成功時立即回傳已排隊批次。

GET /api/flow/batches/{batchId} 回傳批次狀態、錨點清單、當前輪次、當前 session、完成數、行動統計、預測成功數、成功率與各輪摘要。

## 策略與後台

| 方法與路徑 | 用途 |
| --- | --- |
| GET /api/flow/strategies | 回傳指定 scope 的正式版本、revision、歷史與結構 |
| POST /api/flow/strategies/{agent} | 產生並發佈後台人工參數版本 |
| GET /api/flow/versions | 依 scope 與可選 Agent 列出版本、差異與是否正式 |
| POST /api/flow/versions/{versionId}/rollback | 將指定舊版本重新發布為新版本 |
| GET /api/flow/events | 列出版本、驗證、回滾與提案事件 |
| GET /api/flow/overview | 回傳 session 與版本統計、累積紙上報酬與近期事件 |

## 其他

| 方法與路徑 | 用途 |
| --- | --- |
| GET /api/watchlist | 讀取自選清單 |
| POST /api/watchlist | 新增自選標的 |
| DELETE /api/watchlist/{symbol} | 刪除自選標的 |
| GET /api/backtest | 讀取離線量化快照 |
| GET /api/quant-scan | 即時執行單標的滾動驗證 |
