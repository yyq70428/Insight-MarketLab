import pandas as pd
import numpy as np

from app.backend.analysis.engine import analyze, rsi, macd
from app.backend.analysis.pivots import find_pivots
from app.backend.analysis.harmonics import detect_harmonics
from app.backend.analysis.support_resistance import detect_zones


def fixture_frame(count=240):
    x = np.arange(count)
    close = 100 + np.sin(x / 8) * 8 + x * .05
    return pd.DataFrame({"time": 1_700_000_000 + x * 86400, "open": close-.2, "high": close+1,
                         "low": close-1, "close": close, "volume": 1000+x})


def test_pivots_alternate_and_last_is_unconfirmed():
    pivots = find_pivots(fixture_frame())
    assert len(pivots) >= 5
    assert all(a["kind"] != b["kind"] for a, b in zip(pivots, pivots[1:]))
    assert all(a["time"] < b["time"] for a, b in zip(pivots, pivots[1:]))
    assert pivots[-1]["confirmed"] is False


def test_analysis_limits_and_indicators_are_finite():
    result = analyze(fixture_frame(), harmonic_limit=2, zone_limit=3)
    assert len(result["harmonics"]) <= 2
    assert len(result["zones"]) <= 3
    assert len(result["indicators"]) == 240
    assert 0 <= result["indicators"][-1]["rsi"] <= 100


def test_flat_series_has_neutral_rsi_and_macd():
    close = pd.Series([10.0] * 100)
    line, signal, histogram = macd(close)
    assert rsi(close).iloc[-1] == 50
    assert line.iloc[-1] == signal.iloc[-1] == histogram.iloc[-1] == 0


def test_exact_gartley_requires_valid_d_ratio():
    prices = [100.0, 200.0, 138.2, 176.4, 121.4]
    pivots = [{"index": i, "time": 1000 + i, "price": price,
               "kind": "low" if i % 2 == 0 else "high", "confirmed": True} for i, price in enumerate(prices)]
    matches = detect_harmonics(pivots)
    assert matches and matches[0]["name"] == "Gartley"
    assert .74 <= matches[0]["ratios"]["ad_xa"] <= .82
    bad = [dict(point) for point in pivots]
    bad[-1]["price"] = 190.0
    assert not any(item["name"] == "Gartley" for item in detect_harmonics(bad))


def test_support_zones_have_real_separated_touches_and_bounds():
    frame = fixture_frame(260)
    pivots = find_pivots(frame)
    zones = detect_zones(frame, pivots, limit=6)
    assert all(zone["touches"] >= 2 for zone in zones)
    assert all(zone["low"] < zone["midpoint"] < zone["high"] for zone in zones)
    assert all(zone["startTime"] <= zone["lastTime"] for zone in zones)
