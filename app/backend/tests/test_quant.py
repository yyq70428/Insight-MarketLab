import pandas as pd
from app.backend.services.quant import backtest


def test_quant_signal_executes_without_future_data():
    rows=[]
    for i in range(160):
        price=100+i*.2
        rows.append({"time":i,"open":price,"high":price+1,"low":price-1,"close":price+.1,"volume":100})
    result=backtest(pd.DataFrame(rows),"ma",{"fast":5,"slow":20,"market":"US"})
    assert result["trades"]==1
    assert len(result["equity"])==160
    assert result["maxDrawdownPct"]<=0
