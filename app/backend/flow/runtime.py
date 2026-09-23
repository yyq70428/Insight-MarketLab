"""Flow orchestration boundary.

The critical ordering is encoded by callers: first-layer reports are persisted before
decision input is built, and future candles may only be loaded after a frozen decision.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from threading import Lock
from uuid import uuid4
import logging
from pymongo.errors import DuplicateKeyError
from .repository import repository, public, now
from .versions import pin_versions
from .policies import validate_overrides, validate_params
from ..services import market_data
from ..services.time_boundary import anchor_cutoff, candle_day, candle_closed, market_timezone
from ..services.agent_pipeline import news_report, execution_decision
from ..services.agent_llm import ModelUnavailable
from ..analysis.technical_agent import technical_report
from ..analysis.execution_agent import paper_validate
from ..analysis.adaptive_agent import adaptive_report

STAGE_ORDER = ("technical", "news", "execution", "adaptive")

def can_enter(stage: str, statuses: dict) -> bool:
    if stage in {"technical", "news"}: return True
    if stage == "execution": return statuses.get("technical") == statuses.get("news") == "completed"
    if stage == "adaptive": return statuses.get("execution") == "completed"
    return False


class FlowConflict(ValueError): pass


class FlowRuntime:
    def __init__(self, repo=repository):
        self.repo = repo
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix='marketlab-flow')
        self._lock = Lock()
        self._active_stages = set()

    @contextmanager
    def stage_lock(self, session_id, agent, role='champion'):
        key = (session_id, agent, role)
        with self._lock:
            if key in self._active_stages: raise FlowConflict('此階段正在執行，請等待原本工作')
            self._active_stages.add(key)
        try: yield
        finally:
            with self._lock: self._active_stages.discard(key)

    def create_session(self, symbol, interval, anchor, overrides=None, previous_id=None, batch_id=None, symbol_name=None):
        if date.fromisoformat(anchor) > datetime.now(market_timezone(symbol)).date():
            raise ValueError('錨點不可在未來')
        if previous_id:
            previous = self.repo.get_session(previous_id)
            if not previous or previous['status'] != 'completed': raise FlowConflict('上一輪尚未完整完成')
            if previous['symbol'] != symbol or previous['interval'] != interval or previous['anchor'] >= anchor:
                raise ValueError('前後輪必須相同標的與週期，錨點必須往後')
        candles = market_data.candles(symbol, interval, '5y', date.fromisoformat(anchor))['candles']
        candles = [r for r in candles if candle_day(symbol, interval, r['time']).isoformat() <= anchor and candle_closed(symbol,interval,r['time'])]
        if len(candles) < 80: raise ValueError('錨點前至少需要 80 根 K 線')
        params, versions, base_versions = pin_versions(self.repo, symbol, interval, anchor, overrides)
        session = self.repo.create_session({'symbol': symbol, 'interval': interval, 'scope': f'{symbol}:{interval}',
            'anchor': anchor, 'dataCutoff': anchor_cutoff(symbol, anchor), 'params': params, 'versions': versions,
            'baseVersions': base_versions, 'previousSessionId': previous_id, 'batchId': batch_id,
            'candleSnapshot': candles, 'labelComplete': False, 'symbolName':symbol_name})
        self.repo.event(session, 'flow', 'session_created', versions=versions)
        for agent, identifier in versions.items():
            if identifier != base_versions[agent]: self.repo.event(session, agent, 'session_override', versionId=identifier)
        self.repo.update_session(session['id'], paramChanges=sum(versions[a] != base_versions[a] for a in versions))
        return self.repo.get_session(session['id'])

    def submit_session(self, session_id):
        session = self.repo.get_session(session_id)
        if not session: raise LookupError('找不到 Session')
        if session['status'] in ('completed', 'failed'): raise FlowConflict('此輪已結束，請建立新輪次')
        job = {'id': uuid4().hex, 'sessionId': session_id, 'status': 'queued', 'active': True, 'createdAt': now()}
        try: self.repo.db.flow_jobs.insert_one(job)
        except DuplicateKeyError as exc: raise FlowConflict('此 Session 已有執行中的工作') from exc
        self.executor.submit(self._job, job['id'], session_id)
        return public(job)

    def _job(self, job_id, session_id):
        self.repo.db.flow_jobs.update_one({'id': job_id}, {'$set': {'status': 'running', 'startedAt': now()}})
        try:
            session = self.run_session(session_id)
            values = {'status': 'completed', 'validationPending': not session.get('labelComplete')}
        except Exception as exc:
            values = {'status': 'failed', 'error': self.error_message(exc)}
        self.repo.db.flow_jobs.update_one({'id': job_id}, {'$set': {**values, 'active': False, 'completedAt': now()}})

    def error_message(self, exc):
        logging.getLogger(__name__).error('Flow failure (%s)', type(exc).__name__, exc_info=exc)
        if isinstance(exc, (ModelUnavailable, FlowConflict)): return str(exc)
        if isinstance(exc, KeyError): return '資料結構不相容，已停止此輪；請檢查舊版策略資料'
        if isinstance(exc, LookupError): return '行情資料不足或來源目前不可用'
        return '執行失敗，請檢查行情、歷史新聞與模型服務後建立新輪次'

    def run_session(self, session_id, progress=None):
        if progress: progress('first_layer')
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks = [pool.submit(self.run_stage, session_id, agent) for agent in ('technical', 'news')]
            # Wait for both tasks so a late failure cannot be hidden by the next stage.
            errors = []
            for task in tasks:
                try: task.result()
                except Exception as exc: errors.append(exc)
            if errors: raise errors[0]
        for stage in ('execution', 'adaptive'):
            if progress: progress(stage)
            self.run_stage(session_id, stage)
        return self.repo.get_session(session_id)

    def run_stage(self, session_id, agent, overrides=None):
        if agent not in STAGE_ORDER: raise ValueError('未知 Agent')
        if overrides and agent != 'execution': raise ValueError('只有決策階段可在執行前覆寫參數')
        with self.stage_lock(session_id, agent):
            session = self.repo.get_session(session_id)
            if not session: raise LookupError('找不到 Session')
            existing = next((r for r in session['runs'][agent] if r['role'] == 'champion'), None)
            if existing:
                if overrides: raise FlowConflict('階段已建立，禁止變更凍結參數')
                if existing['status'] == 'completed': return existing
                raise FlowConflict('此階段執行中或已失敗；同一角色不可重複執行')
            if session['status'] == 'failed': raise FlowConflict('此輪已失敗，請建立新輪次')
            if not can_enter(agent, session['stageStatus']): raise FlowConflict('前置階段尚未完成')
            if overrides:
                from .versions import execution_override
                execution_override(self.repo, session, overrides)
                session = self.repo.get_session(session_id)
            params = session['params'][agent]
            run = self.repo.create_run(agent, session_id, 'champion', params)
            self.repo.db[f'{agent}_runs'].update_one({'id': run['id']}, {'$set': {'strategyVersionId': session['versions'][agent]}})
            self.repo.db[f'{agent}_runs'].update_one({'id':run['id']},{'$set':{'inputSummary':{
                'symbol':session['symbol'],'interval':session['interval'],'anchor':session['anchor'],
                'dataCutoff':session['dataCutoff'],'candleCount':len(session['candleSnapshot']) if agent=='technical' else None,
                'reportIds':{a:[r['id'] for r in session['runs'][a] if r['role']=='champion'] for a in ('technical','news')} if agent=='execution' else {},
                'labelComplete':session.get('labelComplete') if agent=='adaptive' else None}}})
            self.repo.update_session(session_id, **{f'stageStatus.{agent}': 'running'})
            self.repo.event(session, agent, 'started')
            try:
                if agent == 'technical':
                    report = technical_report(market_data.frame_from_rows(session['candleSnapshot']), params=params,
                        symbol=session['symbol'], interval=session['interval'], anchor=session['anchor'])
                elif agent == 'news':
                    report = news_report(session['symbol'], session['anchor'], params, session.get('symbolName'))
                    from ..services.news_evaluation import evaluate_news
                    evaluation = evaluate_news(report)
                    self.repo.db.news_evaluations.insert_one({'sessionId': session_id, 'role': 'champion', 'createdAt': now(), **evaluation})
                    self.repo.update_session(session_id, faithfulness=evaluation['faithfulness'])
                elif agent == 'execution':
                    report = self._execution(session)
                else:
                    report = self._adaptive(session)
                report['identity'] = {'sessionId': session_id, 'symbol': session['symbol'], 'interval': session['interval'], 'anchor': session['anchor']}
                self.repo.finish_run(agent, session_id, 'champion', report)
                fields = {}
                if agent == 'technical': fields = {'technicalBullish': report['bullishPct']}
                if agent == 'news': fields = {'newsBullish': report['bullishPct'], 'articleCount': len(report['sources']), 'newsEvidenceSufficient':report['evidenceSufficient']}
                if agent == 'adaptive': fields = {'status': 'completed', 'completedAt': now(), 'adaptiveConclusion': report['recommendation']}
                if fields: self.repo.update_session(session_id, **fields)
                self.repo.event(session, agent, 'completed')
                return public(self.repo.db[f'{agent}_runs'].find_one({'id': run['id']}))
            except Exception as exc:
                error = self.error_message(exc)
                self.repo.finish_run(agent, session_id, 'champion', error=error)
                self.repo.update_session(session_id, status='failed', error=error)
                self.repo.event(session, agent, 'failed', error=error)
                raise

    def champion(self, session, agent):
        return next(r['report'] for r in session['runs'][agent] if r['role'] == 'champion' and r['status'] == 'completed')

    def _execution(self, session):
        technical, news = self.champion(session, 'technical'), self.champion(session, 'news')
        decision = execution_decision(technical, news, session['params']['execution'])
        decision['frozenAt'] = now().isoformat()
        # Persist and audit BEFORE requesting any future market data, including shadows.
        self.repo.update_session(session['id'], decision=decision, status='execution')
        self.repo.db.execution_runs.update_one({'sessionId': session['id'], 'role': 'champion'}, {'$set': {'decision': decision}})
        self.repo.event(session, 'execution', 'decision_frozen', actionTaken=decision['action'])
        from .learning import prepare_shadows
        prepare_shadows(self, session, technical, news)
        report = self.validate_frozen(session, decision, technical)
        self.repo.update_session(session['id'], status='adaptive')
        return report

    def validate_frozen(self, session, decision, technical):
        if not decision.get('frozenAt'): raise FlowConflict('決策尚未凍結，禁止取得未來資料')
        self.repo.event(session, 'execution', 'future_data_requested')
        rows = market_data.candles(session['symbol'], session['interval'], 'max' if session['interval']=='1d' else '5y')['candles']
        # Using the anchor's date, not the last available candle, avoids a weekend leak.
        future = [r for r in rows if candle_day(session['symbol'], session['interval'], r['time']).isoformat() > session['anchor']
                  and candle_closed(session['symbol'],session['interval'],r['time'])]
        params = session['params']['execution']
        target, stop = self.targets(decision, technical)
        validation = paper_validate(decision, future, target, stop, params['maxHoldingBars'], params['holdThresholdPct'],
                                    reference=technical.get('referencePrice'), basis=params['targetBasis'])
        outcome_time = None
        if validation.get('exitTime'):
            day = candle_day(session['symbol'], session['interval'], validation['exitTime'])
            outcome_time = anchor_cutoff(session['symbol'], day) - timedelta(seconds=1)
        self.repo.update_session(session['id'], outcome=validation, outcomeTime=outcome_time, labelComplete=validation['complete'])
        self.repo.event(session, 'execution', 'validation_completed' if validation['complete'] else 'validation_pending', bars=validation['bars'])
        from .learning import validate_shadows
        validate_shadows(self, session, future, validation)
        # Report the legs that actually governed the exit, keeping the anchor-derived plan alongside.
        return {'decision': decision, 'validation': validation, 'target': validation.get('target', target),
                'stop': validation.get('stop', stop), 'plannedTarget': target, 'plannedStop': stop,
                'replay': future[:validation['bars']]}

    def targets(self, decision, technical):
        if decision['action'] == 'SELL':
            return technical['downside'], technical['expectedSell']
        return technical['expectedSell'], technical['downside']

    def _adaptive(self, session):
        session = self.repo.get_session(session['id'])
        adaptive = session['params']['adaptive']
        report = adaptive_report(session.get('outcome', {}), adaptive['minShadowSessions'],
                                 adaptive.get('maxCandidatesPerAgent', 2),
                                 adaptive.get('rejectAfterShadowSessions', 4))
        from .learning import adapt_session
        report.update(adapt_session(self, session))
        return report

    def create_batch(self, symbol, start, end, max_holding=5, threshold=2, overrides=None, symbol_name=None):
        validate_overrides(overrides or {})
        if end < start or (end-start).days+1 > 94: raise ValueError('日期區間必須正向且最多 94 日（含起迄日）')
        if end > datetime.now(market_timezone(symbol)).date(): raise ValueError('結束日期不可在未來')
        params = validate_params('execution', {'maxHoldingBars': max_holding, 'holdThresholdPct': threshold})
        rows = market_data.candles(symbol, '1d', '5y', end)['candles']
        anchors = sorted({candle_day(symbol, '1d', row['time']).isoformat() for row in rows
                          if start <= candle_day(symbol, '1d', row['time']) <= end and candle_closed(symbol,'1d',row['time'])})
        if not anchors: raise ValueError('此區間沒有可用交易日行情')
        active_key = f'{symbol}:1d:{start.isoformat()}:{end.isoformat()}'
        batch = {'id': uuid4().hex, 'activeKey': active_key, 'symbol': symbol, 'interval': '1d', 'startDate': start.isoformat(), 'endDate': end.isoformat(),
            'anchors': anchors, 'totalRounds': len(anchors), 'completedRounds': 0, 'currentRound': 0, 'currentStage': 'waiting',
            'sessionIds': [], 'rounds': [], 'stats': {'BUY': 0, 'SELL': 0, 'HOLD': 0}, 'successCount': 0, 'successRate': None,
            'validatedRounds': 0, 'pendingValidation': 0, 'initialOverrides': overrides or {},
            'maxHoldingDays': params['maxHoldingBars'], 'holdThresholdPct': params['holdThresholdPct'],
            'status': 'queued', 'createdAt': now(), 'symbolName':symbol_name, 'lastAvailableDate': candle_day(symbol, '1d', rows[-1]['time']).isoformat()}
        try: self.repo.db.flow_batches.insert_one(batch)
        except DuplicateKeyError as exc: raise FlowConflict('相同標的與日期區間已有執行中的批次') from exc
        try:
            self.executor.submit(self.run_batch, batch['id'])
        except Exception:
            self.repo.db.flow_batches.update_one({'id': batch['id']}, {
                '$set': {'status': 'failed', 'error': '背景工作無法啟動', 'completedAt': now()},
                '$unset': {'activeKey': ''}})
            raise
        return public(batch)

    def run_batch(self, batch_id):
        batch = self.repo.db.flow_batches.find_one_and_update({'id': batch_id, 'status': 'queued'}, {'$set': {'status': 'running', 'startedAt': now()}})
        if not batch: return
        def update(**fields): self.repo.db.flow_batches.update_one({'id': batch_id}, {'$set': {**fields, 'updatedAt': now()}})
        previous_id = None
        try:
            for index, anchor in enumerate(batch['anchors']):
                overrides = dict(batch['initialOverrides']) if index == 0 else {}
                overrides['execution'] = {**overrides.get('execution', {}), 'maxHoldingBars': batch['maxHoldingDays'], 'holdThresholdPct': batch['holdThresholdPct']}
                update(currentRound=index+1, currentAnchor=anchor, currentStage='creating_session')
                session = self.create_session(batch['symbol'], '1d', anchor, overrides, previous_id, batch_id, batch.get('symbolName'))
                previous_id = session['id']
                self.repo.db.flow_batches.update_one({'id': batch_id}, {'$push': {'sessionIds': session['id']}})
                update(currentSessionId=session['id'])
                self.run_session(session['id'], lambda stage: update(currentStage=stage))
                self.update_batch_summary(batch_id)
            self.update_batch_summary(batch_id, final=True)
            self.repo.db.flow_batches.update_one({'id': batch_id}, {'$unset': {'activeKey': ''}})
        except Exception as exc:
            self.update_batch_summary(batch_id)
            update(status='failed', error=self.error_message(exc), completedAt=now())
            self.repo.db.flow_batches.update_one({'id': batch_id}, {'$unset': {'activeKey': ''}})

    def update_batch_summary(self, batch_id, final=False):
        batch = self.repo.db.flow_batches.find_one({'id': batch_id})
        rounds = []
        for session_id in batch['sessionIds']:
            s = self.repo.db.sessions.find_one({'id': session_id})
            execution = self.repo.db.execution_runs.find_one({'sessionId': session_id, 'role': 'champion'}, {'report': 1}) or {}
            execution_report = execution.get('report') or {}
            rounds.append({'sessionId': session_id, 'anchor': s['anchor'], 'status': s['status'],
                'anchorTime': s.get('candleSnapshot', [{}])[-1].get('time') if s.get('candleSnapshot') else None,
                'action': s.get('decision', {}).get('action'), 'confidence': s.get('decision', {}).get('confidence'),
                'target': execution_report.get('target'), 'stop': execution_report.get('stop'),
                'modelUsed': s.get('decision', {}).get('modelUsed'), 'evidenceSufficient': s.get('newsEvidenceSufficient', False),
                'validation': s.get('outcome', {}), 'completed': s['status'] == 'completed'})
        completed = sum(r['completed'] for r in rounds)
        validated = [r for r in rounds if r['validation'].get('complete')]
        success = sum(bool(r['validation'].get('success')) for r in validated)
        pending = sum(r['completed'] and not r['validation'].get('complete') for r in rounds)
        fields = {'rounds': rounds, 'completedRounds': completed, 'validatedRounds': len(validated), 'pendingValidation': pending,
            'stats': {a: sum(r['action'] == a for r in rounds) for a in ('BUY','SELL','HOLD')},
            'successCount': success, 'successRate': round(success/len(validated)*100, 2) if validated else None, 'updatedAt': now()}
        if final: fields.update(status='waiting_validation' if pending else 'completed', currentStage='waiting_data' if pending else 'completed', completedAt=now())
        self.repo.db.flow_batches.update_one({'id': batch_id}, {'$set': fields})
        return public(self.repo.db.flow_batches.find_one({'id': batch_id}))

    def refresh_validation(self, session_id):
        with self.stage_lock(session_id, 'validation_refresh'):
            session = self.repo.get_session(session_id)
            if not session or session['status'] != 'completed': raise FlowConflict('本輪分析尚未完成')
            if session.get('labelComplete'): return session
            report = self.validate_frozen(session, session['decision'], self.champion(session, 'technical'))
            self.repo.db.execution_runs.update_one({'sessionId': session_id, 'role': 'champion'}, {'$set': {'report.validation': report['validation'], 'report.replay': report['replay']}})
            # The original adaptive report stays immutable; delayed learning is audited separately.
            if report['validation']['complete']:
                learned = self._adaptive(self.repo.get_session(session_id))
                self.repo.update_session(session_id, delayedAdaptive=learned, adaptiveConclusion=learned['recommendation'])
            return self.repo.get_session(session_id)

    def refresh_batch(self, batch_id):
        batch = self.repo.db.flow_batches.find_one({'id': batch_id})
        if not batch: raise LookupError('找不到批次')
        if batch['status'] not in ('completed', 'waiting_validation'): raise FlowConflict('批次分析仍在執行或已失敗')
        for sid in batch['sessionIds']: self.refresh_validation(sid)
        return self.update_batch_summary(batch_id, final=True)


runtime = FlowRuntime()
