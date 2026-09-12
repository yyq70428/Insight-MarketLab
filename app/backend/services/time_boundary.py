from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def market_timezone(symbol: str) -> ZoneInfo:
    return ZoneInfo("Asia/Taipei" if symbol.endswith((".TW", ".TWO")) else "UTC" if symbol.endswith("-USD") else "America/New_York")


def anchor_cutoff(symbol: str, anchor: str | date) -> datetime:
    day = date.fromisoformat(anchor) if isinstance(anchor, str) else anchor
    return datetime.combine(day + timedelta(days=1), time.min, market_timezone(symbol))


def candle_day(symbol: str, interval: str, timestamp: int) -> date:
    # Yahoo daily bars are date labels normalized to UTC midnight, not instants.
    tz = timezone.utc if interval == "1d" else market_timezone(symbol)
    return datetime.fromtimestamp(timestamp, tz).date()


def candle_closed(symbol: str, interval: str, timestamp: int, at: datetime | None = None) -> bool:
    current = at or datetime.now(timezone.utc)
    if interval != '1d':
        seconds = {'1m':60,'5m':300,'15m':900,'30m':1800,'1h':3600}.get(interval)
        return seconds is not None and timestamp+seconds <= current.timestamp()
    day = candle_day(symbol, interval, timestamp)
    if symbol.endswith('-USD'): close = anchor_cutoff(symbol, day)
    else:
        closing = time(13,30) if symbol.endswith(('.TW','.TWO')) else time(16)
        close = datetime.combine(day, closing, market_timezone(symbol))
    return close <= current
