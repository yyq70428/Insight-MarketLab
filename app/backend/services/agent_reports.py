from threading import Lock
from time import monotonic
from uuid import uuid4
from ..config import get_settings


class LegacyReportStore:
    def __init__(self): self.data={}; self.lock=Lock()
    def put(self, kind: str, identity: dict, report: dict):
        identifier=uuid4().hex
        with self.lock: self.data[identifier]={"kind":kind,"identity":identity,"report":report,"created":monotonic()}
        return identifier
    def get(self, identifier: str, kind: str):
        with self.lock: item=self.data.get(identifier)
        if not item or item["kind"]!=kind or monotonic()-item["created"]>get_settings().agent_report_ttl: return None
        return item


legacy_reports=LegacyReportStore()


def report_summary(report: dict) -> dict:
    """Return only the fields the downstream decision Agent is allowed to read."""
    allowed = {"bullishPct", "bearishPct", "recommendation", "summary", "limitations", "sources", "validCitationIds",
               "expectedBuy", "expectedSell", "downside", "targetBars", "components"}
    return {key: report[key] for key in allowed if key in report}
