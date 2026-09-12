from __future__ import annotations

from itertools import product
import numpy as np
import pandas as pd
from ..analysis.engine import rsi

MARKET_COSTS = {
    "TW": {"buy": .001425, "sell": .001425, "tax": .003, "slippage": .001, "periods": 252},
    "US": {"buy": 0, "sell": 0, "tax": 0, "slippage": .0005, "periods": 252},
    "CRYPTO": {"buy": .001, "sell": .001, "tax": 0, "slippage": .001, "periods": 365},
}


def market_for(symbol):
    return "TW" if symbol.endswith((".TW", ".TWO")) else "CRYPTO" if symbol.endswith("-USD") else "US"


def validate_frame(frame):
    frame = frame.reset_index(drop=True).copy()
    if len(frame) < 2: raise ValueError('至少需要兩根行情')
    required = ['time','open','high','low','close','volume']
    if any(k not in frame for k in required): raise ValueError('行情欄位不完整')
    values = frame[required].to_numpy(dtype=float)
    if not np.isfinite(values).all() or not frame.time.is_monotonic_increasing or frame.time.duplicated().any():
        raise ValueError('行情必須有限、時間升冪且不重複')
    if (frame[['open','high','low','close']] <= 0).any().any() or (frame.volume < 0).any():
        raise ValueError('行情價格與成交量無效')
    if (frame.high < frame[['open','close','low']].max(axis=1)).any() or (frame.low > frame[['open','close','high']].min(axis=1)).any():
        raise ValueError('開收價格超出高低範圍')
    return frame


def signals(frame, strategy, params):
    close = frame.close
    if strategy == 'buy_hold': return pd.Series(1.,index=frame.index)
    if strategy == 'rsi':
        value=rsi(close,params.get('period',14))
        entry=value < params.get('lower',30); leave=value > params.get('upper',70)
        result=pd.Series(np.nan,index=frame.index); result[leave]=0;result[entry]=1
        result.iloc[:params.get('period',14)]=np.nan
        return result.ffill().fillna(0)
    if strategy == 'bollinger':
        period=params.get('period',20);mid=close.rolling(period).mean()
        upper=mid+close.rolling(period).std()*params.get('std',2)
        result=pd.Series(np.nan,index=frame.index);result[close<mid]=0;result[close>upper]=1
        return result.ffill().fillna(0)
    if strategy != 'ma': raise ValueError('未知策略')
    return (close.rolling(params.get('fast',20)).mean()>close.rolling(params.get('slow',60)).mean()).astype(float)


def metrics(equity_values,times,trade_returns,periods):
    equity=np.asarray(equity_values,dtype=float)
    daily=equity/np.r_[1.,equity[:-1]]-1
    peak=np.maximum.accumulate(np.r_[1.,equity])[1:];drawdown=equity/peak-1
    std=float(np.std(daily,ddof=1)) if len(daily)>1 else 0
    return {'totalReturnPct':round((equity[-1]-1)*100,3),
            'annualReturnPct':round((equity[-1]**(periods/len(equity))-1)*100,3),
            'sharpe':round(float(float(np.mean(daily))/std*np.sqrt(periods)),3) if std>0 else 0,
            'maxDrawdownPct':round(float(drawdown.min())*100,3),'trades':len(trade_returns),
            'winRatePct':round(sum(v>0 for v in trade_returns)/len(trade_returns)*100,2) if trade_returns else 0,
            'insufficientSamples':len(trade_returns)<30,
            'equity':[{'time':int(t),'value':round(float(v),8)} for t,v in zip(times,equity)],
            'dailyReturns':[{'time':int(t),'value':float(v)} for t,v in zip(times,daily)]}


def backtest(frame, strategy='ma', params=None, evaluation_start=0):
    params=params or {}; frame=validate_frame(frame)
    if evaluation_start<0 or evaluation_start>=len(frame):raise ValueError('驗證起點無效')
    desired=signals(frame,strategy,params).shift(1).fillna(0).to_numpy()
    # A buy-and-hold benchmark buys at the first evaluation open without a signal.
    if strategy=='buy_hold':desired[:]=1
    costs=MARKET_COSTS[params.get('market','US')]
    cash,shares,entry_cost,entry_time=1.,0.,None,None
    equity,returns,trades=[],[],[]
    rows=frame[['time','open','close']].to_numpy()
    for index in range(evaluation_start,len(frame)):
        stamp,opening,closing=rows[index]
        if desired[index] and not shares:
            entry_cost=opening*(1+costs['slippage']+costs['buy']);shares=cash/entry_cost;cash=0.;entry_time=int(stamp)
        elif not desired[index] and shares:
            received=opening*(1-costs['slippage']-costs['sell']-costs['tax']);cash=shares*received;shares=0.
            net=received/entry_cost-1;returns.append(net)
            trades.append({'entryTime':entry_time,'exitTime':int(stamp),'entry':entry_cost,'exit':received,'netReturnPct':net*100})
        equity.append(cash+shares*closing)
    if shares:
        received=rows[-1,2]*(1-costs['slippage']-costs['sell']-costs['tax']);equity[-1]=shares*received
        net=received/entry_cost-1;returns.append(net)
        trades.append({'entryTime':entry_time,'exitTime':int(rows[-1,0]),'entry':entry_cost,'exit':received,'netReturnPct':net*100,'forcedClose':True})
    result=metrics(equity,rows[evaluation_start:,0],returns,costs['periods'])
    return {**result,'tradeLog':trades,'costs':costs,'params':params,'strategy':strategy}


def candidates(strategy):
    if strategy=='ma':return [{'fast':f,'slow':s} for f,s in product([16,20,24],[48,60,72])]
    if strategy=='rsi':return [{'period':p,'lower':lo,'upper':100-lo} for p,lo in product([11,14,17],[24,30,36])]
    return [{'period':p,'std':v} for p,v in product([16,20,24],[1.6,2,2.4])]


def walk_forward(frame,strategy,market):
    frame=validate_frame(frame)
    dates=pd.to_datetime(frame.time,unit='s',utc=True)
    validation_start=dates.iloc[0]+pd.DateOffset(years=2)
    windows=[];equity=[];trade_returns=[];last_equity=1.;last_params=None;last_train=None;last_slice=None;warmup=0
    while validation_start+pd.DateOffset(months=6)<=dates.iloc[-1]+pd.Timedelta(days=1):
        validation_end=validation_start+pd.DateOffset(months=6)
        training_start=validation_start-pd.DateOffset(years=2)
        train=frame.loc[(dates>=training_start)&(dates<validation_start)].reset_index(drop=True)
        indexes=np.flatnonzero((dates>=validation_start)&(dates<validation_end))
        if len(train)<100 or len(indexes)<20:validation_start=validation_end;continue
        trials=[(p,backtest(train,strategy,{**p,'market':market})) for p in candidates(strategy)]
        selected,training=max(trials,key=lambda value:value[1]['sharpe'])
        segment=frame.loc[(dates>=training_start)&(dates<validation_end)].reset_index(drop=True)
        count=len(segment)-len(indexes);result=backtest(segment,strategy,{**selected,'market':market},count)
        equity.extend({'time':r['time'],'value':r['value']*last_equity} for r in result['equity'])
        last_equity=equity[-1]['value'];trade_returns.extend(t['netReturnPct']/100 for t in result['tradeLog'])
        windows.append({'trainStart':training_start.isoformat(),'trainEndExclusive':validation_start.isoformat(),
            'validationStart':validation_start.isoformat(),'validationEndExclusive':validation_end.isoformat(),
            'firstTime':int(frame.iloc[indexes[0]].time),'lastTime':int(frame.iloc[indexes[-1]].time),
            'params':selected,'trainSharpe':training['sharpe'],'validationSharpe':result['sharpe'],
            'returnPct':result['totalReturnPct'],'trades':result['trades']})
        last_params,last_train,last_slice,warmup=selected,training,segment,count
        validation_start=validation_end
    if not windows:
        return {'status':'insufficient_history','windows':[],'message':'需至少兩年訓練資料與六個月完整驗證資料；未以一次回測冒充滾動驗證'}
    assert all(a['lastTime']<b['firstTime'] for a,b in zip(windows,windows[1:]))
    result=metrics([r['value'] for r in equity],[r['time'] for r in equity],trade_returns,MARKET_COSTS[market]['periods'])
    benchmark_frame=frame[(frame.time>=equity[0]['time'])&(frame.time<=equity[-1]['time'])].reset_index(drop=True)
    benchmark=backtest(benchmark_frame,'buy_hold',{'market':market})
    train_sharpe=sum(w['trainSharpe'] for w in windows)/len(windows)
    perturbations=[]
    keys=list(last_params)
    choices=[[max(2,round(last_params[k]*factor)) if isinstance(last_params[k],int) else round(last_params[k]*factor,3) for factor in (.8,1,1.2)] for k in keys]
    reference=backtest(last_slice,strategy,{**last_params,'market':market},warmup)
    for values in product(*choices):
        params=dict(zip(keys,values))
        if strategy=='ma' and params['fast']>=params['slow']:continue
        if strategy=='rsi' and not 0<params['lower']<params['upper']<100:continue
        tested=backtest(last_slice,strategy,{**params,'market':market},warmup)
        perturbations.append({'params':params,'returnPct':tested['totalReturnPct'],'differencePct':round(tested['totalReturnPct']-reference['totalReturnPct'],3)})
    return {'status':'completed','result':result,'windows':windows,'benchmark':benchmark,'trainSharpe':round(train_sharpe,3),
        'overfitRisk':bool(train_sharpe>0 and result['sharpe']<train_sharpe*.5),
        'robustness':{'selectedOn':'last_training_window','bestParams':last_params,'referenceReturnPct':reference['totalReturnPct'],
            'perturbations':perturbations,'robust':all(p['differencePct']>=-5 for p in perturbations),
            'criterion':'所有 ±20% 組合於最後驗證窗相對報酬下降不超過 5 個百分點'},
        'limitations':['每個驗證視窗末強制平倉並計入成本；同期間買入持有不重新進出。',
                        '擾動測試僅為敏感度檢查，不能保證未来績效。']}
