import json
import numpy as np
import pandas as pd

from app.backend.analysis.engine import analyze
from app.backend.analysis.support_resistance import historical_zones, _separated_touch_indexes


def history(count=720):
    x = np.arange(count)
    # Repeated real extrema at substantially different historical price regimes.
    close = 80 + x * .35 + np.sin(x / 8) * 12
    return pd.DataFrame({"time": 1_700_000_000 + x * 86400, "open": close - .2,
                         "high": close + 1, "low": close - 1, "close": close, "volume": 1000 + x % 40 * 100})


def test_chart_history_retains_old_price_regions_without_changing_agent_zones():
    frame = history()
    original = analyze(frame)
    chart = analyze(frame, include_zone_history=True)
    assert chart["zones"] == original["zones"] and len(chart["zones"]) <= 6
    assert "historicalZones" not in original
    zones = chart["historicalZones"]
    assert 6 < len(zones) <= 96
    assert min(z["midpoint"] for z in zones) < 120
    assert max(z["midpoint"] for z in zones) > 270
    assert min(z["asOfTime"] for z in zones) < frame.iloc[240].time
    assert all(z["historical"] and z["touches"] >= 2 for z in zones)
    assert all(z["windowStartTime"] <= z["startTime"] <= z["lastTime"] <= z["asOfTime"] <= frame.iloc[-1].time for z in zones)
    json.dumps(chart, allow_nan=False)


def test_completed_historical_windows_do_not_use_later_prices():
    frame = history(480)
    cutoff = int(frame.iloc[239].time)
    before = historical_zones(frame.iloc[:240], limit=1000)
    frame.loc[240:, ["open", "high", "low", "close"]] *= 100
    later = [zone for zone in historical_zones(frame, limit=1000) if zone["asOfTime"] <= cutoff]
    assert later == before


def test_small_history_budget_is_distributed_across_time_not_only_recent_price():
    frame = history()
    zones = historical_zones(frame, limit=6)
    assert len(zones) == 6
    assert len({zone["asOfTime"] for zone in zones}) == 6
    assert min(zone["midpoint"] for zone in zones) < 120
    assert max(zone["midpoint"] for zone in zones) > 270


def test_touch_spacing_uses_positional_candles_including_nondefault_dataframe_index():
    frame = history(10)
    frame.index = np.arange(50, 60)
    assert _separated_touch_indexes(frame, 0, 1000) == [0, 3, 6, 9]


def test_short_or_disabled_history_is_empty():
    assert historical_zones(history(10)) == []
    assert historical_zones(history(), limit=0) == []
