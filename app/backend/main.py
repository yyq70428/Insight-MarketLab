from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
import json
from typing import Any
from datetime import timedelta, datetime, timezone
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .analysis.engine import analyze
from .analysis.technical_agent import technical_report
from .config import get_settings
from .flow.policies import DEFAULT_POLICIES, POLICY_SCHEMA
from .flow.repository import repository
from .flow.routes import router as flow_router
from .services.agent_pipeline import news_report, execution_decision
from .flow.policies import validate_params
from .services.agent_llm import ModelUnavailable
from .services.time_boundary import candle_day
from .services.historical_news import historical_news, identify_symbol
from .services import market_data
from .services.quant import backtest, market_for
from .services.scanner import scanner
from .services.alerts import alerts
from .services.daily_report import daily_report, history as report_history, render_html as render_report_html
from .data.universe import UNIVERSE, SYMBOLS
from .services.store import watchlist_store
from .services.agent_reports import legacy_reports
from .analysis.news_agent import insufficient_news_report
from .analysis.execution_agent import decide, paper_validate
from .analysis.adaptive_agent import adaptive_report
from .validators import normalize_symbol, parse_anchor, validate_interval, validate_range

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        watchlist_store.initialize()
    except Exception:
        pass
    try:
        repository.initialize()
    except Exception:
        pass
    scanner.start()
    alerts.start()
    daily_report.start()
    yield
    alerts.stop_event.set()
    daily_report.stop_event.set()


app = FastAPI(title="MarketLab", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_list, allow_methods=["*"], allow_headers=["*"], allow_credentials=False)
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


def safe_upstream(call):
    try:
        return call()
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, "上游市場資料暫時無法使用，請稍後重試") from exc


def require_mongo():
    try:
        repository.require()
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get("/health")
def health():
    return {"status": "ok", "mongo": repository.available(), "postgres": watchlist_store.available()}


@app.get("/api/search")
def api_search(q: str = Query(min_length=1, max_length=64), limit: int = Query(8, ge=1, le=12)):
    return {"results": safe_upstream(lambda: market_data.search(q, limit))}


@app.get("/api/quote")
def api_quote(symbol: str):
    return safe_upstream(lambda: market_data.quote(normalize_symbol(symbol)))


@app.get("/api/candles")
def api_candles(symbol: str, interval: str = "1d", range: str = "2y", anchor: str | None = None):
    normalized = normalize_symbol(symbol); validate_interval(interval); validate_range(range); cutoff = parse_anchor(anchor)
    return safe_upstream(lambda: market_data.candles(normalized, interval, range, cutoff))


@app.get("/api/analysis")
def api_analysis(symbol: str, interval: str = "1d", range: str = "2y", anchor: str | None = None):
    payload = api_candles(symbol, interval, range, anchor)
    result = analyze(market_data.frame_from_rows(payload["candles"]), settings.max_harmonic_results,
                     settings.max_sr_zones, include_zone_history=True)
    return {"symbol": payload["symbol"], "interval": interval, "anchor": payload["anchor"], **result}


@app.get("/api/profile")
def api_profile(symbol: str):
    return safe_upstream(lambda: market_data.profile(normalize_symbol(symbol)))


@app.get("/api/news")
def api_news(symbol: str):
    normalized = normalize_symbol(symbol)
    return {"symbol": normalized, "items": safe_upstream(lambda: market_data.news(normalized)), "source": "Yahoo Finance"}


@app.get("/api/news-tw")
def api_news_tw(symbol: str, page: int = Query(1, ge=1, le=100)):
    symbol = normalize_symbol(symbol)
    if not symbol.endswith(('.TW','.TWO')): raise HTTPException(422,'此來源只支援台灣標的')
    from .services.time_boundary import market_timezone
    anchor = datetime.now(market_timezone(symbol)).date().isoformat()
    result = safe_upstream(lambda: historical_news(symbol,anchor,30,3))
    items = [r for r in result['sources'] if r['type']=='stock']
    return {'items':items[(page-1)*8:page*8], 'page':page, 'totalPages':(len(items)+7)//8,'total':len(items),
            'source':'鉅亨已驗證近 30 日新聞','excluded':result['excluded'],'search':result['search']}


@app.get("/api/patterns")
def api_patterns():
    return scanner.get()


@app.get("/api/technical-agent")
def api_technical_agent(symbol: str, interval: str = "1d", range: str = "2y", anchor: str | None = None):
    payload = api_candles(symbol, interval, range, anchor)
    try:
        report = technical_report(market_data.frame_from_rows(payload["candles"]), symbol=payload['symbol'], interval=interval, anchor=payload['anchor'])
        identity = {"symbol": payload["symbol"], "interval": interval, "anchor": payload["anchor"]}
        return {**report, "reportId": legacy_reports.put("technical", identity, report), "identity": identity}
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get("/api/agent-config")
def agent_config():
    return {"modelConfigured": bool(settings.openai_api_key), "model": settings.openai_model,
            "newsSource": "鉅亨分類歷史新聞", "reportTtl": settings.agent_report_ttl}


@app.get("/api/news-identity")
def news_identity(symbol: str):
    normalized = normalize_symbol(symbol)
    return safe_upstream(lambda:identify_symbol(normalized))


class NewsAgentRequest(BaseModel):
    symbol: str
    interval: str = "1d"
    anchor: date
    lookbackDays: int = Field(30, ge=7, le=90)
    rounds: int = Field(3, ge=3, le=5)
    name: str | None = Field(None, max_length=120)


@app.post("/api/news-agent")
def legacy_news_agent(body: NewsAgentRequest):
    symbol=normalize_symbol(body.symbol); interval=validate_interval(body.interval, flow=True)
    try:
        report=news_report(symbol, body.anchor.isoformat(), validate_params('news', {'lookbackDays':body.lookbackDays,'rounds':body.rounds}), body.name)
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    identity={"symbol":symbol,"interval":interval,"anchor":body.anchor.isoformat()}
    return {**report,"reportId":legacy_reports.put("news",identity,report),"identity":identity,
            "search":{"lookbackDays":body.lookbackDays,"rounds":body.rounds,"source":"鉅亨分類歷史新聞"}}


class ExecutionRequest(BaseModel):
    technicalReportId: str
    newsReportId: str
    technicalWeight: float = Field(.65, ge=0, le=1)
    minConfidence: float = Field(52, ge=0, le=100)
    maxHoldingBars: int = Field(5, ge=1, le=7)
    holdThresholdPct: float = Field(2, ge=.1, le=20)


@app.post("/api/execution-agent")
def legacy_execution(body: ExecutionRequest):
    technical=legacy_reports.get(body.technicalReportId,"technical"); news=legacy_reports.get(body.newsReportId,"news")
    if not technical or not news: raise HTTPException(404,"Agent 報告不存在或已過期")
    if technical["identity"]!=news["identity"]: raise HTTPException(409,"技術與新聞報告的標的、週期或錨點不一致")
    try:
        decision=execution_decision({**technical['report'],'identity':technical['identity']}, {**news['report'],'identity':news['identity']},
                                   validate_params('execution', {'technicalWeight':body.technicalWeight,'minConfidence':body.minConfidence}))
    except ModelUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    identity=technical["identity"]
    if not identity.get('anchor'): raise HTTPException(422,'紙上驗證必須使用歷史錨點')
    decision['frozenAt']=datetime.now(timezone.utc).isoformat()
    decision_id=legacy_reports.put('execution',identity,{'decision':decision})
    # This is intentionally the first point at which post-anchor candles are requested.
    full=safe_upstream(lambda:market_data.candles(identity["symbol"],identity["interval"],"5y",None))["candles"]
    future=[row for row in full if candle_day(identity['symbol'],identity['interval'],row['time']).isoformat()>identity['anchor']]
    target,stop=(technical['report']['downside'],technical['report']['expectedSell']) if decision['action']=='SELL' else (technical['report']['expectedSell'],technical['report']['downside'])
    validation=paper_validate(decision,future,target,stop,body.maxHoldingBars,body.holdThresholdPct,
                              reference=technical['report'].get('referencePrice'))
    return {"reportId":decision_id,"identity":identity,"decision":decision,"validation":validation}


@app.get("/api/adaptive-agent")
def legacy_adaptive_agent(symbol: str, interval: str="1d", range: str="5y", anchor: str|None=None):
    payload=api_candles(symbol,interval,range,anchor); frame=market_data.frame_from_rows(payload["candles"])
    if len(frame)<120: raise HTTPException(422,"自適應候選至少需要 120 根錨點前歷史資料")
    from .flow.learning import technical_candidate
    result=technical_candidate(frame,DEFAULT_POLICIES['technical'])
    return {'candidate':result[0] if result else None,'evidence':result[1] if result else None,
            'policy':DEFAULT_POLICIES['adaptive'],'message':'候選需後續影子驗證，未直接發布正式版本' if result else '沒有通過時間順序驗證的候選，維持原參數'}


app.include_router(flow_router)


class WatchlistItem(BaseModel):
    symbol: str


@app.get("/api/daily-report/universe")
def daily_report_universe():
    return {"total": len(SYMBOLS),
            "symbols": [{"symbol": s, "name": n, "sector": c,
                         "market": "台股" if s.endswith((".TW", ".TWO")) else "美股"} for s, n, c in UNIVERSE]}


@app.get("/api/daily-report/status")
def daily_report_status():
    from .services.mailer import missing_settings
    return {**daily_report.status, "enabled": settings.daily_report_enabled,
            "scheduledAt": settings.daily_report_time, "timezone": settings.daily_report_timezone,
            "weekdaysOnly": settings.daily_report_weekdays_only,
            "lastRunDate": daily_report.last_run_date.isoformat() if daily_report.last_run_date else None,
            "mailMissing": missing_settings()}


class DailyReportRequest(BaseModel):
    symbols: list[str] | None = Field(None, max_length=70)
    notify: bool = True


@app.post("/api/daily-report/run")
def daily_report_run(body: DailyReportRequest, tasks: BackgroundTasks):
    """Kick off a run now. `symbols` limits the universe, which is how you smoke-test
    the mail path without paying for 70 LLM calls."""
    targets = None
    if body.symbols:
        targets = [normalize_symbol(s) for s in body.symbols]
        unknown = [s for s in targets if s not in SYMBOLS]
        if unknown:
            raise HTTPException(422, "不在固定清單內的標的：" + "、".join(unknown))
    if daily_report.running:
        raise HTTPException(409, "每日報告正在執行中")
    tasks.add_task(lambda: daily_report.run(targets, body.notify))
    return {"started": True, "total": len(targets or SYMBOLS), "notify": body.notify,
            "usedDefault": targets is None, "hint": "以 GET /api/daily-report/status 追蹤進度"}


@app.get("/api/daily-report/history")
def daily_report_history(limit: int = Query(20, ge=1, le=100)):
    return report_history.list(limit)


@app.get("/api/daily-report/history/{run_id}")
def daily_report_detail(run_id: str):
    record = report_history.get(run_id)
    if not record:
        raise HTTPException(404, "找不到這筆執行紀錄")
    return record


@app.get("/api/daily-report/history/{run_id}/preview", include_in_schema=False)
def daily_report_preview(run_id: str):
    """The exact HTML that was mailed, so the page can show what the recipient saw."""
    record = report_history.get(run_id)
    if not record:
        raise HTTPException(404, "找不到這筆執行紀錄")
    if not record.get("rows"):
        raise HTTPException(409, "這筆紀錄沒有可呈現的結果")
    html = render_report_html({"rows": record["rows"], "reportDate": record.get("reportDate") or "—",
                               "elapsedSeconds": record.get("elapsedSeconds") or 0, "total": record["total"]},
                              link_base="", link_target="_blank")
    return Response(content=html, media_type="text/html; charset=utf-8")


@app.get("/api/watchlist")
def watchlist():
    if not watchlist_store.available(): raise HTTPException(503, "PostgreSQL 不可用，前端將改用本機自選清單")
    return {"items": watchlist_store.list()}


@app.post("/api/watchlist", status_code=201)
def add_watchlist(body: WatchlistItem):
    if not watchlist_store.available(): raise HTTPException(503, "PostgreSQL 不可用")
    symbol = normalize_symbol(body.symbol); watchlist_store.add(symbol); return {"symbol": symbol}


@app.delete("/api/watchlist/{symbol}")
def remove_watchlist(symbol: str):
    if not watchlist_store.available(): raise HTTPException(503, "PostgreSQL 不可用")
    watchlist_store.remove(normalize_symbol(symbol)); return {"removed": True}


@app.get("/api/quant-scan")
def quant_scan(symbol: str, strategy: str = Query("ma", pattern="^(ma|rsi|bollinger)$"), range: str = "5y"):
    from .services.quant_research import research
    normalized = normalize_symbol(symbol)
    if range not in ('2y','5y','10y'):raise HTTPException(422,'量化回測範圍限 2y、5y、10y')
    return safe_upstream(lambda:research(normalized,strategy,range))


@app.get("/api/backtest")
def offline_backtest():
    directory=Path(__file__).resolve().parents[2]/'quant/results'
    snapshots=[]
    for path in sorted(directory.glob('*.json'))[:100]:
        if path.is_symlink() or path.stat().st_size>10_000_000: continue
        try: snapshots.append({'file':path.name,'result':json.loads(path.read_text(encoding='utf-8'))})
        except (ValueError,OSError): continue
    return {"snapshots": snapshots, "disclaimer": "歷史模擬不代表未來保證"}


def page(name: str):
    target = FRONTEND / "html" / name
    if not target.exists(): raise HTTPException(404)
    return FileResponse(target)


@app.get("/", include_in_schema=False)
def home_page(): return page("index.html")


@app.get("/dashboard", include_in_schema=False)
def dashboard_page(): return page("dashboard.html")

@app.get("/prediction", include_in_schema=False)
def prediction_page(): return page("prediction.html")


@app.get("/scanner", include_in_schema=False)
def scanner_page(): return page("scanner.html")


@app.get("/stock", include_in_schema=False)
def stock_page(): return page("stock.html")


@app.get("/quant", include_in_schema=False)
def quant_page(): return page("quant.html")

@app.get("/reports", include_in_schema=False)
def reports_page(): return page("reports.html")
