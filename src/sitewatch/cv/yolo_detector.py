from __future__ import annotations

from pathlib import Path

from sitewatch.cv.preprocess import load_bgr
from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import BBox, Detection
from sitewatch.settings import get_settings, load_yaml, project_root


def resolve_yolo_weights(explicit: Path | None = None) -> Path:
    """Weights live in LCT2026/models or SITEWATCH_YOLO_WEIGHTS. Never a neighbour-project path."""
    if explicit is not None:
        return Path(explicit)
    settings = get_settings()
    if settings.yolo_weights:
        return Path(settings.yolo_weights)
    models_dir = project_root() / "models"
    preferred = models_dir / "yolo26m.pt"
    if preferred.is_file():
        return preferred
    matches = sorted(path for path in models_dir.glob("yolo26*.pt") if path.is_file())
    if matches:
        return matches[0]
    return preferred


class YOLODetector:
    """Ultralytics YOLO26m adapter. CV-only: no KSG, no business rules."""

    name = "yolo26m"

    def __init__(self, weights: Path | None = None, device: str | None = None) -> None:
        settings = get_settings()
        self.weights = resolve_yolo_weights(weights)
        self.device = device or settings.yolo_device
        self.min_confidence = float(load_yaml("thresholds.yaml")["detection"]["min_confidence"])
        self._model = None

    def _load(self):
        if not self.weights.exists():
            raise FileNotFoundError(
                f"YOLO weights not found at {self.weights}. "
                "Place weights under models/ or set SITEWATCH_YOLO_WEIGHTS. "
                "Demo uses SITEWATCH_DETECTOR=annotation (sidecar labels), not trained construction YOLO."
            )
        if self._model is None:
            from ultralytics import YOLO

            self._model = YOLO(str(self.weights))
        return self._model

    def detect(self, image_path: Path) -> list[Detection]:
        model = self._load()
        image = load_bgr(image_path)
        results = model.predict(
            source=image,
            conf=self.min_confidence,
            device=self.device,
            verbose=False,
        )
        detections: list[Detection] = []
        if not results:
            return detections
        result = results[0]
        names = result.names or {}
        if result.boxes is None:
            return detections
        for box in result.boxes:
            cls_id = int(box.cls[0].item())
            raw = str(names.get(cls_id, cls_id))
            class_name = canonical_class(raw)
            if class_name is None:
                continue
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            detections.append(
                Detection(
                    class_name=class_name,
                    bbox=BBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3]),
                    confidence=float(box.conf[0].item()),
                    model_name=self.name,
                    model_version=self.weights.name,
                )
            )
        return detections
