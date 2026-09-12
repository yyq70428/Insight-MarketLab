from __future__ import annotations


def insufficient_news_report(sources: list[dict], reason: str = "可驗證新聞證據不足") -> dict:
    return {"bullishPct": 50.0, "bearishPct": 50.0, "directionScore": 0, "coverage": 0,
            "summary": reason, "limitations": [reason], "findings": [], "sources": sources,
            "validCitationIds": [], "evidenceSufficient": False}


def validate_findings(findings: list[dict], sources: list[dict]) -> tuple[list[dict], list[str]]:
    known = {item["id"]: item for item in sources}
    valid, limitations, used = [], [], set()
    for item in findings[:6]:
        source_id = item.get("sourceId")
        source = known.get(source_id)
        if not source or source_id in used or item.get("type") != source.get("type"):
            limitations.append(f"忽略無效、重複或類型不符引用：{source_id}")
            continue
        used.add(source_id)
        valid.append(item)
    return valid, limitations
