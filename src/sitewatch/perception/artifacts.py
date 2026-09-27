"""Write debug artifacts for a perception run."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sitewatch.cv.visualize import draw_detections
from sitewatch.domain.contracts import Detection, ObservedState, PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource


def _evidence_to_detections(evidence: list[PerceptionEvidence]) -> list[Detection]:
    out: list[Detection] = []
    for ev in evidence:
        if ev.bbox is None:
            continue
        if ev.source not in {EvidenceSource.SAM3, EvidenceSource.GROUNDING_DINO, EvidenceSource.ANNOTATION}:
            continue
        out.append(
            Detection(
                class_name=ev.normalized_label,
                bbox=ev.bbox,
                confidence=ev.score,
                mask_path=ev.mask_reference,
                model_name=ev.model,
                model_version=ev.model_version,
            )
        )
    return out


def write_run_artifacts(
    *,
    artifact_dir: Path,
    image_path: Path,
    observed: ObservedState,
    sam_evidence: list[PerceptionEvidence] | None = None,
    qwen_structured: dict[str, Any] | None = None,
) -> dict[str, str]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    original = artifact_dir / "original.jpg"
    if image_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}:
        if image_path.resolve() != original.resolve():
            shutil.copy2(image_path, original)
        paths["original"] = str(original)

    det_list = sam_evidence if sam_evidence is not None else [
        e for e in observed.evidence if e.source == EvidenceSource.SAM3
    ]
    detections_json = artifact_dir / "detections.json"
    detections_json.write_text(
        json.dumps([e.model_dump(mode="json") for e in det_list], ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    paths["detections"] = str(detections_json)

    overlay = artifact_dir / "sam_overlay.jpg"
    try:
        draw_detections(image_path, _evidence_to_detections(det_list), overlay)
        paths["sam_overlay"] = str(overlay)
    except Exception:  # noqa: BLE001
        pass

    if qwen_structured is not None:
        qwen_path = artifact_dir / "qwen_result.json"
        qwen_path.write_text(json.dumps(qwen_structured, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        paths["qwen_result"] = str(qwen_path)

    obs_path = artifact_dir / "observed_state.json"
    obs_path.write_text(observed.model_dump_json(indent=2), encoding="utf-8")
    paths["observed_state"] = str(obs_path)

    if observed.pipeline_run is not None:
        run_path = artifact_dir / "pipeline_run.json"
        run_path.write_text(observed.pipeline_run.model_dump_json(indent=2), encoding="utf-8")
        paths["pipeline_run"] = str(run_path)

    return paths
