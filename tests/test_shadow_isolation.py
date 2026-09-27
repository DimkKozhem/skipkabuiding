"""Shadow isolation. DINO path completed 2026-09-27.

YOLOE-26L uses the same enqueue. The extra test only checks its own evidence source.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml

from sitewatch.api.main import create_app
from sitewatch.pipeline.demo_assets import generate_demo_assets
from sitewatch.pipeline.observe import observe_image
from sitewatch.pipeline.seed import seed_catalog
from sitewatch.services.alert_diag import load_alert_payload
from sitewatch.services.queries import get_alert
from sitewatch.settings import get_settings, project_root
from sitewatch.storage.db import get_session
from sitewatch.storage.models import ActualStateRecord, Alert, DetectionRecord, DeviationRecord, EvidenceArtifactRecord
from tests.test_shadow_candidates import _Boxes, _box, _cfg, _payloads

from fastapi.testclient import TestClient


def _flags() -> dict:
    path = project_root() / "config" / "shadow_candidates.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        "enabled": bool(raw.get("enabled")),
        "grounding_dino": bool((raw.get("sources") or {}).get("grounding_dino", {}).get("enabled")),
        "yoloe_26l": bool((raw.get("sources") or {}).get("yoloe_26l", {}).get("enabled")),
    }


def test_shadow_frame_is_visible_and_does_not_enter_plan_fact(tmp_path: Path, monkeypatch):
    baseline_flags = _flags()
    assert baseline_flags == {"enabled": False, "grounding_dino": False, "yoloe_26l": False}

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
    fact_before = _payloads()

    cfg = _cfg(tmp_path)
    dino = _Boxes([_box("excavator", 0.93) for _ in range(4)])
    monkeypatch.setenv("SITEWATCH_SHADOW_CANDIDATES", "1")
    monkeypatch.setattr("sitewatch.cv.shadow.load_shadow_config", lambda: cfg)
    monkeypatch.setattr("sitewatch.cv.shadow.build_source_runners", lambda _cfg: {"grounding_dino": dino})

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
    assert stored[0] == fact_before[0]
    assert "grounding_dino" not in stored[1]
    assert "shadow_candidate" not in stored[1]
    assert json.loads(stored[1])["equipment"]["excavator"]["count"] == 1

    with get_session() as session:
        deviations = session.query(DeviationRecord).all()
        assert deviations
        assert {row.alert_type for row in deviations} == {"model_candidate"}
        payload = json.loads(deviations[0].payload_json)
        assert payload["rule_id"] == "shadow.candidate"
        assert payload["observed"]["role"] == "shadow_candidate"
        assert payload["observed"]["promotes_actual_state"] is False
        assert len(payload["observed"]["detections"]) == 4
        alerts = session.query(Alert).all()
        assert {row.alert_type for row in alerts} == {"model_candidate"}
        assert alerts[0].message
        alert_id = alerts[0].id
        models = {row.model_name for row in session.query(DetectionRecord).all()}
        assert models.isdisjoint({"grounding_dino", "yoloe_26l", "shadow-fake"})
        artifacts = session.query(EvidenceArtifactRecord).all()
        shadow_rows = [row for row in artifacts if row.source == "grounding_dino"]
        fact_rows = [row for row in artifacts if row.source != "grounding_dino"]
        artifact_count = len(shadow_rows)
        assert len(shadow_rows) == 4
        assert fact_rows
        for row in shadow_rows:
            meta = json.loads(row.payload_json)["metadata"]
            assert meta["role"] == "shadow_candidate"
            assert meta["accepted_into_fact"] is False
        for row in fact_rows:
            assert json.loads(row.payload_json).get("metadata", {}).get("role") != "shadow_candidate"
        state_count = session.query(ActualStateRecord).count()

    detail = get_alert(alert_id)
    assert detail["evidence"]
    assert detail["evidence"][0]["viz_path"]
    assert Path(detail["evidence"][0]["viz_path"]).is_file()
    assert detail["deviation"]["rule_id"] == "shadow.candidate"

    client = TestClient(create_app())
    summary_response = client.get("/api/alerts/summary")
    summary = load_alert_payload(summary_response.content, tmp_path / "summary.json")
    assert summary["by_type"] == {"model_candidate": 1}
    assert summary["total"] == 1
    typed = client.get("/api/alerts?type=model_candidate&limit=5")
    rows = load_alert_payload(typed.content, tmp_path / "candidates.json")
    assert len(rows) == 1
    assert rows[0]["type"] == "model_candidate"
    assert rows[0]["observed"]["promotes_actual_state"] is False
    assert client.get("/api/alerts?type=schedule_delay").json() == []
    assert client.get("/api/alerts?type=missing_equipment").json() == []

    calls_after_frame = dino.calls
    assert calls_after_frame == 1
    monkeypatch.setenv("SITEWATCH_SHADOW_CANDIDATES", "0")
    third = observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T12:30:00"),
    )
    assert third.equipment_count("excavator") == 1
    assert dino.calls == calls_after_frame
    with get_session() as session:
        assert session.query(Alert).filter_by(alert_type="model_candidate").count() == 1
        assert session.query(Alert).filter(Alert.alert_type.in_(("schedule_delay", "missing_equipment"))).count() == 0
        assert session.query(EvidenceArtifactRecord).filter_by(source="grounding_dino").count() == artifact_count
        assert session.query(ActualStateRecord).count() == state_count + 1
    assert _payloads()[1] == stored[1]
    assert _flags() == baseline_flags


def test_pilot_plan_lists_three_frames_and_stays_off():
    from sitewatch.cv.shadow import shadow_pilot_plan

    plan = shadow_pilot_plan()
    assert plan["will_run"] is False
    assert plan["pilot_enabled"] is False
    assert plan["global_enabled"] is False
    assert plan["workers"] == 1
    assert plan["max_jobs"] == 6
    assert plan["max_jobs_means"] == "model_executions"
    assert plan["expected_runs"] == 6
    assert plan["results"] == "shadow_only"
    assert plan["allowlist_only"] is True
    assert [item["zone"] for item in plan["frames"]] == ["house6", "office_01", "road_alley"]
    from sitewatch.cv.shadow_pilot import assert_batch_not_truncated

    assert assert_batch_not_truncated(
        frames=3, sources=2, max_jobs=6, max_jobs_means="model_executions", expected_runs=6
    ) == 6
    try:
        assert_batch_not_truncated(
            frames=3, sources=2, max_jobs=3, max_jobs_means="model_executions", expected_runs=6
        )
    except RuntimeError as exc:
        assert "отрежет" in str(exc)
    else:
        raise AssertionError("a short max_jobs must refuse the batch")
    assert plan["models"]["grounding_dino"]["enabled"] is False
    assert plan["models"]["yoloe_26l"]["enabled"] is False


def test_yoloe_evidence_source_stays_distinct(tmp_path: Path, monkeypatch):
    generate_demo_assets()
    seed_catalog()
    image = get_settings().data_dir / "demo" / "images" / "zone_a_normal_1.jpg"
    observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T10:30:00"),
    )
    before = _payloads()
    cfg = _cfg(tmp_path, dino=False, yoloe=True)
    yoloe = _Boxes([_box("dump_truck", 0.8)])
    monkeypatch.setenv("SITEWATCH_SHADOW_CANDIDATES", "1")
    monkeypatch.setattr("sitewatch.cv.shadow.load_shadow_config", lambda: cfg)
    monkeypatch.setattr("sitewatch.cv.shadow.build_source_runners", lambda _ignored: {"yoloe_26l": yoloe})
    after = observe_image(
        image_path=image,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T11:00:00"),
    )
    assert after.equipment_count("dump_truck") == 3
    assert _payloads()[0] == before[0]
    assert "yoloe_26l" not in _payloads()[1]
    with get_session() as session:
        sources = {row.source for row in session.query(EvidenceArtifactRecord).all()}
        assert "yoloe_26l" in sources
        assert "grounding_dino" not in sources
        kinds = {row.alert_type for row in session.query(Alert).all()}
        assert kinds == {"model_candidate"}
        payload = json.loads(session.query(DeviationRecord).one().payload_json)
        assert payload["rule_id"] == "shadow.candidate"
        assert payload["observed"]["detections"][0]["class_name"] == "dump_truck"
