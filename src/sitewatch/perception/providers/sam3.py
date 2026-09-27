"""SAM3 segmentation provider — real ultralytics SAM3SemanticPredictor path."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

import cv2
import numpy as np

from sitewatch.domain.contracts import BBox, PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource, StageStatus
from sitewatch.perception.ontology import canonical_label, perception_config, prompts_for
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.perception.telemetry import gpu_telemetry, normalize_device, reset_peak_stats
from sitewatch.settings import get_settings


def _resolve_checkpoint() -> Path | None:
    settings = get_settings()
    cfg = perception_config().get("sam3") or {}
    candidates: list[Path] = []
    if settings.sam3_checkpoint:
        candidates.append(Path(settings.sam3_checkpoint))
    raw = str(cfg.get("checkpoint") or "").strip()
    if raw:
        candidates.append(Path(raw))
    candidates.extend(
        [
            settings.models_dir / "sam3.1_multiplex.pt",
            settings.models_dir / "sam3.pt",
            Path.home()
            / ".cache/huggingface/hub/models--facebook--sam3.1/snapshots/daa63191845a41281374e725f4c9e51c7a824460/sam3.1_multiplex.pt",
        ]
    )
    for path in candidates:
        if path.is_file():
            return path
    return None


def evidence_from_boxes(
    *,
    boxes: list[tuple[str, BBox, float, str | None]],
    model: str,
    model_version: str,
    source: EvidenceSource = EvidenceSource.SAM3,
) -> list[PerceptionEvidence]:
    out: list[PerceptionEvidence] = []
    for raw_label, bbox, score, mask_ref in boxes:
        norm = canonical_label(raw_label) or raw_label
        out.append(
            PerceptionEvidence(
                evidence_id=uuid.uuid4().hex,
                source=source,
                model=model,
                model_version=model_version,
                class_name=norm,
                bbox=bbox,
                mask_reference=mask_ref,
                score=float(score),
                raw_label=raw_label,
                normalized_label=norm,
                metadata={"raw_prompt": raw_label},
            )
        )
    return out


class Sam3Provider:
    name = "sam3"

    def __init__(self, *, enabled: bool | None = None) -> None:
        settings = get_settings()
        cfg = perception_config().get("sam3") or {}
        if enabled is None:
            enabled = settings.sam3_enabled if settings.sam3_enabled is not None else bool(cfg.get("enabled", True))
        self.enabled = bool(enabled)
        self.device = settings.sam3_device or str(cfg.get("device") or "cuda:0")
        self.threshold = float(
            settings.sam3_threshold if settings.sam3_threshold is not None else (cfg.get("threshold") or 0.35)
        )
        self.iou_nms = float(cfg.get("iou_nms") or 0.5)
        self.imgsz = int(cfg.get("imgsz") or 720)
        self.prompt_batch_size = max(1, int(cfg.get("prompt_batch_size") or 4))
        self.model = str(cfg.get("model") or "sam3.1")
        self.model_version = str(cfg.get("model_version") or "n/a")
        self.primary_prompt_only = bool(cfg.get("primary_prompt_only", True))
        self._predictor = None
        self._checkpoint: Path | None = None
        self._load_error: str | None = None
        self._image_set: str | None = None

    def _try_load(self) -> str | None:
        if self._predictor is not None:
            return None
        if self._load_error:
            return self._load_error
        checkpoint = _resolve_checkpoint()
        if checkpoint is None:
            self._load_error = "sam3_no_checkpoint"
            return self._load_error
        try:
            from ultralytics.models.sam import SAM3SemanticPredictor
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"sam3_unavailable:{exc}"
            return self._load_error

        device = self.device
        # Ultralytics device: "0" / "cpu" / "cuda:0"
        if device.startswith("cuda:"):
            ul_device = device.split(":", 1)[1]
        elif device in {"cuda", "gpu"}:
            ul_device = "0"
        else:
            ul_device = device

        try:
            overrides = dict(
                conf=self.threshold,
                iou=self.iou_nms,
                task="segment",
                mode="predict",
                model=str(checkpoint),
                imgsz=self.imgsz,
                save=False,
                verbose=False,
                device=ul_device,
            )
            predictor = SAM3SemanticPredictor(overrides=overrides)
            # Force model build
            _ = predictor.model
            self._predictor = predictor
            self._checkpoint = checkpoint
            self.model_version = checkpoint.name
            return None
        except Exception as exc:  # noqa: BLE001
            self._load_error = f"sam3_load_failed:{exc}"
            return self._load_error

    def segment(
        self,
        image_path: Path,
        prompts: list[str],
        *,
        artifact_dir: Path | None = None,
    ) -> ProviderResult:
        started = time.perf_counter()
        if not self.enabled:
            return ProviderResult(
                status=StageStatus.SKIPPED,
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=0.0,
            )

        err = self._try_load()
        if err:
            return ProviderResult(
                status=StageStatus.UNAVAILABLE,
                error=err,
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                extras=gpu_telemetry(self.device),
            )

        assert self._predictor is not None
        reset_peak_stats(self.device)
        text_prompts = list(prompts)
        if not text_prompts:
            return ProviderResult(
                status=StageStatus.SUCCESS,
                evidence=[],
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                extras={"note": "empty_prompts"},
            )

        try:
            boxes_out: list[tuple[str, BBox, float, str | None]] = []
            mask_dir = None
            if artifact_dir is not None:
                mask_dir = Path(artifact_dir) / "masks"
                mask_dir.mkdir(parents=True, exist_ok=True)

            image_key = str(image_path.resolve())
            if self._image_set != image_key:
                self._predictor.set_image(str(image_path))
                self._image_set = image_key

            batch = self.prompt_batch_size
            for offset in range(0, len(text_prompts), batch):
                chunk = text_prompts[offset : offset + batch]
                prompt_to_canonical = [canonical_label(p) or p for p in chunk]
                results = self._predictor(text=chunk)
                self._collect_boxes(
                    results=results or [],
                    text_prompts=chunk,
                    prompt_to_canonical=prompt_to_canonical,
                    boxes_out=boxes_out,
                    mask_dir=mask_dir,
                )
                # Free activation peaks between batches
                try:
                    import torch

                    if torch.cuda.is_available() and self.device.startswith("cuda"):
                        torch.cuda.empty_cache()
                except Exception:  # noqa: BLE001
                    pass

            evidence = evidence_from_boxes(
                boxes=boxes_out,
                model=self.model,
                model_version=self.model_version,
            )
            for ev in evidence:
                ev.metadata["canonical_class"] = ev.normalized_label
                ev.metadata["provider"] = "sam3"

            tele = gpu_telemetry(self.device)
            return ProviderResult(
                status=StageStatus.SUCCESS,
                evidence=evidence,
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                extras={
                    "checkpoint": str(self._checkpoint) if self._checkpoint else None,
                    "n_prompts": len(text_prompts),
                    "prompt_batch_size": batch,
                    "imgsz": self.imgsz,
                    "n_detections": len(evidence),
                    **tele,
                },
            )
        except Exception as exc:  # noqa: BLE001
            err = str(exc)
            if "out of memory" in err.lower():
                err = f"sam3_oom:{err}"
            else:
                err = f"sam3_inference_failed:{err}"
            return ProviderResult(
                status=StageStatus.FAILED,
                error=err,
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                extras=gpu_telemetry(self.device),
            )

    @staticmethod
    def _collect_boxes(
        *,
        results: list,
        text_prompts: list[str],
        prompt_to_canonical: list[str],
        boxes_out: list[tuple[str, BBox, float, str | None]],
        mask_dir: Path | None,
    ) -> None:
        for res in results:
            if res.boxes is None or len(res.boxes) == 0:
                continue
            xyxy = res.boxes.xyxy.cpu().numpy()
            confs = res.boxes.conf.cpu().numpy() if res.boxes.conf is not None else np.ones(len(xyxy))
            clss = res.boxes.cls.cpu().numpy() if res.boxes.cls is not None else np.zeros(len(xyxy))
            masks = None
            if res.masks is not None and getattr(res.masks, "data", None) is not None:
                masks = res.masks.data.cpu().numpy()

            for i, (box, score, cls_i) in enumerate(zip(xyxy, confs, clss)):
                idx = int(cls_i)
                raw_prompt = text_prompts[idx] if 0 <= idx < len(text_prompts) else str(idx)
                canon = prompt_to_canonical[idx] if 0 <= idx < len(prompt_to_canonical) else raw_prompt
                mask_ref = None
                if masks is not None and i < len(masks) and mask_dir is not None:
                    mask_path = mask_dir / f"{canon}_{i}_{uuid.uuid4().hex[:8]}.png"
                    mask_u8 = (masks[i].astype(np.float32) > 0.5).astype(np.uint8) * 255
                    cv2.imwrite(str(mask_path), mask_u8)
                    mask_ref = str(mask_path)
                boxes_out.append(
                    (
                        raw_prompt,
                        BBox(x1=float(box[0]), y1=float(box[1]), x2=float(box[2]), y2=float(box[3])),
                        float(score),
                        mask_ref,
                    )
                )


def build_sam_prompts_from_ontology(*, mvp_only: bool = True) -> list[tuple[str, str]]:
    """Return list of (canonical, prompt_text) for SAM3."""
    from sitewatch.perception.ontology import mvp_class_list

    classes = mvp_class_list() if mvp_only else None
    cfg = perception_config().get("sam3") or {}
    primary_only = bool(cfg.get("primary_prompt_only", True))
    pairs: list[tuple[str, str]] = []
    seen_prompts: set[str] = set()
    for canonical in classes or []:
        prompts = prompts_for(canonical)
        if not prompts:
            prompts = [canonical.replace("_", " ")]
        chosen = prompts[:1] if primary_only else prompts
        for p in chosen:
            if p in seen_prompts:
                continue
            seen_prompts.add(p)
            pairs.append((canonical, p))
    return pairs
