"""Deterministic source-assessment recommendation policy."""

from dataclasses import dataclass
from typing import Literal

Recommendation = Literal["APPROVED", "CONDITIONAL", "REJECTED"]
WEIGHTS = {
    "relevance": 25,
    "joinability": 25,
    "accessibility": 20,
    "documentation": 15,
    "quality": 15,
}


@dataclass(frozen=True)
class Assessment:
    relevance: float
    joinability: float
    accessibility: float
    documentation: float
    quality: float

    @property
    def score(self) -> float:
        values = vars(self)
        return float(sum(float(values[name]) * weight / 100 for name, weight in WEIGHTS.items()))

    @property
    def recommendation(self) -> Recommendation:
        if self.score >= 70:
            return "APPROVED"
        if self.score >= 50:
            return "CONDITIONAL"
        return "REJECTED"
