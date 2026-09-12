import numpy as np
import pandas as pd
import pytest
import json
from app.backend.services.quant import backtest,walk_forward,validate_frame


def frame(count=1500):
    index=np.arange(count);close=100+index*.025+np.sin(index/13)*7
    return pd.DataFrame({'time':1577836800+index*86400,'open':close-.2,'high':close+1,'low':close-1,'close':close,'volume':100})


def test_next_open_and_costs_independently():
    data=frame(100)
    r=backtest(data,'ma',{'fast':3,'slow':5,'market':'TW'})
    first=r['tradeLog'][0]
    assert first['entryTime']==data.iloc[5].time
    expected=data.iloc[5].open*(1+.001+.001425)
    assert first['entry']==pytest.approx(expected)
    assert len(r['dailyReturns'])==100


def test_no_future_perturbation_changes_past_equity():
    data=frame(160);original=backtest(data,'ma',{'fast':5,'slow':20})
    data.loc[100:,['open','high','low','close']]*=10
    changed=backtest(data,'ma',{'fast':5,'slow':20})
    assert original['equity'][:100]==changed['equity'][:100]


def test_buy_hold_keeps_first_entry_cost_in_total_return():
    data=pd.DataFrame({'time':[1,2],'open':[100,100],'high':[100,100],'low':[100,100],'close':[100,100],'volume':[1,1]})
    r=backtest(data,'buy_hold',{'market':'TW'})
    expected=((1-.001-.001425-.003)/(1+.001+.001425)-1)*100
    assert r['totalReturnPct']==pytest.approx(expected,abs=.001)
    assert r['maxDrawdownPct']<0


def test_windows_are_nonoverlapping_parameters_only_selected_on_training():
    data=frame();result=walk_forward(data,'ma','US')
    assert result['status']=='completed'
    windows=result['windows'];assert len(windows)>=3
    assert all(a['lastTime']<b['firstTime'] for a,b in zip(windows,windows[1:]))
    assert len({r['time'] for r in result['result']['equity']})==len(result['result']['equity'])
    assert result['benchmark']['equity'][0]['time']==result['result']['equity'][0]['time']
    changed=data.copy();changed.loc[1000:,['open','high','low','close']]*=2
    other=walk_forward(changed,'ma','US')
    assert windows[0]==other['windows'][0]
    assert len(result['robustness']['perturbations'])==9
    json.dumps(result,allow_nan=False)


def test_short_history_does_not_claim_walkforward_complete():
    result=walk_forward(frame(300),'rsi','TW')
    assert result['status']=='insufficient_history' and result['windows']==[]


def test_duplicate_and_bad_ohlc_are_rejected():
    data=frame(100);data.loc[2,'time']=data.loc[1,'time']
    with pytest.raises(ValueError):validate_frame(data)
    data=frame(100);data.loc[0,'high']=0
    with pytest.raises(ValueError):validate_frame(data)
