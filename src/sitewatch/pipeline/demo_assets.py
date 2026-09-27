from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from sitewatch.settings import get_settings


W, H = 1280, 720


def _write(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), image)
    return path


def _put(image, text, xy, scale=0.7, color=(255, 255, 255), thick=2):
    cv2.putText(image, text, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)


def _rect(image, box, color, label=None):
    x1, y1, x2, y2 = [int(v) for v in box]
    cv2.rectangle(image, (x1, y1), (x2, y2), color, -1)
    cv2.rectangle(image, (x1, y1), (x2, y2), (20, 20, 20), 2)
    if label:
        _put(image, label, (x1 + 6, y1 + 22), 0.55, (10, 10, 10), 1)
    return box


def _sky_ground(brightness: int = 0) -> np.ndarray:
    image = np.zeros((H, W, 3), dtype=np.uint8)
    for y in range(360):
        image[y, :] = (180 + brightness, 160 + brightness, 90 + brightness)
    image[360:, :] = (60, 90, 70)
    return image


def _excavator(image, origin, shift=0) -> list:
    x, y = origin[0] + shift, origin[1]
    body = [x, y, x + 210, y + 110]
    arm = [x + 180, y - 70, x + 320, y + 20]
    bucket = [x + 300, y - 20, x + 360, y + 50]
    _rect(image, body, (0, 210, 255), "excavator")
    _rect(image, arm, (0, 170, 210))
    _rect(image, bucket, (0, 120, 160))
    return [body]


def _dump_truck(image, origin, shift=0) -> list:
    x, y = origin[0] + shift, origin[1]
    cabin = [x, y + 20, x + 70, y + 90]
    bed = [x + 70, y, x + 220, y + 90]
    _rect(image, cabin, (40, 40, 40), "cab")
    _rect(image, bed, (0, 120, 230), "dump_truck")
    return [bed]


def _crane(image, origin) -> list:
    x, y = origin
    mast = [x + 30, 80, x + 55, y + 160]
    arm = [x + 55, 90, x + 260, 120]
    base = [x, y + 130, x + 110, y + 180]
    _rect(image, base, (40, 80, 200), "crane")
    _rect(image, mast, (30, 60, 170))
    _rect(image, arm, (20, 50, 150))
    return [base]


def _building(image, floors: int = 4) -> list:
    boxes = []
    foundation = [760, 560, 1180, 620]
    _rect(image, foundation, (80, 80, 80), "foundation")
    boxes.append(("foundation", foundation))
    floor_h = 70
    for idx in range(floors):
        y2 = 560 - idx * floor_h
        y1 = y2 - floor_h
        box = [780, y1, 1160, y2]
        _rect(image, box, (160 + idx * 8, 160, 150), f"wall {idx + 1}")
        boxes.append(("wall", box))
        for col_x in (800, 920, 1040):
            col = [col_x, y1 + 8, col_x + 22, y2 - 4]
            _rect(image, col, (40, 160, 200))
            boxes.append(("column", col))
        slab = [780, y1, 1160, y1 + 12]
        _rect(image, slab, (200, 200, 80))
        boxes.append(("slab", slab))
    return boxes


def _sidecar(path: Path, timestamp: datetime, camera: str, zone: str, detections: list, scene: dict) -> Path:
    payload = {
        "image": path.name,
        "timestamp": timestamp.isoformat(),
        "camera_id": camera,
        "zone": zone,
        "detections": detections,
        "scene": scene,
        "model_version": "demo-labels",
    }
    out = path.with_suffix(".json")
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def _det(name: str, box, conf: float) -> dict:
    return {"class_name": name, "bbox": [int(v) for v in box], "confidence": conf}


def generate_demo_assets() -> Path:
    """Synthetic demo assets.

    DEMO 1 zone_a NORMAL: excavator=1, dump_truck=3
    DEMO 2 zone_b MISSING: excavator=1, dump_truck=0
    DEMO 3 building_01 NO DYNAMICS / DELAY: 4 structural levels while KSG advances 4→6
    """
    root = get_settings().data_dir / "demo"
    images = root / "images"
    images.mkdir(parents=True, exist_ok=True)

    # NORMAL excavation — 3 frames, excavator + 3 dump trucks
    for idx, shift in enumerate((0, 18, 36)):
        ts = datetime.fromisoformat(f"2026-09-18T10:{30 + idx * 5:02d}:00")
        image = _sky_ground()
        cv2.rectangle(image, (40, 390), (1100, 680), (20, 55, 90), -1)
        _put(image, "ZONE A  |  excavation  |  2026-09-18", (30, 40))
        _put(image, "cam_pit_a  same viewpoint", (30, 70), 0.55)
        exc = _excavator(image, (80, 470), shift=0)[0]
        t1 = _dump_truck(image, (420, 500), shift=shift)[0]
        t2 = _dump_truck(image, (200, 540), shift=shift // 2)[0]
        t3 = _dump_truck(image, (680, 520), shift=shift // 3)[0]
        _put(image, "NORMAL: excavator + 3 dump trucks", (30, 700), 0.55, (220, 255, 220))
        path = _write(images / f"zone_a_normal_{idx + 1}.jpg", image)
        _sidecar(
            path,
            ts,
            "cam_pit_a",
            "zone_a",
            [
                _det("excavator", exc, 0.91),
                _det("dump_truck", t1, 0.88),
                _det("dump_truck", t2, 0.86),
                _det("dump_truck", t3, 0.84),
            ],
            {"visibility": "good", "coverage": "full"},
        )

    # MISSING EQUIPMENT — 3 frames, only excavator
    for idx in range(3):
        ts = datetime.fromisoformat(f"2026-09-18T11:{10 + idx * 5:02d}:00")
        image = _sky_ground(-10)
        cv2.rectangle(image, (40, 390), (700, 680), (18, 50, 80), -1)
        _put(image, "ZONE B  |  excavation  |  2026-09-18", (30, 40))
        _put(image, "cam_pit_b  same viewpoint", (30, 70), 0.55)
        exc = _excavator(image, (90, 480))[0]
        _put(image, "MISSING_EQUIPMENT: dump_truck not observed", (30, 700), 0.55, (180, 180, 255))
        path = _write(images / f"zone_b_missing_{idx + 1}.jpg", image)
        _sidecar(
            path,
            ts,
            "cam_pit_b",
            "zone_b",
            [_det("excavator", exc, 0.90)],
            {"visibility": "good", "coverage": "full"},
        )

    # building_01: 4 этажа в scene.floors (не count slab-боксов); КСГ 4→6 без визуальной динамики.
    dates = [
        ("2026-09-01T12:00:00", 8),
        ("2026-09-08T12:00:00", 4),
        ("2026-09-15T12:00:00", 0),
        ("2026-09-22T12:00:00", -6),
    ]
    for stamp, brightness in dates:
        ts = datetime.fromisoformat(stamp)
        image = _sky_ground(brightness)
        _put(image, f"BUILDING 01  |  superstructure  |  {ts.date()}", (30, 40))
        _put(image, "cam_building  same viewpoint", (30, 70), 0.55)
        boxes = _building(image, floors=4)
        crane = _crane(image, (430, 430))[0]
        _put(image, "NO DYNAMICS: 4 levels while KSG advances", (30, 700), 0.5, (200, 220, 255))
        path = _write(images / f"building_01_{ts.date().isoformat()}.jpg", image)
        detections = [_det(name, box, 0.84) for name, box in boxes] + [_det("mobile_crane", crane, 0.87)]
        _sidecar(
            path,
            ts,
            "cam_building",
            "building_01",
            detections,
            {"visibility": "good", "coverage": "full", "foundation": True, "floors": 4},
        )

    video_path = root / "video" / "zone_a_window.mp4"
    video_path.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 6, (W, H))
    for idx, shift in enumerate(range(0, 48, 3)):
        image = _sky_ground()
        cv2.rectangle(image, (40, 390), (1100, 680), (20, 55, 90), -1)
        _excavator(image, (80, 470))
        _dump_truck(image, (420, 500), shift=shift)
        _dump_truck(image, (200, 540), shift=shift // 2)
        _dump_truck(image, (680, 520), shift=shift // 3)
        _put(image, f"video sample frame {idx}", (30, 40))
        writer.write(image)
    writer.release()
    frame = _sky_ground()
    cv2.rectangle(frame, (40, 390), (1100, 680), (20, 55, 90), -1)
    video_exc = _excavator(frame, (80, 470))[0]
    video_t1 = _dump_truck(frame, (420, 500))[0]
    video_t2 = _dump_truck(frame, (200, 540))[0]
    video_t3 = _dump_truck(frame, (680, 520))[0]
    _sidecar(
        video_path,
        datetime.fromisoformat("2026-09-18T10:00:00"),
        "cam_pit_a",
        "zone_a",
        [
            _det("excavator", video_exc, 0.91),
            _det("dump_truck", video_t1, 0.88),
            _det("dump_truck", video_t2, 0.86),
            _det("dump_truck", video_t3, 0.84),
        ],
        {"visibility": "good", "coverage": "full"},
    )
    return root
