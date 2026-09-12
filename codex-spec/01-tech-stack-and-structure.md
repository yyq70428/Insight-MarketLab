# 01 — 技術棧與結構規格

## 技術棧

| 層級 | 規格 |
| --- | --- |
| 後端 | Python 3.12、FastAPI、Pydantic、Uvicorn |
| 市場資料 | yfinance、requests、BeautifulSoup |
| 數值分析 | NumPy、Pandas、SciPy |
| 模型 | OpenAI Responses API 相容介面與結構化輸出 |
| 主資料庫 | MongoDB 7，用於 session、Agent run、job、batch 與策略版本 |
| 輔助資料庫 | PostgreSQL 16，用於自選清單與告警去重 |
| 前端 | 原生 HTML、CSS、JavaScript |
| 圖表 | TradingView Lightweight Charts 4.2.3 本地資產 |
| 部署 | Docker Compose，單一應用容器同時供應 API 與靜態前端 |

## 目錄邊界

| 目錄 | 責任 |
| --- | --- |
| app/backend/analysis | 純分析、評分、決策與紙上交易規則 |
| app/backend/services | 市場資料、新聞、模型客戶端、掃描與輔助儲存 |
| app/backend/flow | 持久化 session、狀態機、策略版本、影子測試、後台投影、job 與 batch |
| app/backend/tests | 分析邊界、時間防作弊、狀態機、版本與批次測試 |
| app/frontend/html | 主頁、掃描器、個股、量化與後台頁面 |
| app/frontend/css | 共用主題、各頁樣式與主頁佈局修正 |
| app/frontend/js | API、圖表、指標、疊圖、Agent、批次與後台互動 |
| deploy | 應用映像與容器編排 |
| quant/results | 離線量化快照，預設不追蹤產生結果 |

## 完整目錄結構

下表定義產品原始碼、測試、部署與規格資產的必要位置。快取、編譯產物、虛擬環境、本機資料庫及實際環境檔不屬於專案結構。

### 根目錄

| 路徑 | 類型 | 責任 |
| --- | --- | --- |
| app | 目錄 | 應用程式後端、前端與測試 |
| 本規格目錄 | 目錄 | 產品、系統、介面、資料與驗收規格，以及視覺參考圖 |
| deploy | 目錄 | 容器映像與服務編排定義 |
| quant | 目錄 | 量化研究輸出邊界 |
| spec | 目錄 | 補充性的資料庫與系統說明 |
| README.md | 文件 | 專案介紹、環境準備與操作入口 |
| .env.example | 文件 | 可公開的環境變數名稱與安全預設範本 |
| .gitignore | 文件 | 版本控制排除規則 |
| .dockerignore | 文件 | 容器建置內容排除規則 |

### 後端

| 路徑 | 責任 |
| --- | --- |
| app/backend/__init__.py | 後端套件識別 |
| app/backend/main.py | FastAPI 入口、頁面路由、API 掛載、靜態資產與啟動生命週期 |
| app/backend/config.py | 環境設定、預設值、連線參數與安全邊界 |
| app/backend/validators.py | 代號、週期、日期與請求參數驗證 |
| app/backend/requirements.txt | 後端執行相依項目 |
| app/backend/data/scan_symbols.txt | 背景掃描標的清單 |
| app/backend/analysis/__init__.py | 分析套件識別 |
| app/backend/analysis/engine.py | 技術分析協調與統一輸出 |
| app/backend/analysis/pivots.py | 轉折點、ATR 與 ZigZag |
| app/backend/analysis/harmonics.py | 諧波型態辨識、完成度與價格區間 |
| app/backend/analysis/support_resistance.py | 支撐壓力聚類、強度與區間 |
| app/backend/analysis/technical_agent.py | 技術訊號、權重與多空報告 |
| app/backend/analysis/news_agent.py | 新聞證據聚合與多空判斷 |
| app/backend/analysis/execution_agent.py | 買進、賣出、觀望與目標時程判斷 |
| app/backend/analysis/joint_execution.py | 技術與新聞報告的聯合決策 |
| app/backend/analysis/adaptive_agent.py | 驗證結果、候選參數與自適應建議 |
| app/backend/services/market_data.py | 行情、報價、公司資料、搜尋與快取 |
| app/backend/services/historical_news.py | 歷史新聞搜尋、原文時間驗證與來源整理 |
| app/backend/services/agent_llm.py | 模型請求、結構化回應與錯誤處理 |
| app/backend/services/agent_reports.py | Agent 報告格式與資料轉換 |
| app/backend/services/scanner.py | 多標的背景掃描、進度與結果快取 |
| app/backend/services/store.py | PostgreSQL 自選清單與告警資料存取 |
| app/backend/flow/__init__.py | Flow 套件識別 |
| app/backend/flow/routes.py | Flow、job、batch、策略與後台 API |
| app/backend/flow/runtime.py | 階段編排、背景任務、幂等與批次執行 |
| app/backend/flow/repository.py | MongoDB session、run、job、batch 與版本持久化 |
| app/backend/flow/policies.py | Agent 參數結構、預設值與驗證範圍 |
| app/backend/flow/versions.py | 正式版本、session 覆寫、候選、發布與回滾 |
| app/backend/flow/learning.py | 影子測試、自適應評估與採用條件 |
| app/backend/flow/quality.py | 新聞報告品質、忠實度與評審結果 |
| app/backend/flow/dashboard.py | 後台統計、曲線、輪次、版本與稽核投影 |

### 後端測試

| 路徑 | 責任 |
| --- | --- |
| app/backend/tests/__init__.py | 後端測試套件識別 |
| app/backend/tests/test_flow_session.py | session 階段、唯一性、幂等與時間邊界 |
| app/backend/tests/test_flow_policy.py | 策略參數、版本、revision 與回滾 |
| app/backend/tests/test_news_pipeline.py | 新聞擷取、截止點、來源與模型失敗 |
| app/backend/tests/test_adaptive_agent.py | 候選、影子樣本、採用與自適應限制 |
| app/backend/tests/test_batch_flow.py | 日期區間、逐輪順序、持有期與 HOLD 驗證 |

### 前端

| 路徑 | 責任 |
| --- | --- |
| app/frontend/html/index.html | 主圖表、時間錨點與 Agent Flow |
| app/frontend/html/dashboard.html | 自適應後台與五個管理頁籤 |
| app/frontend/html/scanner.html | 多標的掃描器 |
| app/frontend/html/stock.html | 個股分析與新聞 |
| app/frontend/html/quant.html | 量化回測與研究快照 |
| app/frontend/css/main.css | 全域主題、元件與圖表工作區 |
| app/frontend/css/layout-fixes.css | 主頁比例、側欄與響應式修正 |
| app/frontend/css/dashboard.css | Agent 後台佈局與元件 |
| app/frontend/css/scanner.css | 掃描器樣式 |
| app/frontend/css/stock.css | 個股頁樣式 |
| app/frontend/css/quant.css | 量化頁樣式 |
| app/frontend/js/app.js | 主頁狀態、搜尋、載入與互動協調 |
| app/frontend/js/api.js | 前端 API 請求與錯誤處理 |
| app/frontend/js/chart.js | K 線、成交量、時間軸與未來播放 |
| app/frontend/js/indicators.js | RSI 與 MACD 副圖 |
| app/frontend/js/overlays.js | 諧波、ZigZag、支撐壓力與交易標記 |
| app/frontend/js/anchor-guard.js | 歷史錨點狀態與未來資料隔離 |
| app/frontend/js/technical-agent.js | 技術 Agent 參數、執行與報告 |
| app/frontend/js/news-agent.js | 新聞 Agent 參數、進度與報告 |
| app/frontend/js/execution-agent.js | 決策、紙上交易與驗證播放 |
| app/frontend/js/adaptive-agent.js | 自適應建議、候選與結果呈現 |
| app/frontend/js/agent-pipeline.js | 單次 Flow、階段進度與區間批次 |
| app/frontend/js/dashboard.js | 後台資料、表格、版本與稽核互動 |
| app/frontend/js/scanner.js | 掃描器進度、篩選與卡片 |
| app/frontend/js/quant.js | 量化回測輸入、狀態與結果 |
| app/frontend/js/util.js | 共用格式化與安全 DOM 工具 |
| app/frontend/js/vendor/lightweight-charts.standalone.js | 固定版本的本地圖表資產 |
| app/frontend/tests/execution-replay.cjs | 前端未來 K 線播放與交易驗證測試 |

### 部署與量化輸出

| 路徑 | 責任 |
| --- | --- |
| deploy/Dockerfile | app 容器映像、相依安裝、資產內容與啟動程序 |
| deploy/docker-compose.yml | app、PostgreSQL、MongoDB、網路、健康檢查、連接埠與 volume 編排 |
| quant/results/.gitkeep | 保留離線量化結果目錄；實際產生結果不得進入版本控制 |

## 執行模型

- 應用啟動時嘗試初始化 PostgreSQL；失敗不得影響圖表功能。
- 應用啟動時啟動單例背景掃描執行緒。
- 單次完整 Flow 由背景任務處理，狀態寫入 MongoDB。
- 區間序列回測由單一批次背景任務處理，同一批次不得並行執行多輪。
- 當前工作機制不是獨立可恢復 worker queue；應用在任務中途重啟後，原任務不會自動續跑。

## 開發約束

- 前端 API 使用相對路徑，以支援反向代理子路徑。
- 圖表庫版本必須保持 4.2.3，不得直接升級到不相容主版本。
- 外部請求必須有逾時、識別字串與有界限的資料量。
- 模型輸出必須通過結構與範圍驗證，不得執行模型生成的程式或表達式。
- 上游新聞、文章與網頁文字一律視為不可信輸入。
