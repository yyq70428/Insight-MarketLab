# 07 — 資料庫規格

## 責任分工

MongoDB 是 Agent Flow、批次回測、策略版本與審計事件的必要資料庫。PostgreSQL 只負責自選清單與告警去重。兩者不得交換責任。

## MongoDB collections

| collection | 用途 | 主要約束 |
| --- | --- | --- |
| sessions | 每個錨點的主狀態、版本釘選、參數、前後輪關係與結果時間 | 識別值唯一；scope 與錨點可查詢 |
| technical_runs | 技術面 champion 與 shadow run | session 與 role 組合唯一 |
| news_runs | 新聞面 champion 與 shadow run | session 與 role 組合唯一 |
| execution_runs | 決策、未來驗證、champion 與 shadow run | session 與 role 組合唯一；可依候選版本查詢 |
| adaptive_runs | 每輪自適應報告 | session 與 role 組合唯一 |
| news_evaluations | 新聞引用與忠實度評審 | session 與 role 組合唯一 |
| strategy_versions | 四種 Agent 的不可變參數版本、父版本、生效時間、狀態與驗證 | 依 scope、Agent 與狀態查詢 |
| strategy_heads | 每個 scope 當前正式版本、revision 與發布歷史 | scope 為主識別值 |
| strategy_events | 設定、提案、驗證、提升與回滾審計 | 依 session、scope 與時間查詢 |
| flow_jobs | 單次完整 Flow 工作狀態 | 依 session 查詢；同 session 不得同時有多個 queued 或 running job |
| flow_batches | 區間序列回測設定、錨點、進度、session 清單與統計 | 依建立時間倒序查詢 |

## run 文件

每個 run 包含識別值、session、role、Agent、狀態、策略版本、參數、建立時間、完成時間、報告、輸入摘要與可選錯誤。狀態為 running、completed 或 failed。

階段建立後不可重複執行。已完成的階段必須幂等回傳原結果；執行中或失敗時必須阻止同角色重複寫入。

## session 狀態

- 建立後進入 first_layer。
- 技術與新聞各自有 running、completed 或 failed 階段狀態。
- 決策完成後進入 adaptive，並記錄 outcomeTime 與 labelComplete。
- 自適應完成後進入 completed。
- 任一 champion 階段失敗時進入 failed 並保留可讀錯誤。

## 策略版本

- scope 由正規化代號與週期組成。
- 每個 Agent 的基準版本只建立一次。
- session 建立時依錨點截止時間選擇當時可用版本並釘選，後續不得被新版本改寫。
- 使用者 session 覆寫、後台人工修改、自適應候選、驗證發布與回滾都必須產生新版本與事件。
- 正式版本切換使用 revision 比對，過期父版本不得覆寫新狀態。

## batch 文件

批次包含標的、日線週期、開始與結束日、最長持有天數、HOLD 門檻、實際交易日錨點、總輪數、完成輪數、當前輪、當前階段、當前 session、session 清單、初始覆寫、BUY、SELL、HOLD 數量、成功預測數、成功率、狀態、錯誤與時間。

## PostgreSQL

watchlist 資料包含正規化代號與新增時間，代號唯一。alert_log 包含去重指紋與發送時間，指紋唯一。建表必須幂等。

PostgreSQL 不可用時，watchlist API 回傳服務不可用，前端可降級為本地儲存。MongoDB 不可用時，Flow、批次與後台必須明確失敗，不得使用暫存替代。
