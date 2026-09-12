from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import PyMongoError, DuplicateKeyError

from ..config import get_settings


def now():
    return datetime.now(timezone.utc)


def public(document):
    if isinstance(document, datetime):
        return document.replace(tzinfo=document.tzinfo or timezone.utc).isoformat()
    if isinstance(document, dict):
        return {key: public(value) for key, value in document.items() if key != "_id"}
    if isinstance(document, list):
        return [public(value) for value in document]
    return document


class FlowRepository:
    collections = ("sessions", "technical_runs", "news_runs", "execution_runs", "adaptive_runs", "news_evaluations",
                   "strategy_versions", "strategy_heads", "strategy_events", "flow_jobs", "flow_batches")

    def __init__(self):
        settings = get_settings()
        self.client = MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=4500, tz_aware=True) if settings.mongodb_uri else None
        self.db = self.client[settings.mongodb_database] if self.client else None
        self._initialized = False
        self._initialization_lock = Lock()

    def available(self) -> bool:
        if not self.client:
            return False
        try:
            self.client.admin.command("ping")
            return True
        except PyMongoError:
            return False

    def require(self):
        if not self.available():
            raise RuntimeError("MongoDB 未設定或目前無法連線")

    def initialize(self):
        """Initialize once per process, retrying on the first request if startup missed Atlas."""
        if self._initialized: return
        with self._initialization_lock:
            if self._initialized: return
            self.require()
            self.interrupt_stale_work()
            self.ensure_indexes()
            self._initialized = True

    @staticmethod
    def _current_id_index(collection):
        if any(info.get('key') == [('id', 1)] for info in collection.index_information().values()): return
        collection.create_index('id', unique=True, name='current_id_unique',
                                partialFilterExpression={'id': {'$type': 'string'}})

    def ensure_indexes(self):
        self.require()
        self._current_id_index(self.db.sessions)
        self.db.sessions.create_index([("scope", ASCENDING), ("anchor", DESCENDING)])
        for name in ("technical_runs", "news_runs", "execution_runs", "adaptive_runs", "news_evaluations"):
            self.db[name].create_index([("sessionId", ASCENDING), ("role", ASCENDING)], unique=True)
        self._current_id_index(self.db.strategy_versions)
        if not any(info.get('key') == [('scope', 1)] for info in self.db.strategy_heads.index_information().values()):
            self.db.strategy_heads.create_index('scope', unique=True, name='current_scope_unique',
                                                partialFilterExpression={'scope': {'$type': 'string'}})
        self._current_id_index(self.db.flow_jobs)
        self.db.flow_jobs.create_index("sessionId", unique=True, partialFilterExpression={"active": True}, name="one_active_job")
        self._current_id_index(self.db.flow_batches)
        self.db.flow_batches.create_index('activeKey', unique=True, sparse=True, name='one_active_batch')
        self.db.strategy_shadow_samples.create_index([("candidateId", 1), ("sessionId", 1)], unique=True)

    def create_session(self, payload: dict) -> dict:
        self.require()
        document = {"id": uuid4().hex, "status": "first_layer", "stageStatus": {name: "waiting" for name in ("technical", "news", "execution", "adaptive")},
                    "createdAt": now(), "updatedAt": now(), **payload}
        self.db.sessions.insert_one(document)
        return public(document)

    def get_session(self, session_id: str) -> dict | None:
        self.require()
        session = public(self.db.sessions.find_one({"id": session_id}))
        if not session:
            return None
        session["runs"] = {name.replace("_runs", ""): [public(row) for row in self.db[name].find({"sessionId": session_id})]
                           for name in ("technical_runs", "news_runs", "execution_runs", "adaptive_runs")}
        session["events"] = [public(row) for row in self.db.strategy_events.find({"sessionId": session_id}).sort("createdAt", ASCENDING)]
        session["jobActive"] = bool(self.db.flow_jobs.find_one({"sessionId": session_id, "active": True}))
        session["newsEvaluations"] = public(list(self.db.news_evaluations.find({"sessionId": session_id})))
        identifiers = list(session.get('versions', {}).values()) + list(session.get('baseVersions', {}).values())
        # Include adaptive candidates created by this session so the prediction
        # journey can explain parameter changes instead of showing only IDs.
        learning = session.get('learningResult') or {}
        identifiers += list(learning.get('candidates') or [])
        identifiers += [row['id'] for row in self.db.strategy_versions.find(
            {'sessionId': session_id, 'status': 'candidate'}, {'id': 1})]
        session["relatedVersions"] = public(list(self.db.strategy_versions.find({'id': {'$in': identifiers}})))
        return session

    def list_sessions(self, query: dict, limit: int = 100) -> list[dict]:
        self.require()
        return [public(row) for row in self.db.sessions.find(query).sort("createdAt", DESCENDING).limit(limit)]

    def create_run(self, agent: str, session_id: str, role: str, params: dict) -> dict:
        self.require()
        collection = self.db[f"{agent}_runs"]
        existing = collection.find_one({"sessionId": session_id, "role": role})
        if existing:
            return public(existing)
        document = {"id": uuid4().hex, "sessionId": session_id, "agent": agent, "role": role, "status": "running",
                    "params": params, "createdAt": now()}
        try:
            collection.insert_one(document)
        except DuplicateKeyError:
            return public(collection.find_one({"sessionId": session_id, "role": role}))
        return public(document)

    def finish_run(self, agent: str, session_id: str, role: str, report: dict | None = None, error: str | None = None):
        status = "failed" if error else "completed"
        update = {"status": status, "completedAt": now(), "report": report}
        if error:
            update["error"] = error
        self.db[f"{agent}_runs"].update_one({"sessionId": session_id, "role": role}, {"$set": update})
        if role == "champion":
            self.db.sessions.update_one({"id": session_id}, {"$set": {f"stageStatus.{agent}": status, "updatedAt": now()}})

    def event(self, session: dict, agent: str, action: str, **extra):
        self.db.strategy_events.insert_one({"id": uuid4().hex, "sessionId": session["id"], "scope": session["scope"],
                                           "agent": agent, "action": action, "createdAt": now(), **extra})

    def update_session(self, session_id: str, **values):
        self.db.sessions.update_one({"id": session_id}, {"$set": {"updatedAt": now(), **values}})

    def interrupt_stale_work(self):
        error = "應用於執行中重新啟動；請建立新的執行工作"
        # A second computer may legitimately be running against the same Atlas DB.
        # Only reclaim work with no heartbeat for 30 minutes (or legacy rows with no timestamps).
        stale_before = now() - timedelta(minutes=30)
        stale_before_iso = stale_before.isoformat()
        stale = {"$or": [
            {"updatedAt": {"$lt": stale_before}},
            {"updatedAt": {"$lt": stale_before_iso}},
            {"updatedAt": {"$exists": False}, "startedAt": {"$lt": stale_before}},
            {"updatedAt": {"$exists": False}, "startedAt": {"$lt": stale_before_iso}},
            {"updatedAt": {"$exists": False}, "startedAt": {"$exists": False}, "createdAt": {"$lt": stale_before}},
            {"updatedAt": {"$exists": False}, "startedAt": {"$exists": False}, "createdAt": {"$lt": stale_before_iso}},
            {"updatedAt": {"$exists": False}, "startedAt": {"$exists": False}, "createdAt": {"$exists": False}},
        ]}
        self.db.flow_jobs.update_many({"status": {"$in": ["queued", "running"]}, **stale},
                                     {"$set": {"status": "interrupted", "active": False, "error": error, "updatedAt": now()}})
        self.db.flow_batches.update_many({"status": {"$in": ["queued", "running"]}, **stale},
                                        {"$set": {"status": "interrupted", "error": error, "updatedAt": now()},
                                         "$unset": {"activeKey": ""}})
        for agent in ("technical", "news", "execution", "adaptive"):
            for run in self.db[f"{agent}_runs"].find({"status": "running", "role": "champion", **stale}):
                session_id = run.get("sessionId")
                if session_id:
                    self.finish_run(agent, session_id, "champion", error=error)
                    self.update_session(session_id, status="failed", error=error)
                else:
                    self.db[f"{agent}_runs"].update_one({"_id": run["_id"]}, {"$set": {
                        "status": "interrupted", "error": error, "completedAt": now()}})

    def overview(self, scope: str | None = None):
        self.require()
        query = {"scope": scope} if scope else {}
        rows = list(self.db.sessions.find(query).sort("anchor", ASCENDING))
        completed = [row for row in rows if row.get("status") == "completed" and row.get("labelComplete")]
        returns = [float(row.get("outcome", {}).get("netReturnPct", 0)) for row in completed]
        from .dashboard import split_return_summary
        return {"total": len(rows), "completed": sum(row.get("status") == "completed" for row in rows),
                "waitingValidation": sum(row.get("status") == "completed" and not row.get("labelComplete") for row in rows),
                "returnSummary": split_return_summary(returns), "failed": sum(row.get("status") == "failed" for row in rows),
                "onlineRounds": sum(bool(row.get("labelComplete")) for row in rows), "pendingCandidates": self.db.strategy_versions.count_documents({**query, "id": {"$exists": True}, "status": "candidate"}),
                "curve": [{"anchor": row.get("anchor"), "value": round(sum(returns[:i+1])/(i+1), 3)} for i, row in enumerate(completed)],
                "recentEvents": [public(row) for row in self.db.strategy_events.find(query).sort("createdAt", DESCENDING).limit(10)]}


repository = FlowRepository()
