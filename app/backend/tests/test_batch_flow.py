from app.backend.flow.runtime import can_enter


def test_next_stage_is_strictly_ordered():
    statuses={"technical":"completed","news":"running"}
    assert not can_enter("execution",statuses)
    statuses["news"]="completed"
    assert can_enter("execution",statuses)
    assert not can_enter("adaptive",statuses)


def test_adaptive_only_after_execution():
    assert can_enter("adaptive",{"execution":"completed"})
