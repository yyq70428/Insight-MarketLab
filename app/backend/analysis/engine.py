from __future__ import annotations

import pandas as pd
from .harmonics import detect_harmonics
from .pivots import find_pivots
from .support_resistance import detect_zones, historical_zones


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    losses = (-delta.clip(upper=0)).ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    rs = gains / losses.replace(0, float("nan"))
    value = 100 - 100 / (1 + rs)
    value = value.mask((losses == 0) & (gains > 0), 100)
    return value.fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    signal_line = line.ewm(span=signal, adjust=False).mean()
    return line, signal_line, line - signal_line


def analyze(frame: pd.DataFrame, harmonic_limit: int = 8, zone_limit: int = 6,
            *, include_zone_history: bool = False) -> dict:
    pivots = find_pivots(frame)
    rsi_values = rsi(frame.close)
    macd_line, signal_line, histogram = macd(frame.close)
    indicators = []
    for idx, row in frame.iterrows():
        indicators.append({"time": int(row.time), "rsi": round(float(rsi_values.iloc[idx]), 3),
                           "macd": round(float(macd_line.iloc[idx]), 4), "signal": round(float(signal_line.iloc[idx]), 4),
                           "histogram": round(float(histogram.iloc[idx]), 4)})
    result = {"pivots": pivots, "harmonics": detect_harmonics(pivots, harmonic_limit),
            "zones": detect_zones(frame, pivots, zone_limit), "indicators": indicators,
            "latestPrice": float(frame.iloc[-1].close) if not frame.empty else None}
    if include_zone_history:
        result["historicalZones"] = historical_zones(frame)
        result["zoneHistoryBasis"] = "歷史區間依各段 K 線回看整理；起點不是當時已確認的交易訊號，未使用錨點後資料。"
    return result
