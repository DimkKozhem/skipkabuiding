from sitewatch.domain.contracts import BBox, PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource
from sitewatch.perception.work_zone import center_inside, clip_to_work_zone, polygon_from_evidence


def _ev(label: str, x1, y1, x2, y2, score=0.8) -> PerceptionEvidence:
    return PerceptionEvidence(
        evidence_id=label,
        source=EvidenceSource.SAM3,
        model="sam3",
        class_name=label,
        bbox=BBox(x1=x1, y1=y1, x2=x2, y2=y2),
        score=score,
        raw_label=label,
        normalized_label=label,
    )


def test_site_box_excludes_neighbor_building():
    zone = polygon_from_evidence(
        [_ev("construction site", 150, 640, 1720, 1080)],
        frame_width=1920,
        frame_height=1080,
    )
    assert zone
    neighbor = _ev("facade", 80, 180, 700, 520)
    machine = _ev("excavator", 400, 800, 600, 980)
    kept = clip_to_work_zone([neighbor, machine], zone, frame_width=1920, frame_height=1080)
    labels = [item.normalized_label for item in kept]
    assert labels == ["excavator"]
    assert center_inside(machine.bbox, zone, frame_width=1920, frame_height=1080)
