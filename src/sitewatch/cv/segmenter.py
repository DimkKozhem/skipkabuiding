from __future__ import annotations

from pathlib import Path

from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import BBox, Detection


class YOLOSegDetector:
    """YOLO26m-seg adapter. Use when a box is not enough (area / contour)."""

    name = "yolo26m-seg"

    def __init__(self, weights: Path | None = None) -> None:
        self.weights = Path(weights or "yolo26m-seg.pt")
        self._model = None

    def detect(self, image_path: Path) -> list[Detection]:
        from ultralytics import YOLO

        if self._model is None:
            self._model = YOLO(str(self.weights))
        results = self._model.predict(source=str(image_path), verbose=False)
        detections: list[Detection] = []
        if not results:
            return detections
        result = results[0]
        names = result.names or {}
        if result.boxes is None:
            return detections
        for idx, box in enumerate(result.boxes):
            class_name = canonical_class(str(names.get(int(box.cls[0].item()), "")))
            if class_name is None:
                continue
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            extra = {}
            if result.masks is not None and idx < len(result.masks):
                extra["has_mask"] = True
            detections.append(
                Detection(
                    class_name=class_name,
                    bbox=BBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3]),
                    confidence=float(box.conf[0].item()),
                    model_name=self.name,
                    model_version=self.weights.name,
                    extra=extra,
                )
            )
        return detections
