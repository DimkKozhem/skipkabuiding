"""Plan/fact facade — delegates to DeviationEngine. Never receives raw frames."""

from __future__ import annotations

from sitewatch.deviation.engine import DeviationEngine
from sitewatch.domain.contracts import ActualState, DeviationCandidate, EvidenceRef, ExpectedState


class PlanFactEngine:
    """Compares ActualState with PlannedState/ExpectedState only."""

    def __init__(self, deviation: DeviationEngine | None = None) -> None:
        self._deviation = deviation or DeviationEngine()

    def evaluate(
        self,
        expected: ExpectedState,
        actual: ActualState,
        history: list[ActualState] | None = None,
        expected_series: list[ExpectedState] | None = None,
        evidence: list[EvidenceRef] | None = None,
        visual_changes: list[float | None] | None = None,
    ) -> list[DeviationCandidate]:
        return self._deviation.evaluate(
            expected,
            actual,
            history=history,
            expected_series=expected_series,
            evidence=evidence,
            visual_changes=visual_changes,
        )
