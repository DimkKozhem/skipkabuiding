from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import cv2

from sitewatch.domain.enums import PerceptionMode
from sitewatch.perception.pipeline import resolve_perception_mode
from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.observe import (
    CAPTURE_ORIGIN_SCHEDULED,
    observe_image,
    observe_video,
)
from sitewatch.services.queries import _camera_item, _session
from sitewatch.settings import get_settings
from sitewatch.storage.models import Camera, Project, Zone

log = logging.getLogger("sitewatch.capture")

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
STREAM_PREFIXES = ("rtsp://", "rtsps://", "http://", "https://")


def _ensure_explicit_empty_sidecar(image_path: Path) -> None:
    """Live capture without labels: write explicit empty sidecar (≠ missing file)."""
    if resolve_perception_mode() != PerceptionMode.ANNOTATION:
        return
    sidecar = image_path.with_suffix(".json")
    if sidecar.exists():
        return
    sidecar.write_text(
        json.dumps(
            {
                "detections": [],
                "scene": {},
                "model_version": "capture-explicit-empty",
                "note": "live capture without labels; not a missing-sidecar error",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return bool(int(value)) if value not in (None, "") else False


def camera_is_due(camera: Camera, now: datetime, *, force: bool = False) -> bool:
    uri = (getattr(camera, "uri", "") or "").strip()
    if not uri:
        return False
    if force:
        return True
    if not _as_bool(getattr(camera, "enabled", True)):
        return False
    last = getattr(camera, "last_captured_at", None)
    if last is None:
        return True
    minutes = max(int(getattr(camera, "interval_minutes", 30) or 30), 1)
    return (now - last).total_seconds() >= minutes * 60


def resolve_capture_path(uri: str, *, camera_code: str, now: datetime) -> Path:
    text = uri.strip()
    settings = get_settings()
    if text.lower().startswith(STREAM_PREFIXES):
        dest = settings.data_dir / "raw" / "capture" / f"{camera_code}_{now.strftime('%Y%m%dT%H%M%S')}.jpg"
        dest.parent.mkdir(parents=True, exist_ok=True)
        capture = cv2.VideoCapture(text)
        try:
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok or frame is None:
            raise RuntimeError("не удалось снять кадр с видеопотока")
        if not cv2.imwrite(str(dest), frame):
            raise RuntimeError("не удалось сохранить кадр с видеопотока")
        return dest
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = (settings.data_dir / path).resolve()
    if path.is_dir():
        files = [
            item
            for item in path.iterdir()
            if item.is_file() and item.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES
        ]
        if not files:
            raise RuntimeError("в папке нет кадров")
        return max(files, key=lambda item: item.stat().st_mtime)
    if path.is_file():
        if path.suffix.lower() not in IMAGE_SUFFIXES | VIDEO_SUFFIXES:
            raise RuntimeError("файл источника должен быть jpeg, png, webp, mp4, webm или mov")
        return path
    raise RuntimeError("источник не найден")


def _mark_camera(camera_id: str, *, captured_at: datetime | None, error: str) -> None:
    with _session() as session:
        camera = session.get(Camera, camera_id)
        if camera is None:
            return
        if captured_at is not None:
            camera.last_captured_at = captured_at
        camera.last_error = (error or "")[:2000]


def capture_camera(camera: Camera, *, project_code: str, zone_code: str, now: datetime) -> dict:
    uri = (camera.uri or "").strip()
    if not uri:
        return {"camera": camera.code, "ok": False, "skipped": True, "reason": "no uri"}
    try:
        source = resolve_capture_path(uri, camera_code=camera.code, now=now)
        suffix = source.suffix.lower()
        if suffix in VIDEO_SUFFIXES:
            observe_video(
                video_path=source,
                project_code=project_code,
                zone_code=zone_code,
                camera_code=camera.code,
                timestamp=now,
                capture_origin=CAPTURE_ORIGIN_SCHEDULED,
            )
            source_type = "video"
        else:
            _ensure_explicit_empty_sidecar(source)
            observe_image(
                image_path=source,
                project_code=project_code,
                zone_code=zone_code,
                camera_code=camera.code,
                timestamp=now,
                capture_origin=CAPTURE_ORIGIN_SCHEDULED,
            )
            source_type = "photo"
        alert_ids: list[str] = []
        evaluate_error = ""
        try:
            alert_ids = evaluate_zone_date(project_code=project_code, zone_code=zone_code, on_date=now.date())
        except ValueError as exc:
            evaluate_error = str(exc)
            log.info("capture evaluate skipped %s/%s: %s", project_code, zone_code, exc)
        _mark_camera(camera.id, captured_at=now, error=evaluate_error)
        return {
            "camera": camera.code,
            "ok": True,
            "skipped": False,
            "source_type": source_type,
            "path": str(source),
            "alert_ids": alert_ids,
            "evaluate_error": evaluate_error,
        }
    except Exception as exc:
        _mark_camera(camera.id, captured_at=None, error=str(exc))
        log.warning("capture failed %s: %s", camera.code, exc)
        return {"camera": camera.code, "ok": False, "skipped": False, "reason": str(exc)}


def capture_due_cameras(
    *,
    now: datetime | None = None,
    force: bool = False,
    camera_code: str | None = None,
    project_code: str | None = None,
    zone_code: str | None = None,
) -> dict:
    stamp = now or datetime.utcnow()
    with _session() as session:
        query = session.query(Camera)
        if camera_code:
            query = query.filter_by(code=camera_code)
        cameras = query.order_by(Camera.code.asc()).all()
        zones = {item.id: item for item in session.query(Zone).all()}
        projects = {item.id: item for item in session.query(Project).all()}
        jobs: list[tuple[Camera, str, str]] = []
        for camera in cameras:
            zone = zones.get(camera.zone_id)
            if zone is None:
                continue
            project = projects.get(zone.project_id)
            if project is None:
                continue
            if project_code and project.code != project_code:
                continue
            if zone_code and zone.code != zone_code:
                continue
            if not camera_is_due(camera, stamp, force=force):
                continue
            jobs.append((camera, project.code, zone.code))
    results = [capture_camera(camera, project_code=project, zone_code=zone, now=stamp) for camera, project, zone in jobs]
    return {
        "ok": True,
        "at": stamp.isoformat(),
        "processed": len(results),
        "captured": sum(1 for item in results if item.get("ok")),
        "results": results,
    }


def capture_status() -> dict:
    settings = get_settings()
    now = datetime.utcnow()
    with _session() as session:
        cameras = session.query(Camera).order_by(Camera.code.asc()).all()
        zones = {item.id: item for item in session.query(Zone).all()}
        projects = {item.id: item for item in session.query(Project).all()}
        items = []
        for camera in cameras:
            zone = zones.get(camera.zone_id)
            project = projects.get(zone.project_id) if zone else None
            item = _camera_item(camera)
            item["project"] = project.code if project else None
            item["project_name"] = project.name if project else None
            item["zone"] = zone.code if zone else None
            item["zone_name"] = zone.name if zone else None
            item["due"] = camera_is_due(camera, now, force=False)
            items.append(item)
    return {
        "loop": bool(settings.capture_loop),
        "tick_seconds": int(settings.capture_tick_seconds),
        "interval_default_minutes": 30,
        "cameras": items,
    }
