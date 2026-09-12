from __future__ import annotations

import numpy as np
import pandas as pd


def atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - prev).abs(),
        (frame["low"] - prev).abs(),
    ], axis=1).max(axis=1)
    return true_range.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def find_pivots(frame: pd.DataFrame, window: int = 4, price_pct: float = 0.025) -> list[dict]:
    if len(frame) < window * 2 + 1:
        return []
    volatility = atr(frame).bfill().fillna(0)
    raw: list[dict] = []
    for idx in range(window, len(frame) - window):
        row = frame.iloc[idx]
        highs = frame["high"].iloc[idx-window:idx+window+1]
        lows = frame["low"].iloc[idx-window:idx+window+1]
        is_high = row.high >= highs.max()
        is_low = row.low <= lows.min()
        # An outside bar can be both a local high and low. Its intrabar order is
        # unknowable from OHLC, so using both would invent two same-time pivots.
        if is_high and is_low:
            continue
        if is_high:
            raw.append({"index": idx, "time": int(row.time), "price": float(row.high), "kind": "high", "confirmed": True})
        if is_low:
            raw.append({"index": idx, "time": int(row.time), "price": float(row.low), "kind": "low", "confirmed": True})
    pivots: list[dict] = []
    for point in sorted(raw, key=lambda item: item["index"]):
        if pivots and point["kind"] == pivots[-1]["kind"]:
            more_extreme = point["price"] > pivots[-1]["price"] if point["kind"] == "high" else point["price"] < pivots[-1]["price"]
            if more_extreme:
                pivots[-1] = point
            continue
        if pivots:
            threshold = max(pivots[-1]["price"] * price_pct, float(volatility.iloc[point["index"]]))
            if abs(point["price"] - pivots[-1]["price"]) < threshold:
                continue
        pivots.append(point)
    last = frame.iloc[-1]
    if pivots:
        next_kind = "low" if pivots[-1]["kind"] == "high" else "high"
        price = float(last.low if next_kind == "low" else last.high)
        pivots.append({"index": len(frame)-1, "time": int(last.time), "price": price, "kind": next_kind, "confirmed": False})
    if any(left["time"] >= right["time"] for left, right in zip(pivots, pivots[1:])):
        raise ValueError("ZigZag 轉折時間必須嚴格升冪")
    return pivots
