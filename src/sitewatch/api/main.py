from __future__ import annotations

import logging
import re
import tempfile
import threading
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from sitewatch.cv.factory import build_detector
from sitewatch.cv.annotation_detector import MissingAnnotationSidecarError
from sitewatch.inspector.workflow import load_inspector_cfg, reasons_for_status, status_label
from sitewatch.pipeline.capture import capture_due_cameras, capture_status
from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline import housing16
from sitewatch.pipeline.observe import (
    CAPTURE_ORIGIN_MANUAL,
    observe_image,
    observe_video,
)
from sitewatch.pipeline.seed import seed_demo
from sitewatch.catalog import construction as construction_catalog
from sitewatch.services import catalog
from sitewatch.services.media import public_media_url
from sitewatch.services.queries import (
    assert_capture_point,
    dashboard,
    alert_summary,
    get_alert,
    get_evidence,
    get_project,
    inspection_brief,
    inspector_queue,
    latest_actual_state,
    latest_observed_state,
    list_alerts,
    list_observations,
    list_stages,
    object_page,
    add_candidate_review,
    set_alert_status,
    timeline,
    zone_plan_fact,
)
from sitewatch.settings import get_settings, project_root

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}
KSG_SUFFIXES = {".csv", ".xlsx", ".xls", ".json"}
MAX_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_KSG_BYTES = 8 * 1024 * 1024

api = APIRouter(prefix="/api")


class ObserveIn(BaseModel):
    image_path: str
    project: str = "site_001"
    zone: str
    camera: str
    timestamp: str


class InferenceIn(BaseModel):
    image_path: str
    detector: str | None = None


class AnalysisIn(BaseModel):
    project: str = "site_001"
    zone: str
    date: date


class EvaluateIn(BaseModel):
    project: str = "site_001"
    zone: str
    date: date


class StatusIn(BaseModel):
    status: str
    reason: str = ""
    note: str = ""
    actor: str | None = None


class ObservationCreateIn(BaseModel):
    image_path: str
    project: str = "site_001"
    zone: str
    camera: str
    timestamp: str
    run_analysis: bool = Field(default=False)


class ProjectCreateIn(BaseModel):
    code: str
    name: str
    address: str = ""


class ProjectUpdateIn(BaseModel):
    name: str | None = None
    address: str | None = None


class ZoneCreateIn(BaseModel):
    code: str | None = None
    name: str
    description: str = ""
    construction_type_id: str | None = None


class ZoneUpdateIn(BaseModel):
    name: str | None = None
    description: str | None = None
    construction_type_id: str | None = None


class ZoneNoteCreateIn(BaseModel):
    body: str
    author: str = ""


class CameraCreateIn(BaseModel):
    code: str
    name: str
    location: str = ""
    orientation: str = ""
    source_type: str = "photo"
    uri: str = ""
    enabled: bool = True
    interval_minutes: int = 30


class CameraUpdateIn(BaseModel):
    name: str | None = None
    location: str | None = None
    orientation: str | None = None
    source_type: str | None = None
    uri: str | None = None
    enabled: bool | None = None
    interval_minutes: int | None = None


class StageCreateIn(BaseModel):
    start_date: date
    end_date: date | None = None
    stage: str
    stage_label: str = ""
    expected: dict = Field(default_factory=dict)


class StageUpdateIn(BaseModel):
    start_date: date | None = None
    end_date: date | None = None
    stage: str | None = None
    stage_label: str | None = None
    expected: dict | None = None


class CaptureRunIn(BaseModel):
    camera: str | None = None
    project: str | None = None
    zone: str | None = None
    force: bool = True


def _exc_message(exc: Exception, fallback: str) -> str:
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    text = str(exc).strip().strip("'\"")
    return text or fallback


def _catalog_result(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except KeyError as exc:
        raise HTTPException(404, _exc_message(exc, "not found")) from exc
    except PermissionError as exc:
        raise HTTPException(409, _exc_message(exc, "conflict")) from exc
    except ValueError as exc:
        raise HTTPException(400, _exc_message(exc, "invalid request")) from exc


@api.get("/health")
def api_health():
    return {"ok": True}


@api.get("/inspector/config")
def api_inspector_config():
    cfg = load_inspector_cfg()
    reasons = {
        status: reasons_for_status(status) for status in (cfg.get("reasons") or {})
    }
    statuses = {
        code: status_label(code) for code in (cfg.get("statuses") or {})
    }
    return {
        "disclaimer": str(cfg.get("disclaimer") or "").strip(),
        "actor_default": str(cfg.get("actor_default") or "inspector"),
        "statuses": statuses,
        "reasons": reasons,
        "on_site_checks": cfg.get("on_site_checks") or {},
    }


@api.post("/demo/seed")
def api_seed():
    return seed_demo()


@api.get("/projects")
def api_projects():
    return dashboard()


@api.post("/projects")
def api_create_project(body: ProjectCreateIn):
    return _catalog_result(catalog.create_project, code=body.code, name=body.name, address=body.address)


@api.patch("/projects/{project_code}")
def api_update_project(project_code: str, body: ProjectUpdateIn):
    return _catalog_result(
        catalog.update_project,
        project_code,
        **body.model_dump(exclude_unset=True),
    )


@api.get("/catalog/stages")
def api_catalog_stages():
    return catalog.catalog_stages()


@api.get("/catalog/construction-types")
def api_construction_types():
    try:
        return construction_catalog.list_construction_types()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc


@api.get("/catalog/construction-types/{type_id}/works")
def api_construction_works(type_id: str):
    try:
        return construction_catalog.list_works_for_type(type_id)
    except KeyError as exc:
        raise HTTPException(404, _exc_message(exc, "construction type not found")) from exc
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(500, str(exc)) from exc


@api.post("/projects/{project_code}/zones")
def api_create_zone(project_code: str, body: ZoneCreateIn):
    return _catalog_result(
        catalog.create_zone,
        project_code,
        code=body.code,
        name=body.name,
        description=body.description,
        construction_type_id=body.construction_type_id,
    )


@api.patch("/projects/{project_code}/zones/{zone_code}")
def api_update_zone(project_code: str, zone_code: str, body: ZoneUpdateIn):
    payload = body.model_dump(exclude_unset=True)
    return _catalog_result(catalog.update_zone, project_code, zone_code, **payload)


@api.get("/projects/{project_code}/zones/{zone_code}/notes")
def api_list_zone_notes(project_code: str, zone_code: str):
    return _catalog_result(catalog.list_zone_notes, project_code, zone_code)


@api.post("/projects/{project_code}/zones/{zone_code}/notes")
def api_create_zone_note(project_code: str, zone_code: str, body: ZoneNoteCreateIn):
    return _catalog_result(
        catalog.create_zone_note,
        project_code,
        zone_code,
        body=body.body,
        author=body.author,
    )


@api.delete("/projects/{project_code}/zones/{zone_code}")
def api_delete_zone(project_code: str, zone_code: str):
    return _catalog_result(catalog.delete_zone, project_code, zone_code)


@api.delete("/observations/{observation_id}")
def api_delete_observation(observation_id: str):
    return _catalog_result(catalog.delete_observation, observation_id)


@api.post("/projects/{project_code}/zones/{zone_code}/cameras")
def api_create_camera(project_code: str, zone_code: str, body: CameraCreateIn):
    return _catalog_result(
        catalog.create_camera,
        project_code,
        zone_code,
        **body.model_dump(),
    )


@api.patch("/cameras/{camera_code}")
def api_update_camera(camera_code: str, body: CameraUpdateIn):
    return _catalog_result(catalog.update_camera, camera_code, **body.model_dump(exclude_unset=True))


@api.delete("/cameras/{camera_code}")
def api_delete_camera(camera_code: str):
    return _catalog_result(catalog.delete_camera, camera_code)


@api.post("/projects/{project_code}/zones/{zone_code}/ksg")
def api_create_stage(project_code: str, zone_code: str, body: StageCreateIn):
    return _catalog_result(
        catalog.create_stage,
        project_code,
        zone_code,
        start_date=body.start_date,
        end_date=body.end_date,
        stage=body.stage,
        stage_label_text=body.stage_label,
        expected=body.expected,
    )


@api.patch("/ksg/{stage_id}")
def api_update_stage(stage_id: str, body: StageUpdateIn):
    return _catalog_result(catalog.update_stage, stage_id, **body.model_dump(exclude_unset=True))


@api.delete("/ksg/{stage_id}")
def api_delete_stage(stage_id: str):
    return _catalog_result(catalog.delete_stage, stage_id)


@api.post("/projects/{project_code}/zones/{zone_code}/ksg/import")
async def api_import_ksg(
    project_code: str,
    zone_code: str,
    file: UploadFile = File(...),
    replace: str = Form("true"),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in KSG_SUFFIXES:
        raise HTTPException(400, "schedule file must be csv, xlsx or json")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "empty file")
    if len(payload) > MAX_KSG_BYTES:
        raise HTTPException(400, "file is larger than 8 MB")
    should_replace = replace.strip().lower() in {"1", "true", "yes", "on"}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename or "schedule.csv").name
        path.write_bytes(payload)
        return _catalog_result(
            catalog.import_schedule_file,
            path,
            project_code=project_code,
            zone_code=zone_code,
            replace=should_replace,
        )


def _require_housing_16(project_id: str) -> None:
    if project_id != housing16.PROJECT_CODE:
        raise HTTPException(404, f"schedule API is available only for {housing16.PROJECT_CODE}")


@api.get("/projects/{project_id}/schedule")
def api_housing_schedule(project_id: str):
    _require_housing_16(project_id)
    try:
        return housing16.get_schedule()
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@api.post("/projects/{project_id}/schedule")
async def api_housing_schedule_upload(project_id: str, file: UploadFile = File(...)):
    _require_housing_16(project_id)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".csv":
        raise HTTPException(400, "schedule file must be csv")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "empty file")
    if len(payload) > MAX_KSG_BYTES:
        raise HTTPException(400, "file is larger than 8 MB")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / Path(file.filename or "ksg.csv").name
        path.write_bytes(payload)
        try:
            housing16.import_housing_schedule(path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return housing16.get_schedule()


@api.post("/projects/{project_id}/run")
def api_housing_run(project_id: str):
    _require_housing_16(project_id)
    try:
        return housing16.run_timelapse()
    except FileNotFoundError as exc:
        detail = str(exc)
        if "видео" in detail.lower():
            raise HTTPException(404, "видео ещё не загружено") from exc
        raise HTTPException(404, detail) from exc
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/capture/status")
def api_capture_status():
    return capture_status()


@api.post("/capture/run")
def api_capture_run(body: CaptureRunIn | None = None):
    payload = body or CaptureRunIn()
    return capture_due_cameras(
        force=payload.force,
        camera_code=payload.camera,
        project_code=payload.project,
        zone_code=payload.zone,
    )


@api.get("/projects/{project_id}")
def api_project(project_id: str):
    try:
        return get_project(project_id)
    except KeyError as exc:
        raise HTTPException(404, "project not found") from exc


@api.get("/projects/{project_id}/stages")
def api_stages(project_id: str):
    try:
        return list_stages(project_id)
    except KeyError as exc:
        raise HTTPException(404, "project not found") from exc


@api.get("/projects/{project_id}/observations")
def api_observations(project_id: str, zone: str | None = None):
    try:
        return list_observations(project_id, zone_code=zone)
    except KeyError as exc:
        raise HTTPException(404, "project not found") from exc


@api.get("/projects/{project_code}/zones/{zone_code}")
def api_object(project_code: str, zone_code: str):
    try:
        return object_page(project_code, zone_code)
    except Exception as exc:
        raise HTTPException(404, str(exc)) from exc


@api.get("/projects/{project_code}/zones/{zone_code}/timeline")
def api_timeline(project_code: str, zone_code: str):
    return timeline(project_code, zone_code)


@api.get("/alerts/summary")
def api_alert_summary(status: str | None = None, zone: str | None = None, project: str | None = None):
    """Type counts without alert bodies. A failed read is not an empty queue."""
    return alert_summary(status=status, zone_code=zone, project_code=project)


@api.get("/alerts")
def api_alerts(
    status: str | None = None,
    zone: str | None = None,
    project: str | None = None,
    type: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    if limit is not None and limit < 0:
        raise HTTPException(400, "limit must be >= 0")
    if offset < 0:
        raise HTTPException(400, "offset must be >= 0")
    return list_alerts(
        status=status,
        zone_code=zone,
        project_code=project,
        alert_type=type,
        limit=limit,
        offset=offset,
    )


@api.get("/queue")
def api_queue(status: str = "open"):
    return inspector_queue(status=status)


@api.get("/alerts/{alert_id}")
def api_alert(alert_id: str):
    try:
        return get_alert(alert_id)
    except KeyError as exc:
        raise HTTPException(404, "alert not found") from exc


@api.get("/alerts/{alert_id}/brief")
def api_alert_brief(alert_id: str):
    try:
        return inspection_brief(alert_id)
    except KeyError as exc:
        raise HTTPException(404, "alert not found") from exc


@api.post("/alerts/{alert_id}/status")
def api_alert_status(alert_id: str, body: StatusIn):
    allowed = {"open", "confirmed", "rejected", "needs_more_data"}
    if body.status not in allowed:
        raise HTTPException(400, "status must be open|confirmed|rejected|needs_more_data")
    try:
        return set_alert_status(
            alert_id,
            body.status,
            reason=body.reason,
            note=body.note,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(404, "alert not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.post("/alerts/{alert_id}/decision")
def api_alert_decision(alert_id: str, body: StatusIn):
    return api_alert_status(alert_id, body)


class CandidateReviewIn(BaseModel):
    source: str
    verdict: str
    wrong_type: str = ""
    missed_object: str = ""
    actor: str | None = None


@api.post("/alerts/{alert_id}/candidate-review")
def api_candidate_review(alert_id: str, body: CandidateReviewIn):
    """Spot-check a model proposal. Does not write the fact and does not open a deviation."""
    try:
        return add_candidate_review(
            alert_id,
            source=body.source,
            verdict=body.verdict,
            wrong_type=body.wrong_type,
            missed_object=body.missed_object,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(404, "alert not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@api.get("/evidence/{evidence_id}")
def api_evidence(evidence_id: str):
    try:
        return get_evidence(evidence_id)
    except KeyError as exc:
        raise HTTPException(404, "evidence not found") from exc


def _parse_timestamp(raw: str) -> datetime:
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(400, "timestamp must be ISO-8601") from exc


def _safe_upload_name(filename: str | None, stamp: datetime) -> str:
    original = Path(filename or "capture.jpg").name
    suffix = original.rsplit(".", 1)[-1].lower() if "." in original else "jpg"
    stem = re.sub(r"[^a-zA-Z0-9._-]+", "_", Path(original).stem).strip("._")[:60] or "capture"
    return f"{stamp.strftime('%Y%m%dT%H%M%S')}_{stem}.{suffix}"


def _visible_count(state) -> int:
    n = 0
    for stat in (state.equipment or {}).values():
        n += int(getattr(stat, "count", 0) or 0)
    for stat in (state.elements or {}).values():
        n += int(getattr(stat, "count", 0) or 0)
    return n


@api.post("/observations")
def api_create_observation(body: ObservationCreateIn):
    try:
        assert_capture_point(body.project, body.zone, body.camera)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    stamp = _parse_timestamp(body.timestamp)
    state = observe_image(
        image_path=Path(body.image_path),
        project_code=body.project,
        zone_code=body.zone,
        camera_code=body.camera,
        timestamp=stamp,
        capture_origin=CAPTURE_ORIGIN_MANUAL,
    )
    result: dict = {"ok": True, "actual_state": state.model_dump(mode="json"), "n_detections": _visible_count(state)}
    if body.run_analysis:
        result["alert_ids"] = evaluate_zone_date(
            project_code=body.project,
            zone_code=body.zone,
            on_date=stamp.date(),
        )
    return result


@api.post("/observations/upload")
async def api_upload_observation(
    file: UploadFile = File(...),
    project: str = Form(...),
    zone: str = Form(...),
    camera: str = Form(...),
    timestamp: str = Form(...),
    run_analysis: str = Form("true"),
    sidecar: UploadFile | None = File(default=None),
):
    try:
        assert_capture_point(project, zone, camera)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    stamp = _parse_timestamp(timestamp)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in IMAGE_SUFFIXES and suffix not in VIDEO_SUFFIXES:
        raise HTTPException(400, "file must be jpeg, png, webp, mp4, webm or mov")
    payload = await file.read()
    if not payload:
        raise HTTPException(400, "empty file")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, "file is larger than 80 MB")
    name = _safe_upload_name(file.filename, stamp)
    should_evaluate = run_analysis.strip().lower() in {"1", "true", "yes", "on"}
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / name
        source.write_bytes(payload)
        if sidecar is not None and suffix not in VIDEO_SUFFIXES:
            side_payload = await sidecar.read()
            if side_payload:
                source.with_suffix(".json").write_bytes(side_payload)
        try:
            if suffix in VIDEO_SUFFIXES:
                state = observe_video(
                    video_path=source,
                    project_code=project,
                    zone_code=zone,
                    camera_code=camera,
                    timestamp=stamp,
                    capture_origin=CAPTURE_ORIGIN_MANUAL,
                )
                source_type = "video"
            else:
                state = observe_image(
                    image_path=source,
                    project_code=project,
                    zone_code=zone,
                    camera_code=camera,
                    timestamp=stamp,
                    capture_origin=CAPTURE_ORIGIN_MANUAL,
                )
                source_type = "photo"
        except MissingAnnotationSidecarError as exc:
            raise HTTPException(400, str(exc)) from exc
    detector = build_detector()
    result: dict = {
        "ok": True,
        "project": project,
        "zone": zone,
        "camera": camera,
        "timestamp": stamp.isoformat(),
        "source_type": source_type,
        "detector": getattr(detector, "name", get_settings().detector),
        "n_detections": _visible_count(state),
        "actual_state": state.model_dump(mode="json"),
        "media_url": public_media_url(str(get_settings().data_dir / "source" / project / name)),
        "alert_ids": [],
    }
    if should_evaluate:
        result["alert_ids"] = evaluate_zone_date(project_code=project, zone_code=zone, on_date=stamp.date())
    return result


@api.post("/inference")
def api_inference(body: InferenceIn):
    detector = build_detector(body.detector)
    detections = detector.detect(Path(body.image_path))
    return {
        "detector": getattr(detector, "name", body.detector or "annotation"),
        "detections": [item.model_dump(mode="json") for item in detections],
    }


@api.post("/analysis")
def api_analysis(body: AnalysisIn):
    return {
        "alert_ids": evaluate_zone_date(
            project_code=body.project,
            zone_code=body.zone,
            on_date=body.date,
        )
    }


@api.post("/observe")
def api_observe(body: ObserveIn):
    from sitewatch.perception.pipeline import is_real_mode, resolve_perception_mode

    mode = resolve_perception_mode()
    if is_real_mode(mode):
        from sitewatch.pipeline.jobs import enqueue_frame_analysis

        job_id = enqueue_frame_analysis(
            image_path=Path(body.image_path),
            project_code=body.project,
            zone_code=body.zone,
            camera_code=body.camera,
            timestamp=datetime.fromisoformat(body.timestamp),
            capture_origin=CAPTURE_ORIGIN_MANUAL,
            run_evaluate=False,
        )
        return {"job_id": job_id, "status": "queued", "async": True, "mode": mode.value}
    state = observe_image(
        image_path=Path(body.image_path),
        project_code=body.project,
        zone_code=body.zone,
        camera_code=body.camera,
        timestamp=datetime.fromisoformat(body.timestamp),
        capture_origin=CAPTURE_ORIGIN_MANUAL,
    )
    return state.model_dump(mode="json")


@api.post("/evaluate")
def api_evaluate(body: EvaluateIn):
    return {"alert_ids": evaluate_zone_date(project_code=body.project, zone_code=body.zone, on_date=body.date)}


@api.get("/jobs/{job_id}")
def api_get_job(job_id: str):
    from sitewatch.pipeline.jobs import get_job

    payload = get_job(job_id)
    if payload is None:
        raise HTTPException(404, "job not found")
    return payload


@api.get("/projects/{project_code}/zones/{zone_code}/observed-state")
def api_observed_state(project_code: str, zone_code: str):
    payload = latest_observed_state(project_code, zone_code)
    if payload is None:
        raise HTTPException(404, "observed state not found")
    return payload


@api.get("/projects/{project_code}/zones/{zone_code}/actual-state")
def api_actual_state(project_code: str, zone_code: str):
    payload = latest_actual_state(project_code, zone_code)
    if payload is None:
        raise HTTPException(404, "actual state not found")
    return payload


@api.get("/projects/{project_code}/zones/{zone_code}/plan-fact")
def api_plan_fact(project_code: str, zone_code: str):
    payload = zone_plan_fact(project_code, zone_code)
    if payload is None:
        raise HTTPException(404, "zone not found")
    return payload


def _capture_loop(stop: threading.Event, tick: int) -> None:
    log = logging.getLogger("sitewatch.capture")
    while not stop.wait(max(int(tick), 5)):
        try:
            capture_due_cameras()
        except Exception:
            log.exception("capture tick failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    stop = threading.Event()
    app.state.capture_stop = stop
    if settings.capture_loop:
        thread = threading.Thread(
            target=_capture_loop,
            args=(stop, settings.capture_tick_seconds),
            daemon=True,
            name="sitewatch-capture",
        )
        thread.start()
        app.state.capture_thread = thread
    yield
    stop.set()
    try:
        from sitewatch.pipeline.jobs import shutdown_executor

        shutdown_executor()
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Скрипка", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api)

    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/media/video/{filename}")
    def media_scenario_video(filename: str):
        """Serve scenario videos from project video/ without breaking /media data mount."""
        safe = Path(filename).name
        if safe != filename or ".." in filename:
            raise HTTPException(400, "invalid filename")
        path = project_root() / "video" / safe
        if not path.is_file():
            raise HTTPException(404, "видео ещё не загружено")
        return FileResponse(path, media_type="video/mp4" if path.suffix.lower() == ".mp4" else None)

    dist = project_root() / "frontend" / "dist"
    index = dist / "index.html"

    @app.get("/health")
    def root_health():
        return {"ok": True, "ui": "react" if index.is_file() else "api-only"}

    if index.is_file():
        assets = dist / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets)), name="spa-assets")

        @app.get("/")
        def spa_index():
            return FileResponse(index)
    else:

        @app.get("/")
        def api_root():
            return {
                "ok": True,
                "service": "sitewatch",
                "ui": "missing",
                "hint": "cd frontend && npm install && npm run build",
            }

    app.mount("/media", StaticFiles(directory=str(data_dir)), name="media")

    if index.is_file():

        @app.exception_handler(StarletteHTTPException)
        async def spa_or_http(request: Request, exc: StarletteHTTPException):
            path = request.url.path
            api_like = path.startswith("/api") or path.startswith("/media") or path.startswith("/assets")
            if exc.status_code == 404 and not api_like:
                return FileResponse(index)
            return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    return app


app = create_app()
