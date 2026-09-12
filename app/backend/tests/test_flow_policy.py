import pytest
import pandas as pd
from app.backend.analysis.technical_agent import technical_report


def frame(count=90):
    rows=[]
    for i in range(count): rows.append({"time":i,"open":100+i*.1,"high":101+i*.1,"low":99+i*.1,"close":100+i*.1,"volume":1000})
    return pd.DataFrame(rows)


def test_technical_agent_requires_80_candles():
    with pytest.raises(ValueError, match="80"): technical_report(frame(79))


def test_all_zero_weights_are_rejected():
    with pytest.raises(ValueError, match="全部為零"):
        technical_report(frame(), {"harmonics":0,"supportResistance":0,"macd":0,"rsi":0})


def test_weights_are_normalized():
    result=technical_report(frame(), {"harmonics":100,"supportResistance":100,"macd":100,"rsi":100})
    assert round(result["bullishPct"]+result["bearishPct"], 5)==100
