from __future__ import annotations

from pathlib import Path

from sitewatch.domain.contracts import Detection


class SAM2Refiner:
    """Optional precision layer: YOLO box → SAM 2 mask. Not used on every inference."""

    name = "sam2"

    def __init__(self, checkpoint: Path | None = None) -> None:
        self.checkpoint = checkpoint or Path("/home/dimk/my_project/sam2/checkpoints/sam2.1_hiera_tiny.pt")

    def refine(self, image_path: Path, detections: list[Detection]) -> list[Detection]:
        if not detections:
            return detections
        # Lazy hook: keep the contract without forcing SAM on the critical path.
        for det in detections:
            det.extra = {**det.extra, "sam_available": self.checkpoint.exists(), "refined": False}
        return detections
