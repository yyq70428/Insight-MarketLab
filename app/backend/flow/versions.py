from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from threading import RLock
from uuid import uuid4
from .policies import DEFAULT_POLICIES, validate_params, validate_overrides
from .repository import now, public
from ..services.time_boundary import anchor_cutoff

version_lock = RLock()

def diff_params(previous: dict, current: dict) -> dict:
    keys = set(previous) | set(current)
    return {key: {"from": previous.get(key), "to": current.get(key)} for key in keys if previous.get(key) != current.get(key)}


def version_eligible_at(version: dict, anchor_time) -> bool:
    return bool(version.get("effectiveAt") and version["effectiveAt"] <= anchor_time and version.get("status") == "active")


def ensure_baselines(repo, scope):
    with version_lock:
        versions = {}
        for agent, params in DEFAULT_POLICIES.items():
            identifier = sha256(f'baseline:{scope}:{agent}'.encode()).hexdigest()[:32]
            versions[agent] = identifier
            repo.db.strategy_versions.update_one({'id': identifier}, {'$setOnInsert': {
                'id': identifier, 'scope': scope, 'agent': agent, 'status': 'active', 'kind': 'baseline',
                'params': deepcopy(params), 'hypothesis': '規格預設基準', 'effectiveAt': datetime(1970,1,1,tzinfo=timezone.utc),
                'createdAt': now(), 'diff': {}, 'parentVersionId': None}}, upsert=True)
        repo.db.strategy_heads.update_one({'scope': scope}, {'$setOnInsert': {'scope': scope, 'revision': 0, 'versions': versions, 'updatedAt': now()}}, upsert=True)


def pin_versions(repo, symbol, interval, anchor, overrides=None):
    with version_lock:
        return _pin_versions(repo, symbol, interval, anchor, overrides)


def _pin_versions(repo, symbol, interval, anchor, overrides=None):
    overrides = validate_overrides(overrides or {})
    scope = f'{symbol}:{interval}'; ensure_baselines(repo, scope)
    cutoff = anchor_cutoff(symbol, anchor).astimezone(timezone.utc)
    params, versions, base_versions = {}, {}, {}
    for agent in DEFAULT_POLICIES:
        selected = repo.db.strategy_versions.find_one({'scope': scope, 'agent': agent, 'status': 'active',
            'effectiveAt': {'$lt': cutoff}}, sort=[('effectiveAt', -1), ('createdAt', -1)])
        params[agent] = validate_params(agent, selected['params'])
        versions[agent] = base_versions[agent] = selected['id']
        if overrides.get(agent):
            previous = params[agent]
            params[agent] = validate_params(agent, overrides[agent], previous)
            identifier = uuid4().hex
            repo.db.strategy_versions.insert_one({'id': identifier, 'scope': scope, 'agent': agent, 'kind': 'session_override',
                'status': 'override', 'params': params[agent], 'parentVersionId': selected['id'], 'createdAt': now(),
                'effectiveAt': cutoff, 'hypothesis': '本輪使用者覆寫', 'diff': diff_params(previous, params[agent])})
            versions[agent] = identifier
    return params, versions, base_versions


def execution_override(repo, session, overrides):
    params = validate_params('execution', overrides, session['params']['execution'])
    previous = session['params']['execution']; identifier = uuid4().hex
    repo.db.strategy_versions.insert_one({'id':identifier,'scope':session['scope'],'agent':'execution','status':'override',
        'kind':'session_override','params':params,'parentVersionId':session['versions']['execution'],'createdAt':now(),
        'effectiveAt':anchor_cutoff(session['symbol'],session['anchor']),'hypothesis':'決策前本輪參數覆寫','diff':diff_params(previous,params)})
    repo.update_session(session['id'], **{'params.execution':params,'versions.execution':identifier,'paramChanges':session.get('paramChanges',0)+1})
    repo.event(session,'execution','session_override',versionId=identifier)


def publish(repo, scope, agent, params, revision, hypothesis, source=None, effective_at=None):
    params = validate_params(agent, params)
    ensure_baselines(repo, scope)
    with version_lock:
        head = repo.db.strategy_heads.find_one({'scope': scope})
        if head['revision'] != revision: raise ValueError('策略 revision 已變更，請重新載入')
        parent = repo.db.strategy_versions.find_one({'id': head['versions'][agent]})
        identifier = uuid4().hex
        version = {'id': identifier, 'scope': scope, 'agent': agent, 'status': 'active', 'kind': 'rollback' if source else 'publish',
            'params': params, 'parentVersionId': parent['id'], 'hypothesis': hypothesis, 'createdAt': now(),
            'effectiveAt': effective_at or now(), 'diff': diff_params(parent['params'], params), 'rollbackOf': source}
        # Serialize within the specified single-process worker; CAS protects the head.
        repo.db.strategy_versions.insert_one(version)
        result = repo.db.strategy_heads.update_one({'scope': scope, 'revision': revision},
            {'$set': {f'versions.{agent}': identifier, 'updatedAt': now()}, '$inc': {'revision': 1}})
        if not result.modified_count:
            repo.db.strategy_versions.update_one({'id': identifier}, {'$set': {'status': 'conflict'}})
            raise ValueError('策略 revision 衝突')
        repo.db.strategy_events.insert_one({'scope': scope, 'agent': agent, 'action': 'rollback' if source else 'publish',
            'versionId': identifier, 'sourceVersionId': source, 'createdAt': now()})
        return {**public(version), 'revision': revision+1}
