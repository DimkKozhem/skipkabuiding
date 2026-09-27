"""Project ObservedState / entities onto legacy ActualState elements/equipment."""

from __future__ import annotations

from sitewatch.domain.contracts import (
    ActualState,
    CountStat,
    EntityActualFact,
    EntityObservation,
    ObservedState,
    ObservationQuality,
    PresenceStat,
)
from sitewatch.domain.enums import (
    CoverageLevel,
    EntityNature,
    EntityVisibility,
    MeasurementType,
    Visibility,
)
from sitewatch.perception.ontology import is_equipment, nature_for, perception_config, state_key_for
from sitewatch.works.derive import derive_work_facts


def _frame_confirms(obs: EntityObservation) -> bool:
    if obs.status not in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}:
        return False
    if any(note.startswith("agreement:vlm_only") or note.startswith("agreement:conflict") or note == "vlm_only" for note in obs.notes):
        return False
    floor = float((perception_config().get("temporal") or {}).get("confirm_min_confidence") or 0.55)
    return obs.confidence >= floor


_LEGACY_EQUIPMENT_ALIASES = {
    "road_roller": "roller",
    "mobile_crane": "mobile_crane",
}


def _visibility_to_obs_quality(obs: ObservedState) -> ObservationQuality:
    if not obs.quality.usable:
        vis = Visibility.POOR
    elif obs.quality.visibility >= 0.7:
        vis = Visibility.GOOD
    elif obs.quality.visibility >= 0.4:
        vis = Visibility.DEGRADED
    else:
        vis = Visibility.POOR
    cov = CoverageLevel.FULL if obs.quality.coverage >= 0.6 else CoverageLevel.PARTIAL
    notes = list(obs.quality.issues)
    notes.extend(obs.observation.limitations)
    return ObservationQuality(
        visibility=vis,
        coverage=cov,
        n_frames=1,
        mean_model_confidence=0.0,
        evidence_confidence=0.0,
        notes=notes,
    )


def _known_count(obs: EntityObservation) -> int | None:
    if obs.count_visible is not None:
        return int(obs.count_visible)
    if isinstance(obs.value, bool) or obs.value is None:
        return None
    if isinstance(obs.value, (int, float)):
        return int(obs.value)
    return None


def entity_obs_to_stat(obs: EntityObservation) -> CountStat | PresenceStat | None:
    """Unknown observations are omitted. A missed detection is not count zero."""
    if obs.measurement in {MeasurementType.PRESENCE, MeasurementType.AREA, MeasurementType.AREA_OR_PRESENCE}:
        if obs.value is None and obs.status not in {
            EntityVisibility.VISIBLE,
            EntityVisibility.PARTIALLY_VISIBLE,
        }:
            return None
        detected = obs.status in {
            EntityVisibility.VISIBLE,
            EntityVisibility.PARTIALLY_VISIBLE,
        } or bool(obs.value)
        count = _known_count(obs)
        return PresenceStat(
            detected=detected,
            count=int(count if count is not None else (1 if detected else 0)),
            max_confidence=obs.confidence,
        )
    count = _known_count(obs)
    if count is None:
        return None
    return CountStat(count=count, max_confidence=obs.confidence)


def observed_to_frame_actual(observed: ObservedState) -> ActualState:
    """Single-frame projection (pre-temporal). Used as seed for TemporalStateEngine."""
    elements: dict[str, CountStat | PresenceStat] = {}
    equipment: dict[str, CountStat] = {}
    entities: dict[str, EntityActualFact] = {}

    for label, obs in observed.structures.items():
        key = state_key_for(label)
        # legacy keys
        if label == "floor_slab":
            key = "slabs"
            stat = entity_obs_to_stat(obs)
            if stat is not None:
                # Плиты ≠ этажи: не копируем count боксов в floors.
                elements["slabs"] = stat
        elif label == "window_opening":
            key = "windows"
            stat = entity_obs_to_stat(obs)
            if stat is not None:
                elements[key] = stat
        elif label == "column":
            stat = entity_obs_to_stat(obs)
            if stat is not None:
                elements["columns"] = stat
        elif label == "wall":
            stat = entity_obs_to_stat(obs)
            if stat is not None:
                elements["walls"] = stat
        elif label == "beam":
            stat = entity_obs_to_stat(obs)
            if stat is not None:
                elements["beams"] = stat
        else:
            stat = entity_obs_to_stat(obs)
            if stat is not None:
                elements[key] = stat
        confirmed = _frame_confirms(obs)
        entities[label] = EntityActualFact(
            measurement=obs.measurement,
            nature=nature_for(label),
            last_confirmed_value=obs.value if confirmed else None,
            last_confirmed_at=observed.captured_at if confirmed else None,
            current_visibility=obs.status,
            current_confidence=obs.confidence,
            current_value=obs.value,
            freshness="fresh" if confirmed else "unknown",
        )

    for label, obs in observed.equipment.items():
        legacy = _LEGACY_EQUIPMENT_ALIASES.get(label, label)
        stat = entity_obs_to_stat(obs)
        if isinstance(stat, PresenceStat):
            equipment[legacy] = CountStat(count=stat.count, max_confidence=stat.max_confidence)
        elif isinstance(stat, CountStat):
            equipment[legacy] = stat
        # also keep crane_manipulator alias used by demo rules
        if label == "mobile_crane" and legacy in equipment:
            equipment.setdefault("crane_manipulator", equipment[legacy])
        if label == "road_roller" and legacy in equipment:
            equipment.setdefault("roller", equipment[legacy])
        confirmed = _frame_confirms(obs)
        entities[label] = EntityActualFact(
            measurement=obs.measurement,
            nature=EntityNature.TRANSIENT,
            last_confirmed_value=obs.value if confirmed else None,
            last_confirmed_at=observed.captured_at if confirmed else None,
            current_visibility=obs.status,
            current_confidence=obs.confidence,
            current_value=obs.value,
            freshness="fresh" if confirmed else "unknown",
        )

    scene = dict(observed.scene_attributes)
    if observed.visible_floor_levels is not None:
        scene["visible_floor_levels"] = observed.visible_floor_levels
        status = scene.get("floors_status")
        if status not in {"proven", "proposed"}:
            derivation = str(scene.get("floors_derivation") or "")
            if derivation in {"annotation", "scene_label", "floor_bands_proven", "manual_gt"}:
                status = "proven"
            else:
                status = "proposed"
                scene.setdefault("floors_derivation", "visible_floor_levels")
        scene["floors_status"] = status
        # Confirmed structural count only when proven; proposed stays as observation.
        if status == "proven":
            scene["structural_levels"] = observed.visible_floor_levels
            elements["floors"] = CountStat(
                count=int(observed.visible_floor_levels),
                max_confidence=0.8,
            )
        else:
            scene.pop("structural_levels", None)
            elements["floors"] = CountStat(
                count=int(observed.visible_floor_levels),
                max_confidence=0.5,
            )
    if observed.total_floor_count is not None:
        scene["total_floor_count"] = observed.total_floor_count
    else:
        scene.setdefault("total_floor_count", None)

    if observed.observation.summary:
        scene["observation_summary"] = observed.observation.summary
    if observed.observation.limitations:
        scene["limitation"] = "; ".join(observed.observation.limitations)

    quality = _visibility_to_obs_quality(observed)
    confs = [o.confidence for o in list(observed.structures.values()) + list(observed.equipment.values())]
    if confs:
        quality.mean_model_confidence = round(sum(confs) / len(confs), 4)

    run_id = observed.pipeline_run.run_id if observed.pipeline_run else None
    work_code = str(scene.get("work_code") or scene.get("stage") or "unknown")
    work_facts = derive_work_facts(observed, work_code=work_code)

    # Confirmed floors WorkFact only when proven; proposed stays observation without inventing 0.
    floors_fact = work_facts.get("visible_floor_levels")
    if floors_fact is not None and floors_fact.value is not None:
        if floors_fact.certainty.value == "confirmed" and scene.get("floors_status") == "proven":
            elements["floors"] = CountStat(count=int(floors_fact.value), max_confidence=0.8)
            scene["structural_levels"] = int(floors_fact.value)
            if scene.get("floors_derivation") not in {
                "floor_bands_proven",
                "manual_gt",
                "annotation",
                "scene_label",
            }:
                scene["floors_derivation"] = "work_fact:visible_floor_levels"
        elif floors_fact.certainty.value == "confirmed" and scene.get("floors_status") != "proven":
            # Confirmed method but frame not proven → keep as proposed observation
            scene.setdefault("floors_status", "proposed")
            elements["floors"] = CountStat(count=int(floors_fact.value), max_confidence=0.5)
            scene.pop("structural_levels", None)
        elif floors_fact.value is not None and floors_fact.certainty.value != "confirmed":
            # Unknown/processing — do not write as structural fact
            if "floors" in elements and float(getattr(elements["floors"], "max_confidence", 0) or 0) <= 0.5:
                pass

    return ActualState(
        object_id=observed.object_id,
        zone_id=observed.zone_id,
        timestamp=observed.captured_at,
        camera_code=observed.camera_id,
        elements=elements,
        equipment=equipment,
        quality=quality,
        scene_attributes=scene,
        entities=entities,
        work_facts=work_facts,
        pipeline_run_id=run_id,
        processed_at=observed.pipeline_run.processed_at if observed.pipeline_run else None,
    )


def sync_legacy_projection(actual: ActualState) -> ActualState:
    """Rebuild elements/equipment from entities for UI/deviation compatibility."""
    if not actual.entities:
        return actual
    elements: dict[str, CountStat | PresenceStat] = {}
    equipment: dict[str, CountStat] = {}

    for label, fact in actual.entities.items():
        # Machines only — scaffolding/formwork are temporary structures, not gear.
        treat_as_equipment = is_equipment(label) or label in {
            "excavator",
            "dump_truck",
            "loader",
            "bulldozer",
            "road_roller",
            "concrete_mixer",
            "concrete_pump",
            "mobile_crane",
            "tower_crane",
            "truck",
        }
        if treat_as_equipment:
            legacy = _LEGACY_EQUIPMENT_ALIASES.get(label, label)
            val = fact.last_confirmed_value if fact.last_confirmed_value is not None else fact.current_value
            count = int(val or 0) if not isinstance(val, bool) else int(val)
            if fact.nature == EntityNature.TRANSIENT:
                # This frame's count only. A carried confirmation stays on the entity
                # and is not treated as a detection on a later empty frame.
                if fact.current_value is None or fact.last_confirmed_value is None:
                    continue
                cur = fact.current_value
                count = int(cur) if not isinstance(cur, bool) else int(cur)
            equipment[legacy] = CountStat(count=count, max_confidence=fact.current_confidence)
            continue

        key = state_key_for(label)
        if label == "floor_slab":
            key = "slabs"
        elif label == "window_opening":
            key = "windows"
        elif label == "column":
            key = "columns"
        elif label == "wall":
            key = "walls"

        val = fact.last_confirmed_value
        if val is None and fact.nature == EntityNature.TRANSIENT:
            val = fact.current_value
        if val is None:
            continue
        if fact.measurement in {MeasurementType.PRESENCE, MeasurementType.AREA, MeasurementType.AREA_OR_PRESENCE}:
            detected = bool(val) if isinstance(val, bool) else float(val or 0) > 0
            elements[key] = PresenceStat(
                detected=detected,
                count=int(detected),
                max_confidence=fact.current_confidence,
            )
        else:
            elements[key] = CountStat(count=int(val or 0), max_confidence=fact.current_confidence)

    # floors: proven structural_levels preferred; else proposed visible_floor_levels for UI.
    levels = actual.scene_attributes.get("structural_levels")
    status = actual.scene_attributes.get("floors_status") or actual.scene_attributes.get(
        "floors_status_latest"
    )
    if levels is None:
        levels = actual.scene_attributes.get("visible_floor_levels")
        if status is None and levels is not None:
            status = "proposed"
    if levels is not None and "floors" not in elements:
        try:
            conf = 0.8 if status == "proven" else 0.5
            elements["floors"] = CountStat(count=int(levels), max_confidence=conf)
        except (TypeError, ValueError):
            pass
    if status and "floors_status" not in actual.scene_attributes:
        actual.scene_attributes["floors_status"] = status

    actual.elements = elements
    actual.equipment = equipment
    return actual
