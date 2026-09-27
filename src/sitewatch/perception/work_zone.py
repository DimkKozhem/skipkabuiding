"""Construction footprint on a fixed camera.

Neighbors and the road stay in frame. The site is the region that keeps
changing across the series. Stages and equipment are read inside that region.
"""

from __future__ import annotations

import cv2
import numpy as np

from sitewatch.domain.contracts import BBox, PerceptionEvidence
from sitewatch.perception.ontology import canonical_label


ZONE_PROMPTS = ("construction site", "building under construction", "excavation")


def polygon_from_evidence(
    items: list[PerceptionEvidence],
    *,
    frame_width: float,
    frame_height: float,
    min_score: float = 0.55,
) -> list[list[float]]:
    """One rectangle around the site boxes. Neighbors and the road stay outside it."""
    if frame_width <= 0 or frame_height <= 0:
        return []
    boxes = [item.bbox for item in items if item.bbox is not None and item.score >= min_score]
    if not boxes:
        return []
    x1 = min(box.x1 for box in boxes) / frame_width
    y1 = min(box.y1 for box in boxes) / frame_height
    x2 = max(box.x2 for box in boxes) / frame_width
    y2 = max(box.y2 for box in boxes) / frame_height
    x1, y1 = max(0.0, x1), max(0.0, y1)
    x2, y2 = min(1.0, x2), min(1.0, y2)
    if (x2 - x1) * (y2 - y1) < 0.05 or (x2 - x1) * (y2 - y1) > 0.8:
        return []
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def center_inside(box: BBox, polygon: list[list[float]], *, frame_width: float, frame_height: float) -> bool:
    if not polygon or frame_width <= 0 or frame_height <= 0:
        return True
    cx = ((box.x1 + box.x2) / 2.0) / frame_width
    cy = ((box.y1 + box.y2) / 2.0) / frame_height
    contour = np.array(polygon, dtype=np.float32).reshape(-1, 1, 2)
    return cv2.pointPolygonTest(contour, (cx, cy), False) >= 0


def clip_to_work_zone(
    items: list[PerceptionEvidence],
    polygon: list[list[float]],
    *,
    frame_width: float,
    frame_height: float,
) -> list[PerceptionEvidence]:
    """Keep detections whose center lies on the construction footprint.

    A crane jib often leaves the pit, so crane boxes are kept when they overlap the zone.
    """
    if not polygon:
        return items
    cranes = {"tower_crane", "mobile_crane"}
    kept: list[PerceptionEvidence] = []
    for item in items:
        if item.bbox is None:
            kept.append(item)
            continue
        label = canonical_label(item.normalized_label) or item.normalized_label
        if label in cranes and _overlaps_zone(item.bbox, polygon, frame_width, frame_height):
            kept.append(item)
            continue
        if center_inside(item.bbox, polygon, frame_width=frame_width, frame_height=frame_height):
            kept.append(item)
    return kept


def _overlaps_zone(box: BBox, polygon: list[list[float]], frame_width: float, frame_height: float) -> bool:
    contour = np.array(polygon, dtype=np.float32).reshape(-1, 1, 2)
    for x, y in (
        (box.x1, box.y1),
        (box.x2, box.y1),
        (box.x1, box.y2),
        (box.x2, box.y2),
        ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2),
    ):
        if cv2.pointPolygonTest(contour, (x / frame_width, y / frame_height), False) >= 0:
            return True
    return False
