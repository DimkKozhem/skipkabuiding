from __future__ import annotations

from sitewatch.domain.contracts import ObservationQuality
from sitewatch.domain.enums import CoverageLevel, Visibility
from sitewatch.settings import load_yaml


def evidence_confidence(quality: ObservationQuality, thresholds: dict | None = None) -> float:
    cfg = (thresholds or load_yaml("thresholds.yaml")).get("evidence", {})
    score = 1.0
    if quality.n_frames < int(cfg.get("min_observations", 2)):
        score -= 0.25
    if quality.visibility == Visibility.DEGRADED:
        score -= float(cfg.get("poor_visibility_penalty", 0.35)) * 0.6
    if quality.visibility == Visibility.POOR:
        score -= float(cfg.get("poor_visibility_penalty", 0.35))
    if quality.coverage != CoverageLevel.FULL:
        score -= float(cfg.get("incomplete_coverage_penalty", 0.40))
    if quality.mean_model_confidence < 0.5:
        score -= float(cfg.get("low_model_conf_penalty", 0.25))
    return max(0.0, min(1.0, round(score, 4)))


def sufficient_for_positive(quality: ObservationQuality, thresholds: dict | None = None) -> bool:
    """What is visible can be used even from a single clear frame."""
    cfg = (thresholds or load_yaml("thresholds.yaml")).get("evidence", {})
    conf = quality.evidence_confidence or evidence_confidence(quality, thresholds)
    return quality.visibility != Visibility.POOR and conf >= float(cfg.get("min_evidence_confidence", 0.45)) * 0.6


def sufficient_for_absence(quality: ObservationQuality, thresholds: dict | None = None) -> bool:
    """Absence is not proven by a missed detection on one frame."""
    cfg = (thresholds or load_yaml("thresholds.yaml")).get("evidence", {})
    conf = quality.evidence_confidence or evidence_confidence(quality, thresholds)
    return (
        quality.n_frames >= int(cfg.get("min_observations", 2))
        and conf >= float(cfg.get("min_evidence_confidence", 0.45))
        and quality.visibility != Visibility.POOR
        and quality.coverage == CoverageLevel.FULL
    )


def sufficient_evidence(quality: ObservationQuality, thresholds: dict | None = None) -> bool:
    return sufficient_for_absence(quality, thresholds)
