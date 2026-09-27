from fastapi.testclient import TestClient

from sitewatch.api.main import create_app
from sitewatch.pipeline.seed import seed_demo
from sitewatch.services.media import public_media_url
from sitewatch.settings import get_settings, project_root


def test_public_media_url_maps_data_dir():
    rel = "demo/images/building_01_2026-09-01.jpg"
    data = get_settings().data_dir
    assert public_media_url(rel) == f"/media/{rel}"
    assert public_media_url(str(data / rel)) == f"/media/{rel}"
    assert public_media_url("/tmp/not-under-data.jpg") == ""
    assert public_media_url("") == ""


def test_api_health_and_inspector_config():
    client = TestClient(create_app())
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["ok"] is True
    root = client.get("/health")
    assert root.status_code == 200
    assert root.json()["ok"] is True
    cfg = client.get("/api/inspector/config")
    assert cfg.status_code == 200
    body = cfg.json()
    assert "confirmed" in body["reasons"]
    assert body["statuses"]["open"]
    assert body["actor_default"] == "inspector"


def test_api_demo_pages_and_media():
    seed_demo()
    client = TestClient(create_app())
    projects = client.get("/api/projects").json()
    assert projects[0]["code"] == "site_001"
    zones = {item["code"] for item in projects[0]["zones"]}
    assert {"zone_a", "zone_b", "building_01"} <= zones

    page_a = client.get("/api/projects/site_001/zones/zone_a").json()
    assert page_a["observations"]
    image_url = page_a["observations"][0]["image_url"]
    assert image_url.startswith("/media/")
    media = client.get(image_url)
    assert media.status_code == 200, image_url
    assert media.headers["content-type"].startswith("image/")

    page_b = client.get("/api/projects/site_001/zones/zone_b").json()
    assert any(item["type"] == "missing_equipment" for item in page_b["alerts"])

    page_c = client.get("/api/projects/site_001/zones/building_01").json()
    types = {item["type"] for item in page_c["alerts"]}
    assert "no_dynamics" in types
    history = client.get("/api/projects/site_001/zones/building_01/timeline").json()
    assert any(row["date"] == "2026-09-22" for row in history)
    by_date = {row["date"]: [a["type"] for a in row.get("alerts") or []] for row in history}
    assert "no_dynamics" not in by_date.get("2026-09-01", [])
    assert "no_dynamics" in by_date.get("2026-09-22", [])

    queue = client.get("/api/queue").json()
    assert queue
    alert_id = queue[0]["id"]
    detail = client.get(f"/api/alerts/{alert_id}").json()
    assert detail["evidence"]
    assert detail["evidence"][0]["media_url"].startswith("/media/")
    brief = client.get(f"/api/alerts/{alert_id}/brief").json()
    assert brief["on_site_checks"]

    cfg = client.get("/api/inspector/config").json()
    reason = next(iter(cfg["reasons"]["confirmed"]))
    decided = client.post(
        f"/api/alerts/{alert_id}/decision",
        json={"status": "confirmed", "reason": reason, "actor": "pytest"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "confirmed"
    remaining = {item["id"] for item in client.get("/api/queue").json()}
    assert alert_id not in remaining


def test_dashboard_vitrine_order_and_badges():
    """Витрина: delay > equipment > no_dynamics > stale > quiet; rank_reason / card_state."""
    from datetime import datetime

    from sitewatch.services.queries import sort_zones_for_vitrine, zone_badge_fields

    forbidden = (
        "строительство остановлено",
        "подрядчик нарушил",
        "не соответствует проекту",
        "срыв",
    )

    def _assert_soft_labels(*texts: str | None) -> None:
        for raw in texts:
            low = (raw or "").lower()
            for phrase in forbidden:
                assert phrase not in low, raw

    badge_delay = zone_badge_fields({"schedule_delay": 1, "no_dynamics": 1})
    assert badge_delay["primary_badge"] == "schedule_delay"
    assert badge_delay["schedule_delay"] is True
    assert "отставание" in (badge_delay["badge_label"] or "").lower()
    assert [item["code"] for item in badge_delay["badges"]] == ["schedule_delay", "no_dynamics"]
    assert badge_delay["badges"][0]["label"] == badge_delay["badge_label"]
    assert "динамик" in badge_delay["badges"][1]["label"].lower()
    _assert_soft_labels(badge_delay["badge_label"], *(item["label"] for item in badge_delay["badges"]))

    badge_eq = zone_badge_fields({"missing_equipment": 1})
    assert badge_eq["primary_badge"] == "equipment"
    assert badge_eq["attention"] is True
    assert [item["code"] for item in badge_eq["badges"]] == ["equipment"]
    assert "техник" in (badge_eq["badge_label"] or "").lower()
    _assert_soft_labels(badge_eq["badge_label"])

    badge_unexpected = zone_badge_fields({"unexpected_equipment": 1})
    assert badge_unexpected["primary_badge"] == "equipment"
    assert "нетипичн" in (badge_unexpected["badge_label"] or "").lower()
    _assert_soft_labels(badge_unexpected["badge_label"])

    badge_dyn = zone_badge_fields({"no_dynamics": 1})
    assert badge_dyn["primary_badge"] == "no_dynamics"
    assert "динамик" in (badge_dyn["badge_label"] or "").lower()
    assert [item["code"] for item in badge_dyn["badges"]] == ["no_dynamics"]

    assert zone_badge_fields({})["primary_badge"] is None
    assert zone_badge_fields({})["badges"] == []

    now = datetime(2026, 9, 22, 12, 0, 0)
    ordered = sort_zones_for_vitrine(
        [
            {
                "code": "quiet_new",
                "name": "Quiet New",
                "schedule_delay": False,
                "attention": False,
                "open_alerts": 0,
                "alert_counts": {},
                "last_observed_at": "2026-09-22T11:00:00",
                "preview_url": "/media/a.jpg",
            },
            {
                "code": "quiet_old",
                "name": "Quiet Old",
                "schedule_delay": False,
                "attention": False,
                "open_alerts": 0,
                "alert_counts": {},
                "last_observed_at": "2026-09-01T12:00:00",
                "preview_url": "/media/b.jpg",
            },
            {
                "code": "equip",
                "name": "Equip",
                "schedule_delay": False,
                "attention": True,
                "open_alerts": 1,
                "alert_counts": {"missing_equipment": 1},
                "last_observed_at": "2026-09-10T12:00:00",
                "preview_url": "/media/c.jpg",
            },
            {
                "code": "delay",
                "name": "Delay",
                "schedule_delay": True,
                "attention": True,
                "open_alerts": 2,
                "alert_counts": {"schedule_delay": 1},
                "last_observed_at": "2026-09-05T12:00:00",
                "preview_url": "/media/d.jpg",
            },
        ],
        now=now,
    )
    assert [z["code"] for z in ordered] == ["delay", "equip", "quiet_old", "quiet_new"]
    assert ordered[2]["stale"] is True
    assert ordered[2]["card_state"] == "stale"
    assert ordered[3]["card_state"] == "on_plan"
    assert ordered[3]["stale"] is False
    for row in ordered:
        assert row.get("rank_reason")
        _assert_soft_labels(row["rank_reason"], row.get("freshness_label"))

    seed_demo()
    client = TestClient(create_app())
    project = client.get("/api/projects").json()[0]
    codes = [item["code"] for item in project["zones"]]
    # building_01 (delay) > zone_b (equipment) > zone_a (тихо)
    assert codes.index("building_01") < codes.index("zone_b") < codes.index("zone_a")

    by_code = {item["code"]: item for item in project["zones"]}
    building = by_code["building_01"]
    assert building["primary_badge"] == "schedule_delay"
    assert building["schedule_delay"] is True
    assert "отставание" in (building["badge_label"] or "").lower()
    assert [item["code"] for item in building["badges"]] == ["schedule_delay", "no_dynamics"]
    assert building["badges"][0]["label"] == building["badge_label"]
    assert "динамик" in building["badges"][1]["label"].lower()
    assert building["rank_reason"]
    assert building["card_state"] == "possible_issue"
    assert building["freshness_label"]
    _assert_soft_labels(
        building["badge_label"],
        building["rank_reason"],
        *(item["label"] for item in building["badges"]),
    )

    assert by_code["zone_b"]["primary_badge"] == "equipment"
    assert by_code["zone_b"]["attention"] is True
    assert by_code["zone_b"]["rank_reason"]
    assert "техник" in by_code["zone_b"]["rank_reason"].lower()
    assert [item["code"] for item in by_code["zone_b"]["badges"]] == ["equipment"]
    assert by_code["zone_a"]["primary_badge"] is None
    assert by_code["zone_a"]["badges"] == []
    assert by_code["zone_a"]["attention"] is False
    assert by_code["zone_a"]["open_alerts"] == 0
    # Demo zone_a без open-сигналов; кадр в seed старше порога freshness → stale, не «авария».
    assert by_code["zone_a"]["card_state"] in {"on_plan", "stale"}
    assert by_code["zone_a"]["rank_reason"]
    if by_code["zone_a"]["card_state"] == "on_plan":
        assert by_code["zone_a"]["rank_reason"] == "По плану"
    else:
        assert by_code["zone_a"]["stale"] is True
        assert "старше" in by_code["zone_a"]["rank_reason"].lower() or "кадра" in by_code["zone_a"]["rank_reason"].lower()
    for zone in project["zones"]:
        assert zone.get("rank_reason")
        _assert_soft_labels(zone["rank_reason"])
        assert zone.get("card_state") in {
            "on_plan",
            "observation",
            "possible_issue",
            "needs_check",
            "confirmed",
            "stale",
            "no_frame",
        }
        assert "stale" in zone
        assert zone.get("freshness_label")


def test_vitrine_stale_above_quiet_fresh():
    """Stale без сигнала поднимается над тихой свежей зоной; seed не трогаем."""
    from datetime import datetime

    from sitewatch.services.queries import sort_zones_for_vitrine

    now = datetime(2026, 9, 22, 15, 0, 0)
    ordered = sort_zones_for_vitrine(
        [
            {
                "code": "fresh_quiet",
                "name": "А свежая",
                "alert_counts": {},
                "open_alerts": 0,
                "last_observed_at": "2026-09-22T14:00:00",
                "preview_url": "/media/fresh.jpg",
            },
            {
                "code": "stale_quiet",
                "name": "Б устаревшая",
                "alert_counts": {},
                "open_alerts": 0,
                "last_observed_at": "2026-09-10T10:00:00",
                "preview_url": "/media/old.jpg",
            },
        ],
        now=now,
    )
    assert [z["code"] for z in ordered] == ["stale_quiet", "fresh_quiet"]
    assert ordered[0]["stale"] is True
    assert ordered[0]["card_state"] == "stale"
    assert "старше" in ordered[0]["rank_reason"].lower()
    assert ordered[1]["card_state"] == "on_plan"
    assert ordered[1]["rank_reason"] == "По плану"
    forbidden = ("строительство остановлено", "подрядчик нарушил", "не соответствует проекту", "срыв")
    for row in ordered:
        low = row["rank_reason"].lower()
        for phrase in forbidden:
            assert phrase not in low


def test_api_list_alerts_include_plan_fact_preview():
    seed_demo()
    client = TestClient(create_app())
    projects = client.get("/api/projects").json()
    zone_a = next(item for item in projects[0]["zones"] if item["code"] == "zone_a")
    assert zone_a["last_observed_at"]
    assert zone_a["preview_url"].startswith("/media/")
    assert zone_a["open_alerts"] == 0

    page = client.get("/api/projects/site_001/zones/zone_a").json()
    assert page["observations"][0]["camera_code"]
    assert page["last_observed_at"]

    alerts = client.get("/api/alerts").json()
    missing = next(item for item in alerts if item["type"] == "missing_equipment")
    assert missing["expected"]["dump_truck"] == 2
    assert missing["observed"]["dump_truck"] == 0
    assert missing["title"]
    assert missing["latest_evidence"]["media_url"].startswith("/media/")
    assert missing["last_observed_at"]

    dynamics = next(item for item in alerts if item["type"] == "no_dynamics")
    assert dynamics["expected"]["floors"] in {5, 6}
    assert dynamics["observed"]["floors"] == 4

    detail = client.get(f"/api/alerts/{missing['id']}").json()
    assert detail["zone_name"]
    assert detail["evidence"][0]["camera_code"]
    assert detail["title"]


def test_spa_or_missing_ui_hint():
    client = TestClient(create_app())
    index = project_root() / "frontend" / "dist" / "index.html"
    home = client.get("/")
    assert home.status_code == 200
    if index.is_file():
        assert "text/html" in home.headers.get("content-type", "")
        queued = client.get("/queue")
        assert queued.status_code == 200
        assert "text/html" in queued.headers.get("content-type", "")
        assert client.get("/api/health").json()["ok"] is True
    else:
        body = home.json()
        assert body["ui"] == "missing"
        assert "npm run build" in body["hint"]
    missing = client.get("/api/alerts/does-not-exist")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "alert not found"


def test_api_project_cameras_and_alert_filter():
    seed_demo()
    client = TestClient(create_app())
    project = client.get("/api/projects").json()[0]
    zone_a = next(item for item in project["zones"] if item["code"] == "zone_a")
    assert zone_a["last_source"] == "annotation"
    assert {item["code"] for item in zone_a["cameras"]} == {"cam_pit_a"}
    page = client.get("/api/projects/site_001/zones/zone_a").json()
    assert page["cameras"][0]["code"] == "cam_pit_a"
    assert page["ksg"]
    own = client.get("/api/alerts?project=site_001&status=open").json()
    assert own
    assert all(item["project"] == "site_001" for item in own)
    empty = client.get("/api/alerts?project=missing_site").json()
    assert empty == []


def test_api_alert_summary_type_and_page_do_not_swallow_errors(tmp_path):
    from sitewatch.services.alert_diag import AlertReadError, load_alert_payload

    seed_demo()
    client = TestClient(create_app())
    summary = client.get("/api/alerts/summary?project=site_001")
    assert summary.status_code == 200
    body = summary.json()
    assert body["total"] == sum(body["by_type"].values())
    assert body["by_type"].get("missing_equipment", 0) >= 1
    assert "model_candidate" not in body["by_type"]
    typed = client.get("/api/alerts?project=site_001&type=missing_equipment").json()
    assert typed
    assert {item["type"] for item in typed} == {"missing_equipment"}
    page = client.get("/api/alerts?project=site_001&type=missing_equipment&limit=1&offset=0")
    assert page.status_code == 200
    assert len(page.json()) == 1
    assert client.get("/api/alerts?limit=-1").status_code == 400

    saved = load_alert_payload(summary.content, tmp_path / "summary.json")
    assert saved["total"] == body["total"]
    assert (tmp_path / "summary.json").read_bytes() == summary.content
    try:
        load_alert_payload(b"", tmp_path / "empty.json")
        raise AssertionError("empty alerts body was treated as a queue")
    except AlertReadError as exc:
        assert exc.path == tmp_path / "empty.json"
        assert (tmp_path / "empty.json").read_bytes() == b""
    try:
        load_alert_payload(b"not-json", tmp_path / "bad.json")
        raise AssertionError("invalid alerts body was treated as a queue")
    except AlertReadError as exc:
        assert b"not-json" == (tmp_path / "bad.json").read_bytes()


def test_api_upload_observation_without_sidecar():
    """Annotation mode без sidecar — 400, не «успех» с нулевыми детекциями."""
    seed_demo()
    client = TestClient(create_app())
    image = get_settings().data_dir / "demo" / "images" / "zone_a_normal_1.jpg"
    stamp = "2026-09-23T10:00:00"
    with image.open("rb") as handle:
        response = client.post(
            "/api/observations/upload",
            data={
                "project": "site_001",
                "zone": "zone_a",
                "camera": "cam_pit_b",
                "timestamp": stamp,
                "run_analysis": "true",
            },
            files={"file": ("field-shot.jpg", handle, "image/jpeg")},
        )
    assert response.status_code == 400
    with image.open("rb") as handle:
        response = client.post(
            "/api/observations/upload",
            data={
                "project": "site_001",
                "zone": "zone_a",
                "camera": "cam_pit_a",
                "timestamp": stamp,
                "run_analysis": "true",
            },
            files={"file": ("field-shot.jpg", handle, "image/jpeg")},
        )
    assert response.status_code == 400
    assert "sidecar" in response.json()["detail"].lower()


def test_api_capture_origin_scheduled_vs_manual():
    """scheduled_capture (seed/цикл) и manual_upload дают разный cover_origin; без метки — null."""
    import cv2
    import numpy as np

    from sitewatch.storage.db import get_session, init_db
    from sitewatch.storage.models import MediaAsset

    seed_demo()
    client = TestClient(create_app())
    project = client.get("/api/projects").json()[0]
    zone_a = next(item for item in project["zones"] if item["code"] == "zone_a")
    assert zone_a["cover_origin"] == "scheduled_capture"
    assert zone_a["cover_origin_label"] == "Камера"
    assert zone_a["cover_camera_name"] == "Камера котлована А"
    assert zone_a["last_source"] == "annotation"
    assert zone_a["cover_origin_label"] != zone_a["last_source"]

    page = client.get("/api/projects/site_001/zones/zone_a").json()
    assert page["cover_origin"] == "scheduled_capture"
    assert page["cover_origin_label"] == "Камера"
    assert page["observations"][0]["capture_origin"] == "scheduled_capture"
    assert page["observations"][0]["capture_origin_label"] == "Камера"

    shot = get_settings().data_dir / "raw" / "capture_origin_test.jpg"
    shot.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(shot), np.zeros((48, 64, 3), dtype=np.uint8))
    patched = client.patch(
        "/api/cameras/cam_pit_a",
        json={"uri": str(shot), "enabled": True, "interval_minutes": 30},
    )
    assert patched.status_code == 200, patched.text
    from datetime import datetime

    from sitewatch.pipeline.capture import capture_due_cameras

    captured = capture_due_cameras(
        camera_code="cam_pit_a",
        force=True,
        now=datetime(2098, 6, 1, 10, 0, 0),
    )
    assert captured["captured"] == 1
    after_capture = client.get("/api/projects").json()[0]
    zone_a = next(item for item in after_capture["zones"] if item["code"] == "zone_a")
    assert zone_a["cover_origin"] == "scheduled_capture"
    assert zone_a["cover_origin_label"] == "Камера"

    image = get_settings().data_dir / "demo" / "images" / "zone_a_normal_1.jpg"
    sidecar = image.with_suffix(".json")
    assert sidecar.is_file(), "demo image must have annotation sidecar"
    with image.open("rb") as handle, sidecar.open("rb") as side:
        uploaded = client.post(
            "/api/observations/upload",
            data={
                "project": "site_001",
                "zone": "zone_a",
                "camera": "cam_pit_a",
                "timestamp": "2099-01-01T12:00:00",
                "run_analysis": "false",
            },
            files={
                "file": ("inspect.jpg", handle, "image/jpeg"),
                "sidecar": ("inspect.json", side, "application/json"),
            },
        )
    assert uploaded.status_code == 200, uploaded.text
    after_upload = client.get("/api/projects").json()[0]
    zone_a = next(item for item in after_upload["zones"] if item["code"] == "zone_a")
    assert zone_a["cover_origin"] == "manual_upload"
    assert zone_a["cover_origin_label"] == "Инспекция"
    assert zone_a["cover_camera_name"] == "Камера котлована А"

    init_db()
    with get_session() as session:
        asset = session.query(MediaAsset).order_by(MediaAsset.timestamp.desc()).first()
        assert asset is not None
        asset.meta_json = "{}"
        session.add(asset)
    cleared = client.get("/api/projects").json()[0]
    zone_a = next(item for item in cleared["zones"] if item["code"] == "zone_a")
    assert zone_a["cover_origin"] is None
    assert zone_a["cover_origin_label"] is None
    assert zone_a["cover_camera_name"] == "Камера котлована А"

def test_operator_catalog_schedule_sources_and_capture(tmp_path):
    import cv2
    import numpy as np

    client = TestClient(create_app())
    created = client.post(
        "/api/projects",
        json={"code": "site_field", "name": "Площадка полевая", "address": "Москва"},
    )
    assert created.status_code == 200, created.text
    duplicate = client.post("/api/projects", json={"code": "site_field", "name": "Дубль"})
    assert duplicate.status_code == 409

    zone = client.post("/api/projects/site_field/zones", json={"code": "building_02", "name": "Корпус 2"})
    assert zone.status_code == 200
    stages = client.get("/api/catalog/stages").json()
    assert any(item["code"] == "superstructure" for item in stages)

    ksg = tmp_path / "ksg.csv"
    ksg.write_text("date,end_date,stage,floors\n2026-09-01,2026-09-30,superstructure,5\n", encoding="utf-8")
    with ksg.open("rb") as handle:
        imported = client.post(
            "/api/projects/site_field/zones/building_02/ksg/import",
            data={"replace": "true"},
            files={"file": ("ksg.csv", handle, "text/csv")},
        )
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported"] == 1
    rows = client.get("/api/projects/site_field/stages").json()
    assert rows[0]["id"]
    assert rows[0]["expected"]["floors"] == 5
    patched = client.patch(f"/api/ksg/{rows[0]['id']}", json={"expected": {"floors": 6}})
    assert patched.status_code == 200
    assert patched.json()["expected"]["floors"] == 6
    rejected = client.patch(
        f"/api/ksg/{rows[0]['id']}",
        json={"start_date": "2026-10-02", "end_date": "2026-09-01"},
    )
    assert rejected.status_code == 400
    assert "раньше начала" in rejected.json()["detail"]
    kept = client.get("/api/projects/site_field/stages").json()
    assert kept[0]["start_date"] == "2026-09-01"
    assert kept[0]["end_date"] == "2026-09-30"
    moved = client.patch(
        f"/api/ksg/{rows[0]['id']}",
        json={"start_date": "2026-09-02", "end_date": "2026-10-15"},
    )
    assert moved.status_code == 200
    assert moved.json()["start_date"] == "2026-09-02"
    assert moved.json()["end_date"] == "2026-10-15"

    shot = tmp_path / "shot.jpg"
    cv2.imwrite(str(shot), np.zeros((48, 64, 3), dtype=np.uint8))
    camera = client.post(
        "/api/projects/site_field/zones/building_02/cameras",
        json={
            "code": "cam_north",
            "name": "Север фасада",
            "location": "башенный кран",
            "uri": str(shot),
            "interval_minutes": 30,
        },
    )
    assert camera.status_code == 200, camera.text
    captured = client.post("/api/capture/run", json={"camera": "cam_north", "force": True})
    assert captured.status_code == 200, captured.text
    body = captured.json()
    assert body["captured"] == 1
    page = client.get("/api/projects/site_field/zones/building_02").json()
    assert page["ksg"][0]["id"]
    assert page["cameras"][0]["uri"]
    assert page["observations"]
    status = client.get("/api/capture/status").json()
    assert status["interval_default_minutes"] == 30
    north = next(item for item in status["cameras"] if item["code"] == "cam_north")
    assert north["last_captured_at"]

    blocked = client.delete("/api/cameras/cam_north")
    assert blocked.status_code == 409
    assert "отключить" in blocked.json()["detail"].lower()
    paused = client.patch("/api/cameras/cam_north", json={"enabled": False})
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False

    spare = client.post(
        "/api/projects/site_field/zones/building_02/cameras",
        json={"code": "cam_spare", "name": "Резерв"},
    )
    assert spare.status_code == 200
    removed = client.delete("/api/cameras/cam_spare")
    assert removed.status_code == 200


def test_zone_construction_type_and_notes():
    seed_demo()
    client = TestClient(create_app())
    created = client.post(
        "/api/projects/site_001/zones",
        json={
            "name": "Корпус восток",
            "description": "Фасад со стороны двора",
            "construction_type_id": "housing",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["code"].startswith("obj_")
    assert body["description"] == "Фасад со стороны двора"
    assert body["construction_type_id"] == "housing"
    assert body["construction_type_name"] == "Жильё"

    bad = client.post(
        "/api/projects/site_001/zones",
        json={"name": "Плохой вид", "construction_type_id": "not_real"},
    )
    assert bad.status_code == 400

    legacy = client.post(
        "/api/projects/site_001/zones",
        json={"code": "legacy_zone", "name": "Старый формат"},
    )
    assert legacy.status_code == 200, legacy.text
    assert legacy.json()["code"] == "legacy_zone"
    assert legacy.json()["construction_type_id"] is None

    page = client.get(f"/api/projects/site_001/zones/{body['code']}").json()
    assert page["zone"]["construction_type_id"] == "housing"
    assert page["zone"]["construction_type_name"] == "Жильё"
    assert page["zone"]["description"] == "Фасад со стороны двора"

    note = client.post(
        f"/api/projects/site_001/zones/{body['code']}/notes",
        json={"body": "На западном фасаде временно демонтированы леса.", "author": "pytest"},
    )
    assert note.status_code == 200, note.text
    listed = client.get(f"/api/projects/site_001/zones/{body['code']}/notes")
    assert listed.status_code == 200
    notes = listed.json()
    assert len(notes) == 1
    assert "леса" in notes[0]["body"]
    assert notes[0]["author"] == "pytest"

    empty = client.post(
        f"/api/projects/site_001/zones/{body['code']}/notes",
        json={"body": "  "},
    )
    assert empty.status_code == 400

    projects = client.get("/api/projects").json()
    zone = next(item for item in projects[0]["zones"] if item["code"] == body["code"])
    assert zone["construction_type_name"] == "Жильё"


def test_delete_zone_removes_frames_cameras_and_signals():
    seed_demo()
    client = TestClient(create_app())
    page = client.get("/api/projects/site_001/zones/zone_b").json()
    assert page["observations"]
    assert page["cameras"]
    assert any(item["zone"] == "zone_b" for item in client.get("/api/alerts").json())

    removed = client.delete("/api/projects/site_001/zones/zone_b")
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"ok": True, "zone": "zone_b"}
    assert client.get("/api/projects/site_001/zones/zone_b").status_code == 404

    projects = client.get("/api/projects").json()
    codes = {item["code"] for item in projects[0]["zones"]}
    assert "zone_b" not in codes
    assert {"zone_a", "building_01"} <= codes
    alerts = client.get("/api/alerts").json()
    assert all(item["zone"] != "zone_b" for item in alerts)
    assert any(item["zone"] == "building_01" for item in alerts)
    assert client.get("/api/projects/site_001/zones/zone_a").status_code == 200

    created = client.post("/api/projects/site_001/zones", json={"name": "Пустой объект"})
    assert created.status_code == 200, created.text
    code = created.json()["code"]
    empty = client.delete(f"/api/projects/site_001/zones/{code}")
    assert empty.status_code == 200
    assert client.get(f"/api/projects/site_001/zones/{code}").status_code == 404


def test_delete_observation_removes_one_frame():
    seed_demo()
    client = TestClient(create_app())
    page = client.get("/api/projects/site_001/zones/building_01").json()
    shots = page["observations"]
    assert len(shots) >= 2
    target = shots[0]["id"]
    kept = {item["id"] for item in shots[1:]}

    removed = client.delete(f"/api/observations/{target}")
    assert removed.status_code == 200, removed.text
    assert removed.json() == {"ok": True, "observation": target}

    again = client.get("/api/projects/site_001/zones/building_01")
    assert again.status_code == 200, again.text
    left = {item["id"] for item in again.json()["observations"]}
    assert target not in left
    assert kept <= left
    timeline = client.get("/api/projects/site_001/zones/building_01/timeline")
    assert timeline.status_code == 200, timeline.text
    alerts = client.get("/api/alerts")
    assert alerts.status_code == 200, alerts.text
    for item in alerts.json():
        if item["zone"] != "building_01":
            continue
        detail = client.get(f"/api/alerts/{item['id']}")
        assert detail.status_code == 200, detail.text
        assert all(frame.get("observation_id") != target for frame in detail.json()["evidence"])

    missing = client.delete(f"/api/observations/{target}")
    assert missing.status_code == 404
