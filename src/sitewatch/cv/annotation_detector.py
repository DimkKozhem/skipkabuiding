from __future__ import annotations

import json
from pathlib import Path

from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import BBox, Detection


class MissingAnnotationSidecarError(FileNotFoundError):
    """Annotation mode requires a sidecar JSON next to the image (or in annotation_dir)."""


class AnnotationDetector:
    """Reads a sidecar JSON next to the image. Same Detection contract as YOLO."""

    name = "annotation"

    def __init__(self, annotation_dir: Path | None = None, *, require_sidecar: bool = True) -> None:
        self.annotation_dir = annotation_dir
        self.require_sidecar = require_sidecar

    def detect(self, image_path: Path) -> list[Detection]:
        sidecar = self._require_sidecar(image_path)
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        detections: list[Detection] = []
        for item in payload.get("detections", []):
            raw = str(item.get("class_name") or item.get("class") or "")
            class_name = canonical_class(raw)
            if class_name is None:
                continue
            box = item.get("bbox") or item.get("xyxy") or []
            if len(box) != 4:
                continue
            detections.append(
                Detection(
                    class_name=class_name,
                    bbox=BBox(x1=float(box[0]), y1=float(box[1]), x2=float(box[2]), y2=float(box[3])),
                    confidence=float(item.get("confidence", 1.0)),
                    track_id=item.get("track_id"),
                    model_name=self.name,
                    model_version=str(payload.get("model_version", "demo-labels")),
                )
            )
        return detections

    def scene(self, image_path: Path) -> dict:
        sidecar = self._require_sidecar(image_path)
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        return dict(payload.get("scene") or {})

    def has_sidecar(self, image_path: Path) -> bool:
        path = self._sidecar_path(image_path)
        return path is not None and path.exists()

    def _require_sidecar(self, image_path: Path) -> Path:
        path = self._sidecar_path(image_path)
        if path is not None and path.exists():
            return path
        if self.require_sidecar:
            expected = image_path.with_suffix(".json")
            raise MissingAnnotationSidecarError(
                f"annotation mode: missing sidecar for {image_path.name} "
                f"(expected {expected.name} or annotation_dir entry). "
                "Empty detections require an explicit sidecar with detections:[]."
            )
        raise MissingAnnotationSidecarError(f"missing sidecar for {image_path}")

    def _sidecar_path(self, image_path: Path) -> Path | None:
        candidates = [image_path.with_suffix(".json")]
        if self.annotation_dir is not None:
            candidates.append(self.annotation_dir / f"{image_path.stem}.json")
        for path in candidates:
            if path.exists():
                return path
        return candidates[0] if candidates else None
