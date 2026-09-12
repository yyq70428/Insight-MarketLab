# 10 — 部署規格

## 部署檔案位置

| 路徑 | 用途 |
| --- | --- |
| deploy/docker-compose.yml | Docker Compose 的主要服務編排檔，定義 app、PostgreSQL、MongoDB、健康檢查、網路、連接埠及持久化 volume |
| deploy/Dockerfile | app 服務的容器映像定義 |
| .env.example | 根目錄的公開環境設定範本 |
| .env | 根目錄的實際執行環境設定，不得進入版本控制或容器映像 |
| .dockerignore | 根目錄的映像建置排除規則 |

所有 Compose 部署作業均以 deploy/docker-compose.yml 為唯一編排來源，並以專案根目錄作為操作基準。服務名稱、連接埠、依賴關係與 volume 定義不得分散至第二份 Compose 檔案。

## 容器

| 服務 | 映像與責任 | 對外連接埠 |
| --- | --- | --- |
| app | Python 3.12 精簡映像，供應 FastAPI、靜態前端與背景任務 | 本機 9011 與 9012 均對應容器 8000 |
| db | PostgreSQL 16 Alpine，儲存自選清單與告警去重 | 本機 9013 對應容器 5432 |
| mongo | MongoDB 7，儲存 Agent Flow 與版本審計 | 不對本機開放，只在容器網路內使用 |

## 應用映像

- 工作目錄為容器內的專案目錄。
- 先安裝系統數值運算必要的共用庫，再安裝後端依賴。
- 映像內容僅包含應用、必要的量化快照目錄與執行所需資產。
- 實際環境檔、Git 資料、虛擬環境、快取、本地資料庫與產生結果不得進入映像。
- 應用在容器內監聽所有介面的 8000 連接埠，使用單一 worker，以避免掃描執行緒重複啟動。

## 編排

- app 必須等 PostgreSQL 與 MongoDB 健康檢查通過後才啟動。
- PostgreSQL 與 MongoDB 各使用命名 volume 持久化。
- app 與 PostgreSQL 讀取根目錄環境檔。
- app 容器內強制使用 db 作為 PostgreSQL 主機，並避免將外部 DATABASE_URL 誤帶入本地容器環境。
- MongoDB 容器不掛載應用機密環境檔。
- 所有對外連接埠只綁定本機 loopback，預設不暴露到區域網路。

## 健康檢查

PostgreSQL 使用資料庫就緒檢查，MongoDB 使用管理 ping。兩者每 5 秒檢查，有限時間逾時與重試次數。app 無法連線 MongoDB 時，Flow API 必須在 5 秒左右回傳可讀錯誤。

## 資料持久性

重建 app 不得刪除 PostgreSQL 或 MongoDB volume。容器重建後必須能讀取原有 session、批次、策略版本與自選清單。

當前背景 job 與 batch 沒有獨立 worker 的中斷恢復能力。應用重啟時已寫入的階段與報告仍保留，但 running 任務需要人工處理或新建批次。

## 安全

- 實際環境檔永不進入映像建置內容或版本控制。
- 生產環境不得使用開放的 CORS 來源。
- 正式 MongoDB 使用受限帳號、加密連線與最小網路允許清單。
- PostgreSQL 密碼、MongoDB 連線字串、模型金鑰與 webhook 只能由執行環境注入。
