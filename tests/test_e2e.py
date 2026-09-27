from pathlib import Path

from sitewatch.pipeline.seed import seed_demo
from sitewatch.services.queries import get_alert, list_alerts, object_page, timeline
from sitewatch.storage.db import get_session
from sitewatch.storage.models import Alert, DetectionRecord, Evidence, MediaAsset, Observation


def test_demo_three_scenarios():
    result = seed_demo()
    assert result["images"] >= 10
    assert result["alerts"] >= 2
    assert result["performance"]["mean_ms_per_observation"] > 0
    assert result["performance"]["images_per_sec"] > 0
    assert result["performance"]["video"]["sample_fps"] > 0
    assert result["performance"]["video"]["source_fps"] > 0

    alerts = list_alerts()
    types = {item["type"] for item in alerts}
    assert "missing_equipment" in types
    assert "no_dynamics" in types
    assert "schedule_delay" in types
    for item in alerts:
        assert "остановлен" not in (item.get("message") or "").lower()

    missing = next(item for item in alerts if item["type"] == "missing_equipment")
    detail = get_alert(missing["id"])
    assert detail["evidence"], "alert must point to source images"
    assert detail["deviation"]["expected"]["dump_truck"] == 2
    assert detail["deviation"]["observed"]["dump_truck"] == 0
    assert detail["deviation"]["evidence_ids"]
    assert detail["evidence"][0]["media_id"] or detail["evidence"][0]["media_path"]
    assert "Самосвал" in detail["message"] or "самосвал" in detail["message"].lower()
    source = Path(detail["evidence"][0]["media_path"])
    assert source.exists()
    assert "source" in source.parts or source.exists()

    page_b = object_page("site_001", "zone_b")
    assert page_b["expected"]["stage"] == "excavation"
    assert page_b["expected"]["stage_label"] == "Разработка котлована"
    assert page_b["actual"]["equipment"]["dump_truck"]["count"] == 0
    assert page_b["alerts"]
    assert page_b["observations"][0]["source"]

    page_a = object_page("site_001", "zone_a")
    assert page_a["actual"]["equipment"]["dump_truck"]["count"] >= 2
    equipment_alerts = [a for a in page_a["alerts"] if a["type"] == "missing_equipment"]
    assert not equipment_alerts, "NORMAL scenario must not raise missing_equipment"

    page_c = object_page("site_001", "building_01")
    building_types = {a["type"] for a in page_c["alerts"]}
    assert "no_dynamics" in building_types
    assert "schedule_delay" in building_types
    nd = next(a for a in page_c["alerts"] if a["type"] == "no_dynamics")
    nd_detail = get_alert(nd["id"])
    assert nd_detail["message"].startswith("Выявлены признаки отсутствия строительной динамики. Требуется проверка.")
    assert "отсутствия строительной динамики" in nd_detail["message"]
    assert "остановлен" not in nd_detail["message"].lower()
    assert len(nd_detail["evidence"]) >= 3
    for ev in nd_detail["evidence"]:
        assert ev["observation_id"]
        assert Path(ev["media_path"]).exists()
        assert ev["detections"]
    delay_details = [get_alert(a["id"]) for a in page_c["alerts"] if a["type"] == "schedule_delay"]
    delay_with_six = next(
        item for item in delay_details if item["deviation"]["expected"].get("floors") == 6
    )
    assert delay_with_six["deviation"]["observed"]["floors"] == 4

    history = timeline("site_001", "building_01")
    dates = [row["date"] for row in history]
    assert "2026-09-01" in dates
    assert "2026-09-22" in dates
    by_row = {row["date"]: row for row in history}
    assert by_row["2026-09-01"].get("change") is None
    later = by_row["2026-09-22"]["change"]
    assert later["comparable"] is True
    assert later["kind"] == "unchanged"
    assert later["element_deltas"] == {}
    assert later["equipment_deltas"] == {}
    marked = [row for row in history if any(a["type"] in {"no_dynamics", "schedule_delay"} for a in row.get("alerts") or [])]
    assert marked
    by_date = {row["date"]: [a["type"] for a in row.get("alerts") or []] for row in history}
    assert "no_dynamics" not in by_date.get("2026-09-01", [])
    assert "no_dynamics" not in by_date.get("2026-09-08", [])
    assert "no_dynamics" in by_date.get("2026-09-15", [])
    assert "no_dynamics" in by_date.get("2026-09-22", [])
    assert "schedule_delay" not in by_date.get("2026-09-01", [])
    assert "schedule_delay" in by_date.get("2026-09-15", [])
    assert "schedule_delay" in by_date.get("2026-09-22", [])

    with get_session() as session:
        assert session.query(Observation).count() >= 10
        assert session.query(Alert).count() >= 2
        assert session.query(Evidence).count() >= 1
        obs = session.query(Observation).first()
        assert obs.source
        assert session.query(DetectionRecord).filter_by(observation_id=obs.id).count() >= 1
        media = session.get(MediaAsset, obs.media_id)
        assert media is not None
        assert Path(media.path).exists()
