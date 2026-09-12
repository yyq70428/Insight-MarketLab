from datetime import datetime, timezone
import json

import numpy as np
import pandas as pd
import pytest

from app.backend.analysis.macd_context import score_macd
from app.backend.analysis.technical_agent import technical_report, expected_time
from app.backend.flow.policies import validate_params


def wave(direction=1,mode='histogram',fading=False):
    line=pd.Series(np.linspace(-5,5,180))*direction
    if fading:line.iloc[-5:]=np.array([4.7,4.6,4.5,4.4,4.3])*direction
    histogram=pd.Series([float(direction)]*len(line));signal=line-histogram
    return score_macd(line,signal,histogram,100,validate_params('technical',{'macdMode':mode}))


@pytest.mark.parametrize('mode',['histogram','waveform'])
def test_high_position_reduces_bullish_strength_without_flipping(mode):
    result=wave(mode=mode)
    assert result['positionPct']==100 and result['zone']=='high'
    assert 50<=result['score']<70 and result['score']<result['baseScore']
    assert result['guardApplied'] and '追高' in result['interpretation']


@pytest.mark.parametrize('mode',['histogram','waveform'])
def test_low_position_reduces_bearish_strength_without_flipping(mode):
    result=wave(-1,mode)
    assert result['positionPct']==0 and result['zone']=='low'
    assert 30<result['score']<=50 and result['score']>result['baseScore']
    assert '追空' in result['interpretation']


@pytest.mark.parametrize('direction',[1,-1])
def test_extreme_position_with_fading_momentum_is_further_discounted(direction):
    result=wave(direction,fading=True);rising=wave(direction)
    assert result['weakening'] and abs(result['score']-50)<abs(rising['score']-50)


@pytest.mark.parametrize('mode',['histogram','waveform'])
def test_flat_wave_is_neutral_not_a_bottom_or_top(mode):
    line=pd.Series([0.0]*180)
    result=score_macd(line,line,line,100,validate_params('technical',{'macdMode':mode}))
    assert result['score']==50 and result['positionPct']==50 and result['zone']=='flat'


def test_waveform_uses_relative_position_not_absolute_macd_level():
    line=pd.Series(np.linspace(-5,5,180));hist=pd.Series([.2]*180)
    policy=validate_params('technical',{'macdMode':'waveform'})
    a=score_macd(line,line-hist,hist,100,policy)
    b=score_macd(line-100,line-100-hist,hist,100,policy)
    assert a['score']==b['score'] and a['positionPct']==b['positionPct']


def test_high_position_alone_does_not_suppress_actual_bearish_momentum():
    line=pd.Series(np.linspace(-5,5,180));hist=pd.Series([-1.0]*180)
    result=score_macd(line,line-hist,hist,100,validate_params('technical',{}))
    assert result['zone']=='high' and result['score']==15 and not result['guardApplied']


def test_short_valid_position_history_is_missing_not_zero():
    line=pd.Series(np.linspace(-5,5,80));hist=pd.Series([1.0]*80)
    result=score_macd(line,line-hist,hist,100,validate_params('technical',{'macdSlow':60,'macdSignal':20}))
    assert result['positionSamples']==2 and result['positionPct'] is None
    assert result['zone']=='insufficient' and result['score']<=65


def test_position_guard_weight_zero_is_explicitly_disclosed():
    line=pd.Series(np.linspace(-5,5,180));hist=pd.Series([1.0]*180)
    result=score_macd(line,line-hist,hist,100,validate_params('technical',{'positionWeight':0}))
    assert result['score']==result['baseScore'] and not result['guardApplied']
    assert '未啟用' in result['interpretation']


def frame(count=180):
    x=np.arange(count);close=100+x*.03+np.sin(x/8)*5
    return pd.DataFrame({'time':1735689600+x*86400,'open':close-.1,'close':close,'high':close+1,'low':close-1,'volume':1000})


def test_report_has_real_component_reasons_and_consistent_return_denominator():
    result=technical_report(frame(),symbol='0050.TW')
    assert set(result['components'])=={'harmonics','supportResistance','macd','rsi'}
    assert all('錨點內訊號評分' not in c['reason'] for c in result['components'].values())
    assert '柱差' in result['components']['macd']['reason'] and 'RSI(14)' in result['components']['rsi']['reason']
    assert result['upsidePct']==pytest.approx((result['expectedSell']/result['expectedBuy']-1)*100,abs=.001)
    assert result['downsidePct']==pytest.approx((result['downside']/result['expectedBuy']-1)*100,abs=.001)
    assert result['downsidePct']<0 and result['returnBasis']=='expected_buy'
    assert result['bullishPct']+result['bearishPct']==100
    json.dumps(result,allow_nan=False)


def test_report_excludes_future_data_even_if_caller_passes_extra_rows():
    data=frame();anchor=datetime.fromtimestamp(int(data.iloc[119].time),timezone.utc).date().isoformat()
    expected=technical_report(data.iloc[:120],symbol='0050.TW',anchor=anchor)
    data.loc[120:,['open','high','low','close']]*=100
    actual=technical_report(data,symbol='0050.TW',anchor=anchor)
    assert actual==expected


def test_equity_target_date_skips_weekend_and_discloses_calendar_limit():
    result=expected_time(0,1,'0050.TW','1d','2026-09-04')
    assert result['date']=='2026-09-07' and '休市日曆' in result['basis']
    assert expected_time(0,3,'0050.TW','1d','2026-09-01')['date']=='2026-09-04'


def test_crypto_and_intraday_target_units_are_not_stock_trading_days():
    result=expected_time(0,1,'BTC-USD','1d','2026-09-04')
    assert result['date']=='2026-09-05' and result['unit']=='日'
    result=expected_time(0,5,'0050.TW','5m','2026-09-04')
    assert result['date'] is None and result['unit']=='根 K 線'


def test_previous_policy_params_receive_position_window_default():
    assert validate_params('technical',{'macdMode':'histogram'})['macdPositionLookback']==120
    with pytest.raises(ValueError):validate_params('technical',{'macdPositionLookback':0})
