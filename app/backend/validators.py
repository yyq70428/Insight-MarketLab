from __future__ import annotations

import re
from datetime import date, datetime
from fastapi import HTTPException

INTERVALS = {"1m", "5m", "15m", "30m", "1h", "1d", "1wk", "1mo"}
FLOW_INTERVALS = {"1m", "5m", "15m", "30m", "1h", "1d"}
RANGES = {"1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "max"}
SYMBOL_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-=^]{0,19}$")


def normalize_symbol(value: str) -> str:
    symbol = value.strip().upper().replace(" ", "")
    if not SYMBOL_RE.fullmatch(symbol):
        raise HTTPException(422, "標的代號格式不合法")
    if symbol.isdigit():
        symbol += ".TW"
    return symbol


def validate_interval(value: str, flow: bool = False) -> str:
    allowed = FLOW_INTERVALS if flow else INTERVALS
    if value not in allowed:
        raise HTTPException(422, f"不支援的週期：{value}")
    return value


def validate_range(value: str) -> str:
    if value not in RANGES:
        raise HTTPException(422, f"不支援的資料範圍：{value}")
    return value


def parse_anchor(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(422, "日期必須為 YYYY-MM-DD") from exc


def bounded(value: float, low: float, high: float, label: str) -> float:
    if not low <= value <= high:
        raise HTTPException(422, f"{label} 必須介於 {low} 與 {high}")
    return value
