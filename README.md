# MarketLab

## 快速開始

```bash
python -m venv .venv
./.venv/bin/pip install -r app/backend/requirements.txt
./.venv/bin/python -m uvicorn app.backend.main:app --reload
```

開啟 <http://127.0.0.1:8000>。完整 Flow 需要 MongoDB；自選清單持久化需要 PostgreSQL；新聞模型分析需要設定 `OPENAI_API_KEY`。

```bash
# 僅首次安裝時執行；已有 .env 不要覆蓋。
cp .env.example .env
# 編輯 .env，至少設定 POSTGRES_PASSWORD；完整 Flow 另設定 MONGODB_URI 與 OPENAI_API_KEY
docker compose -f deploy/docker-compose.yml --env-file .env up --build
```

Compose 對外只綁定 `127.0.0.1`：應用為 9021、9022，PostgreSQL 為 9023。預設直接使用 `.env` 的 `MONGODB_URI`，不啟動本機 MongoDB；兩台電腦設定同一個 Atlas URI 與 database 時會讀取相同的 Agent／區間回測資料。

已有 `.env` 時，直接在專案根目錄執行：

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

若要改用本機 MongoDB，將 `.env` 設為 `MONGODB_URI=mongodb://mongo:27017/marketlab`，並明確啟用 profile：

```bash
docker compose -f deploy/docker-compose.yml --env-file .env --profile local-mongo up -d --build
```

本機與 Atlas 是兩套不同資料庫；切換 URI 不會自動搬移既有回測資料。

開啟 [工作台](http://127.0.0.1:9021/) 或 [Agent 後台](http://127.0.0.1:9021/dashboard)。Compose 已固定名稱 `insight-marketlab`，避免其他同名 `deploy` 專案互相替換容器。

Agent 後台的「區間回測」頁可同時查看多個標的／日期區間。按「＋ 新增回測列」建立可編輯列，設定標的、開始日、結束日、最長持有與 HOLD 門檻後執行。每列依實際交易日產生橫向節點；點擊已建立 Session 的節點，可查看第一層技術／新聞、第二層決策、第三層自適應摘要，以及完整參數、主報告、影子報告、版本與稽核事件。

本機以 `MARKETLAB_EXISTING_VOLUMES=true` 及兩個 `MARKETLAB_*_VOLUME` 設定保留舊資料卷。新安裝不需設定這三項。不要執行 `down -v`，也不要讓兩個資料庫容器同時掛載同一份資料卷。

## Flow 與區間回測

1. 選歷史錨點，執行第一層或完整 Flow。決策寫入 Mongo 後才讀取後續行情。
2. 區間回測上一輪完成後才建立下一輪，第二輪起使用當時生效版本。
3. 「等待驗證資料」表示完整 K 線不足，不是未開發。「更新後續行情與驗證」不會重算決策。
4. 重載可恢復批次／Session；重建容器保留資料，但進行中的工作會標記中斷，需另建新工作。

首頁將技術與新聞固定為左右並行的「第一層」，決策與紙上驗證為「第二層 · 執行 Agent」，審核與候選版本為「第三層 · 自適應 Agent」。批次逐交易日執行時，左側 K 線會跟隨目前 Session 的錨點；決策凍結後顯示動作、信心、目標與停損，驗證完成後加入進出場標記及實際淨損益，再切到下一個交易日。報告與圖表都綁定同一 Session，分析指標不讀取錨點之後資料；只有紙上驗證回放可顯示後續 K 線。

模型使用 OpenAI Responses API 的 [Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs)，另驗證引用、範圍與報告身分；模型失敗不改用技術分數冒充決策。

`RAGAS_ENABLED=true` 可開啟獨立模型的語意忠實度評審。`RAGAS_MODEL`、`RAGAS_API_KEY`、`RAGAS_BASE_URL` 空白則沿用主模型。此實作為結構化 LLM 評審，不會把引用存在率當成忠實度。

## 技術報告與 MACD 高低位

技術卡顯示多空比例、建議、參考價格、漲跌幅、目標時間、四項分數與理由，以及 MACD 位置診斷。比例是規則加權分數，不是上漲機率。新報告的漲跌幅以預期買入價計算；價格仍沿用 ATR 參考規則，不是成交保證。目標根數沿用 5 根；日線日期僅跳過週末，未套用交易所假日，盤中不推算跨時段日期。

`technical-2.1-position-aware` 的 MACD 工程規則：

- 預設以最近 120 根有效 MACD 的最小／最大值計算相對位置，先排除 EMA 暖身段；不足 20 根時不宣稱位置已知。
- 位置 ≥80% 且偏多時降低追高分數；位置 ≤20% 且偏空時降低追空分數。預設 `positionWeight=0.5`，若斜率或柱差動能反向則再折減一次；不因位置本身反向交易。
- `histogram` 由柱差產生基礎方向；`waveform` 由柱差和平均斜率組合。兩模式都套用位置防護，不再把 MACD 線的絕對高度當成波形位置。
- 80/20、折減與回看長度是本專案可檢驗的啟發式規則，不是 MACD 原生界限，也不是經績效證實的最佳參數。MACD 本身沒有固定上下界，通常用於趨勢而非直接辨識超買超賣。[Fidelity 指標說明](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/macd)

既有 Session 報告不改寫；按「執行判斷」重新分析已完成的技術報告時會建立新輪次，沿用目前設定。舊報告缺少位置診斷會明示，不補造數字。

## 歷史支撐壓力

圖表的 `/api/analysis` 額外回傳 `historicalZones`：以已載入且不超過錨點的 K 線，按最多 240 根的重疊歷史區段、各段自己的 ATR 聚類，保留最多 96 個跨時間及價格區域的候選。Agent 的 `zones` 仍維持最多 6 個近期區間，圖表顯示調整不影響其評分。

平移／縮放時，圖表依視窗內 K 線的價格範圍重新挑選最多 8 區，排除重疊或過密的區間；淡框與「歷史」標籤區分舊區間。歷史區間的 `asOfTime` 必須不晚於視窗末端，類型依視窗末價分類。區間起點是首次觸及時間，不代表當時已經確認；觸及次數屬各歷史區段，並非全期間累計。這是歷史回看參考，不是回測交易訊號。

抓取行情時對 `yf.download` 加入互斥鎖與回傳 ticker 驗證，阻擋掃描器與圖表併發時串用標的／期間；錯標的資料不會寫入快取。目前鎖定的 yfinance 0.2.61 使用共用結果字典，與上游記錄的 [併發問題](https://github.com/ranaroussi/yfinance/issues/2557) 相符。既有持久化報告保留原樣，不會被新資料覆寫。

## 掃描、告警與離線研究

可用 `SCAN_SYMBOLS=0050.TW|ETF,AAPL|科技,BTC-USD|加密資產` 或 `SCAN_SYMBOLS_FILE` 指定掃描範圍。

Discord 預設不發送，設定 `DISCORD_WEBHOOK_URL` 並開啟 `ALERTS_ENABLED=true` 後才啟動，需要 PostgreSQL 去重。驗收未向實際頻道發訊息。

產生離線研究快照（不下單）：

```bash
docker compose -f deploy/docker-compose.yml --env-file .env exec -T app python -m app.backend.services.quant_research --symbols 0050.TW AAPL BTC-USD --range 5y
```

結果寫到主機 `quant/results/`，量化頁會讀取。每窗只以訓練資料選參數；若無法同時提供兩年訓練與六個月驗證，會明確顯示歷史不足。

量化會交叉檢查 FinMind 的大幅價格斷層；如 0050 拆股造成基準不一致，整段改用 Yahoo，顯示來源、實際日期及缺日，不將拆股價差當成持倉虧損。價格報酬未計入股息再投資。

## 測試

```bash
pytest -q app/backend/tests
node --test app/frontend/tests/*.cjs
```

完整容器測試（Mongo 整合使用隨機命名的測試資料庫，不改寫應用資料）：

```bash
docker compose -f deploy/docker-compose.yml --env-file .env exec -T app python -m pytest app/backend/tests -q -p no:cacheprovider
```

實作範圍、真實測試與限制見 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。

歷史模擬結果僅供研究，不代表未來績效。
