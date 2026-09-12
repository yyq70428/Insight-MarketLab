def adaptive_report(outcome: dict, min_samples: int = 8, max_candidates: int = 2,
                    reject_after: int = 4) -> dict:
    if not outcome.get("complete"):
        return {"learned": False, "recommendation": "觀察期尚未完成，保留報告但不學習", "candidates": []}
    return {"learned": True, "recommendation": "維持正式策略；候選需經後續、不重疊影子樣本驗證",
            "policy": {"minShadowSessions": min_samples, "minImprovementPct": .1,
                       "confidenceLowerBound": 0, "maxCandidatesPerAgent": max_candidates,
                       "rejectAfterShadowSessions": reject_after}, "candidates": []}
