from datetime import datetime

from sitewatch.cv.aggregator import detections_to_actual_state
from sitewatch.domain.contracts import ExpectedState
from sitewatch.domain.enums import StateChangeKind
from sitewatch.temporal.engine import TemporalEngine, analyze_state_change


def _state(ts: str, floors: int, camera: str = "cam", columns: int | None = None):
    scene = {"floors": floors, "visibility": "good", "coverage": "full"}
    if columns is not None:
        scene["columns"] = columns
    state = detections_to_actual_state(
        object_id="s",
        zone_id="z",
        timestamp=datetime.fromisoformat(ts),
        camera_code=camera,
        detections=[],
        scene=scene,
    )
    if columns is not None:
        from sitewatch.domain.contracts import CountStat

        state.elements["columns"] = CountStat(count=columns, max_confidence=0.9)
    return state


def test_analyze_state_change_unchanged():
    a = _state("2026-09-01T12:00:00", 4, columns=12)
    b = _state("2026-09-08T12:00:00", 4, columns=12)
    result = analyze_state_change(a, b)
    assert result.changed is False
    assert result.kind == StateChangeKind.UNCHANGED
    assert result.comparable is True
    assert "floors" in result.stable_elements
    assert "columns" in result.stable_elements
    assert result.changed_elements == []


def test_equipment_count_change_is_reported_separately_from_structure():
    from sitewatch.domain.contracts import CountStat

    a = _state("2026-09-01T12:00:00", 4, columns=12)
    b = _state("2026-09-08T12:00:00", 4, columns=12)
    a.equipment["dump_truck"] = CountStat(count=3, max_confidence=0.9)
    b.equipment["dump_truck"] = CountStat(count=1, max_confidence=0.9)
    b.equipment["excavator"] = CountStat(count=1, max_confidence=0.8)
    result = analyze_state_change(a, b)
    assert result.changed is False
    assert result.kind == StateChangeKind.UNCHANGED
    assert result.changed_equipment == ["dump_truck", "excavator"]
    transition = TemporalEngine().transition(a, b)
    assert transition.equipment_deltas["dump_truck"] == -2
    assert transition.equipment_deltas["excavator"] == 1
    assert transition.changed is False


def test_analyze_state_change_changed():
    a = _state("2026-09-01T12:00:00", 4, columns=10)
    b = _state("2026-09-08T12:00:00", 4, columns=12)
    result = analyze_state_change(a, b)
    assert result.changed is True
    assert result.kind == StateChangeKind.CHANGED
    assert "columns" in result.changed_elements


def test_analyze_state_change_unknown_missing_camera():
    a = _state("2026-09-01T12:00:00", 4)
    a.camera_code = None
    b = _state("2026-09-08T12:00:00", 4)
    result = analyze_state_change(a, b)
    assert result.changed is False
    assert result.kind == StateChangeKind.UNKNOWN
    assert result.comparable is False


def test_analyze_state_change_unknown_different_cameras():
    a = _state("2026-09-01T12:00:00", 4, "cam_a")
    b = _state("2026-09-08T12:00:00", 4, "cam_b")
    result = analyze_state_change(a, b)
    assert result.kind == StateChangeKind.UNKNOWN
    assert result.comparable is False
    assert result.same_camera is False


def test_analyze_state_change_unknown_different_orientation():
    a = _state("2026-09-01T12:00:00", 4, "cam")
    b = _state("2026-09-08T12:00:00", 4, "cam")
    a.scene_attributes["orientation"] = "N"
    b.scene_attributes["orientation"] = "SW"
    result = analyze_state_change(a, b)
    assert result.kind == StateChangeKind.UNKNOWN
    assert result.comparable is False
    assert any("orientation" in note for note in result.notes)


def test_no_dynamics_when_schedule_advances_and_state_is_stable():
    engine = TemporalEngine()
    states = [
        _state("2026-09-01T12:00:00", 4),
        _state("2026-09-08T12:00:00", 4),
        _state("2026-09-15T12:00:00", 4),
        _state("2026-09-22T12:00:00", 4),
    ]
    series = [
        ExpectedState(
            date=item.timestamp.date(),
            object_id="s",
            zone_id="z",
            stage="superstructure",
            expected={"floors": n},
        )
        for item, n in zip(states, [4, 4, 5, 6])
    ]
    signal = engine.no_dynamics_signal(states, series)
    assert signal is not None
    assert signal["changed"] is False
    assert signal["schedule_progress"] > 0
    assert signal["observation_period_days"] >= 14
    assert engine.no_dynamics_signal(states, series, visual_changes=None) is not None
    assert engine.no_dynamics_signal(states, series, visual_changes=[None, None, None]) is not None


def test_no_dynamics_not_when_schedule_not_advancing():
    engine = TemporalEngine()
    states = [
        _state("2026-09-01T12:00:00", 4),
        _state("2026-09-08T12:00:00", 4),
        _state("2026-09-15T12:00:00", 4),
        _state("2026-09-22T12:00:00", 4),
    ]
    series = [
        ExpectedState(
            date=item.timestamp.date(),
            object_id="s",
            zone_id="z",
            stage="superstructure",
            expected={"floors": 4},
        )
        for item in states
    ]
    assert engine.no_dynamics_signal(states, series) is None


def test_different_cameras_are_not_compared_as_same_scene():
    engine = TemporalEngine()
    states = [
        _state("2026-09-01T12:00:00", 4, "cam_a"),
        _state("2026-09-22T12:00:00", 4, "cam_b"),
    ]
    series = [
        ExpectedState(date=states[0].timestamp.date(), object_id="s", zone_id="z", stage="s", expected={"floors": 4}),
        ExpectedState(date=states[1].timestamp.date(), object_id="s", zone_id="z", stage="s", expected={"floors": 6}),
    ]
    assert engine.no_dynamics_signal(states, series) is None
