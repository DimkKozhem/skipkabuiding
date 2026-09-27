from datetime import date, datetime

from sitewatch.cv.aggregator import detections_to_actual_state
from sitewatch.deviation.engine import DeviationEngine
from sitewatch.domain.contracts import BBox, Detection, EvidenceRef, ExpectedState
from sitewatch.domain.enums import AlertType


def _state(ts: str, equipment: dict[str, int] | None = None, floors: int = 4, n_frames: int = 3, elements: dict | None = None, camera: str = "cam"):
    dets = []
    for name, count in (equipment or {}).items():
        for _ in range(count):
            dets.append(
                Detection(
                    class_name=name,
                    bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                    confidence=0.9,
                    model_name="test",
                )
            )
    scene = {"floors": floors, "foundation": True, "visibility": "good", "coverage": "full"}
    if elements:
        scene.update(elements)
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="zone_a",
        timestamp=datetime.fromisoformat(ts),
        camera_code=camera,
        detections=dets,
        scene=scene,
        n_frames=n_frames,
    )
    if elements:
        for key, value in elements.items():
            if key in ("visibility", "coverage"):
                continue
            if isinstance(value, bool):
                continue
            from sitewatch.domain.contracts import CountStat

            if key in state.elements:
                state.elements[key] = CountStat(count=int(value), max_confidence=0.9)
            else:
                state.elements[key] = CountStat(count=int(value), max_confidence=0.9)
    # WorkFact path is the plan/fact source of truth.
    from sitewatch.domain.contracts import WorkFact
    from sitewatch.domain.enums import IndicatorKind, ObservationCoverage, WorkCertainty

    stamp = datetime.fromisoformat(ts)
    facts = {}
    if floors is not None and int(floors) > 0:
        facts["visible_floor_levels"] = WorkFact(
            work_code="superstructure",
            indicator_id="visible_floor_levels",
            kind=IndicatorKind.COUNT,
            certainty=WorkCertainty.CONFIRMED,
            value=int(floors),
            unit="levels",
            coverage=ObservationCoverage.FULL,
            captured_at=stamp,
            as_of=stamp.date(),
            method="visible_floor_levels",
            confirms="число видимых этажей целевого корпуса",
        )
    for name, count in (equipment or {}).items():
        facts[f"equipment:{name}"] = WorkFact(
            work_code="excavation",
            indicator_id=f"equipment:{name}",
            kind=IndicatorKind.RESOURCE_COUNT,
            certainty=WorkCertainty.CONFIRMED,
            value=int(count),
            unit="count",
            coverage=ObservationCoverage.FULL,
            captured_at=stamp,
            as_of=stamp.date(),
            method="equipment_count",
            confirms=f"ресурс {name}",
        )
    foundation_flag = bool(scene.get("foundation", True))
    facts["foundation_visible"] = WorkFact(
        work_code="foundation",
        indicator_id="foundation_visible",
        kind=IndicatorKind.PRESENCE,
        certainty=WorkCertainty.CONFIRMED,
        value=foundation_flag,
        coverage=ObservationCoverage.FULL,
        captured_at=stamp,
        as_of=stamp.date(),
        method="foundation_visible",
        confirms="видимый признак фундамента",
    )
    state.work_facts = facts
    return state


def _expected(on: str, stage: str, zone: str = "zone_a", end_date: str | None = None, start_date: str | None = None, **expected):
    from sitewatch.ksg.expected import build_expected_state

    return build_expected_state(
        object_id="site_001",
        zone_id=zone,
        on_date=date.fromisoformat(on),
        stage=stage,
        expected=expected,
        start_date=date.fromisoformat(start_date) if start_date else None,
        end_date=date.fromisoformat(end_date) if end_date else None,
    )


def _evidence(ts: str, oid: str = "obs_001") -> EvidenceRef:
    return EvidenceRef(media_path="a.jpg", timestamp=datetime.fromisoformat(ts), observation_id=oid)


def test_missing_equipment():
    engine = DeviationEngine()
    actual = _state("2026-09-18T10:30:00", {"excavator": 1}, n_frames=3)
    expected = _expected("2026-09-18", "excavation", floors=0, foundation=False)
    found = engine.evaluate(expected, actual, evidence=[_evidence("2026-09-18T10:30:00")])
    types = {item.alert_type for item in found}
    assert AlertType.MISSING_EQUIPMENT in types
    missing = next(item for item in found if item.alert_type == AlertType.MISSING_EQUIPMENT)
    assert missing.expected["dump_truck"] == 2
    assert missing.observed["dump_truck"] == 0
    assert "obs_001" in missing.evidence_ids
    assert "Самосвал" in missing.message


def test_absence_not_proven_from_single_frame():
    engine = DeviationEngine()
    actual = _state("2026-09-18T10:30:00", {"excavator": 1}, n_frames=1)
    expected = _expected("2026-09-18", "excavation")
    found = engine.evaluate(expected, actual)
    types = {item.alert_type for item in found}
    assert AlertType.MISSING_EQUIPMENT not in types
    assert AlertType.INSUFFICIENT_EVIDENCE in types


def test_normal_no_equipment_alert():
    engine = DeviationEngine()
    actual = _state("2026-09-18T10:30:00", {"excavator": 1, "dump_truck": 2}, n_frames=3)
    expected = _expected("2026-09-18", "excavation")
    found = engine.evaluate(expected, actual)
    types = {item.alert_type for item in found}
    assert AlertType.MISSING_EQUIPMENT not in types
    assert AlertType.UNEXPECTED_EQUIPMENT not in types


def test_dump_truck_three_is_ok():
    engine = DeviationEngine()
    actual = _state("2026-09-18T10:30:00", {"excavator": 1, "dump_truck": 3}, n_frames=3)
    expected = _expected("2026-09-18", "excavation")
    found = engine.evaluate(expected, actual)
    assert not any(item.alert_type == AlertType.MISSING_EQUIPMENT for item in found)


def test_unexpected_equipment():
    engine = DeviationEngine()
    actual = _state("2026-09-18T10:30:00", {"excavator": 1, "dump_truck": 2, "concrete_mixer": 1}, n_frames=3)
    expected = _expected("2026-09-18", "excavation")
    found = engine.evaluate(expected, actual)
    types = {item.alert_type for item in found}
    assert AlertType.UNEXPECTED_EQUIPMENT in types
    unexpected = next(item for item in found if item.alert_type == AlertType.UNEXPECTED_EQUIPMENT)
    assert unexpected.observed["concrete_mixer"] == 1


def test_schedule_delay_when_expected_exceeds_actual():
    engine = DeviationEngine()
    actual = _state("2026-09-22T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3)
    expected = _expected("2026-09-22", "superstructure", floors=6, foundation=True)
    found = engine.evaluate(expected, actual, evidence=[_evidence("2026-09-22T12:00:00")])
    assert AlertType.SCHEDULE_DELAY in {item.alert_type for item in found}
    gap = next(item for item in found if item.alert_type == AlertType.SCHEDULE_DELAY)
    assert gap.expected["indicator_id"] == "visible_floor_levels"
    assert gap.expected["value"] == 6
    assert gap.observed["value"] == 4


def test_schedule_delay_when_end_date_passed_and_fact_below_plan():
    engine = DeviationEngine()
    actual = _state("2026-09-25T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3)
    expected = _expected(
        "2026-09-25", "superstructure",
        end_date="2026-09-20", start_date="2026-09-15",
        floors=6, foundation=True,
    )
    found = engine.evaluate(expected, actual, evidence=[_evidence("2026-09-25T12:00:00")])
    delays = [item for item in found if item.alert_type == AlertType.SCHEDULE_DELAY]
    assert delays
    assert delays[0].rule_id == "work.deviation_count"
    soft = delays[0].message.lower()
    for banned in ("сорван", "нарушил", "остановлен", "не соответствует проекту"):
        assert banned not in soft


def test_schedule_delay_future_end_date_keeps_metric_rule():
    engine = DeviationEngine()
    actual = _state("2026-09-22T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3)
    expected = _expected(
        "2026-09-22", "superstructure",
        end_date="2026-09-30", start_date="2026-09-22",
        floors=6, foundation=True,
    )
    found = engine.evaluate(expected, actual, evidence=[_evidence("2026-09-22T12:00:00")])
    delays = [item for item in found if item.alert_type == AlertType.SCHEDULE_DELAY]
    assert delays
    assert delays[0].rule_id == "work.deviation_count"
    assert delays[0].expected["value"] == 6
    assert delays[0].observed["value"] == 4


def test_no_date_based_schedule_delay_when_fact_meets_plan():
    engine = DeviationEngine()
    actual = _state("2026-09-25T12:00:00", {"mobile_crane": 1}, floors=6, n_frames=3)
    expected = _expected(
        "2026-09-25", "superstructure",
        end_date="2026-09-20", start_date="2026-09-15",
        floors=6, foundation=True,
    )
    found = engine.evaluate(expected, actual, evidence=[_evidence("2026-09-25T12:00:00")])
    assert AlertType.SCHEDULE_DELAY not in {item.alert_type for item in found}


def test_insufficient_evidence_when_end_date_passed_and_progress_unknown():
    engine = DeviationEngine()
    actual = _state("2026-09-25T12:00:00", {"mobile_crane": 1}, n_frames=3, floors=0)
    actual.work_facts.pop("visible_floor_levels", None)
    expected = _expected(
        "2026-09-25", "superstructure",
        end_date="2026-09-20", start_date="2026-09-15",
        floors=6, foundation=True,
    )
    found = engine.evaluate(expected, actual, evidence=[_evidence("2026-09-25T12:00:00")])
    types = {item.alert_type for item in found}
    assert AlertType.SCHEDULE_DELAY not in types
    assert AlertType.INSUFFICIENT_EVIDENCE in types
    insuf = next(item for item in found if item.alert_type == AlertType.INSUFFICIENT_EVIDENCE)
    assert insuf.rule_id.startswith("work.")


def test_missing_element_foundation_presence():
    engine = DeviationEngine()
    actual = _state(
        "2026-09-18T10:30:00", {"mobile_crane": 1}, n_frames=3, floors=0,
        elements={"foundation": False},
    )
    actual.scene_attributes["foundation"] = False
    actual.work_facts["foundation_visible"].value = False
    expected = _expected("2026-09-18", "foundation", foundation=True)
    found = engine.evaluate(expected, actual)
    assert any(item.rule_id == "work.deviation_presence" for item in found)


def test_no_dynamics_emitted_when_stable_and_schedule_moves():
    from sitewatch.ksg.expected import build_expected_state

    engine = DeviationEngine()
    history = [
        _state("2026-09-01T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3, camera="cam_building"),
        _state("2026-09-08T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3, camera="cam_building"),
        _state("2026-09-15T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3, camera="cam_building"),
    ]
    actual = _state("2026-09-22T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3, camera="cam_building")
    for item in history + [actual]:
        item.zone_id = "building_01"
    series = [
        build_expected_state(
            object_id="site_001", zone_id="building_01",
            on_date=date.fromisoformat(day), stage="superstructure",
            expected={"floors": floors, "foundation": True},
            schedule_row_id=f"row-{day}",
        )
        for day, floors in [("2026-09-01", 4), ("2026-09-08", 4), ("2026-09-15", 5), ("2026-09-22", 6)]
    ]
    found = engine.evaluate(
        series[-1], actual, history=history, expected_series=series,
        evidence=[
            _evidence("2026-09-01T12:00:00", "obs_1"),
            _evidence("2026-09-08T12:00:00", "obs_2"),
            _evidence("2026-09-15T12:00:00", "obs_3"),
            _evidence("2026-09-22T12:00:00", "obs_4"),
        ],
    )
    types = {item.alert_type for item in found}
    assert AlertType.NO_DYNAMICS in types
    assert AlertType.SCHEDULE_DELAY in types
    nd = next(item for item in found if item.alert_type == AlertType.NO_DYNAMICS)
    assert nd.title == "Признаки отсутствия строительной динамики"
    assert nd.rule_id.startswith("temporal.no_dynamics")
    assert "Выявлены признаки отсутствия строительной динамики" in nd.message
    assert nd.related_dates == ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]
    assert nd.observed["n_states"] == 4
    assert nd.observed["indicator_id"] == "visible_floor_levels"


def test_no_dynamics_not_when_schedule_not_advancing():
    engine = DeviationEngine()
    history = [
        _state("2026-09-01T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3),
        _state("2026-09-08T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3),
        _state("2026-09-15T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3),
    ]
    actual = _state("2026-09-22T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3)
    series = [
        ExpectedState(
            date=date.fromisoformat(day),
            object_id="site_001",
            zone_id="zone_a",
            stage="superstructure",
            expected={"floors": 4, "foundation": True},
        )
        for day in ["2026-09-01", "2026-09-08", "2026-09-15", "2026-09-22"]
    ]
    found = engine.evaluate(series[-1], actual, history=history, expected_series=series)
    types = {item.alert_type for item in found}
    assert AlertType.NO_DYNAMICS not in types
    assert AlertType.SCHEDULE_DELAY not in types


def test_no_dynamics_not_when_floors_increase():
    engine = DeviationEngine()
    history = [
        _state("2026-09-01T12:00:00", {"mobile_crane": 1}, floors=4, n_frames=3),
        _state("2026-09-15T12:00:00", {"mobile_crane": 1}, floors=5, n_frames=3),
    ]
    actual = _state("2026-09-22T12:00:00", {"mobile_crane": 1}, floors=6, n_frames=3)
    series = [
        ExpectedState(
            date=date.fromisoformat(day),
            object_id="site_001",
            zone_id="zone_a",
            stage="superstructure",
            expected={"floors": floors, "foundation": True},
        )
        for day, floors in [("2026-09-01", 4), ("2026-09-15", 5), ("2026-09-22", 6)]
    ]
    found = engine.evaluate(series[-1], actual, history=history, expected_series=series)
    types = {item.alert_type for item in found}
    assert AlertType.NO_DYNAMICS not in types
    assert AlertType.SCHEDULE_DELAY not in types
