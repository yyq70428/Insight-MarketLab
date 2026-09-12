"""Flow routes are mounted by app.backend.main to keep one public FastAPI entrypoint."""
from __future__ import annotations

from datetime import date
from typing import Any
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError
from .runtime import runtime, FlowConflict
from .repository import repository, public
from .policies import DEFAULT_POLICIES, POLICY_SCHEMA, POLICY_MODELS, validate_overrides, validate_params
from .versions import ensure_baselines, publish
from ..services.agent_llm import ModelUnavailable
from ..config import get_settings
from ..validators import normalize_symbol, validate_interval

router = APIRouter(prefix='/api/flow')


def checked(call):
    try:
        repository.initialize()
        return call()
    except HTTPException: raise
    except FlowConflict as exc: raise HTTPException(409, str(exc)) from exc
    except ModelUnavailable as exc: raise HTTPException(503, str(exc)) from exc
    except ValidationError as exc: raise HTTPException(422, 'Agent 參數超出規格範圍或含未知欄位') from exc
    except ValueError as exc: raise HTTPException(422, str(exc)) from exc
    except LookupError as exc: raise HTTPException(404, str(exc)) from exc
    except Exception as exc: raise HTTPException(503, 'Flow 儲存或上游服務暫時不可用') from exc


def session_view(row):
    return {k: v for k, v in row.items() if k != 'candleSnapshot'}


def validated_scope(value):
    symbol, separator, interval = value.rpartition(':')
    if not separator: raise HTTPException(422,'scope 格式為標的:週期')
    return normalize_symbol(symbol)+':'+validate_interval(interval,flow=True)


class SessionCreate(BaseModel):
    symbol: str
    interval: str = '1d'
    anchor: date
    autoRun: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    previousSessionId: str | None = None
    symbolName: str | None = Field(None, max_length=120)


@router.get('/config')
def config():
    settings = get_settings()
    return {'databaseConfigured': bool(settings.mongodb_uri), 'databaseAvailable': repository.available(),
            'modelConfigured': bool(settings.openai_api_key), 'ragasEnabled': settings.ragas_enabled,
            'engine': 'strategy-engine-2', 'model': settings.openai_model, 'agents': list(DEFAULT_POLICIES), 'batchEnabled': True}


@router.get('/policies')
def policies(): return {'defaults': DEFAULT_POLICIES, 'schema': POLICY_SCHEMA, 'models': {a:m.model_json_schema() for a,m in POLICY_MODELS.items()}}


@router.get('/scopes')
def scopes():
    def load():
        values=set(repository.db.sessions.distinct('scope')) | set(repository.db.strategy_heads.distinct('scope'))
        return {'scopes': sorted(values)}
    return checked(load)


@router.post('/sessions', status_code=201)
def create_session(body: SessionCreate):
    def create():
        row = runtime.create_session(normalize_symbol(body.symbol), validate_interval(body.interval, flow=True),
                                     body.anchor.isoformat(), body.params, body.previousSessionId, symbol_name=body.symbolName)
        if body.autoRun: row['job'] = runtime.submit_session(row['id'])
        return session_view(row)
    return checked(create)


@router.get('/sessions')
def sessions(scope: str | None = None, symbol: str | None = None, status: str | None = None, limit: int = Query(100, ge=1, le=200)):
    query = {}
    if scope: query['scope'] = scope
    if symbol: query['symbol'] = normalize_symbol(symbol)
    if status: query['status'] = status
    return checked(lambda: {'sessions': [session_view(row) for row in repository.list_sessions(query, limit)]})


@router.get('/sessions/{session_id}')
def session(session_id: str):
    def load():
        row = repository.get_session(session_id)
        if not row: raise LookupError('找不到 Session')
        return session_view(row)
    return checked(load)


@router.post('/sessions/{session_id}/run', status_code=202)
def run(session_id: str): return checked(lambda: runtime.submit_session(session_id))


class StageRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    autoAdaptive: bool = False


@router.post('/sessions/{session_id}/stages/{agent}')
def stage(session_id: str, agent: str, body: StageRequest | None = None):
    def execute():
        report=runtime.run_stage(session_id, agent, body.params if body else None)
        if agent=='execution' and body and body.autoAdaptive: runtime.run_stage(session_id,'adaptive')
        return report
    return checked(execute)


@router.post('/sessions/{session_id}/refresh-validation')
def refresh(session_id: str): return checked(lambda: session_view(runtime.refresh_validation(session_id)))


class NextSession(BaseModel):
    tradingDays: int = Field(1, ge=1, le=7)
    autoRun: bool = True


@router.post('/sessions/{session_id}/next', status_code=201)
def next_session(session_id: str, body: NextSession):
    def create():
        from ..services import market_data
        from ..services.time_boundary import candle_day
        previous = repository.get_session(session_id)
        if not previous: raise LookupError('找不到 Session')
        if previous['status'] != 'completed': raise FlowConflict('上一輪尚未完整完成')
        rows = market_data.candles(previous['symbol'], previous['interval'], '5y')['candles']
        days = sorted({candle_day(previous['symbol'], previous['interval'], row['time']).isoformat() for row in rows
                       if candle_day(previous['symbol'], previous['interval'], row['time']).isoformat() > previous['anchor']})
        if len(days) < body.tradingDays: raise FlowConflict('尚無足夠後續交易日可建立下一輪')
        row = runtime.create_session(previous['symbol'], previous['interval'], days[body.tradingDays-1], previous_id=session_id)
        if body.autoRun: row['job'] = runtime.submit_session(row['id'])
        return session_view(row)
    return checked(create)


class BatchCreate(BaseModel):
    symbol: str
    startDate: date
    endDate: date
    maxHoldingDays: int = Field(5, ge=1, le=7)
    holdThresholdPct: float = Field(2, ge=.1, le=20)
    params: dict[str, Any] = Field(default_factory=dict)
    symbolName: str | None = Field(None, max_length=120)


@router.post('/batches', status_code=202)
def batch(body: BatchCreate):
    return checked(lambda: runtime.create_batch(normalize_symbol(body.symbol), body.startDate, body.endDate,
                    body.maxHoldingDays, body.holdThresholdPct, body.params, body.symbolName))


@router.get('/batches')
def batches(symbol: str | None = None, limit: int = Query(20, ge=1, le=100)):
    query = {'symbol': normalize_symbol(symbol)} if symbol else {}
    return checked(lambda: {'batches': public(list(repository.db.flow_batches.find(query).sort('createdAt', -1).limit(limit)))})


@router.get('/batches/{batch_id}')
def get_batch(batch_id: str):
    def load():
        row = repository.db.flow_batches.find_one({'id': batch_id})
        if not row: raise LookupError('找不到批次')
        return public(row)
    return checked(load)


@router.post('/batches/{batch_id}/refresh-validation')
def refresh_batch(batch_id: str): return checked(lambda: runtime.refresh_batch(batch_id))


@router.get('/jobs/{job_id}')
def job(job_id: str):
    def load():
        row = repository.db.flow_jobs.find_one({'id': job_id})
        if not row: raise LookupError('找不到工作')
        return public(row)
    return checked(load)


@router.get('/overview')
def overview(scope: str | None = None): return checked(lambda: repository.overview(scope))


@router.get('/strategies')
def strategies(scope: str):
    scope = validated_scope(scope)
    def load():
        ensure_baselines(repository, scope)
        head = repository.db.strategy_heads.find_one({'scope': scope})
        current = {agent: validate_params(agent, repository.db.strategy_versions.find_one({'id': identifier})['params']) for agent, identifier in head['versions'].items()}
        return {'scope': scope, 'revision': head['revision'], 'head': public(head), 'defaults': DEFAULT_POLICIES, 'params': current,
                'models': {a:m.model_json_schema() for a,m in POLICY_MODELS.items()}}
    return checked(load)


class StrategyUpdate(BaseModel):
    scope: str
    params: dict[str, Any]
    hypothesis: str = Field(min_length=3, max_length=500)
    expectedRevision: int = Field(ge=0)


@router.post('/strategies/{agent}', status_code=201)
def strategy(agent: str, body: StrategyUpdate):
    def update():
        try: return publish(repository, validated_scope(body.scope), agent, body.params, body.expectedRevision, body.hypothesis)
        except ValueError as exc:
            if 'revision' in str(exc): raise FlowConflict(str(exc)) from exc
            raise
    return checked(update)


@router.get('/versions')
def versions(scope: str, agent: str | None = None):
    scope = validated_scope(scope)
    query = {'scope': scope, 'id': {'$exists': True}}
    if agent: query['agent'] = agent
    return checked(lambda: {'versions': public(list(repository.db.strategy_versions.find(query).sort('createdAt', -1).limit(200)))})


class Rollback(BaseModel):
    expectedRevision: int = Field(ge=0)
    hypothesis: str = Field('人工回滾', min_length=3, max_length=500)


@router.post('/versions/{version_id}/rollback', status_code=201)
def rollback(version_id: str, body: Rollback):
    def update():
        source = repository.db.strategy_versions.find_one({'id': version_id})
        if not source: raise LookupError('找不到版本')
        if source['status'] != 'active': raise FlowConflict('只能回滾至曾發布的正式版本')
        try: return publish(repository, source['scope'], source['agent'], source['params'], body.expectedRevision, body.hypothesis, source=version_id)
        except ValueError as exc:
            if 'revision' in str(exc): raise FlowConflict(str(exc)) from exc
            raise
    return checked(update)


@router.get('/events')
def events(scope: str | None = None):
    return checked(lambda: {'events': public(list(repository.db.strategy_events.find({'scope': scope} if scope else {}).sort('createdAt', -1).limit(200)))})
