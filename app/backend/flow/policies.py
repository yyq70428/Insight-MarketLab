from __future__ import annotations

from copy import deepcopy
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Weights(StrictPolicy):
    harmonics: float = Field(25, ge=0, le=100)
    supportResistance: float = Field(25, ge=0, le=100)
    macd: float = Field(25, ge=0, le=100)
    rsi: float = Field(25, ge=0, le=100)

    @model_validator(mode="after")
    def nonzero(self):
        if not sum(self.model_dump().values()):
            raise ValueError("技術權重不可全部為零")
        return self


class TechnicalPolicy(StrictPolicy):
    weights: Weights = Field(default_factory=Weights)
    macdMode: Literal["histogram", "waveform"] = "histogram"
    macdFast: int = Field(12, ge=5, le=20)
    macdSlow: int = Field(26, ge=21, le=60)
    macdSignal: int = Field(9, ge=3, le=20)
    macdLookback: int = Field(5, ge=2, le=30)
    macdPositionLookback: int = Field(120, ge=30, le=250)
    slopeWeight: float = Field(.5, ge=0, le=1)
    positionWeight: float = Field(.5, ge=0, le=1)
    rsiMode: Literal["mean_reversion", "trend"] = "mean_reversion"
    rsiPeriod: int = Field(14, ge=7, le=28)
    rsiSensitivity: float = Field(1, ge=.1, le=3)
    harmonicMinScore: float = Field(0, ge=0, le=100)
    formingDiscount: float = Field(.75, ge=0, le=1)
    harmonicHalfLife: int = Field(60, ge=5, le=250)
    srMode: Literal["distance", "strength"] = "distance"
    srDistanceScale: float = Field(3, ge=.1, le=20)
    srAtrSpace: float = Field(1, ge=.1, le=10)
    srPriceSpacePct: float = Field(.5, ge=.1, le=10)


class NewsPolicy(StrictPolicy):
    lookbackDays: int = Field(30, ge=7, le=90)
    rounds: int = Field(3, ge=3, le=5)
    stockWeight: float = Field(.6, ge=.2, le=.9)
    minRelevance: float = Field(0, ge=0, le=1)
    inferenceBias: Literal["balanced", "conservative"] = "balanced"


class ExecutionPolicy(StrictPolicy):
    # Baseline weighting favours the price-derived report.  Strong, well-covered
    # news can move part of that weight into the news report at decision time.
    technicalWeight: float = Field(.65, ge=0, le=1)
    dynamicNewsWeight: bool = True
    newsEventThreshold: float = Field(.20, ge=.05, le=.45)
    newsEventCoverage: float = Field(.70, ge=0, le=1)
    newsEventBoost: float = Field(.15, ge=0, le=.30)
    minConfidence: float = Field(52, ge=0, le=100)
    maxHoldingBars: int = Field(5, ge=1, le=7)
    holdThresholdPct: float = Field(2, ge=.1, le=20)


class AdaptivePolicy(StrictPolicy):
    minShadowSessions: int = Field(8, ge=8, le=100)
    minImprovementPct: float = Field(.1, ge=.1, le=20)
    faithfulnessThreshold: float = Field(.8, ge=0, le=1)
    maxCandidatesPerAgent: int = Field(2, ge=1, le=5)
    rejectAfterShadowSessions: int = Field(4, ge=1, le=20)

POLICY_SCHEMA = {
    "technical.weights.*": [0, 100], "technical.macdFast": [5, 20], "technical.macdSlow": [21, 60],
    "technical.macdSignal": [3, 20], "technical.rsiPeriod": [7, 28], "technical.formingDiscount": [0, 1],
    "news.lookbackDays": [7, 90], "news.rounds": [3, 5], "news.stockWeight": [.2, .9],
    "execution.technicalWeight": [0, 1], "execution.newsEventThreshold": [.05, .45],
    "execution.newsEventCoverage": [0, 1], "execution.newsEventBoost": [0, .30],
    "execution.minConfidence": [0, 100],
    "execution.maxHoldingBars": [1, 7], "execution.holdThresholdPct": [.1, 20],
    "adaptive.minShadowSessions": [8, 100], "adaptive.minImprovementPct": [.1, 20],
    "adaptive.maxCandidatesPerAgent": [1, 5], "adaptive.rejectAfterShadowSessions": [1, 20],
}

POLICY_MODELS = {"technical": TechnicalPolicy, "news": NewsPolicy, "execution": ExecutionPolicy, "adaptive": AdaptivePolicy}
DEFAULT_POLICIES = {agent: model().model_dump() for agent, model in POLICY_MODELS.items()}


def merge_params(base: dict, overrides: dict) -> dict:
    result = deepcopy(base)
    for key, value in overrides.items():
        result[key] = merge_params(result.get(key, {}), value) if isinstance(value, dict) else value
    return result


def validate_params(agent: str, params: dict, base: dict | None = None) -> dict:
    if agent not in POLICY_MODELS:
        raise ValueError("未知 Agent")
    if not isinstance(params, dict): raise ValueError('Agent 參數必須為物件')
    return POLICY_MODELS[agent].model_validate(merge_params(base or DEFAULT_POLICIES[agent], params)).model_dump()


def validate_overrides(params: dict) -> dict:
    for agent, values in params.items():
        validate_params(agent, values)
    return params
