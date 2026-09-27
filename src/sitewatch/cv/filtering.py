from __future__ import annotations

from sitewatch.domain.contracts import Detection
from sitewatch.settings import load_yaml


def min_detection_confidence(thresholds: dict | None = None) -> float:
    cfg = (thresholds or load_yaml("thresholds.yaml")).get("detection", {})
    return float(cfg.get("min_confidence", 0.35))


def filter_detections(
    detections: list[Detection],
    min_confidence: float | None = None,
    thresholds: dict | None = None,
) -> list[Detection]:
    """Drop low-confidence boxes before Observation / ActualState aggregation.

    Detectors emit raw Detection objects. Business rules never see unfiltered YOLO output.
    """
    threshold = min_detection_confidence(thresholds) if min_confidence is None else float(min_confidence)
    return [item for item in detections if item.confidence >= threshold]
