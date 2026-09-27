"""Minimal async frame analysis jobs (thread pool, no Kafka)."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from sitewatch.domain.enums import JobStatus
from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.observe import observe_image
from sitewatch.settings import get_settings
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import FrameAnalysisJob

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None
_camera_locks: dict[str, threading.Lock] = {}
_camera_guard = threading.Lock()


def _lock_for_camera(camera_code: str) -> threading.Lock:
    with _camera_guard:
        lock = _camera_locks.get(camera_code)
        if lock is None:
            lock = threading.Lock()
            _camera_locks[camera_code] = lock
        return lock


def get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        workers = max(1, int(get_settings().analysis_workers or 2))
        _executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="frame-analyze")
    return _executor


def shutdown_executor() -> None:
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False, cancel_futures=True)
        _executor = None


def recover_stale_jobs(now: datetime | None = None) -> int:
    """Mark jobs left in processing after a restart or a hang."""
    init_db()
    stamp = now or datetime.utcnow()
    limit = max(60, int(get_settings().analysis_job_stale_seconds or 3600))
    cutoff = stamp - timedelta(seconds=limit)
    recovered = 0
    with get_session() as session:
        rows = (
            session.query(FrameAnalysisJob)
            .filter(FrameAnalysisJob.status == JobStatus.PROCESSING.value)
            .all()
        )
        for job in rows:
            started = job.created_at or stamp
            if started <= cutoff:
                job.status = JobStatus.FAILED.value
                job.error = "stale_running"
                job.finished_at = stamp
                recovered += 1
    return recovered


def enqueue_frame_analysis(
    *,
    image_path: Path,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime | None = None,
    capture_origin: str | None = None,
    run_evaluate: bool = True,
    force: bool = False,
) -> str:
    init_db()
    recover_stale_jobs()
    ts = timestamp or datetime.utcnow()
    path = str(image_path)
    with get_session() as session:
        if not force:
            existing = (
                session.query(FrameAnalysisJob)
                .filter(
                    FrameAnalysisJob.image_path == path,
                    FrameAnalysisJob.camera_code == camera_code,
                    FrameAnalysisJob.status.in_(
                        [JobStatus.QUEUED.value, JobStatus.PROCESSING.value, JobStatus.COMPLETED.value]
                    ),
                )
                .order_by(FrameAnalysisJob.created_at.desc())
                .first()
            )
            if existing is not None:
                return existing.id
        depth = (
            session.query(FrameAnalysisJob)
            .filter(
                FrameAnalysisJob.status.in_([JobStatus.QUEUED.value, JobStatus.PROCESSING.value])
            )
            .count()
        )
        max_queued = max(1, int(get_settings().analysis_max_queued or 4))
        if depth >= max_queued:
            raise RuntimeError("analysis_queue_full")
        job = FrameAnalysisJob(
            status=JobStatus.QUEUED.value,
            project_code=project_code,
            zone_code=zone_code,
            camera_code=camera_code,
            image_path=path,
            capture_origin=capture_origin or "",
        )
        session.add(job)
        session.flush()
        job_id = job.id

    get_executor().submit(_run_job, job_id, ts, run_evaluate)
    return job_id


def _run_job(job_id: str, timestamp: datetime, run_evaluate: bool) -> None:
    with get_session() as session:
        job = session.get(FrameAnalysisJob, job_id)
        if job is None:
            return
        job.status = JobStatus.PROCESSING.value
        project_code = job.project_code
        zone_code = job.zone_code
        camera_code = job.camera_code
        image_path = Path(job.image_path)
        capture_origin = job.capture_origin or None

    try:
        with _lock_for_camera(camera_code):
            actual = observe_image(
                image_path=image_path,
                project_code=project_code,
                zone_code=zone_code,
                camera_code=camera_code,
                timestamp=timestamp,
                capture_origin=capture_origin,
                perception_mode=get_settings().perception_mode,
            )
            eval_error = ""
            if run_evaluate:
                try:
                    evaluate_zone_date(
                        project_code=project_code,
                        zone_code=zone_code,
                        on_date=timestamp.date(),
                    )
                except Exception as exc:  # noqa: BLE001
                    eval_error = f"evaluate_skipped:{exc}"
                    logger.warning("evaluate after analyze failed: %s", exc)

        with get_session() as session:
            job = session.get(FrameAnalysisJob, job_id)
            if job is None:
                return
            job.status = JobStatus.COMPLETED.value
            job.pipeline_run_id = actual.pipeline_run_id or ""
            job.observed_state_id = actual.observed_state_id or ""
            job.finished_at = datetime.utcnow()
            job.error = eval_error
    except Exception as exc:  # noqa: BLE001
        logger.exception("frame analysis job %s failed", job_id)
        with get_session() as session:
            job = session.get(FrameAnalysisJob, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED.value
            job.error = str(exc)
            job.finished_at = datetime.utcnow()


def get_job(job_id: str) -> dict | None:
    init_db()
    with get_session() as session:
        job = session.get(FrameAnalysisJob, job_id)
        if job is None:
            return None
        return {
            "job_id": job.id,
            "status": job.status,
            "project_code": job.project_code,
            "zone_code": job.zone_code,
            "camera_code": job.camera_code,
            "image_path": job.image_path,
            "error": job.error or None,
            "observed_state_id": job.observed_state_id or None,
            "actual_state_id": job.actual_state_id or None,
            "pipeline_run_id": job.pipeline_run_id or None,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        }
