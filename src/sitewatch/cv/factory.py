from __future__ import annotations

from pathlib import Path

from sitewatch.cv.annotation_detector import AnnotationDetector
from sitewatch.cv.yolo_detector import YOLODetector
from sitewatch.settings import get_settings


class HybridDetector:
    """YOLO plus annotation overlay. Useful while the construction model is not trained."""

    name = "hybrid"

    def __init__(self, annotation_dir: Path | None = None) -> None:
        self.yolo = YOLODetector()
        self.annotations = AnnotationDetector(annotation_dir)

    def detect(self, image_path: Path):
        labeled = self.annotations.detect(image_path)
        if labeled:
            return labeled
        return self.yolo.detect(image_path)


def build_detector(kind: str | None = None, annotation_dir: Path | None = None):
    name = (kind or get_settings().detector).lower()
    if name == "yolo":
        return YOLODetector()
    if name == "hybrid":
        return HybridDetector(annotation_dir)
    return AnnotationDetector(annotation_dir)
