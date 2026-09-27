from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from sitewatch.domain.contracts import Detection

_PALETTE = {
    "excavator": (0, 210, 255),
    "dump_truck": (0, 140, 255),
    "truck": (40, 80, 220),
    "bulldozer": (0, 180, 120),
    "mobile_crane": (220, 80, 40),
    "concrete_mixer": (180, 60, 200),
    "roller": (80, 80, 80),
    "crane_manipulator": (200, 120, 40),
    "foundation": (90, 90, 90),
    "column": (160, 160, 40),
    "wall": (80, 140, 200),
    "slab": (200, 180, 80),
    "roof": (60, 60, 180),
    "window": (220, 220, 80),
    "facade": (140, 100, 180),
    "floor": (100, 160, 100),
    "worker": (40, 220, 40),
}


def draw_detections(image_path: Path, detections: list[Detection], out_path: Path) -> Path:
    image = cv2.imread(str(image_path))
    if image is None:
        raise FileNotFoundError(image_path)
    for det in detections:
        color = _PALETTE.get(det.class_name, (255, 255, 255))
        x1, y1, x2, y2 = [int(v) for v in det.bbox.as_xyxy()]
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        label = f"{det.class_name} {det.confidence:.2f}"
        if det.track_id is not None:
            label += f" #{det.track_id}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)
        cv2.rectangle(image, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv2.putText(
            image,
            label,
            (x1 + 3, y1 - 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), image)
    return out_path


def blank_canvas(width: int = 1280, height: int = 720) -> np.ndarray:
    return np.zeros((height, width, 3), dtype=np.uint8)
