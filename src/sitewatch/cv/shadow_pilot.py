"""One-worker shadow pilot. Manifest frames only. Does not write ActualState."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from sitewatch.cv.shadow import (
    _call_runner,
    _detections_from_result,
    _prompts,
    load_shadow_config,
    pilot_closed,
    store_pilot_batches,
)
from sitewatch.cv.shadow_sources import GroundingDinoShadow, Yoloe26lShadow
from sitewatch.domain.enums import StageStatus
from sitewatch.settings import project_root
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import ActualStateRecord, Camera, MediaAsset, Observation, Project, Zone

PROCESSING_VERSION = "shadow-equipment-v1"
SOURCE_ORDER = ("yoloe_26l", "grounding_dino")
_TERMINAL = {"success", "empty_success", "failed"}
_TRANSIENT = ("timeout", "out of memory", "oom", "cuda error", "connection reset", "temporarily", "loading weights")


def assert_batch_not_truncated(
    *,
    frames: int,
    sources: int,
    max_jobs: int,
    max_jobs_means: str,
    expected_runs: int,
) -> int:
    """max_jobs counts model executions. A short limit refuses the batch instead of dropping runs."""
    if max_jobs_means != "model_executions":
        raise RuntimeError("max_jobs считает модельные выполнения (кадр × источник), не кадры")
    planned = frames * sources
    if expected_runs != planned:
        raise RuntimeError(f"expected_runs={expected_runs} не равно {frames}×{sources}={planned}")
    if max_jobs < planned:
        raise RuntimeError(
            f"max_jobs={max_jobs} отрежет {planned - max_jobs} из {planned} выполнений; партия не запускается"
        )
    return planned


def run_pilot(*, manifest_path: str | None = None) -> dict:
    cfg = load_shadow_config()
    pilot = cfg.get("pilot") or {}
    if not pilot.get("allowlist_only"):
        raise RuntimeError("pilot allowlist is required before any shadow run")
    _flip_pilot_enabled(True)
    cfg = load_shadow_config()
    try:
        return _run_enabled(cfg, manifest_path)
    finally:
        _flip_pilot_enabled(False)


def _run_enabled(cfg: dict, manifest_path: str | None) -> dict:
    cfg = {**cfg, "pilot": dict(cfg.get("pilot") or {})}
    if manifest_path:
        cfg["pilot"]["manifest"] = manifest_path
        cfg["pilot"]["jobs"] = "data/observations/shadow_pilot_batch1_jobs.json"
        cfg["pilot"]["state"] = "data/observations/shadow_pilot_batch1_state.json"
    manifest = _read_manifest(cfg, manifest_path)
    if manifest_path:
        cfg["pilot"]["id"] = manifest.get("pilot_id")
        cfg["pilot"]["enabled"] = True
        cfg["pilot"]["allowlist_only"] = True
        cfg["pilot"]["max_jobs"] = int(manifest.get("max_jobs") or 0)
        cfg["pilot"]["max_jobs_means"] = str(manifest.get("max_jobs_means") or "model_executions")
        cfg["pilot"]["expected_runs"] = int(manifest.get("expected_runs") or 0)
        cfg["pilot"]["workers"] = int(manifest.get("workers") or 1)
    pilot = cfg["pilot"]
    if not pilot.get("enabled"):
        raise RuntimeError("pilot.enabled did not turn on for this run")
    if manifest.get("pilot_id") != pilot.get("id"):
        raise RuntimeError("manifest pilot_id does not match shadow config")
    frames = list(manifest.get("frames") or [])
    planned = assert_batch_not_truncated(
        frames=len(frames),
        sources=len(SOURCE_ORDER),
        max_jobs=int(pilot.get("max_jobs") or 0),
        max_jobs_means=str(pilot.get("max_jobs_means") or ""),
        expected_runs=int(pilot.get("expected_runs") or 0),
    )
    if len(frames) > int(manifest.get("max_frames") or len(frames)):
        raise RuntimeError("manifest exceeds the frame cap")
    if planned != int(manifest.get("expected_runs") or planned):
        raise RuntimeError("manifest expected_runs does not match the pilot")
    listed = list(manifest.get("sources") or [])
    if listed != list(SOURCE_ORDER):
        raise RuntimeError("manifest sources must be yoloe_26l then grounding_dino, both of them")
    for frame in frames:
        _verify_frame(frame)
    pending_retry = any(_needs_retry(job) for job in _load_jobs(cfg).values())
    if pilot_closed(cfg) and _all_terminal(cfg, frames) and not pending_retry:
        return {"status": "closed", "jobs": _load_jobs(cfg), "inference": False}

    _write_state(cfg, accepting=True)
    report_jobs: list[dict] = []
    stopped_for_gpu = False
    for frame in frames:
        if stopped_for_gpu:
            break
        batches = []
        for source in SOURCE_ORDER:
            key = f"{frame['observation_id']}|{source}"
            existing = _load_jobs(cfg).get(key) or {}
            if existing.get("status") in _TERMINAL and not _needs_retry(existing):
                report_jobs.append({"key": key, **{k: v for k, v in existing.items() if k != "batch"}, "skipped": True})
                if existing.get("batch"):
                    batches.append(_batch_from_record(existing["batch"]))
                continue
            device = str((cfg.get("sources") or {}).get(source, {}).get("device") or cfg.get("device") or "cuda:1")
            block = _wait_for_gpu(device)
            if block:
                _save_job(cfg, key, {"status": "queued_gpu_busy", "error": block, "attempts": int(existing.get("attempts") or 0)})
                report_jobs.append({"key": key, "status": "queued_gpu_busy", "error": block})
                stopped_for_gpu = True
                break
            outcome = _run_source(cfg, frame, source, previous=existing)
            report_jobs.append({"key": key, **{k: v for k, v in outcome.items() if k != "batch"}})
            if outcome.get("batch"):
                batches.append(outcome["batch"])
            if outcome["status"] == "queued_gpu_busy":
                stopped_for_gpu = True
                break
        if batches and not stopped_for_gpu:
            _commit_frame(cfg, frame, batches)

    if stopped_for_gpu:
        jobs_now = _load_jobs(cfg)
        for frame in frames:
            for source in SOURCE_ORDER:
                key = f"{frame['observation_id']}|{source}"
                status = (jobs_now.get(key) or {}).get("status")
                if status not in _TERMINAL | {"queued_gpu_busy", "retrying"}:
                    _save_job(
                        cfg,
                        key,
                        {"status": "queued_gpu_busy", "error": "queued_behind_busy_gpu", "attempts": 0},
                    )
    jobs = _load_jobs(cfg)
    terminal = _all_terminal(cfg, frames)
    if terminal and not stopped_for_gpu:
        _write_state(cfg, accepting=False)
    return {
        "status": "closed" if terminal and not stopped_for_gpu else "incomplete",
        "inference": True,
        "pilot_id": pilot.get("id"),
        "frames": len(frames),
        "jobs": jobs,
        "report": report_jobs,
    }


def _run_source(cfg: dict, frame: dict, source: str, *, previous: dict) -> dict:
    spec = dict((cfg.get("sources") or {}).get(source) or {})
    if source == "grounding_dino":
        if not spec.get("interpreter"):
            spec["interpreter"] = "/home/dimk/my_project/myenv/bin/python"
        spec["timeout_seconds"] = max(float(spec.get("timeout_seconds") or 0), 600)
    else:
        spec["timeout_seconds"] = max(float(spec.get("timeout_seconds") or 0), 180)
    runner = Yoloe26lShadow(spec) if source == "yoloe_26l" else GroundingDinoShadow(spec)
    prompts = _prompts(spec.get("classes") or [])
    timeout = float(spec.get("timeout_seconds") or cfg.get("timeout_seconds") or 45)
    limit = int(spec.get("max_boxes") or cfg.get("max_boxes") or 20)
    attempts = int(previous.get("attempts") or 0)
    last: dict | None = None
    while attempts < 2:
        attempts += 1
        before = _gpu_memory(spec.get("device") or "cuda:1")
        result = _call_runner(runner, Path(frame["image"]), prompts, timeout)
        after = _gpu_memory(spec.get("device") or "cuda:1")
        detections = _detections_from_result(result, allowed=set(spec.get("classes") or []), limit=limit)
        status = result.status.value
        if result.status == StageStatus.SUCCESS and not detections:
            status = StageStatus.EMPTY_SUCCESS.value
        batch = {
            "source": source,
            "status": status,
            "error": result.error,
            "model": result.model,
            "model_version": result.model_version,
            "latency_ms": result.latency_ms,
            "detections": detections,
            "prompt_version": hashlib.sha256("\n".join(prompts).encode()).hexdigest()[:16],
            "processing_version": PROCESSING_VERSION,
            "checkpoint": spec.get("sha256") or spec.get("revision") or "",
            "parameters": {
                "device": spec.get("device"),
                "conf": spec.get("conf"),
                "imgsz": spec.get("imgsz"),
                "box_threshold": spec.get("box_threshold"),
                "text_threshold": spec.get("text_threshold"),
                "text_model": spec.get("text_model"),
            },
        }
        raw_path = _write_raw(cfg, frame, source, result, batch)
        batch["raw_path"] = str(raw_path)
        record = {
            "status": status if status in _TERMINAL or status == StageStatus.FAILED.value else status,
            "error": result.error,
            "attempts": attempts,
            "latency_ms": result.latency_ms,
            "memory_before_mib": before,
            "memory_after_mib": after,
            "retry_reason": previous.get("retry_reason"),
            "batch": _dump_batch(batch),
        }
        if status == StageStatus.FAILED.value and _is_transient(result.error) and attempts < 2:
            record["status"] = "retrying"
            record["retry_reason"] = result.error or "transient"
            _save_job(cfg, f"{frame['observation_id']}|{source}", record)
            previous = record
            last = {"status": "retrying", "error": result.error, "attempts": attempts, "batch": None}
            continue
        if status == StageStatus.FAILED.value:
            record["status"] = "failed"
        elif status == StageStatus.EMPTY_SUCCESS.value:
            record["status"] = "empty_success"
        elif status == StageStatus.SUCCESS.value:
            record["status"] = "success"
        else:
            record["status"] = "failed"
            record["error"] = record["error"] or status
        _save_job(cfg, f"{frame['observation_id']}|{source}", record)
        return {"status": record["status"], "error": record["error"], "attempts": attempts, "latency_ms": result.latency_ms, "batch": batch if record["status"] in {"success", "empty_success"} else None}
    return last or {"status": "failed", "error": "retry_exhausted", "batch": None}


def _commit_frame(cfg: dict, frame: dict, batches: list[dict]) -> None:
    init_db()
    with get_session() as session:
        project = session.query(Project).filter_by(code=frame["project"]).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=frame["zone"]).one()
        camera = session.query(Camera).filter_by(code=frame["camera"]).one()
        observation = session.get(Observation, frame["observation_id"])
        if observation is None:
            raise RuntimeError(f"observation missing: {frame['observation_id']}")
        state = session.query(ActualStateRecord).filter_by(observation_id=observation.id).one()
        image = Path(frame["image"])
        observation_id = observation.id
        media_id = observation.media_id
        actual_state_id = state.id
        timestamp = observation.timestamp
        project_code = project.code
        zone_code = zone.code
        camera_code = camera.code
    store_pilot_batches(
        image_path=image,
        project_code=project_code,
        zone_code=zone_code,
        camera_code=camera_code,
        timestamp=timestamp,
        observation_id=observation_id,
        media_id=media_id,
        actual_state_id=actual_state_id,
        batches=batches,
        cfg=cfg,
    )


def _dump_batch(batch: dict) -> dict:
    dumped = dict(batch)
    dumped["detections"] = [item.model_dump() for item in batch.get("detections") or []]
    return dumped


def _batch_from_record(raw: dict) -> dict:
    from sitewatch.domain.contracts import Detection

    batch = dict(raw)
    batch["detections"] = [Detection.model_validate(item) for item in raw.get("detections") or []]
    return batch


def _needs_retry(job: dict) -> bool:
    if job.get("status") != "failed" or int(job.get("attempts") or 0) >= 2:
        return False
    text = job.get("error") or ""
    if "box_threshold" in text:
        return True
    return _is_transient(text)


def _is_transient(error: str | None) -> bool:
    text = (error or "").lower()
    if "pin" in text or "weights_missing" in text or "ultralytics" in text:
        return False
    return any(token in text for token in _TRANSIENT)


def _wait_for_gpu(device: str, *, attempts: int = 1, pause_seconds: float = 0) -> str | None:
    """One look at free memory. A busy device stays queued. Other processes keep running."""
    del attempts, pause_seconds
    return _gpu_block_reason(device)


def _gpu_util(device: str) -> int | None:
    index = str(device).split(":")[-1]
    if not index.isdigit():
        return None
    try:
        proc = subprocess.run(
            ["nvidia-smi", f"--id={index}", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(proc.stdout.strip().splitlines()[0])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def _gpu_block_reason(device: str) -> str | None:
    index = device.split(":")[-1] if ":" in device else "0"
    if not index.isdigit():
        return f"queued_gpu_unknown:{device}"
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                f"--id={index}",
                "--query-gpu=memory.free",
                "--format=csv,noheader,nounits",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"queued_gpu_unknown:{exc}"
    if proc.returncode != 0:
        return f"queued_gpu_unknown:{proc.stderr.strip() or proc.returncode}"
    try:
        free = int(proc.stdout.strip().splitlines()[0])
    except (ValueError, IndexError):
        return "queued_gpu_unknown:unparsed"
    if free < 4096:
        return f"queued_gpu_busy:free_mib={free}"
    return None


def _gpu_memory(device: str) -> int | None:
    index = str(device).split(":")[-1]
    if not index.isdigit():
        return None
    try:
        proc = subprocess.run(
            ["nvidia-smi", f"--id={index}", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return int(proc.stdout.strip().splitlines()[0])
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        return None


def _flip_pilot_enabled(value: bool) -> None:
    path = project_root() / "config" / "shadow_candidates.yaml"
    text = path.read_text(encoding="utf-8")
    marker = "\npilot:\n"
    idx = text.find(marker)
    if idx < 0:
        raise RuntimeError("pilot block missing")
    head, tail = text[: idx + len(marker)], text[idx + len(marker) :]
    new_tail, count = re.subn(
        r"^  enabled: (?:true|false)\s*$",
        f"  enabled: {'true' if value else 'false'}",
        tail,
        count=1,
        flags=re.M,
    )
    if count != 1:
        raise RuntimeError("pilot.enabled line missing")
    path.write_text(head + new_tail, encoding="utf-8")


def _sealed_days() -> set[str]:
    path = project_root() / "validation" / "equipment_v1" / "domain_split.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return set(raw.get("holdout_days") or []) | set(raw.get("control_benchmark_days_excluded") or [])


def _verify_frame(frame: dict) -> None:
    image = Path(frame["image"])
    if not image.is_file():
        raise RuntimeError(f"frame missing: {image}")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    if digest != str(frame.get("sha256") or ""):
        raise RuntimeError(f"frame hash does not match the manifest for {frame.get('frame_id')}")
    canonical = project_root() / str(frame.get("canonical_image") or "")
    if not canonical.is_file():
        raise RuntimeError(f"camera frame missing: {canonical}")
    if hashlib.sha256(canonical.read_bytes()).hexdigest() != digest:
        raise RuntimeError(f"stored file is not the camera frame for {frame.get('frame_id')}")
    if frame.get("holdout") or str(frame.get("day") or "") in _sealed_days():
        raise RuntimeError(f"refusing sealed day {frame.get('day')}")
    init_db()
    with get_session() as session:
        observation = session.get(Observation, frame["observation_id"])
        if observation is None:
            raise RuntimeError(f"observation missing: {frame['observation_id']}")
        zone = session.get(Zone, observation.zone_id)
        camera = session.get(Camera, observation.camera_id)
        project = session.get(Project, observation.project_id)
        media = session.get(MediaAsset, observation.media_id)
        if zone is None or camera is None or project is None or media is None:
            raise RuntimeError(f"observation link is incomplete for {frame.get('frame_id')}")
        if project.code != frame["project"] or zone.code != frame["zone"] or camera.code != frame["camera"]:
            raise RuntimeError(f"observation belongs to {zone.code}/{camera.code}, not {frame['zone']}/{frame['camera']}")
        if Path(media.path).resolve() != image.resolve():
            raise RuntimeError(f"observation media is {media.path}, not {image}")


def _read_manifest(cfg: dict, override: str | None) -> dict:
    import yaml

    raw = override or str((cfg.get("pilot") or {}).get("manifest") or "")
    path = Path(raw)
    if not path.is_absolute():
        path = project_root() / raw
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _jobs_path(cfg: dict) -> Path:
    raw = str((cfg.get("pilot") or {}).get("jobs") or "data/observations/shadow_pilot_jobs.json")
    path = Path(raw)
    return path if path.is_absolute() else project_root() / raw


def _state_path(cfg: dict) -> Path:
    raw = str((cfg.get("pilot") or {}).get("state") or "data/observations/shadow_pilot_state.json")
    path = Path(raw)
    return path if path.is_absolute() else project_root() / raw


def _load_jobs(cfg: dict) -> dict:
    path = _jobs_path(cfg)
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("jobs") or {}
    except json.JSONDecodeError:
        return {}


def _save_job(cfg: dict, key: str, record: dict) -> None:
    path = _jobs_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {}
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    jobs = payload.get("jobs") or {}
    jobs[key] = record
    payload["jobs"] = jobs
    payload["pilot_id"] = (cfg.get("pilot") or {}).get("id")
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_state(cfg: dict, *, accepting: bool) -> None:
    path = _state_path(cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pilot_id": (cfg.get("pilot") or {}).get("id"),
                "accepting": accepting,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _all_terminal(cfg: dict, frames: list[dict]) -> bool:
    jobs = _load_jobs(cfg)
    expected = [f"{frame['observation_id']}|{source}" for frame in frames for source in SOURCE_ORDER]
    pilot = cfg.get("pilot") or {}
    if len(expected) > int(pilot.get("max_jobs") or 0):
        return False
    return all((jobs.get(key) or {}).get("status") in _TERMINAL for key in expected)


def _write_raw(cfg: dict, frame: dict, source: str, result, batch: dict) -> Path:
    root = project_root() / "data" / "observations" / "shadow_pilot_raw" / str((cfg.get("pilot") or {}).get("id") or "pilot")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{frame['observation_id']}_{source}.json"
    payload = {
        "frame_id": frame.get("frame_id"),
        "observation_id": frame["observation_id"],
        "source": source,
        "status": result.status.value,
        "error": result.error,
        "model": result.model,
        "model_version": result.model_version,
        "latency_ms": result.latency_ms,
        "prompt_version": batch.get("prompt_version"),
        "processing_version": PROCESSING_VERSION,
        "checkpoint": batch.get("checkpoint"),
        "parameters": batch.get("parameters"),
        "extras": result.extras,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
    return path
