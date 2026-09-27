"""Pilot allowlist, idempotent cards, and reviews stay out of the fact."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sitewatch.cv.shadow import pilot_allows, record_shadow_candidates, store_pilot_batches
from sitewatch.domain.contracts import BBox, Detection
from sitewatch.domain.enums import StageStatus
from sitewatch.pipeline.demo_assets import generate_demo_assets
from sitewatch.pipeline.observe import observe_image
from sitewatch.pipeline.seed import seed_catalog
from sitewatch.services.queries import add_candidate_review, get_alert
from sitewatch.settings import get_settings
from sitewatch.storage.db import get_session
from sitewatch.storage.models import ActualStateRecord, Alert, Evidence, EvidenceArtifactRecord, Observation


def _detection() -> Detection:
    return Detection(
        class_name="excavator",
        bbox=BBox(x1=10, y1=12, x2=40, y2=50),
        confidence=0.8,
        model_name="yoloe_26l",
        model_version="test",
    )


def _cfg(tmp_path: Path, observation_id: str) -> dict:
    return {
        "enabled": True,
        "journal": str(tmp_path / "shadow_journal.jsonl"),
        "pilot": {
            "id": "eq-shadow-test",
            "allowlist_only": True,
            "manifest": str(tmp_path / "manifest.yaml"),
            "state": str(tmp_path / "state.json"),
        },
        "sources": {},
    }


def _write_manifest(cfg: dict, observation_id: str, image: Path) -> None:
    text = (
        "pilot_id: eq-shadow-test\n"
        "frames:\n"
        f"  - observation_id: {observation_id}\n"
        f"    image: {image}\n"
    )
    Path(cfg["pilot"]["manifest"]).write_text(text, encoding="utf-8")


def test_allowlist_blocks_other_frames_and_review_keeps_the_fact(tmp_path: Path, monkeypatch):
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
    before = first.model_dump_json()
    with get_session() as session:
        observation = session.query(Observation).one()
        state = session.query(ActualStateRecord).filter_by(observation_id=observation.id).one()
        observation_id = observation.id
        media_id = observation.media_id
        actual_state_id = state.id
        payload_before = state.payload_json

    cfg = _cfg(tmp_path, observation_id)
    other = tmp_path / "other.jpg"
    _write_manifest(cfg, "other-observation", other)
    assert pilot_allows(cfg, observation_id=observation_id, image_path=image) is False
    monkeypatch.setenv("SITEWATCH_SHADOW_CANDIDATES", "1")
    record_shadow_candidates(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T10:30:00"),
        observation_id=observation_id,
        media_id=media_id,
        actual_state_id=actual_state_id,
        cfg=cfg,
        runners={},
    )
    with get_session() as session:
        assert session.query(Alert).count() == 0

    _write_manifest(cfg, observation_id, image)
    batch = {
        "source": "yoloe_26l",
        "status": StageStatus.SUCCESS.value,
        "error": None,
        "model": "yoloe_26l",
        "model_version": "test",
        "latency_ms": 1,
        "detections": [_detection()],
        "prompt_version": "p1",
        "processing_version": "shadow-equipment-v1",
        "checkpoint": "abc",
    }
    common = dict(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T10:30:00"),
        observation_id=observation_id,
        media_id=media_id,
        actual_state_id=actual_state_id,
        batches=[batch, {**batch, "source": "grounding_dino", "detections": [], "status": StageStatus.EMPTY_SUCCESS.value}],
        cfg=cfg,
    )
    store_pilot_batches(**common)
    store_pilot_batches(**common)
    with get_session() as session:
        alerts = session.query(Alert).all()
        assert len(alerts) == 1
        assert alerts[0].alert_type == "model_candidate"
        assert session.query(Alert).filter(Alert.alert_type != "model_candidate").count() == 0
        assert session.query(Evidence).count() == 1
        assert session.query(EvidenceArtifactRecord).filter_by(source="yoloe_26l").count() == 1
        assert session.get(ActualStateRecord, actual_state_id).payload_json == payload_before
        alert_id = alerts[0].id
    detail = add_candidate_review(
        alert_id,
        source="yoloe_26l",
        verdict="incorrect",
        wrong_type="dump_truck",
        missed_object="кран",
        actor="inspector",
    )
    assert detail["type"] == "model_candidate"
    assert detail["candidate_reviews"][0]["completeness"] == "spot_check"
    assert detail["candidate_reviews"][0]["wrong_type"] == "dump_truck"
    layers = {item["source"]: item for item in detail["model_layers"]}
    assert layers["yoloe_26l"]["boxes"]
    assert layers["grounding_dino"]["boxes"] == []
    with get_session() as session:
        assert session.get(ActualStateRecord, actual_state_id).payload_json == payload_before
        assert session.query(Alert).filter(Alert.alert_type.in_(
            ["missing_equipment", "unexpected_equipment", "schedule_delay", "no_dynamics"]
        )).count() == 0
    again = get_alert(alert_id)
    assert json.loads(before)["equipment"]["excavator"]["count"] == 1
    assert again["status"] == "open"
