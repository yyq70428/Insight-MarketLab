from __future__ import annotations

import math
import pandas as pd

from .pivots import atr, find_pivots


def _separated_touch_indexes(frame: pd.DataFrame, low: float, high: float, gap: int = 3) -> list[int]:
    indexes, last = [], -gap
    hits = ((frame["low"].to_numpy() <= high) & (frame["high"].to_numpy() >= low)).nonzero()[0]
    for idx in hits:
        if idx - last >= gap:
            indexes.append(int(idx)); last = int(idx)
    return indexes


def detect_zones(frame: pd.DataFrame, pivots: list[dict], limit: int | None = 6,
                 *, volume_limit: int | None = 40) -> list[dict]:
    if frame.empty:
        return []
    current = float(frame.iloc[-1]["close"])
    atr_values = atr(frame).dropna()
    recent_atr = float(atr_values.tail(30).median()) if not atr_values.empty else current * .01
    cluster_distance = max(recent_atr * .55, current * .0035)

    candidates = [
        {"price": float(point["price"]), "time": int(point["time"]), "weight": 1.6, "source": "pivot"}
        for point in pivots if point.get("confirmed")
    ]
    if len(frame) >= 20 and frame["volume"].max() > 0:
        volume_cutoff = frame["volume"].quantile(.90)
        median_volume = max(float(frame["volume"].median()), 1.0)
        volume_rows = frame[frame["volume"] >= volume_cutoff]
        if volume_limit is not None:
            volume_rows = volume_rows.tail(volume_limit)
        for _, row in volume_rows.iterrows():
            typical = (float(row["high"]) + float(row["low"]) + float(row["close"])) / 3
            candidates.append({"price": typical, "time": int(row["time"]),
                               "weight": min(2.5, max(1.0, float(row["volume"]) / median_volume)), "source": "volume"})
    if not candidates:
        return []

    clusters: list[list[dict]] = []
    for candidate in sorted(candidates, key=lambda item: item["price"]):
        if clusters:
            total_weight = sum(item["weight"] for item in clusters[-1])
            center = sum(item["price"] * item["weight"] for item in clusters[-1]) / total_weight
            if abs(candidate["price"] - center) <= cluster_distance:
                clusters[-1].append(candidate); continue
        clusters.append([candidate])

    zones = []
    final_index = len(frame) - 1
    for group in clusters:
        total_weight = sum(item["weight"] for item in group)
        midpoint = sum(item["price"] * item["weight"] for item in group) / total_weight
        spread = max((max(item["price"] for item in group) - min(item["price"] for item in group)) / 2, cluster_distance * .22)
        half_width = min(max(spread, current * .0012), cluster_distance * .65)
        low, high = midpoint - half_width, midpoint + half_width
        touch_indexes = _separated_touch_indexes(frame, low, high)
        if len(touch_indexes) < 2:
            continue
        last_index = touch_indexes[-1]
        recency = math.exp(-(final_index - last_index) / max(len(frame) * .22, 1))
        pivot_count = sum(item["source"] == "pivot" for item in group)
        strength = min(100.0, 18 + len(touch_indexes) * 10 + pivot_count * 6 + recency * 22)
        start_index = max(0, touch_indexes[0])
        zones.append({
            "low": round(low, 4), "high": round(high, 4), "midpoint": round(midpoint, 4),
            "touches": len(touch_indexes), "strength": round(strength, 1),
            "startTime": int(frame.iloc[start_index]["time"]), "lastTime": int(frame.iloc[last_index]["time"]),
            "type": "support" if midpoint < current else "resistance",
            "distancePct": round(abs(midpoint - current) / current * 100, 2),
            "sources": {"pivots": pivot_count, "volume": sum(item["source"] == "volume" for item in group)},
        })

    # Composite ranking balances proximity, repeated confirmation, strength and recency.
    zones.sort(key=lambda item: item["distancePct"] - item["strength"] * .035)
    selected = zones[:limit]
    return sorted(selected, key=lambda item: item["midpoint"], reverse=True)


def historical_zones(frame: pd.DataFrame, limit: int = 96, window: int = 240) -> list[dict]:
    """Chart-only retrospective levels, using each historical window's own ATR.

    Do not substitute these for the six actionable zones used by the Agent.
    Each window is evaluated independently; asOfTime discloses the last candle
    used, so startTime is NOT a claim the level was already known at that time.
    Overlapping windows retain formations near window boundaries. Selection is
    spread through history instead of ranked solely against today's price.
    """
    if len(frame) < 20 or limit <= 0:
        return []
    step = max(20, window // 2)
    ends = sorted(set([*range(step, len(frame), step), len(frame)]))
    groups = []
    for end in ends:
        sample = frame.iloc[max(0, end - window):end].reset_index(drop=True)
        levels = detect_zones(sample, find_pivots(sample), limit=None, volume_limit=None)
        levels.sort(key=lambda zone: (-zone["strength"], -zone["touches"], zone["midpoint"]))
        # Cover the local price span as well as time. Strong recent highs must
        # not crowd out the older lows inside the same historical window.
        diverse = levels[:1]
        remaining = levels[1:]
        while remaining:
            next_zone = max(remaining, key=lambda zone: (
                min(abs(zone["midpoint"] - other["midpoint"]) for other in diverse), zone["strength"]))
            diverse.append(next_zone)
            remaining.remove(next_zone)
        groups.append([{**zone, "historical": True, "asOfTime": int(sample.iloc[-1].time),
                        "windowStartTime": int(sample.iloc[0].time)} for zone in diverse])
    selected = []
    # Round-robin chronological windows: a highly volatile recent window cannot
    # consume the entire history budget. Frontend removes overlapping price bands.
    for rank in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if rank < len(group):
                selected.append(group[rank])
                if len(selected) >= limit:
                    return sorted(selected, key=lambda zone: (zone["asOfTime"], zone["midpoint"]))
    return sorted(selected, key=lambda zone: (zone["asOfTime"], zone["midpoint"]))
