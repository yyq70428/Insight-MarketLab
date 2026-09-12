from __future__ import annotations

import threading
import time
import math
from datetime import date, timedelta
from typing import Any, Callable

import pandas as pd
import requests
import yfinance as yf

from ..config import get_settings
from .time_boundary import candle_day


class TTLCache:
    def __init__(self, max_items: int = 256):
        self.max_items, self.data, self.lock = max_items, {}, threading.Lock()

    def get(self, key: str, ttl: int, loader: Callable[[], Any]):
        now = time.monotonic()
        with self.lock:
            hit = self.data.get(key)
            if hit and now - hit[0] < ttl:
                return hit[1]
        value = loader()
        with self.lock:
            if len(self.data) >= self.max_items:
                oldest = min(self.data, key=lambda item: self.data[item][0])
                self.data.pop(oldest, None)
            self.data[key] = (now, value)
        return value


settings = get_settings()
cache = TTLCache(settings.cache_max_items)
# yf.download in the pinned dependency uses process-global result dictionaries.
# Its threads=False only disables inner workers, not concurrent API/scanner calls.
_download_lock = threading.Lock()


def _timestamp(value) -> int:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize("UTC")
    return int(stamp.timestamp())


def _finite_number(value, fallback=None):
    try:
        number = float(value)
        return number if math.isfinite(number) else fallback
    except (TypeError, ValueError):
        return fallback


def _clean_download(raw: pd.DataFrame, expected_symbol: str | None = None) -> tuple[pd.DataFrame, str]:
    if isinstance(raw.columns, pd.MultiIndex):
        ticker_level = raw.columns.names.index("Ticker") if "Ticker" in raw.columns.names else 1
        tickers = {str(value).upper() for value in raw.columns.get_level_values(ticker_level)}
        if expected_symbol and tickers != {expected_symbol.upper()}:
            raise LookupError("上游行情標的與請求不一致，已阻擋混用資料")
        raw = raw.copy()
        raw.columns = raw.columns.droplevel(ticker_level)
    raw = raw.reset_index()
    time_col = "Datetime" if "Datetime" in raw.columns else "Date"
    required = [time_col, "Open", "High", "Low", "Close"]
    if any(column not in raw.columns for column in required):
        raise LookupError("上游行情欄位不完整")
    for column in ("Open", "High", "Low", "Close", "Volume"):
        if column in raw.columns:
            raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw = raw.dropna(subset=required)
    raw = raw.sort_values(time_col).drop_duplicates(time_col, keep="last")
    if "Volume" not in raw.columns:
        raw["Volume"] = 0
    raw["Volume"] = raw["Volume"].fillna(0)
    valid = (
        (raw[["Open", "High", "Low", "Close"]] > 0).all(axis=1)
        & (raw["Volume"] >= 0)
        & (raw["High"] >= raw[["Open", "Close", "Low"]].max(axis=1))
        & (raw["Low"] <= raw[["Open", "Close", "High"]].min(axis=1))
    )
    raw = raw.loc[valid].reset_index(drop=True)
    if raw.empty:
        raise LookupError("上游行情未通過 OHLCV 完整性驗證")
    return raw, time_col


def candles(symbol: str, interval: str, period: str, anchor: date | None = None) -> dict:
    ttl = settings.intraday_cache_ttl if interval.endswith(("m", "h")) else settings.daily_cache_ttl

    def load():
        kwargs: dict[str, Any] = {"interval": interval, "auto_adjust": False, "actions": False, "timeout": settings.upstream_timeout}
        if anchor:
            lookback = {"1m": 7, "5m": 60, "15m": 60, "30m": 60, "1h": 729}.get(interval, 3650)
            kwargs.update(start=anchor - timedelta(days=lookback), end=anchor + timedelta(days=1))
        else:
            intraday_days = {'1m':7,'5m':59,'15m':59,'30m':59,'1h':729}.get(interval)
            if intraday_days:
                kwargs.update(start=date.today()-timedelta(days=intraday_days),end=date.today()+timedelta(days=1))
            else: kwargs["period"] = period
        with _download_lock:
            raw = yf.download(symbol, progress=False, threads=False, **kwargs).copy(deep=True)
        if raw.empty:
            raise LookupError("找不到行情資料")
        raw, time_col = _clean_download(raw, symbol)
        rows = []
        for _, row in raw.iterrows():
            stamp = pd.Timestamp(row[time_col])
            if anchor and candle_day(symbol, interval, _timestamp(stamp)) > anchor:
                continue
            volume = _finite_number(row.Volume, 0) or 0
            rows.append({"time": _timestamp(stamp), "open": round(float(row.Open), 6), "high": round(float(row.High), 6),
                         "low": round(float(row.Low), 6), "close": round(float(row.Close), 6), "volume": max(0, int(volume))})
        if not rows:
            raise LookupError("錨點前沒有行情資料")
        return rows

    rows = cache.get(f"candles:{symbol}:{interval}:{period}:{anchor}", ttl, load)
    if any(left["time"] >= right["time"] for left, right in zip(rows, rows[1:])):
        raise LookupError("上游行情時間不是嚴格升冪")
    return {"symbol": symbol, "interval": interval, "anchor": anchor.isoformat() if anchor else None, "candles": rows,
            "policy": {"futureExcluded": bool(anchor), "cutoffInclusive": True, "count": len(rows),
                       "source": "Yahoo Finance", "validated": True, "priceBasis": "unadjusted-close"}}


def frame_from_rows(rows: list[dict]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=["time", "open", "high", "low", "close", "volume"])
    return frame.sort_values("time").drop_duplicates("time").reset_index(drop=True)


def quote(symbol: str) -> dict:
    def load():
        ticker = yf.Ticker(symbol)
        history = ticker.history(period="5d", interval="1d", auto_adjust=False)
        history = history.dropna(subset=["Open", "High", "Low", "Close"])
        if history.empty:
            raise LookupError("找不到即時報價")
        latest, previous = history.iloc[-1], history.iloc[-2] if len(history) > 1 else history.iloc[-1]
        change = float(latest.Close - previous.Close)
        try:
            currency = ticker.fast_info.get("currency", "") or ""
        except Exception:
            currency = ""
        return {"symbol": symbol, "price": round(float(latest.Close), 4), "change": round(change, 4),
                "changePct": round(change / float(previous.Close) * 100, 3) if previous.Close else 0,
                "open": float(latest.Open), "high": float(latest.High), "low": float(latest.Low),
                "volume": max(0, int(_finite_number(latest.Volume, 0) or 0)), "currency": str(currency), "time": _timestamp(history.index[-1])}
    return cache.get(f"quote:{symbol}", settings.quote_cache_ttl, load)


def search(query: str, limit: int = 8) -> list[dict]:
    def load():
        response = requests.get(settings.yahoo_search_url, params={"q": query, "quotesCount": limit, "newsCount": 0},
                                headers={"User-Agent": settings.upstream_user_agent}, timeout=settings.upstream_timeout)
        response.raise_for_status()
        allowed = {"EQUITY", "ETF", "MUTUALFUND", "CRYPTOCURRENCY", "INDEX", "FUTURE"}
        return [{"symbol": row.get("symbol"), "name": row.get("longname") or row.get("shortname") or row.get("symbol"),
                 "exchange": row.get("exchDisp") or row.get("exchange", ""), "type": row.get("quoteType", "")}
                for row in response.json().get("quotes", []) if row.get("quoteType") in allowed][:limit]
    return cache.get(f"search:{query.lower()}:{limit}", settings.search_cache_ttl, load)


def profile(symbol: str) -> dict:
    def load():
        info = yf.Ticker(symbol).get_info()
        market_cap = _finite_number(info.get("marketCap"))
        return {"symbol": symbol, "name": info.get("longName") or info.get("shortName") or symbol,
                "industry": info.get("industry") or "未知", "sector": info.get("sector") or "未知",
                "marketCap": int(market_cap) if market_cap is not None else None, "exchange": info.get("exchange"), "website": info.get("website"),
                "summary": info.get("longBusinessSummary") or "暫無公司簡介", "currency": info.get("currency")}
    return cache.get(f"profile:{symbol}", settings.profile_cache_ttl, load)


def news(symbol: str) -> list[dict]:
    def load():
        items = yf.Ticker(symbol).news or []
        output = []
        for item in items[:12]:
            content = item.get("content", item)
            canonical = content.get("canonicalUrl") or {}
            provider = content.get("provider") or {}
            output.append({"id": content.get("id"), "title": content.get("title"), "url": canonical.get("url") or item.get("link"),
                           "publisher": provider.get("displayName") or item.get("publisher"),
                           "publishedAt": content.get("pubDate") or item.get("providerPublishTime"), "summary": content.get("summary", "")})
        return output
    return cache.get(f"news:{symbol}", settings.news_cache_ttl, load)
