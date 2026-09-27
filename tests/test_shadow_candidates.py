"""Shadow DINO / YOLOE-26L stay out of the confirmed fact and the deviation engine."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from sitewatch.cv.shadow import _call_runner, record_shadow_candidates
from sitewatch.cv.shadow_sources import GroundingDinoShadow, Yoloe26lShadow, sha256_file
from sitewatch.domain.contracts import BBox, Detection, PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource, PerceptionMode, StageStatus
from sitewatch.perception.fusion.service import EvidenceFusionService
from sitewatch.perception.pipeline import PerceptionPipeline
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.pipeline.demo_assets import generate_demo_assets
from sitewatch.pipeline.observe import observe_image
from sitewatch.pipeline.seed import seed_catalog
from sitewatch.services.queries import get_alert, inspector_queue, set_alert_status, zone_badge_fields
from sitewatch.settings import get_settings, project_root
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import ActualStateRecord, Alert, DetectionRecord, EvidenceArtifactRecord


def _box(class_name: str, confidence: float = 0.9) -> dict:
    return Detection(
        class_name=class_name,
        bbox=BBox(x1=10, y1=10, x2=80, y2=80),
        confidence=confidence,
        model_name="shadow-fake",
        model_version="test",
    ).model_dump()


class _Boxes:
    def __init__(self, rows: list[dict], *, status: StageStatus = StageStatus.SUCCESS, error: str | None = None):
        self.rows = rows
        self.status = status
        self.error = error
        self.calls = 0

    def detect(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        self.calls += 1
        return ProviderResult(
            status=self.status,
            error=self.error,
            model="shadow-fake",
            model_version="test",
            extras={"detections": list(self.rows), "accepted_into_fact": False},
        )


class _Boom:
    def detect(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        raise RuntimeError("shadow source down")


class _Slow:
    def detect(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        time.sleep(0.3)
        return ProviderResult(status=StageStatus.SUCCESS, extras={"detections": [_box("excavator")]})


def _cfg(tmp_path: Path, *, dino: bool = True, yoloe: bool = True) -> dict:
    base = json.loads(json.dumps({
        "enabled": True,
        "journal": str(tmp_path / "shadow_journal.jsonl"),
        "max_boxes": 20,
        "timeout_seconds": 5,
        "device": "cpu",
        "sources": {
            "grounding_dino": {
                "enabled": dino,
                "model": "IDEA-Research/grounding-dino-base",
                "revision": "12bdfa3120f3e7ec7b434d90674b3396eccf88eb",
                "classes": ["excavator", "dump_truck"],
                "timeout_seconds": 5,
                "max_boxes": 20,
            },
            "yoloe_26l": {
                "enabled": yoloe,
                "classes": ["excavator", "dump_truck"],
                "timeout_seconds": 5,
                "max_boxes": 2,
            },
        },
    }))
    return base


def _journal(cfg: dict) -> list[dict]:
    path = Path(cfg["journal"])
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _payloads() -> list[str]:
    with get_session() as session:
        rows = session.query(ActualStateRecord).order_by(ActualStateRecord.timestamp.asc()).all()
        return [row.payload_json for row in rows]


def test_pins_fail_closed_without_inventing_boxes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("sitewatch.cv.shadow_sources.transformers_available", lambda: False)
    dino = GroundingDinoShadow({"model": "IDEA-Research/grounding-dino-base", "revision": "pin"}).detect(
        tmp_path / "frame.jpg",
        ["excavator"],
    )
    assert dino.status == StageStatus.UNAVAILABLE
    assert dino.error == "grounding_dino_no_transformers"
    assert dino.extras["accepted_into_fact"] is False

    missing = Yoloe26lShadow(
        {
            "weights": str(tmp_path / "absent.pt"),
            "sha256": "a" * 64,
            "bytes": 1,
            "version": "v8.4.0",
            "ultralytics_version": "8.4.146",
        }
    ).detect(tmp_path / "frame.jpg", ["excavator"])
    assert missing.status == StageStatus.UNAVAILABLE
    assert "weights_missing" in (missing.error or "")

    blob = tmp_path / "yoloe-26l-seg.pt"
    blob.write_bytes(b"not-the-checkpoint")
    mismatch = Yoloe26lShadow(
        {
            "weights": str(blob),
            "sha256": "b" * 64,
            "bytes": blob.stat().st_size,
            "version": "v8.4.0",
            "ultralytics_version": "8.4.146",
        }
    ).detect(tmp_path / "frame.jpg", ["excavator"])
    assert mismatch.status == StageStatus.FAILED
    assert "sha256" in (mismatch.error or "")

    pinned = Yoloe26lShadow(
        {
            "weights": str(blob),
            "sha256": sha256_file(blob),
            "bytes": blob.stat().st_size,
            "version": "v8.4.0",
            "ultralytics_version": "0.0.0",
        }
    ).detect(tmp_path / "frame.jpg", ["excavator"])
    assert pinned.status == StageStatus.UNAVAILABLE
    assert "ultralytics_pin" in (pinned.error or "")


def test_dino_interpreter_empty_answer_is_not_a_fact(tmp_path: Path):
    worker = tmp_path / "fake_dino.py"
    worker.write_text(
        "#!/usr/bin/env python3\n"
        "import json,sys\n"
        "json.load(sys.stdin)\n"
        "print(json.dumps({'status':'empty_success','detections':[]}))\n",
        encoding="utf-8",
    )
    worker.chmod(0o755)
    result = GroundingDinoShadow(
        {
            "model": "IDEA-Research/grounding-dino-base",
            "revision": "12bdfa3120f3e7ec7b434d90674b3396eccf88eb",
            "interpreter": str(worker),
            "timeout_seconds": 5,
        }
    ).detect(tmp_path / "frame.jpg", ["excavator"])
    assert result.status == StageStatus.EMPTY_SUCCESS
    assert result.extras["detections"] == []
    assert result.extras["accepted_into_fact"] is False

    missing = GroundingDinoShadow(
        {"model": "IDEA-Research/grounding-dino-base", "revision": "pin", "interpreter": str(tmp_path / "no-such-python")}
    ).detect(tmp_path / "frame.jpg", ["excavator"])
    assert missing.status == StageStatus.UNAVAILABLE
    assert missing.error == "grounding_dino_interpreter_missing"


def test_timeout_and_kill_switch_do_not_enqueue(tmp_path: Path, monkeypatch):
    timed = _call_runner(_Slow(), tmp_path / "frame.jpg", ["excavator"], 0.05)
    assert timed.status == StageStatus.FAILED
    assert timed.error == "shadow_timeout"

    monkeypatch.setenv("SITEWATCH_SHADOW_CANDIDATES", "0")
    source = _Boxes([_box("excavator")])
    cfg = _cfg(tmp_path)
    record_shadow_candidates(
        image_path=tmp_path / "frame.jpg",
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime(2026, 9, 18, 10, 0, 0),
        observation_id="missing",
        media_id=None,
        actual_state_id="missing",
        runners={"grounding_dino": source},
        cfg=cfg,
    )
    assert source.calls == 0
    assert _journal(cfg) == []
    init_db()
    with get_session() as session:
        assert session.query(Alert).count() == 0


def test_dino_boxes_stay_out_of_fused_fact(tmp_path: Path):
    image = tmp_path / "frame.jpg"
    rng = np.random.default_rng(1)
    cv2.imwrite(str(image), rng.integers(40, 200, size=(640, 800, 3), dtype=np.uint8))

    class _Sam:
        name = "sam3"
        device = "cpu"

        def segment(self, image_path, prompts, *, artifact_dir=None):
            return ProviderResult(status=StageStatus.SUCCESS, evidence=[], model="sam3-mock", model_version="test")

    class _Dino:
        name = "grounding_dino"
        verify_classes = ["excavator"]

        def detect(self, image_path, prompts, *, class_filter=None, artifact_dir=None):
            boxes = []
            for i in range(4):
                origin = 30 + i * 180
                boxes.append(
                    PerceptionEvidence(
                        evidence_id=f"d{i}",
                        source=EvidenceSource.GROUNDING_DINO,
                        model="dino-mock",
                        model_version="test",
                        class_name="excavator",
                        bbox=BBox(x1=origin, y1=40, x2=origin + 160, y2=200),
                        score=0.99,
                        raw_label="excavator",
                        normalized_label="excavator",
                    )
                )
            return ProviderResult(status=StageStatus.SUCCESS, evidence=boxes, model="dino-mock", model_version="test")

    class _Qwen:
        name = "qwen_vl"

        def interpret(self, image_path, *, evidence, quality, ontology_hints):
            return ProviderResult(status=StageStatus.SKIPPED, model="qwen-mock")

    observed = PerceptionPipeline(
        mode=PerceptionMode.REAL,
        sam3=_Sam(),
        dino=_Dino(),
        qwen=_Qwen(),
        fusion=EvidenceFusionService(),
    ).run(
        image,
        object_id="site_001",
        zone_id="zone_a",
        camera_id="cam_pit_a",
        captured_at=datetime(2026, 9, 18, 12, 0, 0),
        artifact_dir=tmp_path / "artifacts",
    )
    assert all(item.source != EvidenceSource.GROUNDING_DINO for item in observed.evidence)
    stage = next(item for item in observed.pipeline_run.stages if item.name == "grounding_dino")
    assert stage.extras["accepted_into_fact"] is False
    excavator = observed.equipment.get("excavator")
    count = int(excavator.count_visible or 0) if excavator is not None else 0
    assert count != 4


def test_frame_to_inspector_confirmation_keeps_previous_fact(tmp_path: Path, monkeypatch):
    text = (project_root() / "src/sitewatch/cv/shadow.py").read_text(encoding="utf-8")
    assert "DeviationEngine" not in text
    assert "deviation.engine" not in text

    generate_demo_assets()
    seed_catalog()
    image = get_settings().data_dir / "demo" / "images" / "zone_a_normal_1.jpg"
    first = observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T10:30:00"),
    )
    assert first.equipment_count("excavator") == 1
    assert first.equipment_count("dump_truck") == 3
    before = _payloads()
    assert len(before) == 1

    cfg = _cfg(tmp_path)
    dino = _Boxes([_box("excavator", 0.91 + i / 100) for i in range(9)])
    yoloe = _Boxes([], status=StageStatus.EMPTY_SUCCESS)
    monkeypatch.setenv("SITEWATCH_SHADOW_CANDIDATES", "1")
    monkeypatch.setattr("sitewatch.cv.shadow.load_shadow_config", lambda: cfg)
    monkeypatch.setattr(
        "sitewatch.cv.shadow.build_source_runners",
        lambda _cfg_arg: {"grounding_dino": dino, "yoloe_26l": yoloe},
    )
    second = observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T11:30:00"),
    )
    assert second.equipment_count("excavator") == 1
    assert second.equipment_count("dump_truck") == 3
    stored = _payloads()
    assert stored[0] == before[0]
    assert json.loads(stored[1])["equipment"]["excavator"]["count"] == 1

    with get_session() as session:
        models = {row.model_name for row in session.query(DetectionRecord).all()}
        assert "grounding_dino" not in models
        assert "yoloe_26l" not in models
        artifacts = session.query(EvidenceArtifactRecord).all()
        assert any(row.source == "grounding_dino" for row in artifacts)
        assert session.query(Alert).filter(Alert.alert_type != "model_candidate").count() == 0

    queued = [item for item in inspector_queue() if item["type"] == "model_candidate"]
    assert len(queued) == 1
    detail = get_alert(queued[0]["id"])
    assert detail["evidence"]
    assert detail["evidence"][0]["note"]
    assert "не факт" in detail["evidence"][0]["note"]
    assert detail["observed"]["promotes_actual_state"] is False
    assert len(detail["observed"]["detections"]) == 9
    assert "останов" not in (detail["message"] or "").lower()
    assert Path(detail["evidence"][0]["viz_path"]).is_file()
    assert zone_badge_fields({"model_candidate": 1})["attention"] is False

    lines = _journal(cfg)
    assert any(row["status"] == "success" and row["source"] == "grounding_dino" and row["n_boxes"] == 9 for row in lines)
    assert any(row["status"] == "empty_success" and row["source"] == "yoloe_26l" and row["n_boxes"] == 0 for row in lines)
    assert all(row["touched_actual_state"] is False for row in lines)

    snapshot = _payloads()
    decided = set_alert_status(
        detail["id"],
        "confirmed",
        reason="on_site_verified",
        note="проверено, в факт не переносить",
        actor="inspector",
    )
    assert decided["status"] == "confirmed"
    assert decided["decided_by"] == "inspector"
    assert _payloads() == snapshot

    failed = _Boom()
    monkeypatch.setattr(
        "sitewatch.cv.shadow.build_source_runners",
        lambda _cfg_arg: {"grounding_dino": failed, "yoloe_26l": _Boxes([])},
    )
    third = observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T12:30:00"),
    )
    assert third.equipment_count("excavator") == 1
    assert _payloads()[:2] == snapshot
    assert any(row["status"] == "failed" and row["error"] and "shadow source down" in row["error"] for row in _journal(cfg))
    with get_session() as session:
        assert session.query(Alert).filter_by(alert_type="model_candidate").count() == 1
