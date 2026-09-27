"""Additive housing_16 scenario: KSG schedule + timelapse run.

Does not modify seed-demo / site_001. CV still emits ActualState only;
scenario labels come from the pipeline, not from YOLO pretending to be ML.
"""

from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import cv2

from sitewatch.cv.aggregator import detections_to_actual_state
from sitewatch.deviation.engine import DeviationEngine
from sitewatch.domain.contracts import ActualState, BBox, Detection
from sitewatch.evidence.builder import evidence_from_observations
from sitewatch.inspector.workflow import persist_candidate
from sitewatch.ksg.expected import build_expected_state, stage_label
from sitewatch.ksg.parser import parse_ksg
from sitewatch.pipeline.observe import _persist_observation, _write_prediction
from sitewatch.settings import get_settings, project_root
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import (
    ActualStateRecord,
    Alert,
    AlertEvent,
    Camera,
    DeviationRecord,
    Evidence,
    MediaAsset,
    Observation,
    Project,
    ScheduleStage,
    Zone,
)

PROJECT_CODE = "housing_16"
ZONE_CODE = "corpus_01"
CAMERA_CODE = "cam_housing_16"
PROJECT_TITLE = "Жилой дом, 16 этажей"
VIDEO_FILENAME = "triumph_park_phase5.mp4"
VIDEO_URL = f"/media/video/{VIDEO_FILENAME}"
# (id, title, filename, runs_pipeline). Pipeline windows stay on the first clip.
LIBRARY_VIDEOS: list[tuple[str, str, str, bool]] = [
    ("triumph_park_phase5", "Таймлапс корпуса", VIDEO_FILENAME, True),
    (
        "huntington_apartments",
        "Таймлапс Huntington Apartments",
        "huntington_apartments.mp4",
        False,
    ),
]
FRAME_INTERVAL_MINUTES = 30
# One scenario clock: frame i is exactly 30 minutes after frame i-1.
RUN_CLOCK_START = datetime(2026, 4, 1, 8, 0, 0)
MODEL_NAME = "scenario_timelapse"

REQUIRED_CSV_COLUMNS = (
    "project",
    "zone",
    "date",
    "end_date",
    "stage",
    "floors",
    "columns",
    "slabs",
    "walls",
    "foundation",
    "windows",
    "roof",
    "facade",
)

# (stage, t0_sec, t1_sec, frame_count) — skip intro 0–6s
VIDEO_WINDOWS: list[tuple[str, float, float, int]] = [
    ("site_setup", 6.0, 16.0, 2),
    ("excavation", 16.0, 40.0, 4),
    ("foundation", 40.0, 52.0, 2),
    ("underground", 52.0, 60.0, 2),
    ("superstructure", 60.0, 98.0, 16),
    ("facade", 98.0, 124.0, 4),
]

CATALOG_META: dict[str, tuple[str, str]] = {
    "site_setup": ("10.11", "Обустройство строительной площадки"),
    "excavation": ("12.3.1", "Устройство котлована, выемка грунта, шпунтовое ограждение"),
    "foundation": ("12.3.4", "Фундамент, фундаментная плита, фундамент под башенный кран"),
    "underground": ("12.3.9", "Монолит ниже нуля, плита +0.000"),
    "superstructure": ("12.4.29", "Каркас"),
    "facade": ("12.4.11", "Фасад и оконные блоки"),
}


def scenario_dir() -> Path:
    return get_settings().data_dir / "scenarios" / PROJECT_CODE


def ksg_path() -> Path:
    return scenario_dir() / "ksg.csv"


def catalog_path() -> Path:
    return scenario_dir() / "catalog.json"


def video_path() -> Path:
    return project_root() / "video" / VIDEO_FILENAME


def scenario_videos() -> list[dict[str, Any]]:
    return [
        {
            "id": video_id,
            "title": title,
            "url": f"/media/video/{filename}",
            "runs_pipeline": runs_pipeline,
        }
        for video_id, title, filename, runs_pipeline in LIBRARY_VIDEOS
    ]


def ensure_catalog() -> None:
    init_db()
    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).first()
        if project is None:
            project = Project(code=PROJECT_CODE, name=PROJECT_TITLE, address="Москва, сценарий housing_16")
            session.add(project)
            session.flush()
        elif project.name != PROJECT_TITLE:
            project.name = PROJECT_TITLE
        zone = session.query(Zone).filter_by(project_id=project.id, code=ZONE_CODE).first()
        if zone is None:
            zone = Zone(project_id=project.id, code=ZONE_CODE, name="Корпус 1")
            session.add(zone)
            session.flush()
        camera = session.query(Camera).filter_by(code=CAMERA_CODE).first()
        if camera is None:
            session.add(
                Camera(
                    zone_id=zone.id,
                    code=CAMERA_CODE,
                    name="Камера таймлапса housing_16",
                    location="таймлапс",
                    orientation="S",
                    source_type="video",
                    interval_minutes=FRAME_INTERVAL_MINUTES,
                )
            )


def _rebuild_catalog_json(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for row in rows:
        stage = str(row["stage"])
        code, title = CATALOG_META.get(stage, (stage, stage_label(stage)))
        if stage == "superstructure":
            floors = int((row.get("expected") or {}).get("floors") or 0)
            title = f"Каркас, этаж {floors}"
            code = "12.4.29"
        items.append({"stage": stage, "catalog_code": code, "title": title})
    catalog_path().parent.mkdir(parents=True, exist_ok=True)
    catalog_path().write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return items


def _load_catalog() -> list[dict[str, str]]:
    path = catalog_path()
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return []
    return payload


def validate_housing_csv(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    first = text.splitlines()[0] if text.strip() else ""
    headers = [h.strip().lower() for h in first.split(",")]
    missing = [col for col in REQUIRED_CSV_COLUMNS if col not in headers]
    if missing:
        raise ValueError(f"KSG CSV missing columns: {missing}")
    rows = parse_ksg(path, default_zone=ZONE_CODE, default_project=PROJECT_CODE)
    if not rows:
        raise ValueError("KSG file has no rows")
    max_floors = 0
    for row in rows:
        if row["stage"] == "superstructure":
            max_floors = max(max_floors, int((row.get("expected") or {}).get("floors") or 0))
    if max_floors < 16:
        raise ValueError("superstructure floors must reach 16")
    return rows


def import_housing_schedule(path: Path) -> dict[str, Any]:
    """Replace housing_16 ExpectedState / schedule only. Leaves site_001 intact."""
    from sitewatch.ksg.expected import load_equipment_rules
    from sitewatch.storage.models import ExpectedStateRecord

    load_equipment_rules.cache_clear()
    rows = validate_housing_csv(path)
    ensure_catalog()
    dest = ksg_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    if path.resolve() != dest.resolve():
        shutil.copy2(path, dest)
    catalog = _rebuild_catalog_json(rows)

    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=ZONE_CODE).one()
        session.query(ScheduleStage).filter_by(project_id=project.id, zone_id=zone.id).delete()
        session.query(ExpectedStateRecord).filter_by(project_id=project.id, zone_id=zone.id).delete()
        for row in rows:
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
    return {"ok": True, "imported": len(rows), "catalog": len(catalog)}


def ensure_default_schedule_loaded() -> None:
    path = ksg_path()
    if not path.is_file():
        raise FileNotFoundError(f"missing schedule CSV: {path}")
    ensure_catalog()
    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=ZONE_CODE).one()
        n = session.query(ScheduleStage).filter_by(project_id=project.id, zone_id=zone.id).count()
    if n == 0:
        import_housing_schedule(path)


def _det(class_name: str, n: int = 1) -> list[Detection]:
    out: list[Detection] = []
    for i in range(max(n, 0)):
        x = 10.0 + i * 20.0
        out.append(
            Detection(
                class_name=class_name,
                bbox=BBox(x1=x, y1=10.0, x2=x + 40.0, y2=50.0),
                confidence=0.91,
                track_id=i + 1,
                model_name=MODEL_NAME,
                model_version="scenario",
            )
        )
    return out


def scenario_frame_state(stage: str, *, floor_n: int = 0) -> tuple[dict[str, Any], list[Detection]]:
    """Map timelapse stage → scene + synthetic detections (not production ML)."""
    scene: dict[str, Any] = {
        "visibility": "good",
        "coverage": "full",
        "source": MODEL_NAME,
        "limitation": "раскладка таймлапса по этапам сценария, не production ML",
    }
    dets: list[Detection] = []
    if stage == "site_setup":
        scene.update({"floors": 0, "columns": 0, "slabs": 0, "walls": 0, "windows": 0, "foundation": False, "roof": False, "facade": False})
    elif stage == "excavation":
        scene.update({"floors": 0, "columns": 0, "slabs": 0, "walls": 0, "windows": 0, "foundation": False, "roof": False, "facade": False})
        dets.extend(_det("excavator", 1))
        dets.extend(_det("dump_truck", 2))
    elif stage == "foundation":
        scene.update({"floors": 0, "columns": 16, "slabs": 0, "walls": 0, "windows": 0, "foundation": True, "roof": False, "facade": False})
        dets.extend(_det("concrete_mixer", 1))
        dets.extend(_det("mobile_crane", 1))
        dets.extend(_det("foundation", 1))
    elif stage == "underground":
        scene.update({"floors": 0, "columns": 16, "slabs": 1, "walls": 1, "windows": 0, "foundation": True, "roof": False, "facade": False})
        dets.extend(_det("mobile_crane", 1))
        dets.extend(_det("concrete_mixer", 1))
        dets.extend(_det("slab", 1))
        dets.extend(_det("wall", 1))
        dets.extend(_det("foundation", 1))
    elif stage == "superstructure":
        scene.update(
            {
                "floors": floor_n,
                "columns": 16,
                "slabs": floor_n,
                "walls": 0,
                "windows": 0,
                "foundation": True,
                "roof": False,
                "facade": False,
            }
        )
        dets.extend(_det("mobile_crane", 1))
        dets.extend(_det("column", 16))
        dets.extend(_det("slab", max(floor_n, 1)))
        dets.extend(_det("foundation", 1))
    elif stage == "facade":
        scene.update(
            {
                "floors": 16,
                "columns": 16,
                "slabs": 16,
                "walls": 0,
                "windows": 16,
                "foundation": True,
                "roof": True,
                "facade": True,
            }
        )
        dets.extend(_det("window", 16))
        dets.extend(_det("facade", 1))
        dets.extend(_det("roof", 1))
        dets.extend(_det("foundation", 1))
    else:
        raise ValueError(f"unknown timelapse stage: {stage}")
    return scene, dets


def _sample_seconds(t0: float, t1: float, count: int) -> list[float]:
    if count <= 0:
        return []
    if count == 1:
        return [(t0 + t1) / 2.0]
    span = max(t1 - t0, 1e-6)
    step = span / count
    return [t0 + step * (i + 0.5) for i in range(count)]


def _extract_frame(cap: cv2.VideoCapture, fps: float, sec: float, dest: Path) -> Path:
    frame_idx = max(int(sec * fps), 0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError(f"cannot read frame at {sec:.1f}s")
    dest.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(dest), frame)
    return dest


def _try_yolo_detections(image_path: Path) -> list[Detection]:
    try:
        from sitewatch.cv.yolo_detector import YOLODetector

        return list(YOLODetector().detect(image_path))
    except Exception:
        return []


def iter_frame_plan(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Video order. Each next frame is FRAME_INTERVAL_MINUTES after the previous one."""
    grouped: dict[str, list[int]] = {}
    for idx, row in enumerate(rows):
        grouped.setdefault(str(row["stage"]), []).append(idx)
    plan: list[dict[str, Any]] = []
    clock = 0
    for stage, _t0, _t1, n_frames in VIDEO_WINDOWS:
        indices = grouped.get(stage, [])
        for k in range(n_frames):
            if indices:
                if stage == "superstructure":
                    row_index = indices[min(k, len(indices) - 1)]
                else:
                    row_index = indices[min(k * len(indices) // max(n_frames, 1), len(indices) - 1)]
            else:
                row_index = None
            floor_n = (k + 1) if stage == "superstructure" else 0
            stamp = RUN_CLOCK_START + timedelta(minutes=FRAME_INTERVAL_MINUTES * clock)
            plan.append(
                {
                    "stage": stage,
                    "floor_n": floor_n,
                    "row_index": row_index,
                    "stamp": stamp,
                    "slot_end": stamp + timedelta(minutes=FRAME_INTERVAL_MINUTES),
                }
            )
            clock += 1
    return plan


def _row_slots(rows: list[dict[str, Any]]) -> dict[int, tuple[datetime, datetime]]:
    slots: dict[int, tuple[datetime, datetime]] = {}
    for item in iter_frame_plan(rows):
        row_index = item["row_index"]
        if row_index is None:
            continue
        start, end = item["stamp"], item["slot_end"]
        prev = slots.get(row_index)
        if prev is None:
            slots[row_index] = (start, end)
        else:
            slots[row_index] = (min(prev[0], start), max(prev[1], end))
    return slots


def _clear_prior_observations() -> None:
    """Re-run replaces prior timelapse observations; alerts stay (fingerprint)."""
    from sitewatch.storage.models import DetectionRecord, Evidence, MediaAsset, StateTransitionRecord

    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).first()
        if project is None:
            return
        zone = session.query(Zone).filter_by(project_id=project.id, code=ZONE_CODE).first()
        if zone is None:
            return
        alerts = session.query(Alert).filter_by(project_id=project.id, zone_id=zone.id).all()
        alert_ids = [item.id for item in alerts]
        if alert_ids:
            session.query(Evidence).filter(Evidence.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            session.query(AlertEvent).filter(AlertEvent.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            session.query(Alert).filter(Alert.id.in_(alert_ids)).delete(synchronize_session=False)
        session.query(DeviationRecord).filter_by(project_id=project.id, zone_id=zone.id).delete(
            synchronize_session=False
        )
        obs = session.query(Observation).filter_by(project_id=project.id, zone_id=zone.id).all()
        obs_ids = [item.id for item in obs]
        media_ids = [item.media_id for item in obs]
        state_ids = [
            row.id
            for row in session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .all()
        ]
        if state_ids:
            session.query(StateTransitionRecord).filter(
                (StateTransitionRecord.from_state_id.in_(state_ids))
                | (StateTransitionRecord.to_state_id.in_(state_ids))
            ).delete(synchronize_session=False)
        if obs_ids:
            session.query(Evidence).filter(Evidence.observation_id.in_(obs_ids)).update(
                {Evidence.observation_id: None},
                synchronize_session=False,
            )
            session.query(ActualStateRecord).filter(ActualStateRecord.observation_id.in_(obs_ids)).delete(
                synchronize_session=False
            )
            session.query(DetectionRecord).filter(DetectionRecord.observation_id.in_(obs_ids)).delete(
                synchronize_session=False
            )
            session.query(Observation).filter(Observation.id.in_(obs_ids)).delete(synchronize_session=False)
        if media_ids:
            session.query(Evidence).filter(Evidence.media_id.in_(media_ids)).update(
                {Evidence.media_id: None},
                synchronize_session=False,
            )
            session.query(MediaAsset).filter(MediaAsset.id.in_(media_ids)).delete(synchronize_session=False)


def _schedule_stage_for(item: dict[str, Any], stages: list[ScheduleStage]) -> ScheduleStage | None:
    stage = item["stage"]
    floor_n = int(item["floor_n"])
    if stage == "superstructure":
        for row in stages:
            if row.stage != stage:
                continue
            expected = json.loads(row.expected_json or "{}")
            if int(expected.get("floors") or 0) == floor_n:
                return row
    matches = [row for row in stages if row.stage == stage]
    return matches[0] if matches else None


def _evaluate_timelapse_frames(rows: list[dict[str, Any]]) -> None:
    """Compare each frame with the stage it belongs to. Clock step is 30 minutes, not calendar weeks."""
    plan = iter_frame_plan(rows)
    by_stamp = {item["stamp"]: item for item in plan}
    engine = DeviationEngine()
    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).first()
        zone = (
            session.query(Zone).filter_by(project_id=project.id, code=ZONE_CODE).first()
            if project is not None
            else None
        )
        if project is None or zone is None:
            return
        stages = (
            session.query(ScheduleStage)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ScheduleStage.start_date.asc())
            .all()
        )
        state_rows = (
            session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ActualStateRecord.timestamp.asc())
            .all()
        )
        history: list[ActualState] = []
        for state_row in state_rows:
            actual = ActualState.model_validate_json(state_row.payload_json)
            item = by_stamp.get(actual.timestamp.replace(microsecond=0))
            if item is None:
                history.append(actual)
                continue
            stage_row = _schedule_stage_for(item, stages)
            if stage_row is None:
                history.append(actual)
                continue
            expected_payload = json.loads(stage_row.expected_json or "{}")
            on_date = actual.timestamp.date()
            expected = build_expected_state(
                object_id=project.code,
                zone_id=zone.code,
                on_date=on_date,
                stage=stage_row.stage,
                expected=expected_payload,
                start_date=on_date,
                end_date=on_date,
                stage_label_override=stage_row.stage_label or None,
            )
            obs = session.get(Observation, state_row.observation_id) if state_row.observation_id else None
            media = session.get(MediaAsset, obs.media_id) if obs is not None else None
            camera = session.get(Camera, obs.camera_id) if obs is not None and obs.camera_id else None
            evidence = evidence_from_observations(
                [
                    {
                        "media_path": media.path if media else "",
                        "timestamp": actual.timestamp,
                        "observation_id": obs.id if obs else None,
                        "media_id": media.id if media else None,
                        "viz_path": obs.viz_path if obs else None,
                        "camera_code": camera.code if camera else CAMERA_CODE,
                    }
                ]
            )
            for candidate in engine.evaluate(expected, actual, history=history, evidence=evidence):
                persist_candidate(
                    session,
                    project_id=project.id,
                    zone_id=zone.id,
                    candidate=candidate,
                )
            history.append(actual)


def run_timelapse(*, video: Path | None = None) -> dict[str, Any]:
    ensure_default_schedule_loaded()
    path = video or video_path()
    if not path.is_file():
        raise FileNotFoundError("видео ещё не загружено")

    _clear_prior_observations()
    rows = parse_ksg(ksg_path(), default_zone=ZONE_CODE, default_project=PROJECT_CODE)
    frame_plan = iter_frame_plan(rows)
    plan_by_stage: dict[str, list[dict[str, Any]]] = {}
    for item in frame_plan:
        plan_by_stage.setdefault(item["stage"], []).append(item)

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"cannot open video: {path}")
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    frame_count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
    duration = frame_count / fps if fps > 0 else 0.0

    settings = get_settings()
    frames_dir = settings.data_dir / "source" / PROJECT_CODE / "timelapse"
    frames_dir.mkdir(parents=True, exist_ok=True)

    processed = 0
    for stage, t0, t1, n_frames in VIDEO_WINDOWS:
        seconds = _sample_seconds(t0, t1, n_frames)
        stage_plan = plan_by_stage.get(stage, [])
        for idx, sec in enumerate(seconds):
            item = stage_plan[idx] if idx < len(stage_plan) else None
            floor_n = int(item["floor_n"]) if item else ((idx + 1) if stage == "superstructure" else 0)
            stamp = item["stamp"] if item else RUN_CLOCK_START + timedelta(minutes=FRAME_INTERVAL_MINUTES * processed)
            frame_file = frames_dir / f"{stage}_{idx:02d}_{stamp.strftime('%Y%m%dT%H%M%S')}.jpg"
            _extract_frame(cap, fps, sec, frame_file)
            scene, dets = scenario_frame_state(stage, floor_n=floor_n)
            scene["housing_stage"] = stage
            scene["housing_floor"] = floor_n
            # Optional YOLO: store alongside, never claim scenario_timelapse is YOLO.
            yolo_dets = _try_yolo_detections(frame_file)
            all_dets = list(dets) + yolo_dets
            pred_path = _write_prediction(frame_file, stamp, type("D", (), {"name": MODEL_NAME})(), all_dets)
            viz_path = (
                settings.data_dir
                / "observations"
                / "viz"
                / f"{frame_file.stem}_{stamp.strftime('%Y%m%dT%H%M%S')}.jpg"
            )
            from sitewatch.cv.visualize import draw_detections

            draw_detections(frame_file, dets, viz_path)
            actual = detections_to_actual_state(
                object_id=PROJECT_CODE,
                zone_id=ZONE_CODE,
                timestamp=stamp,
                camera_code=CAMERA_CODE,
                detections=dets,
                scene=scene,
                n_frames=1,
            )
            actual.scene_attributes["timelapse_sec"] = sec
            actual.scene_attributes["model_name"] = MODEL_NAME
            _persist_observation(
                project_code=PROJECT_CODE,
                zone_code=ZONE_CODE,
                camera_code=CAMERA_CODE,
                timestamp=stamp,
                source_path=frame_file,
                source_type="video",
                detections=all_dets,
                actual=actual,
                pred_path=pred_path,
                viz_path=viz_path,
                detector_name=MODEL_NAME,
            )
            processed += 1
    cap.release()

    _evaluate_timelapse_frames(rows)

    payload = get_schedule()
    signals = _collect_signals()
    payload["run"] = {
        "frames_processed": processed,
        "frame_interval_minutes": FRAME_INTERVAL_MINUTES,
        "video_duration_sec": round(duration, 2),
        "signals": signals,
    }
    return payload


def _collect_signals() -> list[dict[str, Any]]:
    ensure_catalog()
    out: list[dict[str, Any]] = []
    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).one()
        alerts = (
            session.query(Alert)
            .filter_by(project_id=project.id, status="open")
            .order_by(Alert.created_at.asc())
            .all()
        )
        for alert in alerts:
            at = alert.created_at.isoformat(timespec="seconds") if alert.created_at else None
            # Prefer first evidence timestamp when present.
            if alert.evidence:
                ev = sorted(alert.evidence, key=lambda item: item.timestamp)[0]
                at = ev.timestamp.isoformat(timespec="seconds")
            text = (alert.message or "").split("\n", 1)[0].strip() or alert.alert_type
            out.append({"type": alert.alert_type, "text": text, "at": at})
    return out


def _observed_floors() -> list[tuple[datetime, int]]:
    points: list[tuple[datetime, int]] = []
    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).first()
        if project is None:
            return points
        zone = session.query(Zone).filter_by(project_id=project.id, code=ZONE_CODE).first()
        if zone is None:
            return points
        rows = (
            session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ActualStateRecord.timestamp.asc())
            .all()
        )
        for row in rows:
            payload = json.loads(row.payload_json)
            elements = payload.get("elements") or {}
            floors_stat = elements.get("floors") or {}
            floors = int(floors_stat.get("count") or 0)
            points.append((row.timestamp.replace(microsecond=0), floors))
    return points


def _open_alert_notes() -> list[tuple[datetime, str]]:
    notes: list[tuple[datetime, str]] = []
    with get_session() as session:
        project = session.query(Project).filter_by(code=PROJECT_CODE).first()
        if project is None:
            return notes
        alerts = session.query(Alert).filter_by(project_id=project.id, status="open").all()
        for alert in alerts:
            text = (alert.message or "").split("\n", 1)[0].strip()
            if not text:
                text = f"Выявлены признаки {alert.alert_type}. Требуется проверка."
            short = text[:160]
            stamps = [ev.timestamp.replace(microsecond=0) for ev in (alert.evidence or [])]
            if not stamps and alert.created_at:
                stamps = [alert.created_at.replace(microsecond=0)]
            for stamp in stamps:
                notes.append((stamp, short))
    return notes


def get_schedule() -> dict[str, Any]:
    path = ksg_path()
    if not path.is_file():
        raise FileNotFoundError(f"missing schedule CSV: {path}")
    try:
        ensure_default_schedule_loaded()
    except Exception:
        ensure_catalog()

    rows = parse_ksg(path, default_zone=ZONE_CODE, default_project=PROJECT_CODE)
    catalog = _load_catalog()
    if len(catalog) != len(rows):
        catalog = _rebuild_catalog_json(rows)

    observed = _observed_floors()
    alert_notes = _open_alert_notes()
    slots = _row_slots(rows)
    out_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        meta = catalog[idx] if idx < len(catalog) else {}
        slot = slots.get(idx)
        if slot is not None:
            start_dt, end_dt = slot
        else:
            start_day: date = row["start_date"]
            start_dt = datetime.combine(start_day, datetime.min.time()).replace(hour=8)
            end_dt = start_dt + timedelta(minutes=FRAME_INTERVAL_MINUTES)
        plan_floors = int((row.get("expected") or {}).get("floors") or 0)
        window_facts = [floors for stamp, floors in observed if start_dt <= stamp < end_dt]
        fact_floors: int | None = max(window_facts) if window_facts else None

        open_note = None
        for stamp, note in alert_notes:
            if start_dt <= stamp < end_dt:
                open_note = note
                break

        if fact_floors is None:
            status = "planned"
            fact_note = None
        elif open_note:
            status = "attention"
            fact_note = open_note
        elif fact_floors >= plan_floors:
            status = "done"
            fact_note = None
        else:
            status = "attention"
            fact_note = "Возможное отклонение по этажности. Требуется проверка."

        out_rows.append(
            {
                "stage": row["stage"],
                "catalog_code": meta.get("catalog_code") or CATALOG_META.get(row["stage"], ("",))[0],
                "title": meta.get("title")
                or (
                    f"Каркас, этаж {plan_floors}"
                    if row["stage"] == "superstructure"
                    else stage_label(row["stage"])
                ),
                "date_start": start_dt.isoformat(timespec="seconds"),
                "date_end": end_dt.isoformat(timespec="seconds"),
                "plan_floors": plan_floors,
                "fact_floors": fact_floors,
                "status": status,
                "fact_note": fact_note,
            }
        )

    return {
        "project_id": PROJECT_CODE,
        "title": PROJECT_TITLE,
        "video_url": VIDEO_URL,
        "videos": scenario_videos(),
        "frame_interval_minutes": FRAME_INTERVAL_MINUTES,
        "rows": out_rows,
    }
