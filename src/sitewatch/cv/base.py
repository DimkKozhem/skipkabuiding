from __future__ import annotations

from pathlib import Path
from typing import Protocol

from sitewatch.domain.contracts import Detection


class Detector(Protocol):
    name: str

    def detect(self, image_path: Path) -> list[Detection]:
        """Return detections. Must not consult KSG or business rules."""


class SceneEstimator(Protocol):
    def estimate(self, image_path: Path) -> dict:
        """Optional scene-level attributes (visibility, floors). Not a second state engine."""
