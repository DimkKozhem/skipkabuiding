"""Shadow candidates: frame boxes → evidence → inspector queue. Not ActualState."""

from __future__ import annotations

import json
import logging
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from pathlib import Path

from sitewatch.cv.shadow_sources import GroundingDinoShadow, Yoloe26lShadow
from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import Detection, DeviationCandidate, EvidenceRef, PerceptionEvidence
from sitewatch.domain.enums import AlertType, EvidenceSource, Severity, StageStatus
from sitewatch.inspector.workflow import persist_candidate
from sitewatch.perception.ontology import prompts_for
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.settings import get_settings, load_yaml, project_root
from sitewatch.storage.db import get_session
from sitewatch.storage.models import ActualStateRecord, EvidenceArtifactRecord

logger = logging.getLogger(__name__)

_SOURCE_ENUM = {
    "grounding_dino": EvidenceSource.GROUNDING_DINO,
    "yoloe_26l": EvidenceSource.YOLOE_26L,
}

_MESSAGE = (
    "Обнаружены признаки объектов на кадре. "
    "Это не подтверждённый факт и не отклонение от графика. Требуется проверка."
)


def load_shadow_config() -> dict:
    return load_yaml("shadow_candidates.yaml")


def shadow_pilot_plan(cfg: dict | None = None) -> dict:
    """Fixed-frame pilot. Reading the plan does not start detectors."""
    cfg = cfg if cfg is not None else load_shadow_config()
    pilot = cfg.get("pilot") or {}
    sources = cfg.get("sources") or {}
    frames = [
        {"zone": item.get("zone"), "name": item.get("name"), "frame": item.get("frame")}
        for item in (pilot.get("objects") or [])
    ]
    models = {}
    for name in ("grounding_dino", "yoloe_26l"):
        source = sources.get(name) or {}
        models[name] = {
            "enabled": bool(source.get("enabled")),
            "version": source.get("revision") or source.get("version"),
            "device": source.get("device"),
        }
    return {
        "will_run": False,
        "pilot_enabled": bool(pilot.get("enabled")),
        "global_enabled": bool(cfg.get("enabled")),
        "workers": int(pilot.get("workers") or 1),
        "max_jobs": int(pilot.get("max_jobs") or 0),
        "results": str(pilot.get("results") or "shadow_only"),
        "frames": frames,
        "models": models,
    }


def shadow_master_enabled(cfg: dict | None = None) -> bool:
    """SITEWATCH_SHADOW_CANDIDATES=0 turns the path off without editing the file."""
    raw = os.environ.get("SITEWATCH_SHADOW_CANDIDATES")
    if raw is not None and raw.strip() != "":
        return raw.strip().lower() in {"1", "true", "on", "yes"}
    cfg = cfg if cfg is not None else load_shadow_config()
    return bool(cfg.get("enabled", False))


def build_source_runners(cfg: dict) -> dict:
    runners = {}
    sources = cfg.get("sources") or {}
    dino = sources.get("grounding_dino") or {}
    yoloe = sources.get("yoloe_26l") or {}
    if dino.get("enabled"):
        runners["grounding_dino"] = GroundingDinoShadow(dino)
    if yoloe.get("enabled"):
        runners["yoloe_26l"] = Yoloe26lShadow(yoloe)
    return runners


def record_shadow_candidates(
    *,
    image_path: Path,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime,
    observation_id: str,
    media_id: str | None,
    actual_state_id: str,
    runners: dict | None = None,
    cfg: dict | None = None,
) -> None:
    """Append candidates or a journal line. Restore ActualState if anything rewrote it."""
    cfg = cfg if cfg is not None else load_shadow_config()
    before: str | None = None
    try:
        if not shadow_master_enabled(cfg):
            return
        before = _actual_payload(actual_state_id)
        active = runners if runners is not None else build_source_runners(cfg)
        if not active:
            _journal(cfg, source="shadow", status="skipped", error="no_enabled_source", image=image_path, zone_id=zone_code)
            return
        collected = _collect(image_path, cfg, active)
        accepted = [item for item in collected if item["detections"]]
        for item in collected:
            _journal(
                cfg,
                source=item["source"],
                status=item["status"],
                error=item.get("error"),
                image=image_path,
                zone_id=zone_code,
                n_boxes=len(item["detections"]),
                model=item.get("model"),
                model_version=item.get("model_version"),
                latency_ms=item.get("latency_ms"),
            )
        if not accepted:
            return
        _enqueue(
            cfg=cfg,
            image_path=image_path,
            project_code=project_code,
            zone_code=zone_code,
            camera_code=camera_code,
            timestamp=timestamp,
            observation_id=observation_id,
            media_id=media_id,
            batches=accepted,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("shadow candidates failed closed")
        _journal(cfg, source="shadow", status="failed", error=f"shadow_failed:{exc}", image=image_path, zone_id=zone_code)
    finally:
        _restore_actual_if_changed(cfg, actual_state_id, before, image_path, zone_code)


def _collect(image_path: Path, cfg: dict, runners: dict) -> list[dict]:
    sources = cfg.get("sources") or {}
    default_max = int(cfg.get("max_boxes") or 20)
    default_timeout = float(cfg.get("timeout_seconds") or 45)
    out: list[dict] = []
    for name, runner in runners.items():
        spec = sources.get(name) or {}
        prompts = _prompts(spec.get("classes") or [])
        timeout = float(spec.get("timeout_seconds") or default_timeout)
        limit = int(spec.get("max_boxes") or default_max)
        result = _call_runner(runner, image_path, prompts, timeout)
        detections = _detections_from_result(result, allowed=set(spec.get("classes") or []), limit=limit)
        status = result.status.value
        if result.status == StageStatus.SUCCESS and not detections:
            status = StageStatus.EMPTY_SUCCESS.value
        out.append(
            {
                "source": name,
                "status": status,
                "error": result.error,
                "model": result.model,
                "model_version": result.model_version,
                "latency_ms": result.latency_ms,
                "detections": detections,
                "truncated": bool((result.extras or {}).get("truncated")),
            }
        )
    return out


def _call_runner(runner, image_path: Path, prompts: list[str], timeout: float) -> ProviderResult:
    def _invoke() -> ProviderResult:
        detected = runner.detect(image_path, prompts)
        if isinstance(detected, ProviderResult):
            return detected
        return ProviderResult(status=StageStatus.FAILED, error="shadow_runner_bad_result")

    if timeout <= 0:
        return _invoke()
    pool = ThreadPoolExecutor(max_workers=1)
    future = pool.submit(_invoke)
    try:
        return future.result(timeout=timeout)
    except FuturesTimeout:
        return ProviderResult(status=StageStatus.FAILED, error="shadow_timeout", extras={"accepted_into_fact": False})
    except Exception as exc:  # noqa: BLE001
        return ProviderResult(status=StageStatus.FAILED, error=f"shadow_failed:{exc}", extras={"accepted_into_fact": False})
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _prompts(classes: list) -> list[str]:
    prompts: list[str] = []
    for name in classes:
        canonical = canonical_class(str(name)) or str(name)
        if canonical == "floor":
            continue
        phrase = prompts_for(canonical)[:1]
        prompts.append(phrase[0] if phrase else canonical.replace("_", " "))
    return prompts


def _detections_from_result(result: ProviderResult, *, allowed: set[str], limit: int) -> list[Detection]:
    raw = (result.extras or {}).get("detections") or []
    found: list[Detection] = []
    for item in raw:
        try:
            det = Detection.model_validate(item)
        except Exception:  # noqa: BLE001
            continue
        raw_label = str((det.extra or {}).get("raw_label") or det.class_name)
        class_name = canonical_class(raw_label) or canonical_class(det.class_name)
        if class_name is None or class_name == "floor" or class_name not in allowed:
            continue
        found.append(det.model_copy(update={"class_name": class_name}))
    if len(found) > limit:
        found = sorted(found, key=lambda item: item.confidence, reverse=True)[:limit]
        result.extras["truncated"] = True
    return found


def _enqueue(
    *,
    cfg: dict,
    image_path: Path,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime,
    observation_id: str,
    media_id: str | None,
    batches: list[dict],
) -> None:
    from sitewatch.storage.models import Project, Zone

    detections: list[Detection] = []
    evidence_rows: list[PerceptionEvidence] = []
    for batch in batches:
        source_name = str(batch["source"])
        source = _SOURCE_ENUM.get(source_name, EvidenceSource.GROUNDING_DINO)
        for det in batch["detections"]:
            detections.append(det)
            evidence_rows.append(
                PerceptionEvidence(
                    evidence_id=uuid.uuid4().hex,
                    source=source,
                    model=str(batch.get("model") or source_name),
                    model_version=str(batch.get("model_version") or "n/a"),
                    class_name=det.class_name,
                    bbox=det.bbox,
                    score=det.confidence,
                    raw_label=det.class_name,
                    normalized_label=det.class_name,
                    metadata={
                        "role": "shadow_candidate",
                        "accepted": False,
                        "accepted_into_fact": False,
                        "source_id": source_name,
                    },
                )
            )
    viz_path = _write_viz(image_path, timestamp, detections)
    note = _note(batches)
    with get_session() as session:
        project = session.query(Project).filter_by(code=project_code).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
        for ev in evidence_rows:
            session.add(
                EvidenceArtifactRecord(
                    observation_id=observation_id,
                    evidence_id=ev.evidence_id,
                    source=ev.source.value,
                    class_name=ev.normalized_label,
                    path=str(viz_path or ""),
                    payload_json=ev.model_dump_json(),
                )
            )
        candidate = DeviationCandidate(
            alert_type=AlertType.MODEL_CANDIDATE,
            severity=Severity.INFO,
            zone_id=zone_code,
            object_id=project_code,
            title="Кандидат модели на кадре",
            message=_MESSAGE,
            rationale=(
                "Теневой источник предложил объекты. "
                "Подтверждение карточки фиксирует решение инспектора и не записывает их в факт."
            ),
            expected={"role": "shadow_candidate"},
            observed={
                "role": "shadow_candidate",
                "promotes_actual_state": False,
                "camera_code": camera_code,
                "detections": [item.model_dump() for item in detections],
            },
            rule_id="shadow.candidate",
            evidence=[
                EvidenceRef(
                    media_path=str(image_path),
                    viz_path=str(viz_path) if viz_path else None,
                    timestamp=timestamp,
                    observation_id=observation_id,
                    media_id=media_id,
                    camera_code=camera_code,
                )
            ],
            related_dates=[timestamp.date().isoformat()],
        )
        # Evidence.note is the per-card caption the inspector reads with the frame.
        persist_candidate(session, project_id=project.id, zone_id=zone.id, candidate=candidate)
        _stamp_evidence_note(session, candidate, note, observation_id)


def _stamp_evidence_note(session, candidate: DeviationCandidate, note: str, observation_id: str) -> None:
    from sitewatch.inspector.workflow import candidate_fingerprint
    from sitewatch.storage.models import Alert, Evidence

    session.flush()
    fingerprint = candidate_fingerprint(candidate)
    alert = session.query(Alert).filter_by(fingerprint=fingerprint).order_by(Alert.created_at.asc()).first()
    if alert is None:
        return
    rows = list(session.query(Evidence).filter_by(alert_id=alert.id, observation_id=observation_id).all())
    if not rows:
        rows = [obj for obj in session.new if isinstance(obj, Evidence) and obj.observation_id == observation_id]
    for row in rows:
        row.note = note


def _note(batches: list[dict]) -> str:
    parts = []
    for batch in batches:
        labels = ", ".join(f"{item.class_name} {item.confidence:.2f}" for item in batch["detections"][:8])
        parts.append(f"{batch['source']}: {labels}")
    text = "; ".join(parts)
    return f"Кандидат, не факт. {text}"[:500]


def _write_viz(image_path: Path, timestamp: datetime, detections: list[Detection]) -> Path | None:
    try:
        from sitewatch.cv.visualize import draw_detections

        settings = get_settings()
        out = (
            settings.data_dir
            / "observations"
            / "viz"
            / f"shadow_{image_path.stem}_{timestamp.strftime('%Y%m%dT%H%M%S')}.jpg"
        )
        draw_detections(image_path, detections, out)
        return out
    except Exception as exc:  # noqa: BLE001
        logger.warning("shadow viz skipped: %s", exc)
        return None


def _actual_payload(actual_state_id: str) -> str | None:
    with get_session() as session:
        row = session.get(ActualStateRecord, actual_state_id)
        return None if row is None else row.payload_json


def _restore_actual_if_changed(cfg: dict, actual_state_id: str, before: str | None, image: Path, zone_id: str) -> None:
    if before is None:
        return
    with get_session() as session:
        row = session.get(ActualStateRecord, actual_state_id)
        if row is None or row.payload_json == before:
            return
        row.payload_json = before
    _journal(
        cfg,
        source="shadow",
        status="failed",
        error="actual_state_restore",
        image=image,
        zone_id=zone_id,
    )


def _journal(
    cfg: dict,
    *,
    source: str,
    status: str,
    error: str | None,
    image: Path,
    zone_id: str,
    n_boxes: int = 0,
    model: str | None = None,
    model_version: str | None = None,
    latency_ms: float | None = None,
) -> None:
    raw = str(cfg.get("journal") or "data/observations/shadow_journal.jsonl")
    path = Path(raw)
    if not path.is_absolute():
        path = project_root() / raw
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        line = {
            "at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "status": status,
            "error": error,
            "image": str(image),
            "zone_id": zone_id,
            "n_boxes": n_boxes,
            "model": model,
            "model_version": model_version,
            "latency_ms": latency_ms,
            "touched_actual_state": False,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001
        logger.exception("shadow journal write failed")

