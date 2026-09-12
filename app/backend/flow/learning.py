from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from .repository import now
from .versions import diff_params, publish
from ..services.time_boundary import anchor_cutoff, candle_day
from ..analysis.engine import rsi, macd
from ..services import market_data

def evaluate_shadow(champion_returns: list[float], candidate_returns: list[float], faithfulness: float | None = None,
                    min_samples: int = 8, min_improvement: float = .1, faithfulness_threshold: float = .8) -> dict:
    count = min(len(champion_returns), len(candidate_returns)); deltas=[candidate_returns[i]-champion_returns[i] for i in range(count)]
    mean = sum(deltas)/count if count else 0
    variance = sum((x-mean)**2 for x in deltas)/(count-1) if count>1 else 0
    lower = mean - 1.96*math.sqrt(variance/count) if count else float("-inf")
    passed = count>=min_samples and mean>=min_improvement and lower>0 and (faithfulness is None or faithfulness>=faithfulness_threshold)
    return {"sampleCount":count,"meanImprovementPct":round(mean,4),"lower95Pct":round(lower,4) if math.isfinite(lower) else None,"passed":passed}


def technical_candidate(frame, params, horizon=5):
    """Small, chronological screen; shadow trading is still required for promotion."""
    if len(frame) < 240: return None
    frame = frame.tail(600).reset_index(drop=True)
    indices = list(range(80, len(frame)-horizon, horizon+1))
    if len(indices) < 24: return None
    values = rsi(frame.close, params['rsiPeriod'])
    line, signal, _ = macd(frame.close, params['macdFast'], params['macdSlow'], params['macdSignal'])
    variants = [('mean_reversion', .5), ('mean_reversion', .75), ('trend', .5), ('trend', .75)]
    def returns(mode, rsi_weight, positions):
        output = []
        for i in positions:
            score = (values.iloc[i]-50) * (1 if mode == 'trend' else -1) * rsi_weight
            score += (1 if line.iloc[i] > signal.iloc[i] else -1) * 15 * (1-rsi_weight)
            side = 1 if score > 5 else -1 if score < -5 else 0
            output.append(((frame.close.iloc[i+horizon]/frame.open.iloc[i+1]-1)*100*side - .2) if side else 0)
        return sum(output)/len(output)
    train_end, validation_end = int(len(indices)*.6), int(len(indices)*.8)
    train, validation, test = indices[:train_end], indices[train_end:validation_end], indices[validation_end:]
    chosen = max(variants, key=lambda v: returns(*v, train))
    baseline = (params['rsiMode'], params['weights']['rsi']/max(params['weights']['rsi']+params['weights']['macd'], 1))
    if returns(*chosen, validation) <= returns(*baseline, validation): return None
    improvement = returns(*chosen, test) - returns(*baseline, test)
    if improvement < .1: return None
    candidate = deepcopy(params); candidate['rsiMode'] = chosen[0]
    candidate['weights'] = {'harmonics': 15, 'supportResistance': 15, 'macd': 70*(1-chosen[1]), 'rsi': 70*chosen[1]}
    if candidate == params: return None
    return candidate, {'method': 'chronological_indicator_screen', 'trainSamples': len(train), 'validationSamples': len(validation),
                       'testSamples': len(test), 'testImprovementPct': round(improvement, 4), 'note': '離線指標篩選不等於完整模型交易績效，仍須影子驗證'}


def prepare_shadows(runtime, session, technical, news):
    from ..analysis.technical_agent import technical_report
    from ..services.agent_pipeline import execution_decision, news_report
    repo = runtime.repo
    candidates = list(repo.db.strategy_versions.find({'id': {'$exists': True}, 'scope': session['scope'], 'status': 'candidate',
        'effectiveAt': {'$lt': anchor_cutoff(session['symbol'], session['anchor'])}}).sort('createdAt', -1))
    used_agents = set()
    for candidate in candidates:
        agent = candidate['agent']
        if agent in used_agents or candidate['parentVersionId'] != session['baseVersions'][agent]: continue
        used_agents.add(agent); role = 'shadow:' + candidate['id']
        if repo.db.execution_runs.find_one({'sessionId': session['id'], 'role': role}): continue
        params = deepcopy(session['params']); params[agent] = candidate['params']
        # Batch horizon and HOLD definition must be identical in paired comparisons.
        for key in ('maxHoldingBars', 'holdThresholdPct'): params['execution'][key] = session['params']['execution'][key]
        repo.create_run('execution', session['id'], role, params['execution'])
        try:
            tech, article = technical, news
            if agent == 'technical':
                repo.create_run('technical', session['id'], role, params['technical'])
                tech = technical_report(market_data.frame_from_rows(session['candleSnapshot']), params=params['technical'],
                    symbol=session['symbol'], interval=session['interval'], anchor=session['anchor'])
                tech['identity'] = technical['identity']
                repo.finish_run('technical', session['id'], role, tech)
            elif agent == 'news':
                repo.create_run('news', session['id'], role, params['news'])
                article = news_report(session['symbol'], session['anchor'], params['news'])
                article['identity'] = news['identity']
                repo.finish_run('news', session['id'], role, article)
                from ..services.news_evaluation import evaluate_news
                repo.db.news_evaluations.insert_one({'sessionId':session['id'], 'role':role, 'createdAt':now(), **evaluate_news(article)})
            if agent in ('technical','news'):
                repo.db[f'{agent}_runs'].update_one({'sessionId':session['id'],'role':role},{'$set':{'strategyVersionId':candidate['id']}})
            decision = execution_decision(tech, article, params['execution'])
            decision['frozenAt'] = now().isoformat()
            repo.db.execution_runs.update_one({'sessionId': session['id'], 'role': role}, {'$set': {
                'candidateVersionId': candidate['id'], 'decision': decision, 'technical': {k: tech[k] for k in ('expectedSell','downside')},
                'strategyVersionId': candidate['id']}})
            repo.event(session, agent, 'shadow_decision_frozen', versionId=candidate['id'])
        except Exception as exc:
            if agent in ('technical','news'):
                repo.finish_run(agent, session['id'], role, error=runtime.error_message(exc))
            repo.finish_run('execution', session['id'], role, error=runtime.error_message(exc))
            repo.event(session, agent, 'shadow_failed', versionId=candidate['id'])


def validate_shadows(runtime, session, future, champion):
    from ..analysis.execution_agent import paper_validate
    repo = runtime.repo
    for run in repo.db.execution_runs.find({'sessionId': session['id'], 'role': {'$regex': '^shadow:'}, 'decision.frozen': True}):
        target, stop = runtime.targets(run['decision'], run['technical'])
        outcome = paper_validate(run['decision'], future, target, stop, run['params']['maxHoldingBars'], run['params']['holdThresholdPct'])
        repo.finish_run('execution', session['id'], run['role'], {'decision': run['decision'], 'validation': outcome})
        if not champion.get('complete') or not outcome['complete']: continue
        key = {'candidateId': run['candidateVersionId'], 'sessionId': session['id']}
        quality = repo.db.news_evaluations.find_one({'sessionId':session['id'], 'role':run['role']}) or {}
        repo.db.strategy_shadow_samples.update_one(key, {'$setOnInsert': {**key, 'anchor': session['anchor'],
            'windowStart': future[0]['time'], 'windowEnd': max(champion['exitTime'], outcome['exitTime']),
            'championReturn': champion['netReturnPct'], 'candidateReturn': outcome['netReturnPct'],
            'faithfulness': quality.get('faithfulness'), 'createdAt': now()}}, upsert=True)


def adapt_session(runtime, session):
    repo = runtime.repo; outcome = session.get('outcome', {})
    policy = session['params']['adaptive']
    if not outcome.get('complete'):
        return {'learned': False, 'recommendation': '等待完整觀察期；未使用不完整结果學習', 'candidates': [], 'evaluations': []}
    if session.get('learningProcessed'):
        return session.get('learningResult', {'learned': True, 'recommendation': '本輪已完成自適應審核', 'candidates': []})
    outcome_time = session['outcomeTime']
    if isinstance(outcome_time, str): outcome_time = datetime.fromisoformat(outcome_time)
    effective = outcome_time + timedelta(seconds=1)
    proposals = []
    screened = technical_candidate(market_data.frame_from_rows(session['candleSnapshot']), session['params']['technical'], session['params']['execution']['maxHoldingBars'])
    if screened: proposals.append(('technical', screened[0], screened[1]))
    article = runtime.champion(session, 'news')
    if article.get('evidenceSufficient') and article.get('limitations') and session['params']['news']['minRelevance'] < .5:
        candidate = {**session['params']['news'], 'minRelevance': min(.5, session['params']['news']['minRelevance']+.1)}
        proposals.append(('news', candidate, {'reason': '有效新聞有證據限制，提出提高相關度門檻的影子候選'}))
    if outcome.get('success') is False and session['decision']['action'] != 'HOLD' and session['params']['execution']['minConfidence'] < 90:
        candidate = {**session['params']['execution'], 'minConfidence': session['params']['execution']['minConfidence']+5}
        proposals.append(('execution', candidate, {'reason': '本輪未成功，提出提高信心門檻的影子候選'}))
    created = []
    for agent, params, evidence in proposals:
        if repo.db.strategy_versions.find_one({'id': {'$exists': True}, 'scope': session['scope'], 'agent': agent, 'status': 'candidate', 'parentVersionId': session['baseVersions'][agent]}): continue
        identifier = uuid4().hex
        repo.db.strategy_versions.insert_one({'id': identifier, 'scope': session['scope'], 'agent': agent,
            'status': 'candidate', 'kind': 'adaptive', 'params': params, 'parentVersionId': session['baseVersions'][agent],
            'sessionId': session['id'], 'effectiveAt': effective, 'createdAt': now(), 'evidence': evidence,
            'hypothesis': '候選參數須通過後續不重疊影子比較', 'diff': diff_params(session['params'][agent], params)})
        repo.event(session, agent, 'candidate_proposed', versionId=identifier, effectiveAt=effective)
        created.append(identifier)
    evaluations = []
    for candidate in repo.db.strategy_versions.find({'id': {'$exists': True}, 'scope': session['scope'], 'status': 'candidate'}):
        if repo.db.strategy_events.find_one({'action': 'candidate_promoted', 'sourceVersionId': candidate['id']}): continue
        samples = list(repo.db.strategy_shadow_samples.find({'candidateId': candidate['id']}).sort('windowStart', 1))
        selected, last_end = [], -1
        for sample in samples:
            if sample['windowStart'] > last_end:
                selected.append(sample); last_end = sample['windowEnd']
        evaluation = evaluate_shadow([s['championReturn'] for s in selected], [s['candidateReturn'] for s in selected],
            min_samples=policy['minShadowSessions'], min_improvement=policy['minImprovementPct'])
        # Citation existence is NOT faithfulness; without a semantic judge, never promote news.
        if candidate['agent'] == 'news':
            scores = [s.get('faithfulness') for s in selected]
            if not scores or any(v is None or v < policy['faithfulnessThreshold'] for v in scores):
                evaluation.update(passed=False, reason='忠實度評審缺少或未達門檻，新聞候選不可自動提升')
            evaluation['faithfulness'] = min(scores) if scores and all(v is not None for v in scores) else None
        evaluations.append({'candidateId': candidate['id'], **evaluation})
        repo.event(session, candidate['agent'], 'shadow_evaluated', versionId=candidate['id'], evaluation=evaluation)
        head = repo.db.strategy_heads.find_one({'scope': session['scope']})
        if evaluation['passed'] and head['versions'][candidate['agent']] == candidate['parentVersionId']:
            # Every sample must have matured before the published version can be selected.
            latest_day = candle_day(session['symbol'],session['interval'],last_end)
            eligible = max(effective, anchor_cutoff(session['symbol'], latest_day))
            published = publish(repo, session['scope'], candidate['agent'], candidate['params'], head['revision'],
                                '後續不重疊影子樣本通過改善門檻', effective_at=eligible)
            repo.event(session, candidate['agent'], 'candidate_promoted', versionId=published['id'], sourceVersionId=candidate['id'])
    result = {'learned': True, 'recommendation': '已完成自適應審核；正式策略僅在影子驗證通過後變更', 'candidates': created, 'evaluations': evaluations}
    repo.update_session(session['id'], learningProcessed=True, learningResult=result)
    return result
