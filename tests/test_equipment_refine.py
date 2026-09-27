from sitewatch.domain.contracts import BBox, PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource
from sitewatch.perception.dedup import refine_equipment_evidence, refine_structure_evidence
from sitewatch.perception.scene_narrative import describe_visible_work


def _box(label: str, score: float, x1, y1, x2, y2) -> PerceptionEvidence:
    return PerceptionEvidence(
        evidence_id=label + str(score),
        source=EvidenceSource.SAM3,
        model="sam3",
        class_name=label,
        bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
        score=score,
        raw_label=label,
        normalized_label=label,
    )


def test_same_machine_keeps_one_class_and_drops_cars():
    items = [
        _box("excavator", 0.93, 1073, 610, 1242, 721),
        _box("truck", 0.43, 1073, 611, 1240, 720),
        _box("bulldozer", 0.92, 393, 942, 549, 1026),
        _box("excavator", 0.71, 395, 943, 547, 1025),
        _box("truck", 0.37, 1167, 1010, 1220, 1056),
        _box("excavator", 0.63, 149, 648, 833, 1083),
        _box("facade", 0.8, 100, 80, 400, 400),
    ]
    kept = refine_equipment_evidence(items, frame_width=1920, frame_height=1080)
    labels = [item.normalized_label for item in kept]
    assert labels.count("excavator") == 1
    assert "bulldozer" in labels
    assert "truck" not in labels
    assert "facade" in labels


def test_neighbour_block_drops_and_site_facade_stays():
    # Apartments sit in the upper frame. The building under construction reaches down.
    items = [
        _box("facade", 0.7, 80, 120, 700, 480),
        _box("wall", 0.6, 90, 140, 400, 400),
        _box("roof", 0.55, 100, 80, 680, 200),
        _box("facade", 0.8, 200, 400, 1600, 980),
        _box("beam", 0.5, 400, 500, 520, 540),
        _box("beam", 0.7, 410, 505, 530, 545),
        _box("column", 0.4, 10, 10, 40, 30),
    ]
    kept = refine_structure_evidence(items, frame_width=1920, frame_height=1080)
    labels = [item.normalized_label for item in kept]
    assert labels.count("facade") == 1
    assert "wall" not in labels
    assert "roof" not in labels
    assert labels.count("beam") == 1
    assert "column" not in labels


def test_pit_crane_and_weak_truck_drop():
    items = [
        _box("tower crane", 0.46, 900, 700, 1100, 900),
        _box("truck", 0.40, 1200, 800, 1400, 980),
        _box("excavator", 0.8, 1200, 800, 1450, 1000),
    ]
    kept = refine_equipment_evidence(items, frame_width=1920, frame_height=1080)
    labels = [item.normalized_label for item in kept]
    assert "tower_crane" not in labels
    assert "truck" not in labels
    assert "excavator" in labels


def test_neighbouring_machines_are_not_merged():
    # Two machines side by side, modest overlap, different classes in one family.
    items = [
        _box("excavator", 0.9, 400, 700, 700, 980),
        _box("dump_truck", 0.88, 640, 720, 980, 1000),
    ]
    kept = refine_equipment_evidence(items, frame_width=1920, frame_height=1080)
    labels = {item.normalized_label for item in kept}
    assert labels == {"excavator", "dump_truck"}


def test_tower_crane_beats_overlapping_excavator_label():
    # Same tall silhouette: digger prompt must not rename the crane.
    items = [
        _box("tower_crane", 0.72, 700, 40, 1100, 700),
        _box("excavator", 0.9, 720, 80, 1080, 680),
    ]
    kept = refine_equipment_evidence(items, frame_width=1920, frame_height=1080)
    labels = [item.normalized_label for item in kept if item.normalized_label in {"tower_crane", "excavator"}]
    assert labels == ["tower_crane"]


def test_excavator_under_crane_jib_stays_separate():
    items = [
        _box("tower_crane", 0.8, 600, 20, 1400, 520),
        _box("excavator", 0.85, 1000, 820, 1180, 980),
    ]
    kept = refine_equipment_evidence(items, frame_width=1920, frame_height=1080)
    labels = {item.normalized_label for item in kept}
    assert "tower_crane" in labels
    assert "excavator" in labels


def test_tall_thin_box_not_counted_as_excavator():
    items = [
        _box("excavator", 0.9, 400, 200, 460, 900),  # scaffolding-like
        _box("facade", 0.8, 100, 100, 1600, 900),
    ]
    kept = refine_equipment_evidence(items, frame_width=1920, frame_height=1080)
    labels = [item.normalized_label for item in kept]
    assert "excavator" not in labels
    assert "facade" in labels


def test_narrative_names_visible_work():
    text = describe_visible_work(
        equipment={"excavator": 2, "tower_crane": 1},
        structures_present={"column"},
    )
    assert "2 экскаватора" in text
    assert "башенный кран" in text
    assert "земляных работ" in text
    assert "монтажных работ" in text
    assert "останов" not in text
