"""Daily watchlist report: run both first-layer Agents over the fixed universe and mail it.

Runs the technical and news Agents once per symbol, sequentially. Sequential is deliberate:
the news Agent scrapes 鉅亨網 and then makes one LLM call carrying up to eight full articles,
so fanning 70 of those out in parallel would hammer both upstreams for no wall-clock benefit
the mail schedule cares about.

No decision is produced. The execution Agent needs a frozen anchor and future candles to be
meaningful, which a same-day report cannot supply, so the report shows the two independent
readings side by side and flags where they disagree.
"""
from __future__ import annotations

import html as html_escape
import threading
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..config import get_settings
from ..data.universe import NAMES, SECTORS, SYMBOLS, market_of
from ..flow.policies import DEFAULT_POLICIES
from ..analysis.technical_agent import technical_report
from .agent_pipeline import news_report
from .market_data import candles, frame_from_rows
from .time_boundary import candle_closed, candle_day
from .mailer import mail_configured, missing_settings, send_mail

TECHNICAL_KEYS = ("harmonics", "supportResistance", "macd", "rsi")
COMPONENT_LABELS = {"harmonics": "諧波", "supportResistance": "支撐壓力", "macd": "MACD", "rsi": "RSI"}


def latest_closed_anchor(symbol: str, rows: list[dict]) -> str | None:
    for row in reversed(rows):
        if candle_closed(symbol, "1d", row["time"]):
            return candle_day(symbol, "1d", row["time"]).isoformat()
    return None


def direction_of(percent: float | None) -> str:
    if percent is None:
        return "—"
    if percent >= 55:
        return "偏多"
    if percent <= 45:
        return "偏空"
    return "中性"


def agreement(technical: float | None, news: float | None) -> str:
    if technical is None or news is None:
        return "—"
    left, right = direction_of(technical), direction_of(news)
    if "中性" in (left, right):
        return "其一中性"
    return "一致" if left == right else "衝突"


def analyse_symbol(symbol: str, technical_params: dict, news_params: dict) -> dict:
    """One symbol, both Agents. Never raises: a failure becomes a row with an error."""
    settings = get_settings()
    row = {"symbol": symbol, "name": NAMES.get(symbol, symbol), "sector": SECTORS.get(symbol, "—"),
           "market": market_of(symbol), "anchor": None, "technical": None, "news": None, "errors": {}}
    try:
        rows = candles(symbol, "1d", settings.daily_report_candle_period)["candles"]
        anchor = latest_closed_anchor(symbol, rows)
        if not anchor:
            row["errors"]["data"] = "沒有已收盤的日線"
            return row
        row["anchor"] = anchor
        report = technical_report(frame_from_rows(rows), params=technical_params,
                                  symbol=symbol, interval="1d", anchor=anchor)
        row["technical"] = {
            "bullishPct": report["bullishPct"], "recommendation": report["recommendation"],
            "referencePrice": report["referencePrice"], "atr": report["atr"],
            "expectedBuy": report["expectedBuy"], "expectedSell": report["expectedSell"], "downside": report["downside"],
            "components": {key: report["components"][key] for key in TECHNICAL_KEYS},
            "candleCount": report["input"]["candleCount"],
        }
    except Exception as exc:
        row["errors"]["technical"] = str(exc)
        return row
    try:
        article = news_report(symbol, row["anchor"], news_params, row["name"])
        row["news"] = {
            "bullishPct": article.get("bullishPct"), "coverage": article.get("coverage"),
            "summary": article.get("summary", ""), "evidenceSufficient": bool(article.get("evidenceSufficient")),
            "modelUsed": bool(article.get("modelUsed")), "sourceCount": len(article.get("sources") or []),
            "findingCount": len(article.get("findings") or []), "limitations": article.get("limitations") or [],
        }
    except Exception as exc:
        row["errors"]["news"] = str(exc)
    return row


def collect(symbols=None, progress=None) -> dict:
    settings = get_settings()
    technical_params, news_params = DEFAULT_POLICIES["technical"], DEFAULT_POLICIES["news"]
    targets = list(symbols or SYMBOLS)
    started = datetime.now(ZoneInfo(settings.daily_report_timezone))
    rows = []
    for index, symbol in enumerate(targets, 1):
        rows.append(analyse_symbol(symbol, technical_params, news_params))
        if progress:
            progress(index, len(targets), symbol)
        if index < len(targets):
            time.sleep(max(0.0, settings.daily_report_delay))
    finished = datetime.now(ZoneInfo(settings.daily_report_timezone))
    return {"rows": rows, "startedAt": started.isoformat(), "completedAt": finished.isoformat(),
            "reportDate": started.date().isoformat(), "total": len(targets),
            "elapsedSeconds": round((finished - started).total_seconds(), 1),
            "technicalParams": technical_params, "newsParams": news_params}


def rank(rows: list[dict]) -> list[dict]:
    """Strongest technical conviction first; unusable rows sink to the bottom."""
    def key(row):
        technical = (row.get("technical") or {}).get("bullishPct")
        return (0 if technical is None else 1, abs((technical or 50) - 50))
    return sorted(rows, key=key, reverse=True)


def summarise(result: dict) -> dict:
    rows = result["rows"]
    usable = [r for r in rows if r.get("technical")]
    with_news = [r for r in usable if r.get("news") and r["news"].get("evidenceSufficient")]
    return {
        "total": len(rows), "technicalOk": len(usable), "newsWithEvidence": len(with_news),
        "technicalFailed": sum(1 for r in rows if r["errors"].get("technical") or r["errors"].get("data")),
        "newsFailed": sum(1 for r in rows if r["errors"].get("news")),
        "bullish": sum(1 for r in usable if r["technical"]["bullishPct"] >= 55),
        "bearish": sum(1 for r in usable if r["technical"]["bullishPct"] <= 45),
        "neutral": sum(1 for r in usable if 45 < r["technical"]["bullishPct"] < 55),
        "conflicts": sum(1 for r in with_news if agreement(r["technical"]["bullishPct"], r["news"]["bullishPct"]) == "衝突"),
    }


def _pct(value, digits=1):
    return "—" if value is None else f"{float(value):.{digits}f}"


def render_text(result: dict) -> str:
    stats, lines = summarise(result), []
    lines.append(f"MarketLab 每日雙 Agent 報告 · {result['reportDate']}")
    lines.append(f"標的 {stats['total']} 檔｜技術面成功 {stats['technicalOk']}｜新聞面有效證據 {stats['newsWithEvidence']}")
    lines.append(f"偏多 {stats['bullish']}｜偏空 {stats['bearish']}｜中性 {stats['neutral']}｜方向衝突 {stats['conflicts']}")
    lines.append(f"耗時 {result['elapsedSeconds']} 秒")
    lines.append("")
    lines.append(f"{'標的':<12}{'技術%':>8}{'建議':>6}{'新聞%':>8}{'覆蓋':>7}  一致性")
    for row in rank(result["rows"]):
        technical, news = row.get("technical"), row.get("news")
        if not technical:
            lines.append(f"{row['symbol']:<12}  失敗：{row['errors'].get('technical') or row['errors'].get('data')}")
            continue
        coverage = None if not news else news.get("coverage")
        lines.append(f"{row['symbol']:<12}{_pct(technical['bullishPct']):>8}{technical['recommendation']:>6}"
                     f"{_pct(news and news.get('bullishPct')):>8}"
                     f"{('—' if coverage is None else f'{coverage * 100:.0f}%'):>7}  "
                     f"{agreement(technical['bullishPct'], news and news.get('bullishPct'))}")
    lines.append("")
    lines.append("方向比例是規則加權分數，不是上漲機率或勝率。本報告不構成投資建議。")
    return "\n".join(lines)


def _cell(value, align="right", strong=False, color=None):
    style = f"padding:7px 9px;border-bottom:1px solid #e3e6ec;text-align:{align};white-space:nowrap"
    if strong:
        style += ";font-weight:600"
    if color:
        style += f";color:{color}"
    return f'<td style="{style}">{value}</td>'


def _tone(percent):
    if percent is None:
        return "#6b7280"
    return "#15803d" if percent >= 55 else "#b91c1c" if percent <= 45 else "#6b7280"


def render_html(result: dict) -> str:
    stats = summarise(result)
    esc = html_escape.escape
    head = ("標的", "市場", "產業", "錨點", "技術面看多%", "建議",
            *(COMPONENT_LABELS[key] for key in TECHNICAL_KEYS), "新聞面看多%", "新聞覆蓋", "證據", "方向一致性")
    header = "".join(f'<th style="padding:8px 9px;border-bottom:2px solid #cbd2dd;text-align:right;'
                     f'font-size:12px;color:#374151;white-space:nowrap">{esc(text)}</th>' for text in head)
    body = []
    for row in rank(result["rows"]):
        technical, news = row.get("technical"), row.get("news")
        label = f'{esc(row["symbol"])} {esc(row["name"])}'
        if not technical:
            reason = row["errors"].get("technical") or row["errors"].get("data") or "未知錯誤"
            body.append(f'<tr>{_cell(label, "left", True)}'
                        f'<td colspan="{len(head) - 1}" style="padding:7px 9px;border-bottom:1px solid #e3e6ec;color:#b91c1c">'
                        f'技術面失敗：{esc(str(reason)[:160])}</td></tr>')
            continue
        news_pct = news and news.get("bullishPct")
        coverage = "—" if not news or news.get("coverage") is None else f'{news["coverage"] * 100:.0f}%'
        evidence = "—" if not news else ("充足" if news["evidenceSufficient"] else "不足")
        if row["errors"].get("news"):
            evidence = "失敗"
        verdict = agreement(technical["bullishPct"], news_pct)
        body.append(
            "<tr>" + _cell(label, "left", True)
            + _cell(esc(row["market"]), "left") + _cell(esc(row["sector"]), "left") + _cell(esc(row["anchor"] or "—"))
            + _cell(_pct(technical["bullishPct"]), strong=True, color=_tone(technical["bullishPct"]))
            + _cell(esc(technical["recommendation"]))
            + "".join(_cell(_pct(technical["components"][key]["score"])) for key in TECHNICAL_KEYS)
            + _cell(_pct(news_pct), strong=True, color=_tone(news_pct))
            + _cell(coverage) + _cell(esc(evidence), color="#b91c1c" if evidence in ("不足", "失敗") else None)
            + _cell(esc(verdict), color="#b45309" if verdict == "衝突" else None)
            + "</tr>")
    details = []
    for row in rank(result["rows"]):
        news = row.get("news")
        if not news or not news.get("summary"):
            continue
        limitations = "".join(f"<li>{esc(item)}</li>" for item in news["limitations"][:3])
        details.append(
            f'<div style="margin:0 0 14px;padding:11px 13px;border:1px solid #e3e6ec;border-radius:7px">'
            f'<div style="font-weight:600;margin-bottom:5px">{esc(row["symbol"])} {esc(row["name"])}'
            f'<span style="font-weight:400;color:#6b7280"> · 新聞看多 {_pct(news.get("bullishPct"))}%'
            f' · 引用 {news["findingCount"]}/{news["sourceCount"]} 篇</span></div>'
            f'<div style="color:#374151;line-height:1.65">{esc(news["summary"])}</div>'
            + (f'<ul style="margin:7px 0 0;padding-left:18px;color:#6b7280;font-size:12px">{limitations}</ul>' if limitations else "")
            + "</div>")
    failures = [r for r in result["rows"] if r["errors"]]
    failure_html = ""
    if failures:
        items = "".join(f'<li>{esc(r["symbol"])} {esc(r["name"])} — '
                        + esc("；".join(f"{k}: {str(v)[:120]}" for k, v in r["errors"].items())) + "</li>"
                        for r in failures)
        failure_html = ('<h3 style="margin:26px 0 8px;font-size:15px">未完成的標的</h3>'
                        f'<ul style="margin:0;padding-left:18px;color:#b91c1c;line-height:1.7">{items}</ul>')
    return f"""<div style="font-family:-apple-system,'Noto Sans TC',Arial,sans-serif;color:#111827;max-width:1100px">
  <h2 style="margin:0 0 4px;font-size:19px">MarketLab 每日雙 Agent 報告</h2>
  <div style="color:#6b7280;font-size:13px;margin-bottom:16px">
    {esc(result['reportDate'])}　·　{stats['total']} 檔標的　·　耗時 {result['elapsedSeconds']} 秒
  </div>
  <div style="margin-bottom:18px;padding:11px 13px;background:#f3f5f9;border-radius:7px;font-size:13px;line-height:1.8">
    技術面成功 <b>{stats['technicalOk']}</b> / {stats['total']}　·　新聞面取得有效證據 <b>{stats['newsWithEvidence']}</b>　·
    　偏多 <b style="color:#15803d">{stats['bullish']}</b>　偏空 <b style="color:#b91c1c">{stats['bearish']}</b>
    中性 <b>{stats['neutral']}</b>　·　兩個 Agent 方向衝突 <b style="color:#b45309">{stats['conflicts']}</b> 檔
  </div>
  <table style="border-collapse:collapse;width:100%;font-size:12.5px"><thead><tr>{header}</tr></thead>
  <tbody>{''.join(body)}</tbody></table>
  <h3 style="margin:26px 0 8px;font-size:15px">怎麼讀這張表</h3>
  <div style="font-size:13px;line-height:1.85;color:#374151">
    <b>排序</b>：依技術面偏離中性的幅度由大到小，最上面是訊號最強的標的，不是最值得買的標的。<br>
    <b>技術面看多%</b>：諧波、支撐壓力、MACD、RSI 四項分數的加權結果，50 為中性。後面四欄是各項的原始分數，
    同樣以 50 為中性；諧波若顯示 50，通常是型態距今已超過有效期而不納入計分。<br>
    <b>新聞面看多%</b>：只由錨點當日及以前、且通過查核的鉅亨網報導計算。<b>證據</b>欄顯示「不足」時，
    代表找不到同時涵蓋標的與大盤的有效報導，該列的新聞分數不應採信。<br>
    <b>方向一致性</b>：兩個 Agent 都偏多或都偏空為「一致」，一多一空為「衝突」。衝突不代表訊號無效，
    而是這檔標的價格訊號與消息面正在互相拉扯，值得優先人工確認。<br>
    <b>錨點</b>：每檔各自取最近一根已收盤的日線，所以台股與美股的日期可能相差一天。
  </div>
  {failure_html}
  <h3 style="margin:26px 0 8px;font-size:15px">新聞面摘要</h3>
  {''.join(details) or '<div style="color:#6b7280">今日沒有任何標的取得新聞摘要。</div>'}
  <div style="margin-top:26px;padding-top:12px;border-top:1px solid #e3e6ec;color:#6b7280;font-size:12px;line-height:1.7">
    方向比例是規則加權分數，不是上漲機率或勝率。所有指標與判斷只使用錨點當日及以前的資料。
    本報告由 MarketLab 自動產生，不構成投資建議。
  </div>
</div>"""


class DailyReportService:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.started = False
        self.running = False
        self.last_run_date: date | None = None
        self.status = {"running": False, "lastResult": None, "lastError": None, "progress": None}

    def start(self):
        if not get_settings().daily_report_enabled:
            return
        with self.lock:
            if self.started:
                return
            self.started = True
        threading.Thread(target=self._loop, name="marketlab-daily-report", daemon=True).start()

    def due(self, now: datetime) -> bool:
        settings = get_settings()
        if self.last_run_date == now.date():
            return False
        if settings.daily_report_weekdays_only and now.weekday() >= 5:
            return False
        try:
            hour, minute = (int(part) for part in settings.daily_report_time.split(":")[:2])
        except ValueError:
            return False
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return target <= now < target + timedelta(minutes=settings.daily_report_window_minutes)

    def _loop(self):
        while not self.stop_event.is_set():
            try:
                now = datetime.now(ZoneInfo(get_settings().daily_report_timezone))
                if self.due(now):
                    self.last_run_date = now.date()
                    self.run()
            except Exception as exc:
                self.status["lastError"] = str(exc)
            self.stop_event.wait(60)

    def run(self, symbols=None, notify=True) -> dict:
        with self.lock:
            if self.running:
                raise RuntimeError("每日報告正在執行中")
            self.running = True
        self.status.update(running=True, lastError=None, progress={"completed": 0, "total": len(symbols or SYMBOLS)})
        try:
            def progress(done, total, symbol):
                self.status["progress"] = {"completed": done, "total": total, "symbol": symbol}
            result = collect(symbols, progress)
            stats = summarise(result)
            delivery = {"sent": False, "reason": "未要求寄送"}
            if notify:
                if mail_configured():
                    subject = (f"MarketLab {result['reportDate']} 每日報告 · "
                               f"偏多 {stats['bullish']} / 偏空 {stats['bearish']} / 衝突 {stats['conflicts']}")
                    try:
                        delivery = send_mail(subject, render_html(result), render_text(result))
                    except Exception as exc:
                        delivery = {"sent": False, "reason": f"寄送失敗：{exc}"}
                        self.status["lastError"] = delivery["reason"]
                else:
                    delivery = {"sent": False, "reason": "郵件設定不完整，缺少：" + "、".join(missing_settings())}
            summary = {"reportDate": result["reportDate"], "stats": stats, "delivery": delivery,
                       "elapsedSeconds": result["elapsedSeconds"], "completedAt": result["completedAt"]}
            self.status["lastResult"] = summary
            return {**summary, "rows": result["rows"]}
        except Exception as exc:
            self.status["lastError"] = str(exc)
            raise
        finally:
            self.running = False
            self.status.update(running=False, progress=None)


daily_report = DailyReportService()
