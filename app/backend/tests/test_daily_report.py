from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.backend.config import Settings
from app.backend.data.universe import NAMES, SYMBOLS, TAIWAN_LARGE_CAP, TAIWAN_POTENTIAL, US_LARGE_CAP, market_of
from app.backend.services import daily_report as module
from app.backend.services.daily_report import DailyReportService, agreement, direction_of, latest_closed_anchor, render_html, render_text, summarise
from app.backend.services.mailer import build_message


def test_universe_is_70_unique_symbols_split_60_taiwan_10_us():
    assert len(TAIWAN_LARGE_CAP) + len(TAIWAN_POTENTIAL) == 60 and len(US_LARGE_CAP) == 10
    assert len(SYMBOLS) == 70 and len(set(SYMBOLS)) == 70
    assert sum(market_of(s) == "台股" for s in SYMBOLS) == 60
    assert all(s.endswith((".TW", ".TWO")) for s in SYMBOLS if market_of(s) == "台股")
    assert all(NAMES[s] for s in SYMBOLS)


def test_anchor_picks_the_latest_closed_bar_not_the_last_row(monkeypatch):
    rows = [{"time": 100}, {"time": 200}, {"time": 300}]
    monkeypatch.setattr(module, "candle_closed", lambda symbol, interval, time: time <= 200)
    monkeypatch.setattr(module, "candle_day", lambda symbol, interval, time: __import__("datetime").date(2026, 9, time // 100))
    assert latest_closed_anchor("2330.TW", rows) == "2026-09-02"
    monkeypatch.setattr(module, "candle_closed", lambda *a: False)
    assert latest_closed_anchor("2330.TW", rows) is None


@pytest.mark.parametrize("value,expected", [(70, "偏多"), (55, "偏多"), (50, "中性"), (45, "偏空"), (12, "偏空"), (None, "—")])
def test_direction_thresholds(value, expected):
    assert direction_of(value) == expected


def test_agreement_flags_conflict_but_not_a_neutral_leg():
    assert agreement(70, 65) == "一致" and agreement(20, 30) == "一致"
    assert agreement(70, 30) == "衝突" and agreement(30, 70) == "衝突"
    assert agreement(70, 50) == "其一中性" and agreement(70, None) == "—"


def sample():
    return {"reportDate": "2026-09-24", "elapsedSeconds": 12.5, "total": 3,
            "rows": [
                {"symbol": "2330.TW", "name": "台積電", "sector": "半導體", "market": "台股", "anchor": "2026-09-23",
                 "technical": {"bullishPct": 72.0, "recommendation": "買進", "referencePrice": 1000, "atr": 20,
                               "expectedBuy": 993, "expectedSell": 1030, "downside": 980, "candleCount": 480,
                               "components": {k: {"score": 60.0, "reason": "r"} for k in module.TECHNICAL_KEYS}},
                 "news": {"bullishPct": 30.0, "coverage": 0.75, "summary": "<測試> 新聞摘要 & 內容",
                          "evidenceSufficient": True, "modelUsed": True, "sourceCount": 8,
                          "findingCount": 6, "limitations": ["僅依據已驗證報導"]},
                 "errors": {}},
                {"symbol": "AAPL", "name": "Apple", "sector": "消費電子", "market": "美股", "anchor": "2026-09-23",
                 "technical": {"bullishPct": 50.5, "recommendation": "觀望", "referencePrice": 200, "atr": 4,
                               "expectedBuy": 198, "expectedSell": 206, "downside": 196, "candleCount": 480,
                               "components": {k: {"score": 50.0, "reason": "r"} for k in module.TECHNICAL_KEYS}},
                 "news": {"bullishPct": None, "coverage": None, "summary": "", "evidenceSufficient": False,
                          "modelUsed": False, "sourceCount": 2, "findingCount": 0, "limitations": []},
                 "errors": {}},
                {"symbol": "6488.TWO", "name": "環球晶", "sector": "半導體矽晶圓", "market": "台股", "anchor": None,
                 "technical": None, "news": None, "errors": {"technical": "技術 Agent 至少需要 80 根錨點前 K 線"}},
            ]}


def test_summary_counts_conflicts_and_failures():
    stats = summarise(sample())
    assert stats == {"total": 3, "technicalOk": 2, "newsWithEvidence": 1, "technicalFailed": 1, "newsFailed": 0,
                     "bullish": 1, "bearish": 0, "neutral": 1, "conflicts": 1}


def test_ranking_puts_strongest_signal_first_and_failures_last():
    order = [row["symbol"] for row in module.rank(sample()["rows"])]
    assert order == ["2330.TW", "AAPL", "6488.TWO"]


def test_html_escapes_report_text_and_marks_unusable_rows():
    html = render_html(sample())
    assert "&lt;測試&gt; 新聞摘要 &amp; 內容" in html and "<測試>" not in html
    assert "技術面失敗：" in html and "未完成的標的" in html
    assert "證據" in html and "不足" in html
    assert "方向比例是規則加權分數" in html


def test_text_fallback_covers_every_row():
    text = render_text(sample())
    assert all(symbol in text for symbol in ("2330.TW", "AAPL", "6488.TWO"))
    assert "不構成投資建議" in text


def schedule(**overrides):
    base = {"daily_report_time": "18:00", "daily_report_timezone": "Asia/Taipei",
            "daily_report_window_minutes": 120, "daily_report_weekdays_only": True}
    return Settings(**{**base, **overrides})


@pytest.mark.parametrize("moment,expected", [
    ("2026-09-24T17:59", False),  # before the slot
    ("2026-09-24T18:00", True),   # exactly on time
    ("2026-09-24T19:59", True),   # inside the catch-up window
    ("2026-09-24T20:01", False),  # a restart this late must not fire yesterday's slot
])
def test_schedule_window(monkeypatch, moment, expected):
    monkeypatch.setattr(module, "get_settings", schedule)
    now = datetime.fromisoformat(moment).replace(tzinfo=ZoneInfo("Asia/Taipei"))
    assert DailyReportService().due(now) is expected


def test_schedule_skips_weekends_and_repeat_runs(monkeypatch):
    monkeypatch.setattr(module, "get_settings", schedule)
    service = DailyReportService()
    saturday = datetime(2026, 9, 26, 18, 30, tzinfo=ZoneInfo("Asia/Taipei"))
    assert service.due(saturday) is False
    monkeypatch.setattr(module, "get_settings", lambda: schedule(daily_report_weekdays_only=False))
    assert service.due(saturday) is True
    service.last_run_date = saturday.date()
    assert service.due(saturday) is False


def test_mail_message_carries_both_plain_text_and_html(monkeypatch):
    monkeypatch.setattr("app.backend.services.mailer.get_settings",
                        lambda: Settings(smtp_host="smtp.test", smtp_from="bot@test.local",
                                         report_recipients="a@test.local, b@test.local"))
    message = build_message("主旨", "<b>hi</b>", "hi", ["a@test.local", "b@test.local"])
    parts = {part.get_content_type() for part in message.walk()}
    assert {"text/plain", "text/html"} <= parts
    assert message["To"] == "a@test.local, b@test.local" and "bot@test.local" in message["From"]


def test_recipient_list_accepts_commas_and_semicolons():
    assert Settings(report_recipients="a@x.com; b@x.com ,c@x.com").recipient_list == ["a@x.com", "b@x.com", "c@x.com"]
    assert Settings().recipient_list == []


def test_analyse_symbol_records_failures_instead_of_raising(monkeypatch):
    monkeypatch.setattr(module, "candles", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("上游掛了")))
    row = module.analyse_symbol("2330.TW", {}, {})
    assert row["errors"]["technical"] == "上游掛了" and row["technical"] is None and row["symbol"] == "2330.TW"


def test_news_failure_keeps_the_technical_half_of_the_row(monkeypatch):
    monkeypatch.setattr(module, "candles", lambda *a, **k: {"candles": [{"time": 1}]})
    monkeypatch.setattr(module, "latest_closed_anchor", lambda *a: "2026-09-23")
    monkeypatch.setattr(module, "frame_from_rows", lambda rows: rows)
    monkeypatch.setattr(module, "technical_report", lambda *a, **k: {
        "bullishPct": 61.0, "recommendation": "買進", "referencePrice": 10, "atr": 1, "expectedBuy": 9,
        "expectedSell": 11, "downside": 9, "input": {"candleCount": 200},
        "components": {k2: {"score": 55.0, "reason": "r"} for k2 in module.TECHNICAL_KEYS}})
    monkeypatch.setattr(module, "news_report", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("模型無回應")))
    row = module.analyse_symbol("2330.TW", {}, {})
    assert row["technical"]["bullishPct"] == 61.0
    assert row["news"] is None and row["errors"] == {"news": "模型無回應"}


def test_history_falls_back_to_memory_without_mongo(monkeypatch):
    monkeypatch.setattr(module.repository, "available", lambda: False)
    log = module.ReportHistory(keep=3)
    for index in range(4):
        log.save({"id": f"run{index}", "status": "completed", "total": 70, "startedAt": f"2026-09-2{index}T18:00"})
    listed = log.list()
    assert listed["persistent"] is False
    # Bounded and newest first; the oldest run has been dropped.
    assert [row["id"] for row in listed["runs"]] == ["run3", "run2", "run1"]
    assert log.get("run3")["total"] == 70 and log.get("run0") is None


def test_history_update_replaces_the_same_run_rather_than_appending(monkeypatch):
    monkeypatch.setattr(module.repository, "available", lambda: False)
    log = module.ReportHistory()
    log.save({"id": "r1", "status": "running", "startedAt": "2026-09-24T18:00"})
    log.save({"id": "r1", "status": "completed", "startedAt": "2026-09-24T18:00", "elapsedSeconds": 9})
    runs = log.list()["runs"]
    assert len(runs) == 1 and runs[0]["status"] == "completed" and runs[0]["elapsedSeconds"] == 9


def test_history_summary_excludes_the_heavy_rows_payload(monkeypatch):
    monkeypatch.setattr(module.repository, "available", lambda: False)
    log = module.ReportHistory()
    log.save({"id": "r1", "status": "completed", "startedAt": "2026-09-24T18:00", "rows": sample()["rows"]})
    assert "rows" not in log.list()["runs"][0]
    assert len(log.get("r1")["rows"]) == 3


def test_a_mongo_write_failure_never_breaks_a_run(monkeypatch):
    class Exploding:
        def update_one(self, *a, **k): raise RuntimeError("Atlas 斷線")
    log = module.ReportHistory()
    monkeypatch.setattr(type(log), "collection", property(lambda self: Exploding()))
    log.save({"id": "r1", "status": "completed", "startedAt": "2026-09-24T18:00"})
    assert log.get("r1")["status"] == "completed"


def test_run_records_history_for_both_success_and_failure(monkeypatch):
    monkeypatch.setattr(module.repository, "available", lambda: False)
    monkeypatch.setattr(module, "history", module.ReportHistory())
    monkeypatch.setattr(module, "mail_configured", lambda: False)
    monkeypatch.setattr(module, "collect", lambda symbols, progress: {
        **sample(), "startedAt": "2026-09-24T18:00", "completedAt": "2026-09-24T18:01"})
    service = DailyReportService()
    service.run(["2330.TW"], notify=True)
    run = module.history.list()["runs"][0]
    assert run["status"] == "completed" and run["requestedSymbols"] == ["2330.TW"] and run["trigger"] == "manual"
    assert run["delivery"]["sent"] is False and "郵件設定有問題" in run["delivery"]["reason"]

    monkeypatch.setattr(module, "collect", lambda symbols, progress: (_ for _ in ()).throw(RuntimeError("上游全掛")))
    with pytest.raises(RuntimeError):
        service.run(None, notify=False, trigger="schedule")
    failed = module.history.list()["runs"][0]
    assert failed["status"] == "failed" and failed["error"] == "上游全掛"
    assert failed["requestedSymbols"] is None and failed["total"] == 70 and failed["trigger"] == "schedule"


def test_concurrent_runs_are_rejected(monkeypatch):
    service = DailyReportService()
    service.running = True
    with pytest.raises(RuntimeError, match="執行中"):
        service.run(["2330.TW"])


def mail_settings(**overrides):
    base = {"smtp_host": "smtp.gmail.com", "smtp_user": "bot@gmail.com",
            "smtp_password": "abcdefghijklmnop", "report_recipients": "me@gmail.com"}
    return Settings(**{**base, **overrides})


def test_pasted_chinese_placeholder_is_reported_instead_of_a_unicode_crash(monkeypatch):
    from app.backend.services import mailer
    monkeypatch.setattr(mailer, "get_settings", lambda: mail_settings(smtp_password="<Gmail 應用程式密碼，不是登入密碼>"))
    problems = mailer.missing_settings()
    assert any("非 ASCII" in p and "SMTP_PASSWORD" in p for p in problems)
    assert not mailer.mail_configured()
    with pytest.raises(mailer.MailNotConfigured, match="非 ASCII"):
        mailer.send_mail("s", "<b>h</b>", "h")


def test_google_app_password_spaces_are_stripped_before_auth():
    from app.backend.services.mailer import app_password
    assert app_password("abcd efgh ijkl mnop") == "abcdefghijklmnop"
    assert app_password("  abcd\tefgh ") == "abcdefgh"
    assert app_password("") == ""


def test_valid_mail_settings_report_no_problems(monkeypatch):
    from app.backend.services import mailer
    monkeypatch.setattr(mailer, "get_settings", lambda: mail_settings(smtp_password="abcd efgh ijkl mnop"))
    assert mailer.missing_settings() == [] and mailer.mail_configured()


def test_an_address_shaped_like_a_placeholder_is_rejected(monkeypatch):
    from app.backend.services import mailer
    monkeypatch.setattr(mailer, "get_settings", lambda: mail_settings(smtp_from="<你的信箱>"))
    assert any("不是一個電子郵件位址" in p for p in mailer.missing_settings())


def test_report_without_a_base_url_stays_link_free():
    html = render_html(sample())
    assert "<a href" not in html and "2330.TW" in html


def test_preview_links_are_relative_and_carry_each_row_own_anchor():
    html = render_html(sample(), link_base="", link_target="_blank")
    assert '<a href="/?symbol=2330.TW&amp;anchor=2026-09-23" target="_blank" rel="noopener"' in html
    assert '<a href="/?symbol=AAPL&amp;anchor=2026-09-23"' in html
    # The failed row has no anchor, so it links to the symbol without a date rather than a broken one.
    assert '<a href="/?symbol=6488.TWO"' in html and "anchor=None" not in html


def test_mail_links_are_absolute_and_tolerate_a_trailing_slash():
    from app.backend.services.daily_report import chart_link
    assert chart_link("https://lab.example.com/", "2330.TW", "2026-09-23") == \
        "https://lab.example.com/?symbol=2330.TW&anchor=2026-09-23"
    assert chart_link("", "AAPL", None) == "/?symbol=AAPL"
    assert chart_link(None, "AAPL", "2026-09-23") is None


def test_link_query_is_encoded_not_injected():
    rows = sample()["rows"][:1]
    rows[0]["symbol"] = 'X"><script>alert(1)</script>'
    html = render_html({**sample(), "rows": rows}, link_base="")
    assert "<script>" not in html and "%3Cscript%3E" in html
