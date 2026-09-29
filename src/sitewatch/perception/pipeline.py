"""Perception orchestration: quality → SAM3 → DINO? → Qwen → fusion → ObservedState."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sitewatch.domain.contracts import ObservedState, PipelineRun, PipelineStageResult
from sitewatch.domain.enums import EntityVisibility, PerceptionMode, StageStatus
from sitewatch.perception.artifacts import write_run_artifacts
from sitewatch.perception.dedup import (
    deduplicate_evidence,
    refine_equipment_evidence,
    refine_structure_evidence,
)
from sitewatch.perception.scene_narrative import describe_visible_work
from sitewatch.perception.work_zone import ZONE_PROMPTS, clip_to_work_zone, polygon_from_evidence
from sitewatch.perception.fusion.service import EvidenceFusionService
from sitewatch.perception.ontology import (
    equipment_keys,
    mvp_prompts,
    ontology_version,
    perception_config,
    prompts_for,
    structure_keys,
)
from sitewatch.perception.providers.annotation import AnnotationProvider
from sitewatch.perception.providers.grounding_dino import GroundingDinoProvider
from sitewatch.perception.providers.qwen_vl import QwenVlProvider
from sitewatch.perception.providers.sam3 import Sam3Provider
from sitewatch.perception.quality.opencv_quality import analyze_image_quality
from sitewatch.settings import get_settings

logger = logging.getLogger(__name__)


def resolve_perception_mode(explicit: str | None = None) -> PerceptionMode:
    settings = get_settings()
    raw = explicit or settings.perception_mode or perception_config().get("mode") or "annotation"
    raw = str(raw).lower().strip()
    if raw == "full":
        raw = "real"
    try:
        return PerceptionMode(raw)
    except ValueError:
        logger.warning("unknown perception mode %r — falling back to annotation", raw)
        return PerceptionMode.ANNOTATION


def is_real_mode(mode: PerceptionMode | None = None) -> bool:
    m = mode or resolve_perception_mode()
    return m in {PerceptionMode.REAL, PerceptionMode.FULL}


class PerceptionPipeline:
    def __init__(
        self,
        *,
        mode: PerceptionMode | None = None,
        sam3: Sam3Provider | None = None,
        dino: GroundingDinoProvider | None = None,
        qwen: QwenVlProvider | None = None,
        annotation: AnnotationProvider | None = None,
        fusion: EvidenceFusionService | None = None,
    ) -> None:
        self.mode = mode or resolve_perception_mode()
        if self.mode == PerceptionMode.FULL:
            self.mode = PerceptionMode.REAL
        self.sam3 = sam3 or Sam3Provider()
        self.dino = dino or GroundingDinoProvider()
        self.qwen = qwen or QwenVlProvider()
        self.annotation = annotation or AnnotationProvider()
        self.fusion = fusion or EvidenceFusionService()
        cfg = perception_config()
        self.pipeline_version = str(cfg.get("pipeline_version") or "1.0.0")
        self.prompt_version = str(cfg.get("prompt_version") or "1.0")

    def run(
        self,
        image_path: Path,
        *,
        object_id: str,
        zone_id: str,
        camera_id: str | None,
        captured_at: datetime,
        frame_id: str | None = None,
        artifact_dir: Path | None = None,
    ) -> ObservedState:
        run_id = uuid.uuid4().hex
        frame_id = frame_id or uuid.uuid4().hex
        started = datetime.utcnow()
        stages: list[PipelineStageResult] = []
        errors: list[str] = []
        self._pending_floors = None  # type: ignore[attr-defined]
        self._candidate_boxes = []  # type: ignore[attr-defined]

        if artifact_dir is None:
            artifact_dir = get_settings().data_dir / "observations" / "artifacts" / run_id
        artifact_dir.mkdir(parents=True, exist_ok=True)

        quality = analyze_image_quality(image_path)
        stages.append(
            PipelineStageResult(
                name="quality",
                status=StageStatus.SUCCESS,
                latency_ms=0.0,
                extras=quality.model_dump(),
            )
        )

        all_evidence = []
        work_zone: list[list[float]] = []
        sam_evidence = []
        vlm_structured: dict[str, Any] | None = None
        scene_from_ann: dict[str, Any] = {}
        skip_heavy = bool((perception_config().get("quality") or {}).get("skip_heavy_if_unusable", True))

        if self.mode == PerceptionMode.ANNOTATION:
            ann_res = self.annotation.segment(image_path, mvp_prompts(), artifact_dir=artifact_dir)
            stages.append(
                PipelineStageResult(
                    name="annotation",
                    status=ann_res.status,
                    latency_ms=ann_res.latency_ms,
                    error=ann_res.error,
                    model=ann_res.model,
                    model_version=ann_res.model_version,
                )
            )
            all_evidence.extend(ann_res.evidence)
            scene_from_ann = dict((ann_res.extras or {}).get("scene") or {})
        else:
            # REAL mode
            if not quality.usable and skip_heavy:
                stages.append(
                    PipelineStageResult(
                        name="sam3",
                        status=StageStatus.SKIPPED,
                        error="skipped_unusable_frame",
                        latency_ms=0.0,
                    )
                )
                stages.append(
                    PipelineStageResult(
                        name="grounding_dino",
                        status=StageStatus.SKIPPED,
                        error="skipped_unusable_frame",
                        latency_ms=0.0,
                    )
                )
                stages.append(
                    PipelineStageResult(
                        name="qwen_vl",
                        status=StageStatus.SKIPPED,
                        error="skipped_unusable_frame",
                        latency_ms=0.0,
                    )
                )
                errors.append("frame_quality_unusable")
            else:
                prompts = mvp_prompts()
                sam_cfg = perception_config().get("sam3") or {}
                sam_enabled = bool(sam_cfg.get("enabled", True)) and bool(getattr(self.sam3, "enabled", True))
                candidate_boxes: list[dict[str, Any]] = []
                if not sam_enabled:
                    stages.append(
                        PipelineStageResult(
                            name="sam3",
                            status=StageStatus.SKIPPED,
                            error="sam3_disabled_for_pipeline",
                            latency_ms=0.0,
                        )
                    )
                else:
                    sam_res = self.sam3.segment(image_path, prompts, artifact_dir=artifact_dir)
                    stages.append(
                        PipelineStageResult(
                            name="sam3",
                            status=sam_res.status,
                            latency_ms=sam_res.latency_ms,
                            error=sam_res.error,
                            model=sam_res.model,
                            model_version=sam_res.model_version,
                            device=sam_res.device,
                            extras=sam_res.extras or {},
                        )
                    )
                    if sam_res.error:
                        errors.append(sam_res.error)
                    sam_evidence = list(sam_res.evidence)
                    all_evidence.extend(sam_evidence)

                verify = list(self.dino.verify_classes or [])
                dino_prompts: list[str] = []
                for cls in verify:
                    dino_prompts.extend(prompts_for(cls)[:1])
                dino_res = self.dino.detect(
                    image_path,
                    dino_prompts or prompts,
                    class_filter=verify,
                    artifact_dir=artifact_dir,
                )
                stages.append(
                    PipelineStageResult(
                        name="grounding_dino",
                        status=dino_res.status,
                        latency_ms=dino_res.latency_ms,
                        error=dino_res.error,
                        model=dino_res.model,
                        model_version=dino_res.model_version,
                        device=dino_res.device,
                        extras={**(dino_res.extras or {}), "accepted_into_fact": False},
                    )
                )
                if dino_res.error and dino_res.status not in {StageStatus.SKIPPED, StageStatus.UNAVAILABLE}:
                    errors.append(dino_res.error)
                # Boxes from this stage are not a fact.
                if dino_res.evidence:
                    logger.info(
                        "grounding_dino returned %s boxes; they stay off ActualState",
                        len(dino_res.evidence),
                    )

                # YOLOE + DINO candidates (main path, still not confirmed fact).
                cand_cfg = perception_config().get("equipment_candidates") or {}
                if bool(cand_cfg.get("enabled")) and bool(cand_cfg.get("accept_into_fact")) is False:
                    candidate_boxes = _run_equipment_candidates(image_path, cand_cfg, stages, errors)

                dedup_cfg = perception_config().get("dedup") or {}
                all_evidence = deduplicate_evidence(
                    all_evidence,
                    iou_threshold=float(dedup_cfg.get("iou_threshold") or 0.5),
                    min_score=float(dedup_cfg.get("min_score") or 0.0),
                )
                frame_w, frame_h = _frame_size(image_path)
                if frame_w and frame_h and sam_enabled:
                    all_evidence = refine_equipment_evidence(
                        all_evidence,
                        frame_width=frame_w,
                        frame_height=frame_h,
                    )
                    all_evidence = refine_structure_evidence(
                        all_evidence,
                        frame_width=frame_w,
                        frame_height=frame_h,
                    )
                    zone_res = self.sam3.segment(image_path, list(ZONE_PROMPTS), artifact_dir=None)
                    work_zone = polygon_from_evidence(
                        zone_res.evidence,
                        frame_width=frame_w,
                        frame_height=frame_h,
                    )
                    if not work_zone:
                        finished = self.sam3.segment(image_path, ["apartment building"], artifact_dir=None)
                        largest = max(
                            finished.evidence,
                            key=lambda item: (item.bbox.x2 - item.bbox.x1) * (item.bbox.y2 - item.bbox.y1)
                            if item.bbox is not None else 0,
                            default=None,
                        )
                        if largest is not None and largest.score >= 0.55:
                            work_zone = polygon_from_evidence(
                                [largest],
                                frame_width=frame_w,
                                frame_height=frame_h,
                            )
                    if work_zone:
                        all_evidence = clip_to_work_zone(
                            all_evidence,
                            work_zone,
                            frame_width=frame_w,
                            frame_height=frame_h,
                        )
                sam_evidence = [e for e in all_evidence if e.source.value == "sam3"]

                qwen_res = self.qwen.interpret(
                    image_path,
                    evidence=all_evidence,
                    quality=quality.model_dump(),
                    ontology_hints={
                        "structures": structure_keys(),
                        "equipment": equipment_keys(),
                        "mvp_classes": list(perception_config().get("mvp_classes") or []),
                    },
                    camera_code=camera_id,
                    captured_at=captured_at,
                    artifact_dir=artifact_dir,
                )
                self._candidate_boxes = candidate_boxes  # type: ignore[attr-defined]
                stages.append(
                    PipelineStageResult(
                        name="qwen_vl",
                        status=qwen_res.status,
                        latency_ms=qwen_res.latency_ms,
                        error=qwen_res.error,
                        model=qwen_res.model,
                        model_version=qwen_res.model_version,
                        extras=qwen_res.extras or {},
                    )
                )
                if qwen_res.error:
                    errors.append(qwen_res.error)
                all_evidence.extend(qwen_res.evidence)
                vlm_structured = (qwen_res.extras or {}).get("vlm_structured")

                # Floors localize: bands+overlay method (not scalar-only Qwen count).
                floors_cfg = perception_config().get("floors_localize") or {}
                if bool(floors_cfg.get("enabled", True)) and qwen_res.status == StageStatus.SUCCESS:
                    from sitewatch.domain.contracts import Detection
                    from sitewatch.perception.floors_localize import (
                        assess_floors_proven,
                        localize_floor_levels,
                    )

                    dets: list[Detection] = []
                    for ev in all_evidence:
                        if ev.bbox is None:
                            continue
                        if ev.metadata.get("outside_work_zone"):
                            continue
                        label = ev.normalized_label or ev.class_name
                        dets.append(
                            Detection(
                                class_name=label,
                                bbox=ev.bbox,
                                confidence=ev.score,
                                mask_path=ev.mask_reference,
                                model_name=ev.model,
                                model_version=ev.model_version,
                            )
                        )
                    floor_dir = artifact_dir / "floors"
                    loc = localize_floor_levels(
                        image_path,
                        detections=dets,
                        out_dir=floor_dir,
                    )
                    proven, prove_reasons = assess_floors_proven(
                        loc,
                        coverage_full=True,
                    )
                    floors_payload = loc.to_dict()
                    floors_payload["floors_status"] = "proven" if proven else "proposed"
                    floors_payload["prove_reasons"] = prove_reasons
                    floors_payload["method"] = "floors_localize"
                    floors_payload["method_version"] = str(floors_cfg.get("method_version") or "1")
                    stages.append(
                        PipelineStageResult(
                            name="floors_localize",
                            status=StageStatus.SUCCESS if not loc.error else StageStatus.FAILED,
                            latency_ms=loc.latency_ms,
                            error=loc.error,
                            extras={
                                "level_count_from_bands": loc.level_count_from_bands,
                                "level_count_proposed": loc.level_count_proposed,
                                "floors_status": floors_payload["floors_status"],
                                "overlay_path": loc.overlay_path,
                                "prove_reasons": prove_reasons,
                            },
                        )
                    )
                    if loc.error:
                        errors.append(loc.error)
                    # Stash for scene merge after fusion.
                    if not hasattr(self, "_pending_floors"):
                        pass
                    self._pending_floors = floors_payload  # type: ignore[attr-defined]
                else:
                    self._pending_floors = None  # type: ignore[attr-defined]

        if self.mode == PerceptionMode.ANNOTATION:
            self._pending_floors = None  # type: ignore[attr-defined]
            detector_status = _component_status(stages, "annotation")
            vlm_component = "not_run"
        else:
            detector_status = _component_status(stages, "sam3")
            vlm_component = _component_status(stages, "qwen_vl")
        structures, equipment, narrative, scene = self.fusion.fuse(
            quality=quality,
            evidence=all_evidence,
            vlm_structured=vlm_structured,
            detector_status=detector_status,
            vlm_status=vlm_component,
        )
        if not narrative.summary.strip():
            counts = {
                label: int(obs.count_visible or 0)
                for label, obs in equipment.items()
            }
            present = {
                label
                for label, obs in structures.items()
                if obs.status in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}
                or int(obs.count_visible or 0) > 0
            }
            narrative.summary = describe_visible_work(equipment=counts, structures_present=present)
        else:
            from sitewatch.temporal.daybook import looks_english

            if looks_english(narrative.summary):
                counts = {
                    label: int(obs.count_visible or 0)
                    for label, obs in equipment.items()
                }
                present = {
                    label
                    for label, obs in structures.items()
                    if obs.status in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}
                    or int(obs.count_visible or 0) > 0
                }
                narrative.summary = describe_visible_work(equipment=counts, structures_present=present)
        if work_zone and narrative.summary and "площадк" not in narrative.summary:
            narrative.summary = narrative.summary.rstrip(".") + ". Соседние дома и дорога в расчёт не входят."
        scene.update(scene_from_ann)
        if work_zone:
            scene["work_zone"] = work_zone
        candidate_boxes = list(getattr(self, "_candidate_boxes", None) or [])
        if candidate_boxes:
            scene["equipment_candidates"] = candidate_boxes
            scene["equipment_candidates_note"] = (
                "Кандидаты локализации техники. Тип автоматически не подтверждён; в факт и отклонения не входят."
            )

        visible_floor_levels = scene.get("visible_floor_levels")
        if visible_floor_levels is None and "floors" in scene_from_ann:
            visible_floor_levels = scene_from_ann.get("floors")
        # Не-строительные сцены (улица/перекрёсток): этажность не применима.
        scene_type = str(scene.get("scene_type") or "").lower()
        if any(tok in scene_type for tok in ("street", "road", "intersection", "square", "plaza", "park")):
            visible_floor_levels = None
            self._pending_floors = None  # type: ignore[attr-defined]

        floors_loc = getattr(self, "_pending_floors", None)
        if isinstance(floors_loc, dict):
            band_n = floors_loc.get("level_count_from_bands")
            if band_n is not None and int(band_n) > 0:
                # Prefer band count over scalar VLM for observation.
                visible_floor_levels = int(band_n)
            scene["floor_bands"] = floors_loc.get("levels") or []
            scene["floor_bands_overlay"] = floors_loc.get("overlay_path")
            scene["floor_bands_crop"] = floors_loc.get("crop_path")
            scene["floor_bands_unambiguous"] = floors_loc.get("unambiguous_count")
            scene["floor_bands_proposed"] = floors_loc.get("level_count_proposed")
            scene["floors_prove_reasons"] = floors_loc.get("prove_reasons") or []
            loc_cfg = perception_config().get("floors_localize") or {}
            scene["floors_method_version"] = str(loc_cfg.get("method_version") or "structural-1")
            if floors_loc.get("floors_status") == "proven":
                scene["floors_status"] = "proven"
                scene["floors_derivation"] = "floor_bands_proven"
            else:
                scene["floors_status"] = "proposed"
                scene["floors_derivation"] = "floor_bands_proposed"
            arts = dict(scene.get("artifact_paths") or {})
            if floors_loc.get("overlay_path"):
                arts["floors_overlay"] = floors_loc["overlay_path"]
            if floors_loc.get("crop_path"):
                arts["floors_crop"] = floors_loc["crop_path"]
            if arts:
                scene["artifact_paths"] = arts

        foundation = structures.get("foundation")
        foundation_visible = scene.get("foundation_visible")
        if foundation_visible is None and foundation is not None:
            foundation_visible = foundation.status in {
                EntityVisibility.VISIBLE,
                EntityVisibility.PARTIALLY_VISIBLE,
            }
        total_floor_count = int(visible_floor_levels) if foundation_visible and visible_floor_levels else None
        # Zero without an explicit confirmed-absence rule is unknown, not a fact.
        if visible_floor_levels is not None:
            try:
                visible_floor_levels = int(visible_floor_levels)
            except (TypeError, ValueError):
                visible_floor_levels = None
        if visible_floor_levels == 0 and "floors" not in scene_from_ann:
            scene["floor_level_candidate"] = {
                "value": 0,
                "origin": "vlm_zero",
                "reason": "ноль без правила подтверждённого отсутствия — неизвестность",
                "confirmed": False,
            }
            visible_floor_levels = None
        if visible_floor_levels is not None:
            scene["visible_floor_levels"] = visible_floor_levels
            if "floors" in scene_from_ann and scene_from_ann.get("floors") is not None:
                scene["floors_status"] = "proven"
                scene.setdefault("floors_derivation", "annotation")
            else:
                scene.setdefault("floors_status", "proposed")
                scene.setdefault("floors_derivation", "visible_floor_levels")
                scene.setdefault(
                    "floor_level_candidate",
                    {
                        "value": int(visible_floor_levels),
                        "origin": "qwen_vl",
                        "reason": "proposed observation",
                        "confirmed": False,
                    },
                )
        else:
            scene.pop("visible_floor_levels", None)
        scene["total_floor_count"] = total_floor_count

        finished = datetime.utcnow()
        total_ms = sum(s.latency_ms or 0.0 for s in stages)
        stages.append(PipelineStageResult(name="fusion", status=StageStatus.SUCCESS, latency_ms=0.0))
        run = PipelineRun(
            run_id=run_id,
            frame_id=frame_id,
            object_id=object_id,
            zone_id=zone_id,
            camera_id=camera_id,
            pipeline_version=self.pipeline_version,
            ontology_version=ontology_version(),
            prompt_version=self.prompt_version,
            started_at=started,
            finished_at=finished,
            total_latency_ms=round(total_ms, 2),
            stages=stages,
            errors=errors,
            device=getattr(self.sam3, "device", None) if is_real_mode(self.mode) else None,
        )

        observed = ObservedState(
            frame_id=frame_id,
            object_id=object_id,
            zone_id=zone_id,
            camera_id=camera_id,
            captured_at=captured_at,
            quality=quality,
            structures=structures,
            equipment=equipment,
            observation=narrative,
            evidence=all_evidence,
            pipeline_run=run,
            scene_attributes=scene,
            visible_floor_levels=int(visible_floor_levels) if visible_floor_levels is not None else None,
            total_floor_count=total_floor_count,
        )

        try:
            paths = write_run_artifacts(
                artifact_dir=artifact_dir,
                image_path=image_path,
                observed=observed,
                sam_evidence=sam_evidence or None,
                qwen_structured=vlm_structured,
            )
            observed.scene_attributes["artifact_paths"] = paths
        except Exception as exc:  # noqa: BLE001
            logger.warning("write_run_artifacts failed: %s", exc)

        return observed


def _run_equipment_candidates(
    image_path: Path,
    cand_cfg: dict[str, Any],
    stages: list[PipelineStageResult],
    errors: list[str],
) -> list[dict[str, Any]]:
    """YOLOE / DINO boxes as candidates only. Never accepted into confirmed fact here."""
    from sitewatch.cv.shadow_sources import GroundingDinoShadow, Yoloe26lShadow

    out: list[dict[str, Any]] = []
    sources = cand_cfg.get("sources") or {}
    for name, spec in sources.items():
        if not isinstance(spec, dict) or not bool(spec.get("enabled")):
            continue
        classes = [str(c) for c in (spec.get("classes") or [])]
        if not classes:
            continue
        try:
            if name == "yoloe_26l":
                worker = Yoloe26lShadow(spec)
            elif name == "grounding_dino":
                worker = GroundingDinoShadow(spec)
            else:
                continue
            result = worker.detect(image_path, classes)
        except Exception as exc:  # noqa: BLE001
            stages.append(
                PipelineStageResult(
                    name=f"candidate_{name}",
                    status=StageStatus.FAILED,
                    error=f"candidate_{name}:{exc}",
                    latency_ms=0.0,
                    extras={"accepted_into_fact": False},
                )
            )
            errors.append(f"candidate_{name}:{exc}")
            continue
        stages.append(
            PipelineStageResult(
                name=f"candidate_{name}",
                status=result.status,
                latency_ms=result.latency_ms,
                error=result.error,
                model=result.model,
                model_version=result.model_version,
                device=result.device,
                extras={**(result.extras or {}), "accepted_into_fact": False},
            )
        )
        if result.error and result.status not in {StageStatus.SKIPPED, StageStatus.UNAVAILABLE, StageStatus.EMPTY_SUCCESS}:
            errors.append(result.error)
        for det in (result.extras or {}).get("detections") or []:
            if not isinstance(det, dict):
                continue
            item = dict(det)
            item["source"] = name
            item["accepted_into_fact"] = False
            item["type_auto_confirmed"] = False
            out.append(item)
    return out


def _component_status(stages: list[PipelineStageResult], name: str) -> str:
    for stage in stages:
        if stage.name != name:
            continue
        if stage.status == StageStatus.SUCCESS:
            return "success"
        if stage.status in {StageStatus.FAILED, StageStatus.UNAVAILABLE}:
            return "failed"
        if stage.status == StageStatus.SKIPPED:
            return "skipped"
    return "not_run"


def _frame_size(image_path: Path) -> tuple[int, int]:
    try:
        import cv2
    except Exception:  # noqa: BLE001
        return 0, 0
    image = cv2.imread(str(image_path))
    if image is None:
        return 0, 0
    height, width = image.shape[:2]
    return int(width), int(height)
