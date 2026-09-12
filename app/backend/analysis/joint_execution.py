from .execution_agent import decide


def joint_decision(technical: dict, news: dict, params: dict | None = None):
    params = params or {}
    return decide(technical, news, params.get("technicalWeight", .5), params.get("minConfidence", 52))
