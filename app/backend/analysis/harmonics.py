from __future__ import annotations

from collections.abc import Mapping


# Classical harmonic constraints.  Ranges are intentionally explicit: every
# required ratio must pass, so a strong match on three legs cannot hide a bad D.
CLASSIC_PATTERNS: dict[str, dict[str, tuple[float, float]]] = {
    "Gartley": {"ab_xa": (.58, .66), "bc_ab": (.382, .886), "cd_bc": (1.13, 1.618), "ad_xa": (.74, .82)},
    "Bat": {"ab_xa": (.382, .50), "bc_ab": (.382, .886), "cd_bc": (1.618, 2.618), "ad_xa": (.84, .93)},
    "Butterfly": {"ab_xa": (.75, .82), "bc_ab": (.382, .886), "cd_bc": (1.618, 2.618), "ad_xa": (1.22, 1.68)},
    "Crab": {"ab_xa": (.382, .618), "bc_ab": (.382, .886), "cd_bc": (2.618, 3.618), "ad_xa": (1.55, 1.68)},
    "Deep Crab": {"ab_xa": (.84, .93), "bc_ab": (.382, .886), "cd_bc": (2.0, 3.618), "ad_xa": (1.55, 1.68)},
}

SPECIAL_PATTERNS: dict[str, dict[str, tuple[float, float]]] = {
    "Cypher": {"ab_xa": (.382, .618), "xc_xa": (1.272, 1.414), "cd_xc": (.75, .82)},
    "Shark": {"bc_ab": (1.13, 1.618), "cd_bc": (1.618, 2.24), "ad_xa": (.886, 1.13)},
    "ABCD": {"bc_ab": (.382, .886), "cd_bc": (1.13, 2.618), "cd_ab": (.90, 1.10)},
}


def _ratio(numerator: float, denominator: float) -> float:
    return abs(numerator / denominator) if denominator else 0.0


def _ratios(x: float, a: float, b: float, c: float, d: float) -> dict[str, float]:
    xa, ab, bc, cd = a - x, b - a, c - b, d - c
    return {
        "ab_xa": _ratio(ab, xa),
        "bc_ab": _ratio(bc, ab),
        "cd_bc": _ratio(cd, bc),
        "ad_xa": _ratio(d - a, xa),
        "xd_xa": _ratio(d - x, xa),
        "xc_xa": _ratio(c - x, xa),
        "cd_xc": _ratio(cd, c - x),
        "cd_ab": _ratio(cd, ab),
    }


def _geometry_ok(points: list[dict], special: str | None = None) -> bool:
    if any(left["kind"] == right["kind"] for left, right in zip(points, points[1:])):
        return False
    x, a, b, c, d = (point["price"] for point in points)
    bullish = points[0]["kind"] == "low"
    if bullish:
        basic = x < a and b < a and c > b and d < c
        return basic and (c > a if special == "Cypher" else True)
    basic = x > a and b > a and c < b and d > c
    return basic and (c < a if special == "Cypher" else True)


def _matches(values: Mapping[str, float], rules: Mapping[str, tuple[float, float]]) -> bool:
    return all(low <= values[key] <= high for key, (low, high) in rules.items())


def _score(values: Mapping[str, float], rules: Mapping[str, tuple[float, float]]) -> float:
    errors = []
    for key, (low, high) in rules.items():
        midpoint = (low + high) / 2
        half_width = max((high - low) / 2, .001)
        errors.append(abs(values[key] - midpoint) / half_width)
    return max(0.0, 100.0 - sum(errors) / len(errors) * 24.0)


def _classic_prz(x: float, a: float, ratio_range: tuple[float, float]) -> tuple[float, float]:
    xa = abs(a - x)
    low_ratio, high_ratio = ratio_range
    if x < a:
        return tuple(sorted((a - high_ratio * xa, a - low_ratio * xa)))
    return tuple(sorted((a + low_ratio * xa, a + high_ratio * xa)))


def _prz(name: str, prices: tuple[float, float, float, float, float], rules: Mapping[str, tuple[float, float]]) -> tuple[float, float]:
    x, a, b, c, _ = prices
    if "ad_xa" in rules:
        return _classic_prz(x, a, rules["ad_xa"])
    if name == "Cypher":
        length = abs(c - x)
        low_ratio, high_ratio = rules["cd_xc"]
        values = (c - high_ratio * length, c - low_ratio * length) if x < a else (c + low_ratio * length, c + high_ratio * length)
        return tuple(sorted(values))
    length = abs(b - a)
    values = (c - 1.1 * length, c - .9 * length) if x < a else (c + .9 * length, c + 1.1 * length)
    return tuple(sorted(values))


def _result(name: str, points: list[dict], values: dict[str, float], rules: Mapping[str, tuple[float, float]]) -> dict:
    prices = tuple(point["price"] for point in points)
    _, a, _, _, d = prices
    low, high = _prz(name, prices, rules)
    return {
        "name": name,
        "direction": "bullish" if points[0]["kind"] == "low" else "bearish",
        "status": "completed" if points[-1]["confirmed"] else "forming",
        "score": round(_score(values, rules), 1),
        "points": [{"label": label, **point} for label, point in zip("XABCD", points)],
        "ratios": {key: round(value, 3) for key, value in values.items() if key in rules},
        "ratioLimits": {key: list(bounds) for key, bounds in rules.items()},
        "prz": {"low": round(low, 4), "high": round(high, 4)},
        "targets": [round(d + (a - d) * ratio, 4) for ratio in (.382, .618)],
    }


def detect_harmonics(pivots: list[dict], limit: int = 8) -> list[dict]:
    results: list[dict] = []
    for start in range(max(0, len(pivots) - 30), len(pivots) - 4):
        points = pivots[start:start + 5]
        if len(points) < 5 or not _geometry_ok(points):
            continue
        prices = tuple(point["price"] for point in points)
        values = _ratios(*prices)
        candidates = list(CLASSIC_PATTERNS.items()) + list(SPECIAL_PATTERNS.items())
        for name, rules in candidates:
            if not _geometry_ok(points, name if name == "Cypher" else None):
                continue
            if _matches(values, rules):
                results.append(_result(name, points, values, rules))
    # Prefer completed, accurate, recent structures and suppress exact duplicate labels.
    ordered = sorted(results, key=lambda item: (item["status"] == "completed", item["score"], item["points"][-1]["time"]), reverse=True)
    unique, seen = [], set()
    for item in ordered:
        identity = (item["name"], tuple(point["time"] for point in item["points"]))
        if identity in seen:
            continue
        seen.add(identity); unique.append(item)
    return unique[:limit]
