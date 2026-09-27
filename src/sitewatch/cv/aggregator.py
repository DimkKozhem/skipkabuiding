from __future__ import annotations

from datetime import datetime

from sitewatch.cv.taxonomy import element_spec, is_element, is_equipment, taxonomy
from sitewatch.domain.contracts import (
    ActualState,
    CountStat,
    Detection,
    ObservationQuality,
    PresenceStat,
)
from sitewatch.domain.enums import CoverageLevel, Visibility


def _max_conf(items: list[Detection]) -> float:
    return max((item.confidence for item in items), default=0.0)


def _count(items: list[Detection]) -> int:
    track_ids = {item.track_id for item in items if item.track_id is not None}
    if track_ids:
        return len(track_ids)
    return len(items)


def _resolved_count(
    class_name: str,
    matched: list[Detection],
    class_counts: dict[str, int] | None,
) -> int:
    """Photo: boxes or unique tracks. Video: window counts, not every sampled frame."""
    if class_counts is not None and class_name in class_counts:
        return int(class_counts[class_name])
    return _count(matched)


def detections_to_actual_state(
    *,
    object_id: str,
    zone_id: str,
    timestamp: datetime,
    camera_code: str | None,
    detections: list[Detection],
    scene: dict | None = None,
    n_frames: int = 1,
    class_counts: dict[str, int] | None = None,
) -> ActualState:
    scene = scene or {}
    elements: dict[str, CountStat | PresenceStat] = {}
    equipment: dict[str, CountStat] = {}

    by_class: dict[str, list[Detection]] = {}
    for det in detections:
        by_class.setdefault(det.class_name, []).append(det)

    for class_name, spec in taxonomy().get("elements", {}).items():
        matched = by_class.get(class_name, [])
        key = spec.get("state_key") or class_name
        count = _resolved_count(class_name, matched, class_counts)
        if spec.get("kind") == "presence":
            elements[key] = PresenceStat(
                detected=count > 0 or bool(scene.get(key)),
                count=count,
                max_confidence=_max_conf(matched),
            )
        else:
            if key in scene:
                count = int(scene.get(key, count))
            elements[key] = CountStat(count=count, max_confidence=_max_conf(matched))

    for class_name in taxonomy().get("equipment", {}):
        matched = by_class.get(class_name, [])
        equipment[class_name] = CountStat(
            count=_resolved_count(class_name, matched, class_counts),
            max_confidence=_max_conf(matched),
        )

    scene_out = dict(scene)
    slabs = elements.get("slabs")
    slab_n = int(slabs.count) if slabs is not None else 0

    # Этажность — только scene.floors / visible_floor_levels.
    # Count детектов slab/floor_slab ≠ число этажей (SAM часто фрагментирует фасад).
    if "floors" in scene:
        floor_n = int(scene["floors"])
        elements["floors"] = CountStat(
            count=floor_n,
            max_confidence=0.8 if floor_n else 0.0,
        )
        scene_out["structural_levels"] = floor_n
        scene_out["visible_floor_levels"] = floor_n
        scene_out["floors_derivation"] = "scene_label"
        scene_out["floors_status"] = "proven"
        scene_out.setdefault(
            "limitation",
            "этажность задана подписью наблюдения, не заявлена как надёжный CV-подсчёт этажей",
        )
    elif scene.get("visible_floor_levels") is not None:
        floor_n = int(scene["visible_floor_levels"])
        elements["floors"] = CountStat(
            count=floor_n,
            max_confidence=0.5 if floor_n else 0.0,
        )
        scene_out["visible_floor_levels"] = floor_n
        scene_out["floors_derivation"] = scene.get("floors_derivation") or "visible_floor_levels"
        status = scene.get("floors_status") or "proposed"
        scene_out["floors_status"] = status
        # VLM scalar alone is proposed — do not confirm structural_levels.
        if status == "proven":
            scene_out["structural_levels"] = floor_n
        else:
            scene_out.pop("structural_levels", None)
    else:
        # Unknown floors: omit the key. Zero is not a default.
        scene_out.setdefault("floors_derivation", "unavailable")
        if slab_n:
            scene_out.setdefault(
                "limitation",
                "видны признаки плит перекрытий; этажность по числу боксов не выводится",
            )

    if "foundation" in scene and "foundation" in elements:
        elements["foundation"] = PresenceStat(
            detected=bool(scene["foundation"]),
            count=max(elements["foundation"].count, int(bool(scene["foundation"]))),
            max_confidence=max(elements["foundation"].max_confidence, 0.8),
        )

    model_confs = [det.confidence for det in detections]
    mean_conf = sum(model_confs) / len(model_confs) if model_confs else 0.0
    visibility = Visibility(scene.get("visibility", Visibility.GOOD))
    coverage = CoverageLevel(scene.get("coverage", CoverageLevel.FULL))

    unused = [name for name in by_class if not is_element(name) and not is_equipment(name)]
    notes = []
    if unused:
        notes.append(f"unmapped_or_other:{','.join(sorted(unused))}")
    if scene_out.get("limitation"):
        notes.append(str(scene_out["limitation"]))

    quality = ObservationQuality(
        visibility=visibility,
        coverage=coverage,
        n_frames=n_frames,
        mean_model_confidence=round(mean_conf, 4),
        evidence_confidence=0.0,
        notes=notes,
    )
    return ActualState(
        object_id=object_id,
        zone_id=zone_id,
        timestamp=timestamp,
        camera_code=camera_code,
        elements=elements,
        equipment=equipment,
        quality=quality,
        scene_attributes=scene_out,
    )


def merge_actual_states(states: list[ActualState]) -> ActualState:
    """Same-day / same-window fusion: max counts, OR presence, summed frames."""
    if not states:
        raise ValueError("no states to merge")
    if len(states) == 1:
        merged = states[0].model_copy(deep=True)
        merged.quality.n_frames = max(merged.quality.n_frames, 1)
        return merged
    ordered = sorted(states, key=lambda item: item.timestamp)
    base = ordered[-1].model_copy(deep=True)
    for state in ordered[:-1]:
        for key, stat in state.elements.items():
            current = base.elements.get(key)
            if current is None:
                base.elements[key] = stat
            elif isinstance(stat, PresenceStat) and isinstance(current, PresenceStat):
                base.elements[key] = PresenceStat(
                    detected=current.detected or stat.detected,
                    count=max(current.count, stat.count),
                    max_confidence=max(current.max_confidence, stat.max_confidence),
                )
            else:
                base.elements[key] = CountStat(
                    count=max(int(current.count), int(stat.count)),
                    max_confidence=max(current.max_confidence, stat.max_confidence),
                )
        for key, stat in state.equipment.items():
            current = base.equipment.get(key)
            if current is None:
                base.equipment[key] = stat
            else:
                base.equipment[key] = CountStat(
                    count=max(current.count, stat.count),
                    max_confidence=max(current.max_confidence, stat.max_confidence),
                )
        for key, fact in (state.work_facts or {}).items():
            cur = (base.work_facts or {}).get(key)
            if cur is None:
                base.work_facts = dict(base.work_facts or {})
                base.work_facts[key] = fact
            elif fact.certainty.value == "confirmed" and (
                cur.certainty.value != "confirmed"
                or (fact.value is not None and cur.value is not None)
            ):
                base.work_facts = dict(base.work_facts or {})
                # Prefer higher confidence / proven; do not invent max for proposed
                if getattr(fact, "coverage", None) and str(getattr(fact.coverage, "value", "")) == "partial":
                    continue
                base.work_facts[key] = fact
    confs = [item.quality.mean_model_confidence for item in ordered]
    base.quality.n_frames = sum(max(item.quality.n_frames, 1) for item in ordered)
    base.quality.mean_model_confidence = round(sum(confs) / len(confs), 4)
    return base


def element_spec_for(class_name: str) -> dict:
    return element_spec(class_name)
