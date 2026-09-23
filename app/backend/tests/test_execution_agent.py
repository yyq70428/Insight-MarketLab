import pytest

from app.backend.analysis.execution_agent import paper_validate, rebase_targets


def test_same_bar_target_and_stop_uses_conservative_stop():
    decision={"action":"BUY"}; future=[{"open":100,"high":112,"low":88,"close":105}]
    result=paper_validate(decision,future,target=110,stop=90,max_bars=5)
    assert result["exitReason"]=="stop" and result["exit"]==90


def test_hold_requires_both_sides_inside_threshold():
    decision={"action":"HOLD"}; quiet=[{"open":100,"high":102,"low":98,"close":101}]
    assert paper_validate(decision,quiet,0,0,1,2)["success"] is True
    assert paper_validate(decision,[{"open":100,"high":102.01,"low":99,"close":100}],0,0,1,2)["success"] is False


def test_favourable_gap_no_longer_eats_the_planned_edge():
    """Reproduces the 2379.TW SELL: anchor close 863, ATR 49.39, fill gapped down to 821."""
    decision={"action":"SELL"}; future=[{"open":821,"high":825,"low":760,"close":770}]
    old=paper_validate(decision,future,target=813.61,stop=937.085,max_bars=5,basis="anchor_close")
    new=paper_validate(decision,future,target=813.61,stop=937.085,max_bars=5,reference=863)
    assert old["exitReason"]=="target" and round(old["netReturnPct"],2)==0.70
    # The gap moved both legs down with it, so the full one-ATR target survives the fill.
    assert new["target"]==pytest.approx(771.61,abs=.01) and new["stop"]==pytest.approx(895.085,abs=.01)
    assert new["netReturnPct"]>5 and new["entryShift"]==pytest.approx(-42,abs=.01)


@pytest.mark.parametrize("action,reference,entry",[("BUY",100,104),("BUY",100,96),("SELL",100,104),("SELL",100,96)])
def test_rebasing_preserves_the_planned_distance_in_both_directions(action,reference,entry):
    planned_target,planned_stop=(110,95) if action=="BUY" else (90,105)
    rebased=rebase_targets(entry,planned_target,planned_stop,reference)
    assert rebased["target"]-entry==pytest.approx(planned_target-reference)
    assert rebased["stop"]-entry==pytest.approx(planned_stop-reference)


def test_anchor_close_basis_and_missing_reference_keep_the_old_numbers():
    for kwargs in ({"basis":"anchor_close","reference":100},{"reference":None}):
        rebased=rebase_targets(104,110,95,**kwargs)
        assert rebased["target"]==110 and rebased["stop"]==95 and rebased["basis"]=="anchor_close"


def test_hold_ignores_targets_so_rebasing_cannot_change_its_verdict():
    quiet=[{"open":100,"high":102,"low":98,"close":101}]
    assert paper_validate({"action":"HOLD"},quiet,0,0,1,2,reference=95)["success"] is True
