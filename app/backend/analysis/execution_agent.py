from __future__ import annotations


def decide(technical: dict, news: dict, technical_weight: float = .5, min_confidence: float = 52) -> dict:
    news_weight = 1 - technical_weight
    score = technical["bullishPct"]*technical_weight + news["bullishPct"]*news_weight
    confidence = round(abs(score-50)*2, 1)
    action = "HOLD" if confidence < min_confidence else ("BUY" if score > 50 else "SELL")
    citations = list(dict.fromkeys(news.get("validCitationIds", [])))
    available = {source["id"] for source in news.get("sources", [])}
    if not set(citations).issubset(available):
        raise ValueError("決策引用包含不存在的新聞來源")
    return {"action": action, "confidence": confidence, "bullishScore": round(score, 1), "citations": citations,
            "technicalReason": technical.get("recommendation"), "newsReason": news.get("summary", "證據不足"),
            "risk": "歷史訊號與紙上驗證不代表未來績效", "frozen": True}


def rebase_targets(entry: float, target: float, stop: float, reference: float | None, basis: str = "entry_price") -> dict:
    """Shift the anchor-derived legs onto the actual fill.

    The technical Agent measures both legs in ATR units from the anchor close, but the order is
    filled at the next bar's open.  An overnight gap in the trade's favour otherwise consumes the
    intended move before entry, so the target is already touched on the first bar and the position
    is closed for a fraction of the planned edge.  Translating both legs by the gap keeps the
    intended ATR distance; "anchor_close" reproduces the pre-fix behaviour for older sessions.
    """
    if basis != "entry_price" or not reference:
        return {"target": target, "stop": stop, "basis": "anchor_close", "shift": 0.0, "reference": reference}
    shift = entry - reference
    return {"target": round(target+shift, 4), "stop": round(stop+shift, 4), "basis": "entry_price",
            "shift": round(shift, 4), "reference": reference}


def paper_validate(decision: dict, future: list[dict], target: float, stop: float, max_bars: int = 5,
                   hold_threshold_pct: float = 2, reference: float | None = None, basis: str = "entry_price") -> dict:
    if not future:
        return {"complete": False, "success": None, "bars": 0, "requiredBars": max_bars,
                "netReturnPct": None, "reason": "尚無錨點後完整 K 線"}
    bars = future[:max_bars]
    entry = bars[0]["open"]
    if decision["action"] == "HOLD":
        max_up = max((bar["high"]-entry)/entry*100 for bar in bars)
        max_down = max((entry-bar["low"])/entry*100 for bar in bars)
        complete = len(bars) >= max_bars
        return {"complete": complete, "entry": entry, "exit": entry, "netReturnPct": 0 if complete else None,
                "maxUpPct": round(max_up, 3), "maxDownPct": round(max_down, 3),
                "success": (max_up <= hold_threshold_pct and max_down <= hold_threshold_pct) if complete else None,
                "bars": len(bars), "requiredBars": max_bars, "entryTime": bars[0].get("time"), "exitTime": bars[-1].get("time"),
                "reason": "觀察期完成" if complete else "等待後續完整 K 線"}
    is_buy = decision["action"] == "BUY"
    planned_target, planned_stop = target, stop
    rebased = rebase_targets(entry, target, stop, reference, basis)
    target, stop = rebased["target"], rebased["stop"]
    exit_price, reason = bars[-1]["close"], "time"
    consumed = 0
    for bar in bars:
        consumed += 1
        stop_hit = bar["low"] <= stop if is_buy else bar["high"] >= stop
        target_hit = bar["high"] >= target if is_buy else bar["low"] <= target
        if stop_hit:
            exit_price, reason = (min(stop, bar["open"]) if is_buy else max(stop, bar["open"])), "stop"
            break
        if target_hit:
            exit_price, reason = target, "target"
            break
    gross = (exit_price-entry)/entry*100 * (1 if is_buy else -1)
    complete = len(bars) >= max_bars or reason != "time"
    return {"complete": complete, "entry": entry, "exit": exit_price, "exitReason": reason,
            "netReturnPct": round(gross-.2, 3) if complete else None, "success": gross-.2 > 0 if complete else None,
            "bars": consumed, "requiredBars": max_bars, "entryTime": bars[0].get("time"), "exitTime": bars[consumed-1].get("time"),
            "target": target, "stop": stop, "plannedTarget": planned_target, "plannedStop": planned_stop,
            "targetBasis": rebased["basis"], "entryShift": rebased["shift"], "anchorReference": rebased["reference"],
            "reason": "驗證完成" if complete else "等待後續完整 K 線"}
