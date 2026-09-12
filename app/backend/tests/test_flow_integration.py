"""Run against an isolated Mongo database; never modify the application's database.

MONGODB_URI must point at a test-accessible Mongo service. Market/model calls here
are deterministic; real upstream smoke checks are separate and explicitly labelled.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import pytest

from app.backend.flow.repository import FlowRepository
from app.backend.flow.runtime import FlowRuntime, FlowConflict
from app.backend.flow.policies import DEFAULT_POLICIES, validate_params
from app.backend.flow.versions import ensure_baselines, publish, pin_versions
from app.backend.services.agent_llm import ModelUnavailable
from app.backend.services.time_boundary import anchor_cutoff, candle_day


@pytest.fixture
def repo():
    row = FlowRepository()
    if not row.available(): pytest.skip('MongoDB integration service unavailable')
    database_name = 'marketlab_test_' + uuid4().hex
    row.db = row.client[database_name]
    row.ensure_indexes()
    try: yield row
    finally:
        # Exact random test database owned by this fixture, never production data.
        row.client.drop_database(database_name)
        row.client.close()


@pytest.fixture
def flow(repo, monkeypatch):
    import app.backend.flow.runtime as module
    import app.backend.flow.learning as learning
    rt = FlowRuntime(repo)
    initial = date(2025, 1, 1)
    rows = [{'time': int(datetime.combine(initial+timedelta(days=i), datetime.min.time(), timezone.utc).timestamp()),
             'open': 100, 'high': 101, 'low': 99, 'close': 100, 'volume': 1000} for i in range(400)]
    anchor = (initial+timedelta(days=300)).isoformat()
    def candles(symbol, interval, period, anchor=None):
        output = rows if anchor is None else [r for r in rows if candle_day(symbol, interval, r['time']) <= anchor]
        return {'candles': deepcopy(output)}
    technical = {'bullishPct': 65, 'bearishPct': 35, 'recommendation': '偏多', 'expectedBuy': 100,
                 'expectedSell': 110, 'downside': 90, 'components': {}}
    news = {'bullishPct': 60, 'bearishPct': 40, 'summary': '可驗證的測試新聞', 'sources': [{'id':'s','type':'stock'},{'id':'m','type':'market'}],
            'validCitationIds':['s','m'], 'limitations':[], 'evidenceSufficient': True, 'findings': []}
    def decision(tech, article, params):
        assert tech['identity'] == article['identity']
        return {'action':'HOLD','confidence':70,'citations':['s','m'],'modelUsed':True,'frozen':True,
                'technicalReason':'測試','newsReason':'測試','risk':'測試'}
    monkeypatch.setattr(module.market_data, 'candles', candles)
    monkeypatch.setattr(module, 'technical_report', lambda *args, **kwargs: deepcopy(technical))
    monkeypatch.setattr(module, 'news_report', lambda *args, **kwargs: deepcopy(news))
    monkeypatch.setattr(module, 'execution_decision', decision)
    monkeypatch.setattr(learning, 'technical_candidate', lambda *a, **kw: None)
    try: yield rt, anchor, rows
    finally: rt.executor.shutdown(wait=True)


def test_complete_flow_persists_and_freezes_before_future(flow, monkeypatch):
    rt, anchor, rows = flow
    market = __import__('app.backend.services.market_data', fromlist=['candles'])
    original = market.candles
    session = rt.create_session('0050.TW', '1d', anchor)
    def guarded(symbol, interval, period, anchor=None):
        if anchor is None:
            stored = rt.repo.get_session(session['id'])
            assert stored['decision']['frozenAt']
            assert stored['stageStatus']['technical'] == stored['stageStatus']['news'] == 'completed'
            assert rt.repo.db.execution_runs.find_one({'sessionId':session['id']})['decision']['frozenAt']
        return original(symbol, interval, period, anchor)
    monkeypatch.setattr(market, 'candles', guarded)
    with pytest.raises(FlowConflict): rt.run_stage(session['id'], 'execution')
    final = rt.run_session(session['id'])
    assert final['status'] == 'completed' and final['labelComplete']
    assert all(value == 'completed' for value in final['stageStatus'].values())
    assert final['outcome']['bars'] == 5
    for agent, runs in final['runs'].items():
        assert len(runs) == 1 and runs[0]['report']['identity']['sessionId'] == session['id']
        assert runs[0]['strategyVersionId'] == final['versions'][agent]
    actions = [e['action'] for e in final['events']]
    assert actions.index('decision_frozen') < actions.index('future_data_requested')
    assert rt.run_stage(session['id'], 'execution')['id'] == final['runs']['execution'][0]['id']
    assert rt.repo.db.execution_runs.count_documents({'sessionId':session['id']}) == 1


def test_batch_is_sequential_and_only_first_round_keeps_technical_override(flow):
    rt, anchor, rows = flow
    first = date.fromisoformat(anchor)
    batch = rt.create_batch('0050.TW', first, first+timedelta(days=1), 3, 2,
                            {'technical': {'rsiMode': 'trend'}, 'execution': {'minConfidence':80}})
    rt.executor.shutdown(wait=True)
    stored = rt.repo.db.flow_batches.find_one({'id':batch['id']})
    assert stored['status'] == 'completed' and stored['completedRounds'] == stored['validatedRounds'] == 2
    a, b = [rt.repo.get_session(sid) for sid in stored['sessionIds']]
    assert a['completedAt'] <= b['createdAt']
    assert b['previousSessionId'] == a['id']
    assert a['params']['technical']['rsiMode'] == 'trend'
    assert b['params']['technical']['rsiMode'] == 'mean_reversion'
    assert b['params']['execution']['minConfidence'] == 52
    assert b['params']['execution']['maxHoldingBars'] == 3


def test_batch_94_calendar_day_limit_is_inclusive(flow, monkeypatch):
    rt,_,_=flow
    import app.backend.flow.runtime as module
    def reached(*args,**kwargs):raise RuntimeError('passed date gate')
    monkeypatch.setattr(module.market_data,'candles',reached)
    start=date(2025,1,1)
    with pytest.raises(ValueError,match='94'):
        rt.create_batch('0050.TW',start,start+timedelta(days=94))
    with pytest.raises(RuntimeError,match='passed date gate'):
        rt.create_batch('0050.TW',start,start+timedelta(days=93))


def test_partial_labels_do_not_count_or_learn_and_refresh_keeps_decision(flow):
    rt, _, rows = flow
    anchor = candle_day('0050.TW', '1d', rows[-2]['time']).isoformat()
    session = rt.create_session('0050.TW', '1d', anchor)
    final = rt.run_session(session['id'])
    frozen = deepcopy(final['decision'])
    assert final['status'] == 'completed' and not final['labelComplete']
    assert final['outcome']['success'] is None and final['outcome']['netReturnPct'] is None
    assert not final['runs']['adaptive'][0]['report']['learned']
    assert rt.repo.overview()['onlineRounds'] == 0
    for _ in range(4): rows.append({**rows[-1], 'time':rows[-1]['time']+86400})
    final = rt.refresh_validation(session['id'])
    assert final['labelComplete'] and final['decision'] == frozen
    assert rt.repo.db.execution_runs.count_documents({'sessionId':session['id'],'role':'champion'}) == 1
    assert final['delayedAdaptive']['learned'] and rt.repo.overview()['onlineRounds'] == 1


def test_model_failure_is_persisted_and_never_silently_replaced(flow, monkeypatch):
    import app.backend.flow.runtime as module
    rt, anchor, _ = flow
    def broken(*a, **kw): raise ModelUnavailable('模型測試失敗')
    monkeypatch.setattr(module, 'execution_decision', broken)
    session = rt.create_session('0050.TW','1d',anchor)
    with pytest.raises(ModelUnavailable): rt.run_session(session['id'])
    result = rt.repo.get_session(session['id'])
    assert result['status'] == result['stageStatus']['execution'] == 'failed'
    assert 'decision' not in result
    assert 'future_data_requested' not in [e['action'] for e in result['events']]
    with pytest.raises(FlowConflict): rt.run_stage(session['id'], 'execution')


def test_stage_concurrency_rejects_duplicate_work(flow, monkeypatch):
    import app.backend.flow.runtime as module
    rt, anchor, _ = flow
    entered, release = Event(), Event()
    original = module.technical_report
    def blocked(*a, **kw):
        entered.set(); assert release.wait(5); return original(*a, **kw)
    monkeypatch.setattr(module, 'technical_report', blocked)
    session = rt.create_session('0050.TW', '1d', anchor)
    task = rt.executor.submit(rt.run_stage, session['id'], 'technical')
    assert entered.wait(5)
    try:
        with pytest.raises(FlowConflict): rt.run_stage(session['id'], 'technical')
    finally: release.set()
    task.result()
    assert rt.repo.db.technical_runs.count_documents({'sessionId':session['id']}) == 1


def test_execution_override_is_immutable_and_other_stages_reject_it(flow):
    rt,anchor,_=flow
    s=rt.create_session('0050.TW','1d',anchor)
    with pytest.raises(ValueError):rt.run_stage(s['id'],'technical',{'rsiMode':'trend'})
    rt.run_stage(s['id'],'technical');rt.run_stage(s['id'],'news')
    rt.run_stage(s['id'],'execution',{'maxHoldingBars':3})
    final=rt.repo.get_session(s['id'])
    assert final['params']['execution']['maxHoldingBars']==3
    assert final['versions']['execution']!=s['versions']['execution']
    with pytest.raises(FlowConflict):rt.run_stage(s['id'],'execution',{'maxHoldingBars':4})


def test_versions_are_immutable_revision_checked_and_time_gated(repo):
    ensure_baselines(repo, '0050.TW:1d')
    params = validate_params('technical', {'rsiMode':'trend'})
    published = publish(repo,'0050.TW:1d','technical',params,0,'測試候選發布',effective_at=anchor_cutoff('0050.TW','2026-09-09'))
    before, _, _ = pin_versions(repo,'0050.TW','1d','2026-09-09')
    after, ids, _ = pin_versions(repo,'0050.TW','1d','2026-09-10')
    assert before['technical']['rsiMode'] == 'mean_reversion'
    assert after['technical']['rsiMode'] == 'trend' and ids['technical'] == published['id']
    with pytest.raises(ValueError): publish(repo,'0050.TW:1d','technical',params,0,'過期版本修改')
    original = repo.db.strategy_versions.find_one({'id':published['id']})
    publish(repo,'0050.TW:1d','technical',DEFAULT_POLICIES['technical'],1,'人工回滾測試',source=published['id'])
    assert repo.db.strategy_versions.find_one({'id':published['id']}) == original


@pytest.mark.parametrize('overlap,agent,promoted',[(True,'execution',False),(False,'execution',True),(False,'news',False)])
def test_shadow_promotion_requires_nonoverlap_and_news_faithfulness(flow,overlap,agent,promoted):
    from app.backend.flow.learning import adapt_session
    rt,anchor,_=flow
    s=rt.create_session('0050.TW','1d',anchor)
    s=rt.run_session(s['id'])
    candidate={'id':uuid4().hex,'scope':s['scope'],'agent':agent,'status':'candidate','kind':'adaptive',
        'params':deepcopy(s['params'][agent]),'parentVersionId':s['baseVersions'][agent],
        'effectiveAt':datetime(2025,1,1,tzinfo=timezone.utc),'createdAt':datetime.now(timezone.utc)}
    rt.repo.db.strategy_versions.insert_one(candidate)
    for i in range(8):
        start=1735689600+(i if overlap else i*6)*86400
        rt.repo.db.strategy_shadow_samples.insert_one({'candidateId':candidate['id'],'sessionId':str(i),
            'windowStart':start,'windowEnd':start+5*86400,'championReturn':0,'candidateReturn':1,'faithfulness':None})
    rt.repo.update_session(s['id'],learningProcessed=False)
    result=adapt_session(rt,rt.repo.get_session(s['id']))
    evaluation=next(e for e in result['evaluations'] if e['candidateId']==candidate['id'])
    assert evaluation['passed'] is promoted
    head=rt.repo.db.strategy_heads.find_one({'scope':s['scope']})
    assert (head['revision']==1) is promoted
    assert rt.repo.db.strategy_versions.find_one({'id':candidate['id']})['status']=='candidate'
    if promoted:
        active=rt.repo.db.strategy_versions.find_one({'id':head['versions'][agent]})
        assert active['effectiveAt']>=datetime.fromisoformat(s['outcomeTime'])


def test_api_contract_and_validation(flow, monkeypatch):
    from fastapi.testclient import TestClient
    from app.backend.main import app
    import app.backend.flow.routes as routes
    rt, anchor, _ = flow
    monkeypatch.setattr(routes, 'repository', rt.repo)
    monkeypatch.setattr(routes, 'runtime', rt)
    client = TestClient(app)
    assert client.post('/api/flow/sessions', json={'symbol':'0050','anchor':anchor,'params':{'technical':{'notAllowed':1}}}).status_code == 422
    response = client.post('/api/flow/sessions', json={'symbol':'0050','anchor':anchor})
    assert response.status_code == 201
    s = response.json(); assert 'candleSnapshot' not in s and s['symbol'] == '0050.TW'
    assert client.post(f"/api/flow/sessions/{s['id']}/stages/execution").status_code == 409
    assert client.get('/api/flow/sessions/missing').status_code == 404
    assert client.post('/api/flow/batches', json={'symbol':'0050','startDate':anchor,'endDate':anchor,'maxHoldingDays':0}).status_code == 422
    assert client.get('/api/flow/strategies',params={'scope':'0050.TW:1d'}).json()['revision'] == 0
    assert client.post(f"/api/flow/sessions/{s['id']}/stages/technical").status_code==200
    assert client.post(f"/api/flow/sessions/{s['id']}/stages/news").status_code==200
    assert client.post(f"/api/flow/sessions/{s['id']}/stages/execution",json={'autoAdaptive':True}).status_code==200
    assert client.get(f"/api/flow/sessions/{s['id']}").json()['stageStatus']['adaptive']=='completed'
