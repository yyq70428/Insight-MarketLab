from types import SimpleNamespace

import pandas as pd
import pytest

from app.backend.services import quant_research as research
from app.backend.services.quant import backtest


def prices(values):
    return pd.DataFrame([{'time':1749513600+i*86400,'open':v,'high':v,'low':v,'close':v,'volume':100}
                         for i,v in enumerate(values)])


def setup_sources(monkeypatch, source, reference):
    monkeypatch.setattr(research,'get_settings',lambda:SimpleNamespace(daily_cache_ttl=1))
    monkeypatch.setattr(research.cache,'get',lambda *args:source.to_dict('records'))
    monkeypatch.setattr(research,'candles',lambda *args:{'candles':reference.to_dict('records')})


def test_split_discontinuity_replaces_whole_source_without_fake_loss(monkeypatch):
    source=prices([188.65,47.57,47.1]);reference=prices([47.1625,47.57,47.1])
    setup_sources(monkeypatch,source,reference)
    frame,metadata=research.research_data('0050.TW')
    assert frame.to_dict('records')==reference.to_dict('records')
    assert metadata['fallback'] and metadata['qualityChecks']['status']=='source_replaced'
    event=metadata['qualityChecks']['events'][0]
    assert event['sourceGapPct'] < -70 and event['referenceGapPct'] > 0
    assert backtest(frame,'buy_hold',{'market':'TW'})['totalReturnPct'] > -2


def test_real_crash_confirmed_in_both_sources_is_not_adjusted(monkeypatch):
    source=prices([100,25,24]);setup_sources(monkeypatch,source,source)
    frame,metadata=research.research_data('0050.TW')
    assert not metadata['fallback'] and not metadata['qualityChecks']['events'][0]['incompatibleBasis']
    assert backtest(frame,'buy_hold',{'market':'TW'})['totalReturnPct'] < -70


def test_unverifiable_discontinuity_blocks_results(monkeypatch):
    source=prices([100,25,24]);setup_sources(monkeypatch,source,source.iloc[1:])
    with pytest.raises(LookupError,match='相同交易日'):
        research.research_data('0050.TW')


def test_no_gap_does_not_require_second_provider(monkeypatch):
    source=prices([100,101,102]);setup_sources(monkeypatch,source,source)
    monkeypatch.setattr(research,'candles',lambda *args:pytest.fail('unnecessary provider request'))
    frame,metadata=research.research_data('0050.TW')
    assert len(frame)==3 and not metadata['fallback']


def test_fallback_discloses_missing_latest_trading_day(monkeypatch):
    source=prices([100]+[25]*39);reference=prices([25]*39)
    setup_sources(monkeypatch,source,reference)
    frame,metadata=research.research_data('0050.TW')
    assert len(frame)==39
    coverage=metadata['qualityChecks']['coverage']
    assert coverage['missingSourceDays']==1 and coverage['usedEnd']<coverage['sourceEnd']


def test_materially_incomplete_fallback_blocks_results(monkeypatch):
    source=prices([100]+[25]*39);reference=prices([25]*30)
    setup_sources(monkeypatch,source,reference)
    with pytest.raises(LookupError,match='95%'):
        research.research_data('0050.TW')
