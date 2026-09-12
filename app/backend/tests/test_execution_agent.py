from app.backend.analysis.execution_agent import paper_validate


def test_same_bar_target_and_stop_uses_conservative_stop():
    decision={"action":"BUY"}; future=[{"open":100,"high":112,"low":88,"close":105}]
    result=paper_validate(decision,future,target=110,stop=90,max_bars=5)
    assert result["exitReason"]=="stop" and result["exit"]==90


def test_hold_requires_both_sides_inside_threshold():
    decision={"action":"HOLD"}; quiet=[{"open":100,"high":102,"low":98,"close":101}]
    assert paper_validate(decision,quiet,0,0,1,2)["success"] is True
    assert paper_validate(decision,[{"open":100,"high":102.01,"low":99,"close":100}],0,0,1,2)["success"] is False
