from datetime import datetime

from sitewatch.cv.aggregator import detections_to_actual_state, merge_actual_states
from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import BBox, Detection


def _det(name: str, conf: float = 0.9, track_id: int | None = None) -> Detection:
    return Detection(
        class_name=name,
        bbox=BBox(x1=1, y1=1, x2=10, y2=10),
        confidence=conf,
        track_id=track_id,
        model_name="test",
    )


def test_detections_to_actual_state_is_model_agnostic():
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="zone_a",
        timestamp=datetime(2026, 9, 18, 10, 30),
        camera_code="cam_pit_a",
        detections=[_det("excavator"), _det("dump_truck"), _det("dump_truck", 0.8)],
    )
    assert state.equipment_count("excavator") == 1
    assert state.equipment_count("dump_truck") == 2
    assert "elements" in state.model_dump()


def test_video_window_counts_override_repeated_frames():
    repeated = [_det("dump_truck", track_id=1) for _ in range(8)] + [_det("excavator", track_id=7)]
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="zone_a",
        timestamp=datetime(2026, 9, 18, 10, 30),
        camera_code="cam_pit_a",
        detections=repeated,
        class_counts={"dump_truck": 1, "excavator": 1},
        n_frames=8,
    )
    assert state.equipment_count("dump_truck") == 1
    assert state.equipment_count("excavator") == 1
    assert state.equipment_count("bulldozer") == 0


def test_unique_tracks_count():
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="zone_a",
        timestamp=datetime(2026, 9, 18, 10, 30),
        camera_code="cam_pit_a",
        detections=[_det("dump_truck", track_id=1), _det("dump_truck", track_id=1), _det("dump_truck", track_id=2)],
    )
    assert state.equipment_count("dump_truck") == 2


def test_scene_floors_override():
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="building_01",
        timestamp=datetime(2026, 9, 1, 12, 0),
        camera_code="cam_building",
        detections=[],
        scene={"floors": 4, "foundation": True, "visibility": "good", "coverage": "full"},
    )
    assert state.element_count("floors") == 4
    assert state.element_present("foundation") is True
    assert state.scene_attributes.get("floors_derivation") == "scene_label"
    assert state.construction()["floors"] == 4


def test_floors_not_derived_from_raw_slab_boxes():
    """SAM/YOLO box count for slab ≠ storeys; without scene.floors этажность неизвестна."""
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="building_01",
        timestamp=datetime(2026, 9, 1, 12, 0),
        camera_code="cam_building",
        detections=[_det("slab"), _det("slab"), _det("slab"), _det("slab")],
    )
    assert state.element_count("slabs") == 4
    assert state.element_count("floors") == 0
    assert state.scene_attributes.get("structural_levels") is None
    assert state.scene_attributes.get("floors_derivation") == "unavailable"


def test_floor_class_is_not_canonical():
    assert canonical_class("floor") is None


def test_structural_levels_only_from_scene_floors():
    state = detections_to_actual_state(
        object_id="site_001",
        zone_id="building_01",
        timestamp=datetime(2026, 9, 1, 12, 0),
        camera_code="cam_building",
        detections=[_det("slab"), _det("slab"), _det("slab"), _det("slab")],
        scene={"floors": 4, "visibility": "good", "coverage": "full"},
    )
    assert state.element_count("slabs") == 4
    assert state.scene_attributes.get("structural_levels") == 4
    assert state.scene_attributes.get("floors_derivation") == "scene_label"
    assert state.element_count("floors") == 4


def test_merge_same_day():
    a = detections_to_actual_state(
        object_id="s",
        zone_id="z",
        timestamp=datetime(2026, 9, 18, 10, 30),
        camera_code="c",
        detections=[_det("excavator")],
    )
    b = detections_to_actual_state(
        object_id="s",
        zone_id="z",
        timestamp=datetime(2026, 9, 18, 10, 45),
        camera_code="c",
        detections=[_det("dump_truck"), _det("dump_truck", 0.7)],
    )
    merged = merge_actual_states([a, b])
    assert merged.equipment_count("excavator") == 1
    assert merged.equipment_count("dump_truck") == 2
    assert merged.quality.n_frames == 2
