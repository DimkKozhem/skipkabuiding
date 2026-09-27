"""Deduplicate overlapping detections from multi-prompt SAM3 runs."""

from __future__ import annotations

from sitewatch.domain.contracts import BBox, PerceptionEvidence
from sitewatch.perception.ontology import canonical_label, equipment_keys, perception_config


def _iou(a: BBox, b: BBox) -> float:
    x1 = max(a.x1, b.x1)
    y1 = max(a.y1, b.y1)
    x2 = min(a.x2, b.x2)
    y2 = min(a.y2, b.y2)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a.x2 - a.x1) * max(0.0, a.y2 - a.y1)
    area_b = max(0.0, b.x2 - b.x1) * max(0.0, b.y2 - b.y1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def deduplicate_evidence(
    items: list[PerceptionEvidence],
    *,
    iou_threshold: float = 0.5,
    min_score: float = 0.0,
) -> list[PerceptionEvidence]:
    """Keep highest-score box per overlapping same-class cluster."""
    filtered = [e for e in items if e.score >= min_score and e.bbox is not None]
    filtered.sort(key=lambda e: e.score, reverse=True)
    kept: list[PerceptionEvidence] = []
    for cand in filtered:
        assert cand.bbox is not None
        duplicate = False
        for prev in kept:
            if prev.normalized_label != cand.normalized_label:
                continue
            if prev.bbox is None:
                continue
            if _iou(cand.bbox, prev.bbox) >= iou_threshold:
                duplicate = True
                break
        if not duplicate:
            kept.append(cand)
    # preserve non-box evidence (e.g. VLM-only)
    no_box = [e for e in items if e.bbox is None]
    return kept + no_box


def _area_ratio(box: BBox, frame_area: float) -> float:
    area = max(0.0, box.x2 - box.x1) * max(0.0, box.y2 - box.y1)
    if frame_area <= 0:
        return 1.0
    return area / frame_area


def refine_equipment_evidence(
    items: list[PerceptionEvidence],
    *,
    frame_width: float,
    frame_height: float,
) -> list[PerceptionEvidence]:
    """Drop implausible equipment boxes and keep one class per physical machine.

    Same-class NMS does not stop one excavator from also being a truck and a bulldozer.
    Distant cars and a crane boom covering a quarter of the frame are not counted.
    """
    cfg = perception_config().get("dedup") or {}
    min_ratio = float(cfg.get("equipment_min_area_ratio") or 0.0022)
    max_ratio = float(cfg.get("equipment_max_area_ratio") or 0.12)
    cross_iou = float(cfg.get("equipment_cross_iou") or 0.55)
    cross_contain = float(cfg.get("equipment_cross_containment") or 0.6)
    families = cfg.get("equipment_families") or []
    gear = set(equipment_keys()) | {"roller", "crane_manipulator"}
    frame_area = float(frame_width) * float(frame_height)

    family_of: dict[str, int] = {}
    for index, group in enumerate(families):
        for name in group or []:
            family_of[str(name)] = index

    structures: list[PerceptionEvidence] = []
    for item in items:
        label = canonical_label(item.normalized_label) or item.normalized_label
        if item.bbox is None or label not in gear:
            structures.append(item)

    # A tower crane fills a large part of the frame; that box is the machine, not a blob.
    crane_labels = {"tower_crane", "mobile_crane"}
    min_scores = cfg.get("equipment_min_score") or {}
    tower_min_area = float(cfg.get("tower_crane_min_area_ratio") or 0.012)
    tower_min_span = float(cfg.get("tower_crane_min_span_ratio") or 0.22)
    mobile_max_area = float(cfg.get("mobile_crane_max_area_ratio") or 0.18)
    gear_boxes = []
    for item in items:
        label = canonical_label(item.normalized_label) or item.normalized_label
        if item.bbox is None or label not in gear:
            continue
        floor = float(min_scores.get(label) or 0.0)
        if item.score < floor:
            continue
        ratio = _area_ratio(item.bbox, frame_area)
        if ratio < min_ratio:
            continue
        if ratio > max_ratio and label not in crane_labels:
            continue
        span = max(item.bbox.x2 - item.bbox.x1, item.bbox.y2 - item.bbox.y1)
        span_ratio = span / max(frame_width, frame_height)
        if label == "tower_crane" and (ratio < tower_min_area or span_ratio < tower_min_span):
            continue
        center_y = ((item.bbox.y1 + item.bbox.y2) / 2) / frame_height if frame_height else 0.0
        tower_max_cy = float(cfg.get("tower_crane_max_center_y") or 0.55)
        if label == "tower_crane" and center_y > tower_max_cy:
            continue
        if label == "mobile_crane" and ratio > mobile_max_area:
            continue
        # Scaffolding / fence posts: tall thin boxes are not diggers.
        width = max(1.0, item.bbox.x2 - item.bbox.x1)
        height = max(1.0, item.bbox.y2 - item.bbox.y1)
        if label in {"excavator", "bulldozer", "loader", "truck", "dump_truck"} and height / width >= 3.2:
            continue
        gear_boxes.append(item)

    def _rank(item: PerceptionEvidence) -> tuple[int, float]:
        label = canonical_label(item.normalized_label) or item.normalized_label
        # Prefer the more specific machine when the same silhouette got two labels.
        # Cranes must beat excavator: boom/mast boxes often also fire digger prompts.
        if label == "tower_crane":
            preference = 4
        elif label == "mobile_crane":
            preference = 3
        elif label in {"excavator", "bulldozer", "loader"}:
            preference = 2
        else:
            preference = 0
        return (preference, item.score)

    gear_boxes.sort(key=_rank, reverse=True)
    kept_gear: list[PerceptionEvidence] = []
    for cand in gear_boxes:
        assert cand.bbox is not None
        label = canonical_label(cand.normalized_label) or cand.normalized_label
        family = family_of.get(label)
        duplicate = False
        for prev in kept_gear:
            if prev.bbox is None:
                continue
            prev_label = canonical_label(prev.normalized_label) or prev.normalized_label
            iou = _iou(cand.bbox, prev.bbox)
            same_family = family is not None and family_of.get(prev_label) == family
            contain = max(_containment(cand.bbox, prev.bbox), _containment(prev.bbox, cand.bbox))
            # Same family: high overlap or nested boxes → one machine.
            if same_family and (iou >= cross_iou or contain >= cross_contain):
                duplicate = True
                break
            # Different families (crane vs excavator): only merge if one box almost
            # contains the other — modest overlap under a jib must keep both.
            if not same_family and contain >= cross_contain:
                duplicate = True
                break
        if not duplicate:
            kept_gear.append(cand)
    return structures + kept_gear


def _containment(inner: BBox, outer: BBox) -> float:
    x1 = max(inner.x1, outer.x1)
    y1 = max(inner.y1, outer.y1)
    x2 = min(inner.x2, outer.x2)
    y2 = min(inner.y2, outer.y2)
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    area = max(0.0, inner.x2 - inner.x1) * max(0.0, inner.y2 - inner.y1)
    return inter / area if area > 0 else 0.0


def refine_structure_evidence(
    items: list[PerceptionEvidence],
    *,
    frame_width: float,
    frame_height: float,
) -> list[PerceptionEvidence]:
    """Keep the building under construction and drop the block across the street.

    Neighbour walls are many medium boxes. The subject is a large wall, facade
    or roof. While the pit has no such box, those classes are the neighbours.
    Smaller parts stay only when their centre lies on that subject.
    """
    cfg = perception_config().get("dedup") or {}
    min_areas = cfg.get("structure_min_area_ratio") or {}
    max_areas = cfg.get("structure_max_area_ratio") or {}
    nms_iou = float(cfg.get("structure_nms_iou") or 0.45)
    contain = float(cfg.get("structure_containment") or 0.72)
    subject_min = float(cfg.get("structure_subject_min_area_ratio") or 0.12)
    skyline_bottom = float(cfg.get("structure_skyline_bottom_max") or 0.60)
    envelope = {"wall", "facade", "roof"}
    frame_area = float(frame_width) * float(frame_height)
    structures = {"wall", "facade", "roof", "beam", "column", "floor_slab", "foundation", "window_opening"}

    other: list[PerceptionEvidence] = []
    candidates: list[tuple[str, PerceptionEvidence, float]] = []
    for item in items:
        label = canonical_label(item.normalized_label) or item.normalized_label
        if item.bbox is None or label not in structures:
            other.append(item)
            continue
        ratio = _area_ratio(item.bbox, frame_area)
        if ratio < float(min_areas.get(label) or 0.0):
            continue
        if label in max_areas and ratio > float(max_areas[label]):
            continue
        candidates.append((label, item, ratio))

    envelopes = [(item, ratio) for label, item, ratio in candidates if label in envelope and item.bbox is not None]
    subject = max(envelopes, key=lambda pair: pair[1])[0].bbox if envelopes and envelopes and max(r for _, r in envelopes) >= subject_min else None

    def _on_subject(box: BBox) -> bool:
        if subject is None:
            return False
        return _containment(box, subject) >= contain

    grouped: dict[str, list[PerceptionEvidence]] = {}
    for label, item, ratio in candidates:
        assert item.bbox is not None
        if label in envelope and item.bbox.y2 / frame_height < skyline_bottom:
            continue
        if label in envelope and subject is not None and item.bbox is not subject and not _on_subject(item.bbox):
            continue
        if label in envelope and subject is None:
            continue
        if label == "column":
            width = item.bbox.x2 - item.bbox.x1
            height = item.bbox.y2 - item.bbox.y1
            if width > height:
                continue
        if label in {"beam", "column", "floor_slab", "window_opening"} and subject is not None and not _on_subject(item.bbox):
            continue
        grouped.setdefault(label, []).append(item)

    kept: list[PerceptionEvidence] = []
    for label, boxes in grouped.items():
        boxes.sort(key=lambda item: item.score, reverse=True)
        chosen: list[PerceptionEvidence] = []
        for cand in boxes:
            assert cand.bbox is not None
            drop = False
            for prev in chosen:
                if prev.bbox is None:
                    continue
                if _iou(cand.bbox, prev.bbox) >= nms_iou:
                    drop = True
                    break
                if _containment(cand.bbox, prev.bbox) >= contain:
                    drop = True
                    break
            if not drop:
                chosen.append(cand)
        kept.extend(chosen)
    # wall, facade and roof on the same pixels are one shell, not three objects.
    shell = [item for item in kept if (canonical_label(item.normalized_label) or item.normalized_label) in envelope]
    rest = [item for item in kept if item not in shell]
    shell.sort(key=lambda item: _area_ratio(item.bbox, frame_area) if item.bbox is not None else 0.0, reverse=True)
    shell_kept: list[PerceptionEvidence] = []
    for cand in shell:
        assert cand.bbox is not None
        if any(
            prev.bbox is not None and (
                _iou(cand.bbox, prev.bbox) >= nms_iou or _containment(cand.bbox, prev.bbox) >= contain
            )
            for prev in shell_kept
        ):
            continue
        shell_kept.append(cand)
    # Window bays and studs inside the shell are not separate columns.
    hosts = [item.bbox for item in shell_kept if item.bbox is not None]
    parts = []
    for item in rest:
        label = canonical_label(item.normalized_label) or item.normalized_label
        if item.bbox is not None and label == "column" and any(_containment(item.bbox, host) >= 0.5 for host in hosts):
            continue
        parts.append(item)
    return other + parts + shell_kept
