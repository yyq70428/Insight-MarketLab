"""Position is a chasing-risk modifier, not an overbought/oversold oracle."""
import math


def score_macd(line, signal, histogram, latest, policy):
    scale=max(abs(float(latest))*.002,.0001)
    lookback=policy['macdLookback']
    # Discard EMA initialization before locating this value in its trailing range.
    warmup=policy['macdSlow']+policy['macdSignal']-2
    window=line.iloc[warmup:].tail(policy['macdPositionLookback'])
    low,high=float(window.min()),float(window.max())
    current,sig,hist=map(float,(line.iloc[-1],signal.iloc[-1],histogram.iloc[-1]))
    span=high-low
    flat=span<=scale*1e-8
    sufficient=len(window)>=20
    position=50.0 if flat else max(0.0,min(100.0,(current-low)/span*100))
    slope=float(line.iloc[-1]-line.iloc[-lookback])/(lookback-1)
    hist_slope=float(histogram.iloc[-1]-histogram.iloc[-lookback])/(lookback-1)
    momentum=hist/scale
    if policy['macdMode']=='waveform':
        weight=policy['slopeWeight']
        momentum=momentum*(1-weight)+slope/scale*weight
    offset=max(-35.0,min(35.0,momentum*10))
    base=50+offset
    zone='insufficient' if not sufficient else 'flat' if flat else 'high' if position>=80 else 'low' if position<=20 else 'middle'
    guarded=(zone=='high' and offset>0) or (zone=='low' and offset<0)
    weakening=(offset>0 and (slope<0 or hist_slope<0)) or (offset<0 and (slope>0 or hist_slope>0))
    if guarded:
        offset*=1-policy['positionWeight']
        if weakening:offset*=1-policy['positionWeight']
    if not sufficient:offset=max(-15.0,min(15.0,offset))
    guard_applied=bool(guarded and policy['positionWeight']>0)
    motion='走平' if math.isclose(slope,0,abs_tol=scale*1e-8) else '回升' if slope>0 else '回落'
    labels={'high':'高位','low':'低位','middle':'中段','flat':'波形平坦','insufficient':'位置樣本不足；'}
    interpretation=f'{labels[zone]}{motion}'
    if guard_applied:
        interpretation+='，已降低追高評分' if zone=='high' else '，已降低追空評分'
        if weakening:interpretation+='；動能減弱，再降低方向強度'
    elif guarded:interpretation+='；位置折減已設為 0，未啟用追價防護'
    else:interpretation+='，仍需其他指標確認'
    return {'line':current,'signal':sig,'histogram':hist,'slope':slope,'histogramSlope':hist_slope,
        'positionPct':round(position,1) if sufficient else None,'positionLow':low,'positionHigh':high,'positionSamples':len(window),'positionSufficient':sufficient,
        'positionLookback':policy['macdPositionLookback'],'slopeLookback':lookback,
        'fast':policy['macdFast'],'slow':policy['macdSlow'],'signalPeriod':policy['macdSignal'],
        'mode':policy['macdMode'],'zone':zone,'baseScore':round(base,1),'score':round(50+offset,1),
        'positionWeight':policy['positionWeight'],'guardApplied':guard_applied,'weakening':bool(weakening),
        'interpretation':interpretation,'riskNote':'低位不代表已落底，高位不代表已見頂；相對位置不是反轉保證。'}
