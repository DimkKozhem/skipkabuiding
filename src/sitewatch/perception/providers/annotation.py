"""Annotation sidecar provider — demo / seed path without GPU models."""

from __future__ import annotations

import time
import uuid
from pathlib import Path

from sitewatch.cv.annotation_detector import AnnotationDetector, MissingAnnotationSidecarError
from sitewatch.cv.filtering import filter_detections
from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource, StageStatus
from sitewatch.perception.ontology import canonical_label
from sitewatch.perception.providers.protocols import ProviderResult


class AnnotationProvider:
    name = "annotation"

    def __init__(self) -> None:
        self.detector = AnnotationDetector(require_sidecar=True)

    def segment(
        self,
        image_path: Path,
        prompts: list[str],
        *,
        artifact_dir: Path | None = None,
    ) -> ProviderResult:
        return self._run(image_path)

    def detect(
        self,
        image_path: Path,
        prompts: list[str],
        *,
        class_filter: list[str] | None = None,
        artifact_dir: Path | None = None,
    ) -> ProviderResult:
        return self._run(image_path)

    def _run(self, image_path: Path) -> ProviderResult:
        started = time.perf_counter()
        try:
            detections = filter_detections(self.detector.detect(image_path))
            scene = self.detector.scene(image_path) or {}
        except MissingAnnotationSidecarError as exc:
            return ProviderResult(
                status=StageStatus.FAILED,
                evidence=[],
                model="annotation",
                model_version="sidecar",
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
                error=str(exc),
                extras={"missing_sidecar": True},
            )
        evidence: list[PerceptionEvidence] = []
        for det in detections:
            norm = canonical_label(det.class_name) or canonical_class(det.class_name) or det.class_name
            evidence.append(
                PerceptionEvidence(
                    evidence_id=uuid.uuid4().hex,
                    source=EvidenceSource.ANNOTATION,
                    model=det.model_name,
                    model_version=det.model_version,
                    class_name=norm,
                    bbox=det.bbox,
                    score=det.confidence,
                    raw_label=det.class_name,
                    normalized_label=norm,
                    metadata={"track_id": det.track_id},
                )
            )
        return ProviderResult(
            status=StageStatus.SUCCESS,
            evidence=evidence,
            model="annotation",
            model_version="sidecar",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            extras={"scene": scene, "detections": detections},
        )
