"""Indicator measurement methods. Registry maps method name → callable.

YAML alone does not implement a measurement.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from sitewatch.domain.contracts import ObservedState, WorkFact
from sitewatch.domain.enums import (
    EntityVisibility,
    IndicatorKind,
    ObservationCoverage,
    StageStatus,
    WorkCertainty,
)
from sitewatch.works.rules import indicator_rule, method_name, work_rules

MethodFn = Callable[..., WorkFact]


def _base(
    *,
    observed: ObservedState,
    work_code: str,
    indicator_id: str,
    kind: IndicatorKind,
    method: str,
    processed_at: datetime | None = None,
) -> dict[str, Any]:
    rule = indicator_rule(indicator_id) or {}
    zone = list(observed.scene_attributes.get("work_zone") or [])
    return {
        "work_code": work_code,
        "indicator_id": indicator_id,
        "kind": kind,
        "part": "target",
        "captured_at": observed.captured_at,
        "processed_at": processed_at or (observed.pipeline_run.processed_at if observed.pipeline_run else None),
        "as_of": observed.captured_at.date() if observed.captured_at else None,
        "method": method,
        "method_version": "facts-2",
        "pipeline_version": (
            observed.pipeline_run.pipeline_version if observed.pipeline_run else "workfact-1"
        ),
        "work_zone": zone,
        "confirms": str(rule.get("confirms") or ""),
    }


def _provider_status(observed: ObservedState, name: str) -> StageStatus | None:
    if not observed.pipeline_run:
        return None
    for stage in observed.pipeline_run.stages:
        if stage.name == name:
            return stage.status
    return None


def _required_failed(observed: ObservedState, indicator_id: str) -> str | None:
    rule = indicator_rule(indicator_id) or {}
    for provider in rule.get("required_providers") or []:
        status = _provider_status(observed, str(provider))
        if status in {StageStatus.FAILED, StageStatus.UNAVAILABLE, StageStatus.INVALID_RESPONSE}:
            return f"required_provider_failed:{provider}:{status.value if status else 'missing'}"
        if status is None and observed.pipeline_run and any(
            s.name == str(provider) for s in observed.pipeline_run.stages
        ):
            continue
        # In annotation mode qwen may be absent — only fail if mode is real and stage missing
        if status is None and str(provider) == "qwen_vl":
            mode = None
            if observed.pipeline_run:
                for s in observed.pipeline_run.stages:
                    if s.name == "annotation" and s.status == StageStatus.SUCCESS:
                        mode = "annotation"
            # annotation path does not require qwen
            if mode == "annotation":
                continue
            # if any stage is qwen-named skipped with enabled false
            for s in (observed.pipeline_run.stages if observed.pipeline_run else []):
                if s.name == "qwen_vl" and s.status == StageStatus.SKIPPED:
                    return f"required_provider_skipped:{provider}"
    return None


def _zone_coverage(observed: ObservedState, requires_zone: bool) -> ObservationCoverage:
    zone = observed.scene_attributes.get("work_zone") or []
    if requires_zone and not zone:
        # explicit target-not-in-frame flag from perception
        if observed.scene_attributes.get("target_not_in_frame"):
            return ObservationCoverage.TARGET_NOT_IN_FRAME
        # annotation / demo without zone: treat as unknown, methods may still run on labels
        if any(
            s.name == "annotation" and s.status == StageStatus.SUCCESS
            for s in (observed.pipeline_run.stages if observed.pipeline_run else [])
        ):
            return ObservationCoverage.UNKNOWN
        # No polygon is not proof the subject is outside the frame.
        if observed.quality.coverage < 0.55:
            return ObservationCoverage.PARTIAL
        return ObservationCoverage.UNKNOWN
    if observed.quality.coverage < 0.55:
        return ObservationCoverage.PARTIAL
    return ObservationCoverage.FULL


def _structure_obs(observed: ObservedState, *labels: str):
    for label in labels:
        if label in observed.structures:
            return label, observed.structures[label]
    return None, None


def _in_zone_evidence(observed: ObservedState, labels: set[str]) -> list[str]:
    zone = observed.scene_attributes.get("work_zone") or []
    ids: list[str] = []
    for ev in observed.evidence:
        if ev.normalized_label not in labels and ev.class_name not in labels:
            continue
        # without zone geometry, accept evidence only for annotation path
        if not zone:
            ids.append(ev.evidence_id)
            continue
        # bbox center check is done at perception clip; here trust work_zone filtering
        if ev.metadata.get("outside_work_zone"):
            continue
        ids.append(ev.evidence_id)
    return ids


def _floor_reading_proven(observed: ObservedState) -> bool:
    """Annotation or verified bands can confirm. An explicit proposed scalar cannot."""
    scene = observed.scene_attributes or {}
    status = scene.get("floors_status")
    if status in {"proposed", "disputed"}:
        return False
    if status == "proven":
        return True
    derivation = str(scene.get("floors_derivation") or "")
    if derivation in {"annotation", "scene_label", "floor_bands_proven", "manual_gt"}:
        return True
    if "floors" in scene:
        stages = observed.pipeline_run.stages if observed.pipeline_run else []
        if any(s.name == "annotation" and s.status == StageStatus.SUCCESS for s in stages):
            return True
    return False


def _stash_floor_candidate(observed: ObservedState, n: int, *, origin: str, reason: str) -> None:
    """Keep a model count beside the fact. Unknown WorkFact.value stays empty."""
    scene = observed.scene_attributes
    if not isinstance(scene, dict):
        return
    scene["floor_level_candidate"] = {
        "value": int(n),
        "origin": origin,
        "reason": reason,
        "confirmed": False,
    }


def visible_floor_levels(
    observed: ObservedState,
    *,
    work_code: str = "superstructure",
    processed_at: datetime | None = None,
) -> WorkFact:
    """Count visible floor levels via floors_localize bands when present.

    Never from SAM box count. Confirmed only when floors_status=proven
    (annotation or floor_bands_proven). Proposed band counts stay UNKNOWN
    with a numeric value for inspection — never treat as proven schedule delay.
    """
    indicator_id = "visible_floor_levels"
    base = _base(
        observed=observed,
        work_code=work_code,
        indicator_id=indicator_id,
        kind=IndicatorKind.COUNT,
        method="floors_localize",
        processed_at=processed_at,
    )
    rule = indicator_rule(indicator_id) or {}
    coverage = _zone_coverage(observed, bool(rule.get("requires_work_zone")))
    base["coverage"] = coverage
    scene = observed.scene_attributes or {}
    if scene.get("floor_bands") is not None or scene.get("floors_derivation", "").startswith("floor_bands"):
        base["method"] = "floors_localize"
        base["method_version"] = str(scene.get("floors_method_version") or "structural-1")

    fail = _required_failed(observed, indicator_id)
    # Prefer localize bands over scalar VLM.
    levels = None
    if scene.get("floor_bands") and scene.get("visible_floor_levels") is not None:
        levels = scene.get("visible_floor_levels")
    if levels is None:
        levels = observed.visible_floor_levels
    if levels is None:
        levels = scene.get("visible_floor_levels")
    if levels is None and scene.get("floor_bands"):
        levels = len(scene.get("floor_bands") or [])
    if levels is None:
        levels = scene.get("structural_levels")
    if levels is None and "floors" in scene:
        levels = scene.get("floors")

    evidence_ids = [
        ev.evidence_id
        for ev in observed.evidence
        if ev.source.value == "qwen_vl" or "floor" in (ev.normalized_label or "")
    ]
    overlay = scene.get("floor_bands_overlay")
    if overlay:
        evidence_ids = list(dict.fromkeys([*evidence_ids, f"overlay:{overlay}"]))

    if fail and levels is None:
        return WorkFact(
            **base,
            certainty=WorkCertainty.PROCESSING_ERROR,
            value=None,
            unit="levels",
            limitations=[fail, "этажность без VLM/полос не выводится из боксов"],
        )

    if coverage == ObservationCoverage.TARGET_NOT_IN_FRAME and levels is None:
        return WorkFact(
            **base,
            certainty=WorkCertainty.NOT_OBSERVABLE,
            value=None,
            unit="levels",
            limitations=["целевой корпус не выделен в зоне наблюдения"],
        )

    if levels is None:
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            unit="levels",
            limitations=["visible_floor_levels не получены"],
            evidence_ids=evidence_ids,
        )

    try:
        n = int(levels)
    except (TypeError, ValueError):
        return WorkFact(
            **base,
            certainty=WorkCertainty.PROCESSING_ERROR,
            value=None,
            unit="levels",
            limitations=["невалидный ответ: этажность не число"],
        )

    if n < 0:
        return WorkFact(
            **base,
            certainty=WorkCertainty.PROCESSING_ERROR,
            value=None,
            unit="levels",
            limitations=["невалидный ответ: отрицательная этажность"],
        )

    min_conf = float(rule.get("min_confidence") or 0.55)
    conf = 0.8
    if observed.pipeline_run:
        for s in observed.pipeline_run.stages:
            if s.name in {"qwen_vl", "floors_localize"} and s.status == StageStatus.SUCCESS:
                conf = float((s.extras or {}).get("floor_confidence") or conf)

    limitations: list[str] = [str(x) for x in (scene.get("floors_prove_reasons") or [])]

    if coverage == ObservationCoverage.TARGET_NOT_IN_FRAME:
        return WorkFact(
            **base,
            certainty=WorkCertainty.NOT_OBSERVABLE,
            value=None,
            unit="levels",
            evidence_ids=evidence_ids,
            limitations=["целевой корпус не выделен; число с кадра не является этажностью объекта"],
        )

    if coverage == ObservationCoverage.PARTIAL:
        limitations.append(
            "покрытие частичное: видимые уровни не являются этажностью всего объекта"
        )
        _stash_floor_candidate(observed, n, origin="partial_frame", reason=limitations[-1])
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            unit="levels",
            evidence_ids=evidence_ids,
            limitations=limitations,
        )

    if scene.get("floors_status") == "disputed":
        return WorkFact(
            **base,
            certainty=WorkCertainty.CONTRADICTION,
            value=n,
            unit="levels",
            evidence_ids=evidence_ids,
            limitations=limitations or ["расхождение proposed vs proven / между кадрами"],
        )

    if not _floor_reading_proven(observed):
        limitations = limitations or [
            "число уровней — наблюдение кадра (proposed), не доказанная этажность объекта"
        ]
        _stash_floor_candidate(
            observed,
            n,
            origin=str(scene.get("floors_derivation") or base.get("method") or "model"),
            reason=limitations[0],
        )
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            unit="levels",
            evidence_ids=evidence_ids,
            limitations=limitations,
        )

    if conf < min_conf:
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            unit="levels",
            evidence_ids=evidence_ids,
            limitations=[f"confidence {conf:.2f} < {min_conf}"],
        )

    return WorkFact(
        **base,
        certainty=WorkCertainty.CONFIRMED,
        value=n,
        unit="levels",
        evidence_ids=evidence_ids,
        limitations=limitations,
    )


def _presence_from_structure(
    observed: ObservedState,
    *,
    work_code: str,
    indicator_id: str,
    method: str,
    labels: tuple[str, ...],
    processed_at: datetime | None = None,
) -> WorkFact:
    rule = indicator_rule(indicator_id) or {}
    base = _base(
        observed=observed,
        work_code=work_code,
        indicator_id=indicator_id,
        kind=IndicatorKind.PRESENCE,
        method=method,
        processed_at=processed_at,
    )
    coverage = _zone_coverage(observed, bool(rule.get("requires_work_zone")))
    base["coverage"] = coverage

    if coverage == ObservationCoverage.TARGET_NOT_IN_FRAME:
        return WorkFact(
            **base,
            certainty=WorkCertainty.NOT_OBSERVABLE,
            value=None,
            limitations=["целевая область не выделена; соседние объекты не учитываются"],
        )

    label, obs = _structure_obs(observed, *labels)
    evidence_ids = _in_zone_evidence(observed, set(labels))
    min_conf = float(rule.get("min_confidence") or 0.5)

    if obs is None:
        # Class key missing is not a confirmed absence. Empty detector output
        # must not become schedule_delay.
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            evidence_ids=evidence_ids,
            limitations=["признак в наблюдении не выделен; это не подтверждённое отсутствие"],
        )

    if any(n.startswith("agreement:conflict") for n in obs.notes):
        return WorkFact(
            **base,
            certainty=WorkCertainty.CONTRADICTION,
            value=None,
            evidence_ids=list(obs.evidence_ids) + evidence_ids,
            limitations=["противоречие детектора и VLM"],
        )

    visible = obs.status in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}
    if not visible:
        # «Не вижу» без отдельного доказательства отсутствия — неизвестность, не факт «работы нет».
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            evidence_ids=list(obs.evidence_ids) + evidence_ids,
            limitations=["признак не выделен на кадре; это не подтверждённое отсутствие и не завершение работы"],
        )

    if obs.confidence < min_conf:
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            evidence_ids=list(obs.evidence_ids) + evidence_ids,
            limitations=[f"confidence {obs.confidence:.2f} < {min_conf}"],
        )

    return WorkFact(
        **base,
        certainty=WorkCertainty.CONFIRMED,
        value=True,
        evidence_ids=list(obs.evidence_ids) + evidence_ids,
        limitations=["подтверждает наличие признака, не завершение работы"],
    )


def excavation_visible(observed: ObservedState, *, work_code: str = "excavation", processed_at=None) -> WorkFact:
    """Pit, disturbed soil, or an excavation entity. Equipment stays a resource count."""
    return _presence_from_structure(
        observed,
        work_code=work_code,
        indicator_id="excavation_visible",
        method="excavation_visible",
        labels=("excavation", "pit", "disturbed_ground"),
        processed_at=processed_at,
    )


def foundation_visible(observed: ObservedState, *, work_code: str = "foundation", processed_at=None) -> WorkFact:
    return _presence_from_structure(
        observed,
        work_code=work_code,
        indicator_id="foundation_visible",
        method="foundation_visible",
        labels=("foundation",),
        processed_at=processed_at,
    )


def facade_visible(observed: ObservedState, *, work_code: str = "facade", processed_at=None) -> WorkFact:
    return _presence_from_structure(
        observed,
        work_code=work_code,
        indicator_id="facade_visible",
        method="facade_visible",
        labels=("facade",),
        processed_at=processed_at,
    )


def roof_visible(observed: ObservedState, *, work_code: str = "facade", processed_at=None) -> WorkFact:
    return _presence_from_structure(
        observed,
        work_code=work_code,
        indicator_id="roof_visible",
        method="roof_visible",
        labels=("roof",),
        processed_at=processed_at,
    )


def windows_visible(observed: ObservedState, *, work_code: str = "facade", processed_at=None) -> WorkFact:
    return _presence_from_structure(
        observed,
        work_code=work_code,
        indicator_id="windows_visible",
        method="windows_visible",
        labels=("window_opening", "window"),
        processed_at=processed_at,
    )


def equipment_count(
    observed: ObservedState,
    *,
    work_code: str = "excavation",
    equipment_class: str,
    processed_at=None,
) -> WorkFact:
    indicator_id = f"equipment:{equipment_class}"
    base = _base(
        observed=observed,
        work_code=work_code,
        indicator_id=indicator_id,
        kind=IndicatorKind.RESOURCE_COUNT,
        method="equipment_count",
        processed_at=processed_at,
    )
    coverage = _zone_coverage(observed, True)
    base["coverage"] = coverage
    obs = observed.equipment.get(equipment_class)
    # aliases
    if obs is None and equipment_class == "dump_truck":
        obs = observed.equipment.get("truck")
    if obs is None and equipment_class == "roller":
        obs = observed.equipment.get("road_roller")
    if obs is None and equipment_class == "crane_manipulator":
        obs = observed.equipment.get("mobile_crane")

    if obs is None:
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            unit="count",
            limitations=["класс техники в сыром ответе не выделен; это не подтверждённый ноль"],
        )

    if any(n.startswith("agreement:conflict") for n in obs.notes):
        return WorkFact(
            **base,
            certainty=WorkCertainty.CONTRADICTION,
            value=None,
            unit="count",
            evidence_ids=list(obs.evidence_ids),
            limitations=["конфликт моделей по технике"],
        )

    count = obs.count_visible
    if count is None and isinstance(obs.value, (int, float)):
        count = int(obs.value)
    if count is None and obs.status in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}:
        count = 1
    if count is None:
        return WorkFact(**base, certainty=WorkCertainty.UNKNOWN, value=None, unit="count")

    return WorkFact(
        **base,
        certainty=WorkCertainty.CONFIRMED,
        value=int(count),
        unit="count",
        evidence_ids=list(obs.evidence_ids),
        limitations=["ресурсный факт; не объём выполненных работ"],
    )


def divider_stage_sign(observed: ObservedState, *, work_code: str = "divider", processed_at=None) -> WorkFact:
    base = _base(
        observed=observed,
        work_code=work_code,
        indicator_id="divider_stage_sign",
        kind=IndicatorKind.STAGE_SIGN,
        method="divider_stage_sign",
        processed_at=processed_at,
    )
    base["coverage"] = ObservationCoverage.FULL
    signs: list[str] = []
    evidence_ids: list[str] = []
    for label, obs in {**observed.structures, **observed.equipment}.items():
        if obs.status not in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}:
            continue
        if label in {"excavator", "bulldozer", "dump_truck", "truck", "loader", "road_roller", "roller"}:
            signs.append(f"equipment:{label}")
            evidence_ids.extend(obs.evidence_ids)
    summary = (observed.observation.summary or "").lower()
    for token in ("бордюр", "curb", "отсып", "насып", "divider", "gravel"):
        if token in summary:
            signs.append(f"narrative:{token}")

    structural = [item for item in signs if not item.startswith("equipment:")]
    if not structural:
        # Equipment in frame is a resource observation, not the divider stage.
        return WorkFact(
            **base,
            certainty=WorkCertainty.UNKNOWN,
            value=None,
            evidence_ids=evidence_ids,
            limitations=[
                "техника в кадре — ресурсное наблюдение; без отсыпки, бордюра или полотна стадия разделителя не подтверждена"
            ],
        )

    return WorkFact(
        **base,
        certainty=WorkCertainty.CONFIRMED,
        value=True,
        evidence_ids=evidence_ids,
        limitations=[f"признаки: {', '.join(signs[:6])}; метры не измеряются"],
    )


def finishing_not_observable(observed: ObservedState, *, work_code: str = "finishing", processed_at=None) -> WorkFact:
    base = _base(
        observed=observed,
        work_code=work_code,
        indicator_id="finishing_observable",
        kind=IndicatorKind.PRESENCE,
        method="finishing_not_observable",
        processed_at=processed_at,
    )
    return WorkFact(
        **base,
        certainty=WorkCertainty.NOT_OBSERVABLE,
        value=None,
        coverage=ObservationCoverage.TARGET_NOT_IN_FRAME,
        limitations=["внутренняя отделка с внешнего кадра не определяется"],
    )


def unimplemented(
    observed: ObservedState,
    *,
    work_code: str,
    indicator_id: str,
    processed_at=None,
) -> WorkFact:
    rule = indicator_rule(indicator_id) or {}
    kind_raw = str(rule.get("kind") or "presence")
    try:
        kind = IndicatorKind(kind_raw)
    except ValueError:
        kind = IndicatorKind.PRESENCE
    base = _base(
        observed=observed,
        work_code=work_code,
        indicator_id=indicator_id,
        kind=kind,
        method="unimplemented",
        processed_at=processed_at,
    )
    return WorkFact(
        **base,
        certainty=WorkCertainty.MEASUREMENT_UNIMPLEMENTED,
        value=None,
        unit=rule.get("unit"),
        limitations=["метод измерения не реализован (запись YAML ≠ реализация)"],
    )


REGISTRY: dict[str, MethodFn] = {
    "visible_floor_levels": visible_floor_levels,
    "excavation_visible": excavation_visible,
    "foundation_visible": foundation_visible,
    "facade_visible": facade_visible,
    "roof_visible": roof_visible,
    "windows_visible": windows_visible,
    "equipment_count": equipment_count,
    "divider_stage_sign": divider_stage_sign,
    "finishing_not_observable": finishing_not_observable,
}


def run_method(name: str | None, observed: ObservedState, **kwargs) -> WorkFact:
    if not name or name not in REGISTRY:
        return unimplemented(
            observed,
            work_code=str(kwargs.get("work_code") or "unknown"),
            indicator_id=str(kwargs.get("indicator_id") or "unknown"),
            processed_at=kwargs.get("processed_at"),
        )
    return REGISTRY[name](observed, **{k: v for k, v in kwargs.items() if k != "indicator_id"})
