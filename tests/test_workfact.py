"""WorkFact / PlannedIndicator contract tests (no GPU)."""

from __future__ import annotations

from datetime import date, datetime

from sitewatch.domain.contracts import (
    ActualState,
    ImageQuality,
    ObservationNarrative,
    ObservedState,
    ObservationQuality,
    PipelineRun,
    PipelineStageResult,
    WorkFact,
)
from sitewatch.domain.enums import (
    AlertType,
    CheckOutcome,
    CoverageLevel,
    IndicatorKind,
    ObservationCoverage,
    StageStatus,
    Visibility,
    WorkCertainty,
)
from sitewatch.ksg.expected import build_expected_state
from sitewatch.works.compare import check_one, freshness_hours
from sitewatch.works.derive import derive_work_facts
from sitewatch.works.methods import divider_stage_sign, excavation_visible, visible_floor_levels
from sitewatch.deviation.engine import DeviationEngine


def _observed(
    *,
    floors: int | None = None,
    structures: dict | None = None,
    equipment: dict | None = None,
    stages: list[PipelineStageResult] | None = None,
    work_zone: list | None = None,
    captured_at: str = "2026-09-22T12:00:00",
) -> ObservedState:
    run = PipelineRun(
        run_id="run1",
        object_id="site_001",
        zone_id="house6",
        camera_id="cam",
        pipeline_version="workfact-1",
        started_at=datetime.fromisoformat(captured_at),
        finished_at=datetime.fromisoformat(captured_at),
        processed_at=datetime.fromisoformat(captured_at),
        stages=stages
        or [
            PipelineStageResult(name="annotation", status=StageStatus.SUCCESS),
        ],
        outcome="succeeded",
    )
    scene = {}
    if floors is not None:
        scene["floors"] = floors
        scene["visible_floor_levels"] = floors
        # Annotation / GT path: number is proven, not a loose VLM proposal.
        scene["floors_status"] = "proven"
        scene["floors_derivation"] = "annotation"
    if work_zone is not None:
        scene["work_zone"] = work_zone
    return ObservedState(
        frame_id="f1",
        object_id="site_001",
        zone_id="house6",
        camera_id="cam",
        captured_at=datetime.fromisoformat(captured_at),
        structures=structures or {},
        equipment=equipment or {},
        observation=ObservationNarrative(summary="test"),
        pipeline_run=run,
        scene_attributes=scene,
        visible_floor_levels=floors,
    )


def test_planned_indicators_split_facade_and_roof():
    expected = build_expected_state(
        object_id="site_001",
        zone_id="house6",
        on_date=date(2026, 10, 15),
        stage="facade",
        expected={"floors": 6, "roof": True, "facade": True, "windows": 0},
        schedule_row_id="row-facade",
    )
    ids = {item.indicator_id for item in expected.planned_indicators}
    assert "facade_visible" in ids
    assert "roof_visible" in ids
    assert "visible_floor_levels" in ids
    # stage facade lists windows_visible; confirms presence-only, not completion
    facade = next(i for i in expected.planned_indicators if i.indicator_id == "facade_visible")
    assert "не завершение" in facade.confirms.lower()
    assert facade.schedule_row_id == "row-facade"


def test_dividing_line_m_is_unimplemented_not_schedule_delay():
    expected = build_expected_state(
        object_id="site_001",
        zone_id="road_alley",
        on_date=date(2016, 11, 3),
        stage="divider",
        expected={"dividing_line_m": 18},
        schedule_row_id="row-road",
    )
    ids = {i.indicator_id for i in expected.planned_indicators}
    assert "dividing_line_m" in ids
    assert "divider_stage_sign" in ids

    actual = ActualState(
        object_id="site_001",
        zone_id="road_alley",
        timestamp=datetime(2016, 11, 3, 12, 0, 0),
        camera_code="cam",
        quality=ObservationQuality(visibility=Visibility.GOOD, coverage=CoverageLevel.FULL, n_frames=3),
        work_facts={
            "dividing_line_m": WorkFact(
                work_code="divider",
                indicator_id="dividing_line_m",
                kind=IndicatorKind.LENGTH_M,
                certainty=WorkCertainty.MEASUREMENT_UNIMPLEMENTED,
                value=None,
                unit="m",
                captured_at=datetime(2016, 11, 3, 12, 0, 0),
                as_of=date(2016, 11, 3),
                method="unimplemented",
            ),
            "divider_stage_sign": WorkFact(
                work_code="divider",
                indicator_id="divider_stage_sign",
                kind=IndicatorKind.STAGE_SIGN,
                certainty=WorkCertainty.CONFIRMED,
                value=True,
                captured_at=datetime(2016, 11, 3, 12, 0, 0),
                as_of=date(2016, 11, 3),
                method="divider_stage_sign",
            ),
        },
    )
    engine = DeviationEngine()
    found = engine.evaluate(expected, actual)
    types = {item.alert_type for item in found}
    assert AlertType.MEASUREMENT_UNIMPLEMENTED in types
    assert AlertType.SCHEDULE_DELAY not in types
    assert AlertType.NO_DYNAMICS not in types


def test_floors_method_not_from_missing_vlm():
    observed = _observed(
        floors=None,
        stages=[
            PipelineStageResult(name="sam3", status=StageStatus.SUCCESS),
            PipelineStageResult(name="qwen_vl", status=StageStatus.FAILED, error="oom"),
        ],
        work_zone=[[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]],
    )
    fact = visible_floor_levels(observed, work_code="superstructure")
    assert fact.certainty == WorkCertainty.PROCESSING_ERROR
    assert fact.value is None


def test_floors_confirmed_from_scene_annotation():
    observed = _observed(
        floors=6,
        work_zone=[[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]],
    )
    fact = visible_floor_levels(observed)
    assert fact.certainty == WorkCertainty.CONFIRMED
    assert fact.value == 6


def test_confirmed_presence_is_not_completion():
    observed = _observed(
        structures={},
        work_zone=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
    )
    # empty success → confirmed False presence, not «work done»
    from sitewatch.domain.contracts import EntityObservation
    from sitewatch.domain.enums import EntityVisibility, MeasurementType

    observed.structures["facade"] = EntityObservation(
        status=EntityVisibility.VISIBLE,
        measurement=MeasurementType.PRESENCE,
        value=True,
        confidence=0.9,
        evidence_ids=["e1"],
    )
    facts = derive_work_facts(observed, work_code="facade", indicator_ids=["facade_visible", "roof_visible"])
    assert facts["facade_visible"].certainty == WorkCertainty.CONFIRMED
    assert facts["facade_visible"].value is True
    assert facts["roof_visible"].certainty == WorkCertainty.UNKNOWN
    assert facts["roof_visible"].value is None
    assert "не завершение" in (facts["facade_visible"].confirms or "").lower()
    # roof not present → confirmed absent, does not close facade work
    assert facts["roof_visible"].value is False or facts["roof_visible"].certainty in {
        WorkCertainty.CONFIRMED,
        WorkCertainty.UNKNOWN,
    }


def test_freshness_uses_evaluation_as_of_not_today():
    captured = datetime(2016, 11, 3, 12, 0, 0)
    age = freshness_hours(captured_at=captured, evaluation_as_of=date(2016, 11, 3))
    assert age < 24
    # relative to today would be years; as_of keeps it fresh for historical replay
    age_future = freshness_hours(captured_at=captured, evaluation_as_of=date(2016, 11, 10))
    assert age_future > 24 * 6


def test_no_observation_after_is_not_no_dynamics():
    planned = build_expected_state(
        object_id="site_001",
        zone_id="house6",
        on_date=date(2026, 12, 31),
        stage="superstructure",
        expected={"floors": 6},
        schedule_row_id="r1",
    ).planned_indicators[0]
    result = check_one(
        planned,
        None,
        evaluation_as_of=date(2026, 12, 31),
        last_observation_date=date(2026, 12, 24),
    )
    assert result.outcome == CheckOutcome.NO_OBSERVATION_AFTER


def test_schedule_delay_requires_confirmed_work_fact():
    expected = build_expected_state(
        object_id="site_001",
        zone_id="building_01",
        on_date=date(2026, 9, 22),
        stage="superstructure",
        expected={"floors": 6},
        schedule_row_id="b1",
    )
    # Actual with legacy zeros but NO work_facts → insufficient, not delay with 0
    actual = ActualState(
        object_id="site_001",
        zone_id="building_01",
        timestamp=datetime(2026, 9, 22, 12, 0, 0),
        camera_code="cam",
        quality=ObservationQuality(
            visibility=Visibility.GOOD,
            coverage=CoverageLevel.FULL,
            n_frames=3,
            mean_model_confidence=0.9,
        ),
        work_facts={},
    )
    engine = DeviationEngine()
    found = engine.evaluate(expected, actual)
    types = {item.alert_type for item in found}
    assert AlertType.SCHEDULE_DELAY not in types
    assert AlertType.INSUFFICIENT_EVIDENCE in types


def test_target_without_zone_needs_capture():
    observed = _observed(floors=None, work_zone=None, stages=[
        PipelineStageResult(name="sam3", status=StageStatus.SUCCESS),
        PipelineStageResult(name="qwen_vl", status=StageStatus.SUCCESS),
    ])
    observed.scene_attributes["target_not_in_frame"] = True
    fact = visible_floor_levels(observed)
    assert fact.certainty in {WorkCertainty.NOT_OBSERVABLE, WorkCertainty.UNKNOWN, WorkCertainty.PROCESSING_ERROR}
    assert fact.value is None


def test_equipment_does_not_confirm_excavation():
    from sitewatch.domain.contracts import EntityObservation
    from sitewatch.domain.enums import EntityVisibility, MeasurementType
    from sitewatch.works.methods import excavation_visible

    observed = _observed(stages=[PipelineStageResult(name="sam3", status=StageStatus.SUCCESS)])
    observed.equipment["bulldozer"] = EntityObservation(
        status=EntityVisibility.VISIBLE,
        measurement=MeasurementType.COUNT,
        value=1,
        confidence=0.9,
        evidence_ids=["eq1"],
    )
    fact = excavation_visible(observed)
    assert fact.certainty == WorkCertainty.UNKNOWN
    assert fact.value is None


def test_reinterpret_keeps_raw_and_drops_equipment_excavation():
    from sitewatch.works.reinterpret import reinterpret_work_facts

    payload = {
        "work_facts": {
            "excavation_visible": {
                "certainty": "confirmed",
                "value": True,
                "limitations": ["признак земляных работ по технике в зоне; не объём выемки"],
                "evidence_ids": ["e1"],
            },
            "facade_visible": {
                "certainty": "confirmed",
                "value": True,
                "limitations": ["подтверждает наличие признака, не завершение работы"],
                "evidence_ids": ["f1"],
            },
        },
        "scene_attributes": {"floors_status": "proposed"},
        "entities": {"bulldozer": {"current_value": 1}},
    }
    out = reinterpret_work_facts(payload, archive=True)
    assert out["work_facts"]["excavation_visible"]["certainty"] == "unknown"
    assert out["work_facts"]["excavation_visible"]["value"] is None
    assert out["work_facts"]["facade_visible"]["value"] is True
    assert out["entities"]["bulldozer"]["current_value"] == 1
    assert out["work_facts_archive"][0]["work_facts"]["excavation_visible"]["value"] is True


def test_divider_absence_of_proxy_classes_is_unknown():
    observed = _observed(
        stages=[PipelineStageResult(name="sam3", status=StageStatus.SUCCESS)],
    )
    fact = divider_stage_sign(observed)
    assert fact.certainty == WorkCertainty.UNKNOWN
    assert fact.value is None


def test_unconfirmed_floor_count_is_a_candidate_not_the_fact():
    observed = _observed(
        floors=None,
        stages=[PipelineStageResult(name="qwen_vl", status=StageStatus.SUCCESS)],
        work_zone=[[0.2, 0.2], [0.8, 0.2], [0.8, 0.9], [0.2, 0.9]],
    )
    observed.visible_floor_levels = 5
    observed.scene_attributes.update(
        {
            "visible_floor_levels": 5,
            "floor_bands": [{"index": 1}],
            "floors_status": "proposed",
            "floors_derivation": "floor_bands_proposed",
            "floors_prove_reasons": ["needs_open_frame_or_gt_match"],
        }
    )
    fact = visible_floor_levels(observed)
    assert fact.certainty == WorkCertainty.UNKNOWN
    assert fact.value is None
    assert observed.scene_attributes["floor_level_candidate"]["value"] == 5
    assert observed.scene_attributes["floor_level_candidate"]["confirmed"] is False


def test_detach_unconfirmed_floor_value_keeps_candidate():
    from sitewatch.works.reinterpret import detach_unconfirmed_floor_value

    payload = {
        "work_facts": {
            "visible_floor_levels": {
                "certainty": "unknown",
                "value": 4,
                "method": "floors_localize",
                "limitations": ["ambiguous_bands"],
            }
        },
        "scene_attributes": {"floors_status": "proposed"},
    }
    detach_unconfirmed_floor_value(payload)
    assert payload["work_facts"]["visible_floor_levels"]["value"] is None
    assert payload["scene_attributes"]["floor_level_candidate"]["value"] == 4
    assert payload["scene_attributes"]["floor_level_candidate"]["origin"] == "floors_localize"


def test_brightness_does_not_delete_a_level():
    import numpy as np

    from sitewatch.perception.floors_localize import FloorBand, gate_bands_on_facade

    crop = np.zeros((100, 40, 3), dtype=np.uint8)
    crop[:] = (80, 80, 80)
    crop[80:] = (210, 210, 210)
    bands = [
        FloorBand(index=1, y0=0.10, y1=0.40),
        FloorBand(index=2, y0=0.40, y1=0.70),
        FloorBand(index=3, y0=0.72, y1=0.98),
    ]
    kept, _notes = gate_bands_on_facade(crop, bands)
    assert [band.index for band in kept] == [1, 2, 3]
