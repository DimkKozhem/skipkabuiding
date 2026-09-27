"""Temporal floors: proven levels, not historical max of proposed numbers."""

from __future__ import annotations

from datetime import datetime

from sitewatch.domain.contracts import ImageQuality, ObservedState
from sitewatch.temporal.state_engine import TemporalStateEngine


def _obs(*, frame_id: str, at: datetime, floors: int, status: str) -> ObservedState:
    return ObservedState(
        frame_id=frame_id,
        object_id="site_001",
        zone_id="house6",
        camera_id="cam",
        captured_at=at,
        quality=ImageQuality(usable=True, visibility=0.9),
        structures={},
        equipment={},
        visible_floor_levels=floors,
        scene_attributes={
            "floors_status": status,
            "floors_derivation": "floor_bands_proven" if status == "proven" else "visible_floor_levels",
        },
    )


def test_proposed_floor_count_does_not_confirm_structural_levels():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 12, 24, 12, 0, 0)
    actual = engine.update(None, _obs(frame_id="f0", at=t0, floors=4, status="proposed"))
    assert actual.scene_attributes.get("visible_floor_levels") == 4
    assert actual.scene_attributes.get("structural_levels") is None
    assert actual.scene_attributes.get("floors_status") == "proposed"


def test_proposed_historical_max_does_not_hide_later_observation():
    """Earlier proposed 5 must not become confirmed truth when later frame proposes 4."""
    engine = TemporalStateEngine()
    t0 = datetime(2026, 6, 15, 12, 0, 0)
    t1 = datetime(2026, 12, 24, 12, 0, 0)
    a0 = engine.update(None, _obs(frame_id="mid", at=t0, floors=5, status="proposed"))
    assert a0.scene_attributes.get("structural_levels") is None
    a1 = engine.update(a0, _obs(frame_id="final", at=t1, floors=4, status="proposed"))
    assert a1.scene_attributes.get("visible_floor_levels") == 4
    assert a1.scene_attributes.get("structural_levels") is None
    assert a1.scene_attributes.get("floors_status_latest") == "proposed"


def test_proven_levels_ratchet_up_only():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 6, 15, 12, 0, 0)
    t1 = datetime(2026, 12, 24, 12, 0, 0)
    a0 = engine.update(None, _obs(frame_id="mid", at=t0, floors=4, status="proven"))
    assert a0.scene_attributes.get("structural_levels") == 4
    a1 = engine.update(a0, _obs(frame_id="final", at=t1, floors=6, status="proven"))
    assert a1.scene_attributes.get("structural_levels") == 6
    assert a1.scene_attributes.get("visible_floor_levels") == 6


def test_proven_not_overwritten_by_lower_proposed():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 6, 15, 12, 0, 0)
    t1 = datetime(2026, 12, 24, 12, 0, 0)
    a0 = engine.update(None, _obs(frame_id="mid", at=t0, floors=5, status="proven"))
    a1 = engine.update(a0, _obs(frame_id="final", at=t1, floors=4, status="proposed"))
    assert a1.scene_attributes.get("visible_floor_levels") == 4
    assert a1.scene_attributes.get("structural_levels") == 5
    assert a1.scene_attributes.get("floors_disputed") == 4


def test_single_lower_proven_reading_stays_disputed():
    """One full lower count does not erase a confirmed number of the same method."""
    engine = TemporalStateEngine()
    t0 = datetime(2026, 6, 1, 12, 0, 0)
    t1 = datetime(2026, 7, 1, 12, 0, 0)
    a0 = engine.update(None, _obs(frame_id="high", at=t0, floors=6, status="proven"))
    a1 = engine.update(a0, _obs(frame_id="low", at=t1, floors=4, status="proven"))
    assert a1.scene_attributes.get("structural_levels") == 6
    assert a1.scene_attributes.get("visible_floor_levels") == 4
    assert a1.scene_attributes.get("floors_disputed") == 4
    fact = a1.work_facts["visible_floor_levels"]
    assert fact.value == 6


def test_repeated_lower_proven_reading_revises_confirmed():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 6, 1, 12, 0, 0)
    t1 = datetime(2026, 7, 1, 12, 0, 0)
    t2 = datetime(2026, 8, 1, 12, 0, 0)
    a0 = engine.update(None, _obs(frame_id="high", at=t0, floors=6, status="proven"))
    a1 = engine.update(a0, _obs(frame_id="low1", at=t1, floors=4, status="proven"))
    a2 = engine.update(a1, _obs(frame_id="low2", at=t2, floors=4, status="proven"))
    assert a2.scene_attributes.get("structural_levels") == 4
    assert a2.scene_attributes.get("floors_disputed") is None
    assert a2.work_facts["visible_floor_levels"].value == 4


def test_stronger_method_corrects_inflated_floors():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 6, 1, 12, 0, 0)
    t1 = datetime(2026, 7, 1, 12, 0, 0)
    weak = _obs(frame_id="ann", at=t0, floors=5, status="proven")
    weak.scene_attributes["floors_derivation"] = "annotation"
    strong = _obs(frame_id="bands", at=t1, floors=4, status="proven")
    a0 = engine.update(None, weak)
    a1 = engine.update(a0, strong)
    assert a1.scene_attributes.get("structural_levels") == 4
    assert "floors_revision:5→4" in a1.change_notes
