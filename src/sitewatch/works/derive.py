"""Derive WorkFact dict from ObservedState via registered methods."""

from __future__ import annotations

from datetime import datetime

from sitewatch.domain.contracts import ObservedState, WorkFact
from sitewatch.works.methods import equipment_count, run_method, unimplemented
from sitewatch.works.rules import method_name, work_rules


DEFAULT_INDICATORS = (
    "visible_floor_levels",
    "excavation_visible",
    "foundation_visible",
    "facade_visible",
    "roof_visible",
    "windows_visible",
    "divider_stage_sign",
)


def derive_work_facts(
    observed: ObservedState,
    *,
    work_code: str | None = None,
    indicator_ids: list[str] | None = None,
    processed_at: datetime | None = None,
) -> dict[str, WorkFact]:
    """Run measurement methods. Missing method → measurement_unimplemented fact."""
    stage = work_code or str(observed.scene_attributes.get("work_code") or "unknown")
    ids = list(indicator_ids or [])
    if not ids:
        stage_map = work_rules().get("stage_indicators") or {}
        ids = list(stage_map.get(stage) or DEFAULT_INDICATORS)
        # always try floors when VLM/scene provides them
        if "visible_floor_levels" not in ids and (
            observed.visible_floor_levels is not None
            or observed.scene_attributes.get("visible_floor_levels") is not None
            or observed.scene_attributes.get("structural_levels") is not None
            or observed.scene_attributes.get("floors") is not None
        ):
            ids.append("visible_floor_levels")

    facts: dict[str, WorkFact] = {}
    processed = processed_at
    if processed is None and observed.pipeline_run:
        processed = observed.pipeline_run.processed_at or observed.pipeline_run.finished_at

    for indicator_id in ids:
        if indicator_id.startswith("equipment:"):
            cls = indicator_id.split(":", 1)[1]
            facts[indicator_id] = equipment_count(
                observed,
                work_code=stage,
                equipment_class=cls,
                processed_at=processed,
            )
            continue
        name = method_name(indicator_id)
        if not name:
            facts[indicator_id] = unimplemented(
                observed,
                work_code=stage,
                indicator_id=indicator_id,
                processed_at=processed,
            )
            continue
        fact = run_method(name, observed, work_code=stage, indicator_id=indicator_id, processed_at=processed)
        facts[fact.indicator_id] = fact

    # Equipment classes seen on frame → resource facts
    for cls in work_rules().get("equipment_resource_classes") or []:
        key = f"equipment:{cls}"
        if key in facts:
            continue
        if cls not in observed.equipment:
            continue
        facts[key] = equipment_count(
            observed,
            work_code=stage,
            equipment_class=cls,
            processed_at=processed,
        )

    return facts
