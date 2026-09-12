from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.backend.services import agent_llm, agent_pipeline
from app.backend.services.historical_news import classify, verify_article
from app.backend.services.time_boundary import candle_day, anchor_cutoff, candle_closed
from app.backend.flow.policies import validate_params
from app.backend.analysis.execution_agent import paper_validate


def test_responses_reasoning_before_message_and_strict_payload(monkeypatch):
    settings = Mock(openai_api_key='test-only-not-real',openai_model='test-model',openai_base_url='https://example.invalid/v1',openai_timeout=1)
    monkeypatch.setattr(agent_llm,'get_settings',lambda:settings)
    response = Mock(status_code=200)
    response.json.return_value={'status':'completed','output':[{'type':'reasoning'},{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]}
    post=Mock(return_value=response);monkeypatch.setattr(agent_llm.requests,'post',post)
    assert agent_llm.structured_response('test',{'body':'文章指令不可信'}, {'type':'object'}) == {'ok':True}
    body=post.call_args.kwargs['json']
    assert body['store'] is False and body['text']['format']['strict'] is True
    response.status_code=401
    with pytest.raises(agent_llm.ModelUnavailable):agent_llm.structured_response('test',{}, {})


def test_news_classification_does_not_use_publisher_suffix_or_other_stock():
    identity={'symbol':'0050.TW','aliases':['0050','元大台灣50']}
    assert classify('其他公司營收創高 | 鉅亨網 - 台股新聞','',identity) is None
    assert classify('外資買超華星光，前鼎收漲停 | 鉅亨網 - 台股新聞','',identity) is None
    assert classify('台股漲百點，三大法人買超','',identity) == 'market'
    assert classify('0050定期定額人數增加','',identity) == 'stock'
    assert classify('營收速報 - 台股大型公司營收一覽','',identity) is None
    assert classify('代號10050公司','',identity) is None


def test_modified_date_is_mandatory_and_future_update_excluded():
    article={'id':'x','url':'https://example.com','type':'stock','publishedAt':'2026-09-09T00:00:00Z'}
    cutoff=anchor_cutoff('0050.TW','2026-09-09')
    assert not verify_article(article,cutoff)[0]
    article['modifiedAt']='2026-09-09T16:00:00Z'
    assert not verify_article(article,cutoff)[0]
    article['modifiedAt']='2026-09-09T15:59:59Z'
    assert verify_article(article,cutoff)[0]


def test_exchange_day_is_not_utc_day_for_us_intraday():
    stamp=datetime(2026,9,10,0,30,tzinfo=timezone.utc).timestamp()
    assert candle_day('AAPL','1h',stamp).isoformat() == '2026-09-09'
    assert candle_day('0050.TW','1h',stamp).isoformat() == '2026-09-10'


def test_partial_current_candle_is_not_a_completed_label():
    day=datetime(2026,9,9,tzinfo=timezone.utc).timestamp()
    assert not candle_closed('0050.TW','1d',day,datetime(2026,9,9,4,tzinfo=timezone.utc))
    assert candle_closed('0050.TW','1d',day,datetime(2026,9,9,6,tzinfo=timezone.utc))
    assert not candle_closed('AAPL','1h',day,datetime(2026,9,9,0,30,tzinfo=timezone.utc))


def test_semantic_judge_disabled_or_failure_does_not_invent_faithfulness(monkeypatch):
    from app.backend.services import news_evaluation as module
    report={'validCitationIds':['s'],'evidenceSufficient':True,'findings':[{'sourceId':'s'}],
            'sources':[{'id':'s','title':'來源','body':'內容'}]}
    monkeypatch.setattr(module,'get_settings',lambda:Mock(ragas_enabled=False))
    assert module.evaluate_news(report)['faithfulness'] is None
    monkeypatch.setattr(module,'get_settings',lambda:Mock(ragas_enabled=True))
    monkeypatch.setattr(module,'structured_response',lambda *a,**kw:{'findings':[{'sourceId':'s','supported':True,'explanation':'來源支持'}]})
    assert module.evaluate_news(report)['faithfulness']==1
    monkeypatch.setattr(module,'structured_response',lambda *a,**kw:{'findings':[]})
    assert module.evaluate_news(report)['status']=='failed'


@pytest.mark.parametrize('params',[{'weights':{'harmonics':0,'supportResistance':0,'macd':0,'rsi':0}}, {'weights':{'rsi':float('nan')}}, {'rsiMode':'not-a-mode'}, {'script':'unsafe'}])
def test_policy_rejects_unknown_and_invalid_values(params):
    with pytest.raises((ValueError,ValidationError)): validate_params('technical',params)


def test_early_exit_counts_only_consumed_bars_and_stop_wins_collision():
    bars=[{'time':i,'open':100,'high':111,'low':89,'close':105} for i in range(1,6)]
    result=paper_validate({'action':'BUY'},bars,110,90,5)
    assert result['bars']==1 and result['exitReason']=='stop' and result['exitTime']==1 and result['complete']


def test_partial_hold_has_no_success_or_return():
    result=paper_validate({'action':'HOLD'},[{'time':1,'open':100,'high':101,'low':99,'close':100}],110,90,5)
    assert result['success'] is None and result['netReturnPct'] is None and not result['complete']
