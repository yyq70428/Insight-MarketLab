def citation_quality(findings: list[dict], sources: list[dict]) -> dict:
    known={row["id"] for row in sources}; citations=[row.get("sourceId") for row in findings]
    valid=sum(item in known for item in citations); total=len(citations)
    return {"citationCount":total,"validCitationCount":valid,"faithfulness":valid/total if total else None}
