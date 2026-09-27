from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import cv2

from sqlalchemy import text

from sitewatch.cv.aggregator import detections_to_actual_state
from sitewatch.cv.annotation_detector import AnnotationDetector, MissingAnnotationSidecarError
from sitewatch.cv.factory import build_detector
from sitewatch.cv.filtering import filter_detections
from sitewatch.cv.video import VideoObserver
from sitewatch.cv.visualize import draw_detections
from sitewatch.domain.contracts import ActualState, Detection, ObservedState
from sitewatch.domain.enums import PerceptionMode
from sitewatch.metrics.collector import MetricsCollector
from sitewatch.perception.pipeline import PerceptionPipeline, resolve_perception_mode
from sitewatch.settings import get_settings
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import (
    ActualStateRecord,
    Camera,
    DetectionRecord,
    EvidenceArtifactRecord,
    MediaAsset,
    Observation,
    ObservedStateRecord,
    PipelineRunRecord,
    Project,
    Zone,
)
from sitewatch.temporal.state_engine import TemporalStateEngine

logger = logging.getLogger(__name__)


def _copy_into(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    return dest


def _store_source_and_annotations(image_path: Path, project_code: str) -> Path:
    """Keep SOURCE separate from AI overlays / prediction JSON."""
    settings = get_settings()
    source_path = _copy_into(image_path, settings.data_dir / "source" / project_code)
    sidecar = image_path.with_suffix(".json")
    if sidecar.exists():
        _copy_into(sidecar, settings.data_dir / "annotations")
        source_sidecar = source_path.with_suffix(".json")
        if sidecar.resolve() != source_sidecar.resolve():
            shutil.copy2(sidecar, source_sidecar)
    return source_path


CAPTURE_ORIGIN_SCHEDULED = "scheduled_capture"
CAPTURE_ORIGIN_MANUAL = "manual_upload"
CAPTURE_ORIGIN_LABELS = {
    CAPTURE_ORIGIN_SCHEDULED: "Камера",
    CAPTURE_ORIGIN_MANUAL: "Инспекция",
}


def capture_origin_label(origin: str | None) -> str | None:
    if not origin:
        return None
    return CAPTURE_ORIGIN_LABELS.get(origin)


def parse_capture_origin(meta_json: str | None) -> str | None:
    if not meta_json:
        return None
    try:
        payload = json.loads(meta_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    origin = payload.get("capture_origin")
    if origin in CAPTURE_ORIGIN_LABELS:
        return str(origin)
    return None


def _media_meta_json(capture_origin: str | None) -> str:
    if capture_origin not in CAPTURE_ORIGIN_LABELS:
        return "{}"
    return json.dumps({"capture_origin": capture_origin}, ensure_ascii=False)


def _load_previous_actual(project_code: str, zone_code: str, camera_code: str | None) -> ActualState | None:
    with get_session() as session:
        project = session.query(Project).filter_by(code=project_code).one_or_none()
        if project is None:
            return None
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none()
        if zone is None:
            return None
        q = (
            session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ActualStateRecord.timestamp.desc(), text("rowid DESC"))
        )
        for row in q.limit(20):
            state = ActualState.model_validate_json(row.payload_json)
            if camera_code and state.camera_code and state.camera_code != camera_code:
                continue
            return state
    return None


def _persist_observation(
    *,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime,
    source_path: Path,
    source_type: str,
    detections: list[Detection],
    actual: ActualState,
    pred_path: Path,
    viz_path: Path,
    detector_name: str,
    capture_origin: str | None = None,
    observed: ObservedState | None = None,
) -> ActualState:
    with get_session() as session:
        project = session.query(Project).filter_by(code=project_code).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
        camera = session.query(Camera).filter_by(code=camera_code).one()
        if camera.orientation:
            actual.scene_attributes.setdefault("orientation", camera.orientation)
            actual.scene_attributes.setdefault("viewpoint", camera.orientation)
        media = MediaAsset(
            camera_id=camera.id,
            path=str(source_path),
            timestamp=timestamp,
            source_type=source_type,
            gps_lat=camera.gps_lat,
            gps_lon=camera.gps_lon,
            meta_json=_media_meta_json(capture_origin),
        )
        session.add(media)
        session.flush()
        observation = Observation(
            project_id=project.id,
            zone_id=zone.id,
            camera_id=camera.id,
            media_id=media.id,
            timestamp=timestamp,
            source=detector_name,
            quality_json=actual.quality.model_dump_json(),
            prediction_path=str(pred_path),
            viz_path=str(viz_path),
        )
        session.add(observation)
        session.flush()
        for det in detections:
            session.add(
                DetectionRecord(
                    observation_id=observation.id,
                    class_name=det.class_name,
                    confidence=det.confidence,
                    x1=det.bbox.x1,
                    y1=det.bbox.y1,
                    x2=det.bbox.x2,
                    y2=det.bbox.y2,
                    track_id=det.track_id,
                    model_name=det.model_name,
                    model_version=det.model_version,
                    mask_path=det.mask_path or "",
                )
            )

        pipeline_run_id = None
        observed_id = None
        if observed is not None and observed.pipeline_run is not None:
            run = observed.pipeline_run
            run_row = PipelineRunRecord(
                id=run.run_id,
                observation_id=observation.id,
                project_id=project.id,
                zone_id=zone.id,
                camera_code=camera_code,
                pipeline_version=run.pipeline_version,
                ontology_version=run.ontology_version,
                prompt_version=run.prompt_version,
                started_at=run.started_at,
                finished_at=run.finished_at,
                total_latency_ms=run.total_latency_ms,
                payload_json=run.model_dump_json(),
                errors_json=json.dumps(run.errors, ensure_ascii=False),
            )
            session.add(run_row)
            pipeline_run_id = run.run_id
            obs_row = ObservedStateRecord(
                observation_id=observation.id,
                project_id=project.id,
                zone_id=zone.id,
                pipeline_run_id=run.run_id,
                timestamp=timestamp,
                payload_json=observed.model_dump_json(),
            )
            session.add(obs_row)
            session.flush()
            observed_id = obs_row.id
            actual.observed_state_id = observed_id
            actual.pipeline_run_id = pipeline_run_id
            for ev in observed.evidence:
                session.add(
                    EvidenceArtifactRecord(
                        observation_id=observation.id,
                        pipeline_run_id=run.run_id,
                        evidence_id=ev.evidence_id,
                        source=ev.source.value,
                        class_name=ev.normalized_label,
                        path=ev.mask_reference or "",
                        payload_json=ev.model_dump_json(),
                    )
                )

        session.add(
            ActualStateRecord(
                observation_id=observation.id,
                project_id=project.id,
                zone_id=zone.id,
                timestamp=timestamp,
                payload_json=actual.model_dump_json(),
            )
        )
    return actual


def _offer_shadow_candidates(
    *,
    image_path: Path,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime,
) -> None:
    """After the fact is stored. A shadow failure leaves that fact in place."""
    try:
        from sitewatch.cv.shadow import record_shadow_candidates

        with get_session() as session:
            project = session.query(Project).filter_by(code=project_code).one()
            zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
            camera = session.query(Camera).filter_by(code=camera_code).one()
            observation = (
                session.query(Observation)
                .filter_by(
                    project_id=project.id,
                    zone_id=zone.id,
                    camera_id=camera.id,
                    timestamp=timestamp,
                )
                .one()
            )
            state = session.query(ActualStateRecord).filter_by(observation_id=observation.id).one()
            observation_id = observation.id
            media_id = observation.media_id
            actual_state_id = state.id
        record_shadow_candidates(
            image_path=image_path,
            project_code=project_code,
            zone_code=zone_code,
            camera_code=camera_code,
            timestamp=timestamp,
            observation_id=observation_id,
            media_id=media_id,
            actual_state_id=actual_state_id,
        )
    except Exception:
        logger.exception("shadow candidates left the stored fact unchanged")


def _write_prediction(source_path: Path, timestamp: datetime, detector_name: str, detections: list[Detection]) -> Path:
    settings = get_settings()
    pred_path = settings.data_dir / "predictions" / f"{source_path.stem}_{timestamp.strftime('%Y%m%dT%H%M%S')}.json"
    pred_path.parent.mkdir(parents=True, exist_ok=True)
    pred_path.write_text(
        json.dumps(
            {
                "source": str(source_path),
                "timestamp": timestamp.isoformat(),
                "detector": detector_name,
                "detections": [item.model_dump() for item in detections],
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return pred_path


def _detections_from_observed(observed: ObservedState) -> list[Detection]:
    out: list[Detection] = []
    for ev in observed.evidence:
        if ev.bbox is None:
            continue
        out.append(
            Detection(
                class_name=ev.normalized_label or ev.raw_label,
                bbox=ev.bbox,
                confidence=ev.score,
                mask_path=ev.mask_reference,
                model_name=ev.model,
                model_version=ev.model_version,
            )
        )
    return out


def observe_image(
    *,
    image_path: Path,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime,
    detector=None,
    scene: dict | None = None,
    capture_origin: str | None = None,
    perception_mode: str | None = None,
) -> ActualState:
    init_db()
    settings = get_settings()
    metrics = MetricsCollector()
    done = metrics.timed("observe_image", path=str(image_path))

    source_path = _store_source_and_annotations(image_path, project_code)
    mode = resolve_perception_mode(perception_mode)

    # Optional forced legacy detector (tests/seed may pass AnnotationDetector)
    if detector is not None and mode == PerceptionMode.ANNOTATION:
        reader = detector if isinstance(detector, AnnotationDetector) else AnnotationDetector()
        try:
            detections = filter_detections(reader.detect(source_path))
            if scene is None:
                scene = reader.scene(source_path) or reader.scene(image_path)
        except MissingAnnotationSidecarError as exc:
            done(error="missing_sidecar")
            raise MissingAnnotationSidecarError(str(exc)) from exc
        scene = scene or {}
        pred_path = _write_prediction(source_path, timestamp, getattr(detector, "name", "annotation"), detections)
        viz_path = (
            settings.data_dir
            / "observations"
            / "viz"
            / f"{source_path.stem}_{timestamp.strftime('%Y%m%dT%H%M%S')}.jpg"
        )
        draw_detections(source_path, detections, viz_path)
        frame_actual = detections_to_actual_state(
            object_id=project_code,
            zone_id=zone_code,
            timestamp=timestamp,
            camera_code=camera_code,
            detections=detections,
            scene=scene,
            n_frames=1,
        )
        pipeline = PerceptionPipeline(mode=PerceptionMode.ANNOTATION)
        observed = pipeline.run(
            source_path,
            object_id=project_code,
            zone_id=zone_code,
            camera_id=camera_code,
            captured_at=timestamp,
        )
        previous = _load_previous_actual(project_code, zone_code, camera_code)
        # Prefer legacy frame counts for demo fidelity; overlay entities from temporal
        temporal = TemporalStateEngine()
        actual = temporal.update(previous, observed)
        # Merge legacy element/equipment counts (seed-demo) while keeping entities
        for key, stat in frame_actual.elements.items():
            actual.elements[key] = stat
        for key, stat in frame_actual.equipment.items():
            actual.equipment[key] = stat
        actual.scene_attributes = {**actual.scene_attributes, **frame_actual.scene_attributes}
        actual.quality = frame_actual.quality
        _persist_observation(
            project_code=project_code,
            zone_code=zone_code,
            camera_code=camera_code,
            timestamp=timestamp,
            source_path=source_path,
            source_type="photo",
            detections=detections,
            actual=actual,
            pred_path=pred_path,
            viz_path=viz_path,
            detector_name=getattr(detector, "name", "annotation"),
            capture_origin=capture_origin,
            observed=observed,
        )
        _offer_shadow_candidates(
            image_path=source_path,
            project_code=project_code,
            zone_code=zone_code,
            camera_code=camera_code,
            timestamp=timestamp,
        )
        done(n_detections=len(detections))
        return actual

    pipeline = PerceptionPipeline(mode=mode)
    observed = pipeline.run(
        source_path,
        object_id=project_code,
        zone_id=zone_code,
        camera_id=camera_code,
        captured_at=timestamp,
    )
    if scene:
        observed.scene_attributes.update(scene)

    detections = _detections_from_observed(observed)
    if mode == PerceptionMode.ANNOTATION:
        from sitewatch.perception.providers.annotation import AnnotationProvider

        ann = AnnotationProvider()
        # Missing sidecar is a hard failure — never persist empty «success».
        if any(
            st.name == "annotation" and st.status.value == "failed"
            for st in (observed.pipeline_run.stages if observed.pipeline_run else [])
        ):
            done(error="missing_sidecar")
            raise MissingAnnotationSidecarError(
                f"annotation mode failed for {source_path.name}: missing or unreadable sidecar"
            )
        try:
            detections = filter_detections(ann.detector.detect(source_path))
            scene_ann = ann.detector.scene(source_path) or {}
            observed.scene_attributes.update(scene_ann)
        except MissingAnnotationSidecarError as exc:
            done(error="missing_sidecar")
            raise

    detector_name = mode.value
    pred_path = _write_prediction(source_path, timestamp, detector_name, detections)
    viz_path = (
        settings.data_dir / "observations" / "viz" / f"{source_path.stem}_{timestamp.strftime('%Y%m%dT%H%M%S')}.jpg"
    )
    if detections:
        draw_detections(source_path, detections, viz_path)
    else:
        # Prefer SAM overlay from perception artifacts when available
        artifact_overlay = (observed.scene_attributes or {}).get("artifact_paths", {}).get("sam_overlay")
        if artifact_overlay and Path(artifact_overlay).is_file():
            import shutil

            shutil.copy2(artifact_overlay, viz_path)
        else:
            # keep original frame as preview rather than empty path
            import shutil

            try:
                shutil.copy2(source_path, viz_path)
            except Exception:
                viz_path = Path("")

    previous = _load_previous_actual(project_code, zone_code, camera_code)
    actual = TemporalStateEngine().update(previous, observed)

    # Annotation mode: align with classic aggregator counts for demo/tests
    if mode == PerceptionMode.ANNOTATION and detections:
        frame_actual = detections_to_actual_state(
            object_id=project_code,
            zone_id=zone_code,
            timestamp=timestamp,
            camera_code=camera_code,
            detections=detections,
            scene=observed.scene_attributes,
            n_frames=1,
        )
        for key, stat in frame_actual.elements.items():
            actual.elements[key] = stat
        for key, stat in frame_actual.equipment.items():
            actual.equipment[key] = stat
        actual.scene_attributes = {**actual.scene_attributes, **frame_actual.scene_attributes}
        actual.quality = frame_actual.quality

    _persist_observation(
        project_code=project_code,
        zone_code=zone_code,
        camera_code=camera_code,
        timestamp=timestamp,
        source_path=source_path,
        source_type="photo",
        detections=detections,
        actual=actual,
        pred_path=pred_path,
        viz_path=viz_path,
        detector_name=detector_name,
        capture_origin=capture_origin,
        observed=observed,
    )
    _offer_shadow_candidates(
        image_path=source_path,
        project_code=project_code,
        zone_code=zone_code,
        camera_code=camera_code,
        timestamp=timestamp,
    )
    done(n_detections=len(detections))
    return actual


def observe_video(
    *,
    video_path: Path,
    project_code: str,
    zone_code: str,
    camera_code: str,
    timestamp: datetime,
    detector=None,
    scene: dict | None = None,
    capture_origin: str | None = None,
) -> ActualState:
    """Sample 1–3 FPS → detections → one Observation Window. Not 30 FPS YOLO."""
    init_db()
    settings = get_settings()
    detector = detector or build_detector()
    metrics = MetricsCollector()
    done = metrics.timed("observe_video", path=str(video_path))

    source_path = _store_source_and_annotations(video_path, project_code)
    observer = VideoObserver(detector)
    detections, counts, n_sampled = observer.observe(source_path)
    detections = filter_detections(detections)

    capture = cv2.VideoCapture(str(source_path))
    src_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    ok, frame = capture.read()
    capture.release()
    frame_path = settings.data_dir / "source" / project_code / f"{source_path.stem}_frame.jpg"
    if ok:
        cv2.imwrite(str(frame_path), frame)
        viz_source = frame_path
    else:
        viz_source = source_path

    pred_path = _write_prediction(source_path, timestamp, getattr(detector, "name", "video"), detections)
    viz_path = settings.data_dir / "observations" / "viz" / f"{source_path.stem}_{timestamp.strftime('%Y%m%dT%H%M%S')}.jpg"
    if viz_source.suffix.lower() in {".jpg", ".jpeg", ".png"}:
        draw_detections(viz_source, detections, viz_path)
    else:
        viz_path = Path("")

    window_end = timestamp + timedelta(seconds=max(n_sampled / max(observer.sample_fps, 0.1), 1.0))
    scene = dict(scene or {})
    scene.setdefault("visibility", "good")
    scene.setdefault("coverage", "full")
    actual = detections_to_actual_state(
        object_id=project_code,
        zone_id=zone_code,
        timestamp=timestamp,
        camera_code=camera_code,
        detections=detections,
        scene=scene,
        n_frames=max(n_sampled, 1),
        class_counts=counts,
    )
    actual.quality.window_start = timestamp
    actual.quality.window_end = window_end
    actual.scene_attributes["video"] = {
        "source_fps": src_fps,
        "sample_fps": observer.sample_fps,
        "sampled_frames": n_sampled,
        "window_counts": counts,
    }
    _persist_observation(
        project_code=project_code,
        zone_code=zone_code,
        camera_code=camera_code,
        timestamp=timestamp,
        source_path=source_path,
        source_type="video",
        detections=detections,
        actual=actual,
        pred_path=pred_path,
        viz_path=viz_path,
        detector_name=getattr(detector, "name", "video"),
        capture_origin=capture_origin,
    )
    done(n_detections=len(detections), sampled_frames=n_sampled, source_fps=src_fps, sample_fps=observer.sample_fps)
    return actual
