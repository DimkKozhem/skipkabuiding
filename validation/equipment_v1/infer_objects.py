"""Offline YOLO26m inference on current object frames.

Does not touch the database, UI, perception config, or observe/evaluate.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
OUT = ROOT / "validation/equipment_v1/objects_infer.json"

CONF = 0.25
NMS_IOU = 0.5
MATCH_IOU = 0.5
NAMES = {
    0: "excavator",
    1: "bulldozer",
    2: "loader",
    3: "truck",
    4: "dump_truck",
    5: "tower_crane",
    6: "mobile_crane",
    7: "concrete_pump",
    8: "aerial_work_platform",
    9: "concrete_mixer",
    10: "person",
}
MODELS = {
    "old": {
        "weights": "data/external/construction_equipment_v1/runs/yolo26m/weights/best.pt",
        "imgsz": 640,
    },
    "model_s": {
        "weights": "data/external/construction_equipment_v1/runs/yolo26m_scale/weights/best.pt",
        "imgsz": 640,
    },
    "model_s960": {
        "weights": "data/external/construction_equipment_v1/runs/yolo26m_scale_960/weights/best.pt",
        "imgsz": 960,
    },
}
GAP_DAYS = 14
HOUSING_GAP = timedelta(hours=4)


def area_bin(frac: float) -> str:
    if frac < 0.002:
        return "<0.2%"
    if frac < 0.005:
        return "0.2-0.5%"
    if frac < 0.01:
        return "0.5-1%"
    if frac < 0.02:
        return "1-2%"
    if frac < 0.05:
        return "2-5%"
    return ">5%"


def iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def dated_frames(years: set[str]) -> list[Path]:
    folder = ROOT / "data/source/site_001"
    found = []
    for path in folder.glob("*.jpg"):
        stem = path.stem
        if len(stem) == 10 and stem[:4] in years:
            datetime.strptime(stem, "%Y-%m-%d")
            found.append(path)
    return sorted(found, key=lambda p: p.stem)


def subsample_days(files: list[Path], gap_days: int) -> list[Path]:
    if not files:
        return []
    gap = timedelta(days=gap_days)
    picked = [files[0]]
    last = datetime.strptime(files[0].stem, "%Y-%m-%d")
    for path in files[1:]:
        ts = datetime.strptime(path.stem, "%Y-%m-%d")
        if ts - last >= gap:
            picked.append(path)
            last = ts
    if picked[-1] != files[-1]:
        picked.append(files[-1])
    return picked


def housing_frames() -> tuple[list[Path], int]:
    folder = ROOT / "data/source/housing_16/timelapse"
    grouped: dict[str, list[tuple[datetime, Path]]] = defaultdict(list)
    total = 0
    for path in folder.glob("*.jpg"):
        total += 1
        left, stamp = path.stem.rsplit("_", 1)
        stage = left.rsplit("_", 1)[0]
        ts = datetime.strptime(stamp, "%Y%m%dT%H%M%S")
        grouped[stage].append((ts, path))
    picked: list[Path] = []
    for items in grouped.values():
        items.sort(key=lambda item: (item[0], item[1].name))
        chosen_ts: datetime | None = None
        for ts, path in items:
            if chosen_ts is None or ts - chosen_ts >= HOUSING_GAP:
                picked.append(path)
                chosen_ts = ts
    picked.sort()
    return picked, total


def select_frames() -> list[dict]:
    catalog = []

    def add(project: str, zone: str, files: list[Path], available: int, rule: str) -> None:
        for path in files:
            catalog.append(
                {
                    "project": project,
                    "zone": zone,
                    "path": str(path.relative_to(ROOT)),
                    "available_in_source": available,
                    "sampling": rule,
                }
            )

    house = dated_frames({"2026"})
    house_picked = subsample_days(house, GAP_DAYS)
    add(
        "site_001",
        "house6",
        house_picked,
        len(house),
        f"daily timelapse extracts, keep one frame every {GAP_DAYS} days plus the last day",
    )

    office = dated_frames({"2022", "2023"})
    office_picked = subsample_days(office, GAP_DAYS)
    add(
        "site_001",
        "office_01",
        office_picked,
        len(office),
        f"daily timelapse extracts, keep one frame every {GAP_DAYS} days plus the last day",
    )

    road = dated_frames({"2016"})
    add(
        "site_001",
        "road_alley",
        road,
        len(road),
        "10-day series, all frames kept",
    )

    housing, housing_n = housing_frames()
    add(
        "housing_16",
        "corpus_01",
        housing,
        housing_n,
        "per stage, keep a frame when the previous kept frame is at least 4 hours earlier",
    )
    return catalog


def det_from_box(xyxy, conf, cls_id, width: int, height: int) -> dict:
    box = [round(float(v), 1) for v in xyxy]
    area = max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])
    frac = area / float(width * height)
    return {
        "class": NAMES[int(cls_id)],
        "confidence": round(float(conf), 4),
        "xyxy": box,
        "area_frac": round(frac, 6),
        "area_bin": area_bin(frac),
    }


def run_model(key: str, frames: list[dict]) -> dict[str, list[dict]]:
    from ultralytics import YOLO

    spec = MODELS[key]
    weights = ROOT / spec["weights"]
    model = YOLO(str(weights))
    by_path: dict[str, list[dict]] = {}
    for index, frame in enumerate(frames, start=1):
        result = model.predict(
            source=str(ROOT / frame["path"]),
            conf=CONF,
            iou=NMS_IOU,
            imgsz=spec["imgsz"],
            device=0,
            verbose=False,
            batch=1,
        )[0]
        height, width = result.orig_shape
        boxes = result.boxes
        if boxes is None or len(boxes) == 0:
            by_path[frame["path"]] = []
        else:
            by_path[frame["path"]] = [
                det_from_box(box, conf, cls_id, width, height)
                for box, conf, cls_id in zip(
                    boxes.xyxy.cpu().tolist(),
                    boxes.conf.cpu().tolist(),
                    boxes.cls.cpu().tolist(),
                )
            ]
        if index == 1 or index % 20 == 0 or index == len(frames):
            print(f"{key} {index}/{len(frames)}", flush=True)
    del model
    return by_path


def unmatched(source: list[dict], other: list[dict]) -> list[dict]:
    found = []
    for det in source:
        if all(iou(det["xyxy"], prev["xyxy"]) < MATCH_IOU for prev in other):
            found.append(det)
    return found


def main() -> None:
    if os.environ.get("CUDA_VISIBLE_DEVICES") != "1":
        raise SystemExit("set CUDA_VISIBLE_DEVICES=1")
    frames = select_frames()
    detections = {key: run_model(key, frames) for key in MODELS}
    objects: dict[tuple[str, str], dict] = {}
    class_counts = {key: Counter() for key in MODELS}
    bin_counts = {key: Counter() for key in MODELS}
    s_only = []

    for frame in frames:
        key = (frame["project"], frame["zone"])
        bucket = objects.setdefault(
            key,
            {
                "project": frame["project"],
                "zone": frame["zone"],
                "available_in_source": frame["available_in_source"],
                "sampling": frame["sampling"],
                "frames": [],
            },
        )
        per_model = {name: detections[name][frame["path"]] for name in MODELS}
        for name, dets in per_model.items():
            for det in dets:
                class_counts[name][det["class"]] += 1
                bin_counts[name][det["area_bin"]] += 1
        for det in unmatched(per_model["model_s"], per_model["old"]):
            s960_hit = any(iou(det["xyxy"], other["xyxy"]) >= MATCH_IOU for other in per_model["model_s960"])
            s_only.append(
                {
                    "project": frame["project"],
                    "zone": frame["zone"],
                    "frame": frame["path"],
                    "class": det["class"],
                    "confidence": det["confidence"],
                    "xyxy": det["xyxy"],
                    "area_frac": det["area_frac"],
                    "area_bin": det["area_bin"],
                    "model_s960_overlap": s960_hit,
                }
            )
        bucket["frames"].append({"path": frame["path"], "detections": per_model})

    payload = {
        "protocol": {
            "conf": CONF,
            "nms_iou": NMS_IOU,
            "tiling": False,
            "match_iou_for_s_only": MATCH_IOU,
            "gpu": "CUDA_VISIBLE_DEVICES=1",
            "models": MODELS,
            "taxonomy": "data/external/construction_equipment_v1/yolo/data.yaml",
            "production_unchanged": True,
        },
        "objects": list(objects.values()),
        "summary": {
            "frames_per_object": {
                f"{item['project']}/{item['zone']}": {
                    "inferred": len(item["frames"]),
                    "available_in_source": item["available_in_source"],
                    "sampling": item["sampling"],
                }
                for item in objects.values()
            },
            "boxes_by_class": {name: dict(class_counts[name]) for name in MODELS},
            "boxes_by_area_bin": {name: dict(bin_counts[name]) for name in MODELS},
            "model_s_found_old_missed": s_only,
        },
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps(payload["summary"]["frames_per_object"], ensure_ascii=False, indent=2))
    print("boxes", json.dumps(payload["summary"]["boxes_by_class"], ensure_ascii=False))
    print("s_only", len(s_only))


if __name__ == "__main__":
    main()
