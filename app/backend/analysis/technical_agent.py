from __future__ import annotations

import math
from datetime import date, timedelta
from .engine import analyze, macd, rsi
from .pivots import atr
from .macd_context import score_macd
from ..flow.policies import validate_params
from ..services.time_boundary import candle_day


DEFAULT_WEIGHTS = {"harmonics": 25, "supportResistance": 25, "macd": 25, "rsi": 25}


def expected_time(last_time, bars, symbol, interval, anchor=None):
    base={'afterBars':bars,'date':None,'estimated':True,'unit':'根 K 線',
          'basis':'依目標根數估算；非保證達標時間，非最大持有期。'}
    if interval!='1d':return base
    day=date.fromisoformat(anchor) if anchor else candle_day(symbol,interval,last_time)
    crypto=symbol.endswith('-USD');remaining=bars
    while remaining:
        day+=timedelta(days=1)
        if crypto or day.weekday()<5:remaining-=1
    return {**base,'date':day.isoformat(),'unit':'日' if crypto else '個交易日',
        'basis':base['basis']+('依日曆日估算。' if crypto else '僅排除週末，未套用交易所休市日曆。')}


def technical_report(frame, weights: dict | None = None, params: dict | None = None, *, symbol='', interval='1d', anchor=None) -> dict:
    if anchor:
        cutoff=date.fromisoformat(anchor)
        frame=frame.loc[frame.time.map(lambda stamp:candle_day(symbol,interval,int(stamp))<=cutoff)].reset_index(drop=True)
    if len(frame) < 80:
        raise ValueError("技術 Agent 至少需要 80 根錨點前 K 線")
    policy = validate_params("technical", {**(params or {}), **({"weights": weights} if weights is not None else {})})
    weights = policy["weights"]
    total = sum(weights.values())
    result = analyze(frame)
    components = {}
    reasons = {}
    latest = result["latestPrice"]
    atr_proxy = float(atr(frame).iloc[-1])
    patterns = [p for p in result["harmonics"] if p["score"] >= policy["harmonicMinScore"]]
    pattern = patterns[0] if patterns else None
    harmonic_signal = 0
    if pattern:
        age = int((frame.time > pattern["points"][-1]["time"]).sum())
        harmonic_signal = pattern["score"] * .5 * math.pow(.5, age / policy["harmonicHalfLife"])
        harmonic_signal *= 1 if pattern["status"] == "completed" else policy["formingDiscount"]
        harmonic_signal *= 1 if pattern["direction"] == "bullish" else -1
    components["harmonics"] = 50 + harmonic_signal
    reasons['harmonics']='未找到符合門檻的型態，中性計分'
    if pattern:
        reasons['harmonics']=f'{pattern["name"]}・{"看漲" if pattern["direction"]=="bullish" else "看跌"}・型態吻合度 {pattern["score"]:.0f}%'
        reasons['harmonics']+=f'；{"已完成" if pattern["status"]=="completed" else "形成中"}，距今 {age} 根，已套用新鮮度折減'
    nearest = min(result["zones"], key=lambda z: z["distancePct"], default=None)
    distance_scale = max(policy['srPriceSpacePct'], atr_proxy/latest*100*policy['srAtrSpace']) * policy['srDistanceScale']
    space = 0 if not nearest else (nearest["strength"] / 100 if policy["srMode"] == "strength"
                                     else math.exp(-nearest["distancePct"] / distance_scale))
    components["supportResistance"] = 50 if not nearest else 50 + 30 * space * (1 if nearest["type"] == "support" else -1)
    nearby=[zone for zone in result['zones'] if zone['distancePct']<=distance_scale]
    support=min((z for z in nearby if z['type']=='support'),key=lambda z:z['distancePct'],default=None)
    resistance=min((z for z in nearby if z['type']=='resistance'),key=lambda z:z['distancePct'],default=None)
    reasons['supportResistance']='；'.join([f'近期支撐 {support["midpoint"]:.2f}' if support else '有效範圍內無支撐',
        f'近期壓力 {resistance["midpoint"]:.2f}' if resistance else '有效範圍內無壓力'])
    if nearest and nearest not in nearby:reasons['supportResistance']+='；最近區間在範圍外，僅保留距離折減後分數'
    line, signal, histogram = macd(frame.close, policy["macdFast"], policy["macdSlow"], policy["macdSignal"])
    macd_detail=score_macd(line,signal,histogram,latest,policy)
    components['macd']=macd_detail['score']
    reasons['macd']=f'MACD {macd_detail["line"]:.2f}、訊號 {macd_detail["signal"]:.2f}、柱差 {macd_detail["histogram"]:+.2f}；{macd_detail["interpretation"]}'
    rsi_value = rsi(frame.close, policy["rsiPeriod"]).iloc[-1]
    rsi_signal = (rsi_value - 50) * policy["rsiSensitivity"] * (1 if policy["rsiMode"] == "trend" else -1)
    components["rsi"] = max(10, min(90, 50 + rsi_signal))
    rsi_state='超買區' if rsi_value>=70 else '超賣區' if rsi_value<=30 else '偏高，未達超買 70' if rsi_value>=60 else '偏低，未達超賣 30' if rsi_value<=40 else '中段'
    reasons['rsi']=f'RSI({policy["rsiPeriod"]}) {rsi_value:.1f}，{rsi_state}；{"趨勢" if policy["rsiMode"]=="trend" else "均值回歸"}模式'
    bullish = sum(components[key] * weights[key] / total for key in weights)
    direction = "買進" if bullish >= 55 else "賣出" if bullish <= 45 else "觀望"
    buy=round(max(latest-atr_proxy*.35,latest*.01),4)
    sell=round(latest+atr_proxy*1.5,4)
    downside=round(max(latest-atr_proxy,latest*.001),4)
    return {"bullishPct": round(bullish, 1), "bearishPct": round(100-bullish, 1), "recommendation": direction,
            "expectedBuy": buy, "expectedSell": sell, "downside": downside, "targetBars": 5,
            "components": {key: {"score": round(value, 1), "reason": reasons[key]} for key, value in components.items()},
            "referencePrice": latest, "upsidePct": round((sell/buy-1)*100,3),
            "downsidePct": round((downside/buy-1)*100,3),'returnBasis':'expected_buy',
            "expectedTime": expected_time(int(frame.iloc[-1].time),5,symbol,interval,anchor),
            'macdContext':macd_detail,'engineVersion':'technical-2.1-position-aware',
            'priceBasis':'買入／賣出／下檔參考價依錨點收盤價與 ATR 推估；漲跌幅以預期買入價計算，未扣成本。',
            'disclaimer':'方向比例是規則加權分數，不是上漲機率或勝率。所有指標與判斷只使用時間錨定點當日及以前的 K 線資料。',
            "analysis": result, "input": {"candleCount": len(frame), "lastTime": int(frame.iloc[-1].time), "weights": weights, "params": policy}}
