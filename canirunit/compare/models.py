from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from canirunit.parsing.schemas import GameDetails
from canirunit.settings.models import SettingsRecommendation


class Verdict(StrEnum):
    BELOW_MIN = "BELOW_MIN"
    MEETS_MIN = "MEETS_MIN"
    MEETS_RECOMMENDED = "MEETS_RECOMMENDED"
    EXCEEDS_RECOMMENDED = "EXCEEDS_RECOMMENDED"
    UNKNOWN = "UNKNOWN"


VERDICT_ICON = {
    Verdict.BELOW_MIN: "❌",
    Verdict.MEETS_MIN: "⚠️",
    Verdict.MEETS_RECOMMENDED: "✅",
    Verdict.EXCEEDS_RECOMMENDED: "🚀",
    Verdict.UNKNOWN: "❔",
}
VERDICT_RANK = {
    Verdict.BELOW_MIN: 0,
    Verdict.MEETS_MIN: 1,
    Verdict.MEETS_RECOMMENDED: 2,
    Verdict.EXCEEDS_RECOMMENDED: 3,
}


class Confidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


CONFIDENCE_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


class Recommendation(StrEnum):
    BUY = "BUY"
    BUY_WITH_COMPROMISES = "BUY_WITH_COMPROMISES"
    RISKY = "RISKY"
    DONT_BUY = "DONT_BUY"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


RECOMMENDATION_TEXT = {
    Recommendation.BUY: "Buy — runs well",
    Recommendation.BUY_WITH_COMPROMISES: "Buy with compromises",
    Recommendation.RISKY: "Risky",
    Recommendation.DONT_BUY: "Don't buy",
    Recommendation.INSUFFICIENT_DATA: "Can't tell — not enough data",
}


class PerformanceScore(BaseModel):
    """A relative performance number on a named, consistent benchmark scale."""

    score: float | None = None
    benchmark: str = ""
    confidence: Confidence = Confidence.LOW
    matched_name: str | None = None
    notes: str | None = None


class RowResult(BaseModel):
    key: Literal["cpu", "gpu", "ram", "vram", "storage", "os", "directx"]
    label: str
    yours: str
    minimum: str | None = None
    recommended: str | None = None
    verdict: Verdict
    confidence: Confidence = Confidence.HIGH
    note: str | None = None
    your_score: float | None = None
    min_score: float | None = None
    rec_score: float | None = None
    benchmark: str | None = None
    specified: bool = True  # False when the publisher lists no requirement for this row

    @computed_field  # type: ignore[prop-decorator]
    @property
    def icon(self) -> str:
        return VERDICT_ICON[self.verdict]


class Report(BaseModel):
    game: GameDetails
    rows: list[RowResult]
    overall_verdict: Verdict
    recommendation: Recommendation
    headline: str
    reasons: list[str] = Field(default_factory=list)
    confidence: Confidence
    bottleneck: str | None = None
    warnings: list[str] = Field(default_factory=list)
    settings: SettingsRecommendation | None = None
