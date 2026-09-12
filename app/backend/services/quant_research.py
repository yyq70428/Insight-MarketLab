from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import requests

from ..config import get_settings
from .market_data import candles, frame_from_rows, cache
from .quant import validate_frame, market_for, backtest, walk_forward


def discontinuities(frame, reference):
    """Reject incompatible price units, never smooth a genuine market crash.

    A large gap is only a screening signal. Compare identical trading dates in
    an independent full-period source before deciding which series to use.
    """
    gaps=(frame.open/frame.close.shift(1)-1).abs()>.35
    lookup=reference.set_index('time');events=[]
    for index in frame.index[gaps]:
        previous,current=frame.iloc[index-1],frame.iloc[index]
        if previous.time not in lookup.index or current.time not in lookup.index:
            raise LookupError('跨來源缺少價格斷層前後的相同交易日，暫停量化以免產生錯誤績效')
        source_move=float(current.open/previous.close)
        reference_move=float(lookup.loc[current.time,'open']/lookup.loc[previous.time,'close'])
        relative=source_move/reference_move
        events.append({'date':datetime.fromtimestamp(int(current.time),timezone.utc).date().isoformat(),
            'sourceGapPct':round((source_move-1)*100,4),'referenceGapPct':round((reference_move-1)*100,4),
            'incompatibleBasis':bool(relative<.8 or relative>1.25)})
    return events


def yahoo_data(symbol,period):
    data=candles(symbol,'1d',period)
    return validate_frame(frame_from_rows(data['candles'])),{
        'source':'Yahoo Finance','priceBasis':'Yahoo Close（拆股還原，未含股息再投資）',
        'fallback':symbol.endswith(('.TW','.TWO')),
        'sourceLimit':'績效未計入現金股息；跨來源的價格與成交量處理可能不同。'}


def research_data(symbol, period='5y'):
    settings=get_settings()
    if symbol.endswith(('.TW','.TWO')):
        try:
            start=date.today()-timedelta(days={'2y':731,'5y':1827,'10y':3653}.get(period,1827))
            def fetch():
                params={'dataset':'TaiwanStockPrice','data_id':symbol.split('.')[0],'start_date':start.isoformat(),'end_date':date.today().isoformat()}
                if settings.finmind_token: params['token']=settings.finmind_token
                response=requests.get('https://api.finmindtrade.com/api/v4/data',params=params,timeout=settings.upstream_timeout)
                response.raise_for_status();data=response.json()
                if data.get('status')!=200 or not data.get('data'):raise ValueError('FinMind 無可用資料')
                frame=pd.DataFrame(data['data']).rename(columns={'max':'high','min':'low','Trading_Volume':'volume'})
                frame['time']=pd.to_datetime(frame['date'],utc=True).astype('int64')//10**9
                frame=frame[['time','open','high','low','close','volume']].apply(pd.to_numeric)
                return validate_frame(frame.sort_values('time')).to_dict('records')
            rows=cache.get(f'quant-finmind:{symbol}:{period}',settings.daily_cache_ttl,fetch)
        except (requests.RequestException,ValueError,KeyError,TypeError): pass
        else:
            frame=validate_frame(frame_from_rows(rows))
            events=[]
            if ((frame.open/frame.close.shift(1)-1).abs()>.35).any():
                reference,metadata=yahoo_data(symbol,period)
                events=discontinuities(frame,reference)
                if any(event['incompatibleBasis'] for event in events):
                    # Replace the entire period, never stitch or guess a split factor.
                    reference=reference.loc[reference.time.between(frame.iloc[0].time,frame.iloc[-1].time)].reset_index(drop=True)
                    matched=set(reference.time)&set(frame.time)
                    if len(matched)/len(frame)<.95:
                        raise LookupError('替代行情涵蓋不足原研究交易日的 95%，暫停量化')
                    iso=lambda stamp:datetime.fromtimestamp(int(stamp),timezone.utc).date().isoformat()
                    coverage={'sourceStart':iso(frame.iloc[0].time),'sourceEnd':iso(frame.iloc[-1].time),
                        'usedStart':iso(reference.iloc[0].time),'usedEnd':iso(reference.iloc[-1].time),
                        'missingSourceDays':len(frame)-len(matched)}
                    return reference,{**metadata,'fallbackReason':'FinMind 出現跨來源確認的價格基準斷層，整段改用 Yahoo；不把拆股價差算成交易損失。',
                        'qualityChecks':{'status':'source_replaced','rejectedSource':'FinMind','events':events,'coverage':coverage}}
            return frame,{'source':'FinMind','priceBasis':'來源日價（未含股息再投資）','fallback':False,
                'qualityChecks':{'status':'screened','events':events},
                'sourceLimit':'已檢查大幅跨日斷層；未提供完整公司行動總報酬還原。'}
    frame,metadata=yahoo_data(symbol,period)
    if metadata['fallback']:metadata['fallbackReason']='FinMind 無法提供通過欄位驗證的資料，整段改用 Yahoo。'
    return frame,metadata


def research(symbol, strategy='ma', period='5y'):
    frame,metadata=research_data(symbol,period)
    market=market_for(symbol);rolling=walk_forward(frame,strategy,market)
    result=rolling['result'] if rolling['status']=='completed' else backtest(frame,strategy,{'market':market})
    return {'symbol':symbol,'strategy':strategy,'market':market,'range':period,**metadata,'result':result,'walkForward':rolling,
        'generatedAt':datetime.now(timezone.utc).isoformat(),'candleCount':len(frame),'lastTime':int(frame.iloc[-1].time),
        'disclaimer':'歷史模擬不代表未來績效；交易次數不足時不可做顯著性推論。'}


def main():
    from ..validators import normalize_symbol
    parser=argparse.ArgumentParser(description='Generate reproducible offline research snapshots (no trading).')
    parser.add_argument('--symbols',nargs='+',default=['0050.TW','AAPL','BTC-USD'])
    parser.add_argument('--range',default='5y',choices=['2y','5y','10y'])
    parser.add_argument('--output',default='quant/results')
    args=parser.parse_args();directory=Path(args.output);directory.mkdir(parents=True,exist_ok=True)
    for symbol in args.symbols:
        symbol=normalize_symbol(symbol)
        for strategy in ('ma','rsi','bollinger'):
            result=research(symbol,strategy,args.range)
            destination=directory/f'{symbol}-{strategy}-{date.today().isoformat()}.json'
            destination.write_text(json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
            print(f'{symbol} {strategy}: {result["walkForward"]["status"]} -> {destination}',flush=True)


if __name__=='__main__':main()
