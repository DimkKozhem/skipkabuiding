from __future__ import annotations

import json
import time
from datetime import date, datetime
from pathlib import Path

from sitewatch.cv.factory import build_detector
from sitewatch.ksg.expected import stage_label
from sitewatch.ksg.parser import parse_ksg
from sitewatch.pipeline.demo_assets import generate_demo_assets
from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.observe import (
    CAPTURE_ORIGIN_SCHEDULED,
    observe_image,
    observe_video,
)
from sitewatch.settings import get_settings
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import Camera, Project, ScheduleStage, Zone


KSG_CSV = """project,zone,date,end_date,stage,floors,columns,slabs,walls,foundation,windows,roof,facade
site_001,zone_a,2026-09-18,2026-09-30,excavation,0,0,0,0,false,0,false,false
site_001,zone_b,2026-09-18,2026-09-30,excavation,0,0,0,0,false,0,false,false
site_001,building_01,2026-09-01,2026-09-07,superstructure,4,12,4,0,true,0,false,false
site_001,building_01,2026-09-08,2026-09-14,superstructure,4,12,4,0,true,0,false,false
site_001,building_01,2026-09-15,2026-09-21,superstructure,5,12,5,0,true,0,false,false
site_001,building_01,2026-09-22,2026-09-28,superstructure,6,12,6,0,true,0,false,false
"""


def _reset_db(db_path: Path) -> None:
    if db_path.exists():
        db_path.unlink()
    from sitewatch.storage import db as dbmod

    dbmod._engine = None
    dbmod.SessionLocal = None
    init_db()


def write_ksg(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(KSG_CSV, encoding="utf-8")
    return path


def seed_catalog() -> None:
    init_db()
    with get_session() as session:
        project = Project(code="site_001", name="ЖК Северный", address="Москва, демо-площадка")
        session.add(project)
        session.flush()
        zones = {
            "zone_a": Zone(project_id=project.id, code="zone_a", name="Котлован А"),
            "zone_b": Zone(project_id=project.id, code="zone_b", name="Котлован Б"),
            "building_01": Zone(project_id=project.id, code="building_01", name="Корпус 1"),
        }
        for zone in zones.values():
            session.add(zone)
        session.flush()
        session.add_all(
            [
                Camera(
                    zone_id=zones["zone_a"].id,
                    code="cam_pit_a",
                    name="Камера котлована А",
                    location="южный борт",
                    orientation="N",
                    gps_lat=55.75,
                    gps_lon=37.61,
                ),
                Camera(
                    zone_id=zones["zone_b"].id,
                    code="cam_pit_b",
                    name="Камера котлована Б",
                    location="западный борт",
                    orientation="E",
                    gps_lat=55.751,
                    gps_lon=37.612,
                ),
                Camera(
                    zone_id=zones["building_01"].id,
                    code="cam_building",
                    name="Камера корпуса 1",
                    location="башенный кран / фасад",
                    orientation="SW",
                    gps_lat=55.752,
                    gps_lon=37.615,
                ),
            ]
        )


def import_ksg(path: Path, *, project_code: str | None = None, replace: bool = False) -> int:
    rows = parse_ksg(path)
    with get_session() as session:
        projects = {item.code: item for item in session.query(Project).all()}
        zones = {(item.project_id, item.code): item for item in session.query(Zone).all()}
        if replace:
            touched: set[tuple[str, str]] = set()
            for row in rows:
                code = project_code or row["project_code"]
                project = projects.get(code)
                if project is None:
                    raise KeyError(f"project not found: {code}")
                zone = zones.get((project.id, row["zone"]))
                if zone is None:
                    raise KeyError(f"zone not found: {row['zone']}")
                key = (project.id, zone.id)
                if key in touched:
                    continue
                session.query(ScheduleStage).filter_by(project_id=project.id, zone_id=zone.id).delete()
                from sitewatch.storage.models import ExpectedStateRecord

                session.query(ExpectedStateRecord).filter_by(project_id=project.id, zone_id=zone.id).delete()
                touched.add(key)
        count = 0
        for row in rows:
            code = project_code or row["project_code"]
            project = projects.get(code)
            if project is None:
                raise KeyError(f"project not found: {code}")
            zone = zones.get((project.id, row["zone"]))
            if zone is None:
                raise KeyError(f"zone not found: {row['zone']}")
            start = row["start_date"]
            session.add(
                ScheduleStage(
                    project_id=project.id,
                    zone_id=zone.id,
                    date=start,
                    start_date=start,
                    end_date=row.get("end_date"),
                    stage=row["stage"],
                    stage_label=row.get("stage_label") or stage_label(row["stage"]),
                    expected_json=json.dumps(row["expected"], ensure_ascii=False),
                )
            )
            count += 1
    return count


def seed_demo() -> dict:
    settings = get_settings()
    _reset_db(settings.sqlite_path)
    demo_root = generate_demo_assets()
    ksg_path = write_ksg(demo_root / "ksg" / "site_001_ksg.csv")
    seed_catalog()
    n_ksg = import_ksg(ksg_path)
    detector = build_detector("annotation")

    images = sorted((demo_root / "images").glob("*.jpg"))
    observed = 0
    latencies_ms: list[float] = []
    for image in images:
        sidecar = json.loads(image.with_suffix(".json").read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        observe_image(
            image_path=image,
            project_code="site_001",
            zone_code=sidecar["zone"],
            camera_code=sidecar["camera_id"],
            timestamp=datetime.fromisoformat(sidecar["timestamp"]),
            detector=detector,
            scene=sidecar.get("scene"),
            capture_origin=CAPTURE_ORIGIN_SCHEDULED,
        )
        latencies_ms.append((time.perf_counter() - t0) * 1000)
        observed += 1

    video_metrics: dict = {}
    video_path = demo_root / "video" / "zone_a_window.mp4"
    if video_path.exists():
        t0 = time.perf_counter()
        video_state = observe_video(
            video_path=video_path,
            project_code="site_001",
            zone_code="zone_a",
            camera_code="cam_pit_a",
            timestamp=datetime.fromisoformat("2026-09-18T10:00:00"),
            detector=detector,
            scene={"visibility": "good", "coverage": "full"},
            capture_origin=CAPTURE_ORIGIN_SCHEDULED,
        )
        video_ms = (time.perf_counter() - t0) * 1000
        video_info = video_state.scene_attributes.get("video") or {}
        sampled = int(video_info.get("sampled_frames") or video_state.quality.n_frames or 0)
        video_metrics = {
            "source_fps": video_info.get("source_fps"),
            "sample_fps": video_info.get("sample_fps"),
            "sampled_frames": sampled,
            "latency_ms": round(video_ms, 2),
            "effective_inference_fps": round(sampled / max(video_ms / 1000.0, 1e-6), 3) if sampled else 0,
            "window_start": video_state.quality.window_start.isoformat() if video_state.quality.window_start else None,
            "window_end": video_state.quality.window_end.isoformat() if video_state.quality.window_end else None,
        }

    jobs = [
        ("zone_a", date(2026, 9, 18)),
        ("zone_b", date(2026, 9, 18)),
        ("building_01", date(2026, 9, 1)),
        ("building_01", date(2026, 9, 8)),
        ("building_01", date(2026, 9, 15)),
        ("building_01", date(2026, 9, 22)),
    ]
    alerts: list[str] = []
    for zone_code, on_date in jobs:
        alerts.extend(evaluate_zone_date(project_code="site_001", zone_code=zone_code, on_date=on_date))

    mean_ms = round(sum(latencies_ms) / len(latencies_ms), 2) if latencies_ms else 0.0
    return {
        "ksg_rows": n_ksg,
        "images": observed,
        "alerts": len(alerts),
        "alert_ids": alerts,
        "performance": {
            "inference_backend": "annotation",
            "images": observed,
            "mean_ms_per_observation": mean_ms,
            "images_per_sec": round(1000.0 / mean_ms, 3) if mean_ms else 0,
            "note": "sidecar annotation latency, not YOLO26m GPU inference",
            "video": video_metrics,
        },
    }
