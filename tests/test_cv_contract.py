from datetime import datetime
from pathlib import Path

import pytest

from sitewatch.cv.filtering import filter_detections
from sitewatch.cv.yolo_detector import YOLODetector, resolve_yolo_weights
from sitewatch.domain.contracts import BBox, Detection
from sitewatch.pipeline.demo_assets import generate_demo_assets
from sitewatch.pipeline.observe import observe_image
from sitewatch.pipeline.seed import seed_catalog
from sitewatch.settings import get_settings
from sitewatch.storage.db import get_session
from sitewatch.storage.models import ActualStateRecord, DetectionRecord, MediaAsset, Observation


def test_detection_becomes_observation_and_source_is_preserved():
    generate_demo_assets()
    seed_catalog()
    image = get_settings().data_dir / "demo" / "images" / "zone_a_normal_1.jpg"
    actual = observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T10:30:00"),
    )
    assert actual.equipment_count("excavator") == 1
    assert actual.equipment_count("dump_truck") == 3

    annotation = get_settings().data_dir / "annotations" / "zone_a_normal_1.json"
    assert annotation.exists()

    with get_session() as session:
        obs = session.query(Observation).one()
        dets = session.query(DetectionRecord).filter_by(observation_id=obs.id).all()
        assert dets
        assert {d.class_name for d in dets} >= {"excavator", "dump_truck"}
        media = session.get(MediaAsset, obs.media_id)
        assert media is not None
        source = Path(media.path)
        assert source.exists()
        assert "source" in source.parts
        assert obs.viz_path and Path(obs.viz_path).exists()
        assert obs.prediction_path and Path(obs.prediction_path).exists()
        assert source.resolve() != Path(obs.viz_path).resolve()
        state = session.query(ActualStateRecord).filter_by(observation_id=obs.id).one()
        assert state.payload_json


def test_filter_detections_drops_low_confidence():
    kept = filter_detections(
        [
            Detection(
                class_name="excavator",
                bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                confidence=0.91,
                model_name="t",
            ),
            Detection(
                class_name="dump_truck",
                bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                confidence=0.10,
                model_name="t",
            ),
        ],
        min_confidence=0.35,
    )
    assert [item.class_name for item in kept] == ["excavator"]


def test_yolo_without_weights_raises_explicitly(tmp_path: Path):
    missing = tmp_path / "no-such-yolo26m.pt"
    detector = YOLODetector(weights=missing)
    with pytest.raises(FileNotFoundError, match="YOLO weights not found"):
        detector.detect(tmp_path / "frame.jpg")


def test_yolo_weights_default_stays_inside_project(monkeypatch):
    monkeypatch.delenv("SITEWATCH_YOLO_WEIGHTS", raising=False)
    from sitewatch.settings import get_settings

    get_settings.cache_clear()
    path = resolve_yolo_weights()
    assert "MVD" not in path.parts
    assert path.name.endswith(".pt")
    assert "models" in path.parts or path.parent.name == "models"

