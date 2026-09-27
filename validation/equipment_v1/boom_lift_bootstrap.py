"""SAM3 bootstrap for late house6 boom lifts. Proposals are not ground truth.

Human confirmation of class and bbox is required before boom_lift_manifest.jsonl.
Does not read or write domain_holdout.json, domain_split.json, the 17 control
days, production DB, UI, or config/perception.yaml.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")

import cv2

from sitewatch.perception.providers.sam3 import Sam3Provider

ROOT = Path("/home/dimk/my_project/LCT2026")
SRC = ROOT / "data/source/site_001"
OUT = ROOT / "validation/equipment_v1"
PROPOSALS = OUT / "boom_lift_sam_proposals.jsonl"
REVIEW = OUT / "boom_lift_review" / "crops"
CONTROL = {
    "2026-01-10", "2026-01-15", "2026-02-01", "2026-03-15", "2026-03-20",
    "2026-04-01", "2026-04-10", "2026-05-01", "2026-05-15", "2026-06-01",
    "2026-06-15", "2026-06-20", "2026-07-01", "2026-07-15", "2026-08-01",
    "2026-09-01", "2026-10-01",
}
PROMPTS = ["boom lift", "cherry picker", "scissor lift"]
START = datetime(2026, 8, 2)
END = datetime(2026, 12, 24)


def candidate_days() -> list[str]:
    days = []
    day = START
    while day <= END:
        stem = day.strftime("%Y-%m-%d")
        if stem not in CONTROL and (SRC / f"{stem}.jpg").is_file():
            days.append(stem)
        day += timedelta(days=1)
    return days


def done_days() -> set[str]:
    if not PROPOSALS.exists():
        return set()
    out = set()
    for line in PROPOSALS.read_text().splitlines():
        if line.strip():
            out.add(json.loads(line)["date"])
    return out


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / (area_a + area_b - inter)


def dedupe(boxes: list[dict], thr: float = 0.5) -> list[dict]:
    ordered = sorted(boxes, key=lambda b: b["score"], reverse=True)
    kept: list[dict] = []
    for box in ordered:
        if any(iou(box["xyxy"], prev["xyxy"]) >= thr for prev in kept):
            continue
        kept.append(box)
    return kept


def main() -> None:
    REVIEW.mkdir(parents=True, exist_ok=True)
    provider = Sam3Provider(enabled=True)
    seen = done_days()
    with PROPOSALS.open("a") as fh:
        for date in candidate_days():
            if date in seen:
                continue
            path = SRC / f"{date}.jpg"
            result = provider.segment(path, PROMPTS)
            raw = []
            if result.evidence:
                for ev in result.evidence:
                    bb = ev.bbox
                    if bb is None:
                        continue
                    raw.append({
                        "prompt": ev.raw_label,
                        "score": round(float(ev.score), 4),
                        "xyxy": [round(bb.x1, 1), round(bb.y1, 1), round(bb.x2, 1), round(bb.y2, 1)],
                    })
            boxes = dedupe(raw)
            img = cv2.imread(str(path))
            h, w = img.shape[:2]
            for i, box in enumerate(boxes):
                x1, y1, x2, y2 = box["xyxy"]
                box["area_frac"] = round(max(0.0, x2 - x1) * max(0.0, y2 - y1) / (w * h), 6)
                pad = 40
                crop = img[max(0, int(y1) - pad):min(h, int(y2) + pad), max(0, int(x1) - pad):min(w, int(x2) + pad)]
                crop_path = REVIEW / f"{date}_{i:02d}.jpg"
                if crop.size:
                    cv2.imwrite(str(crop_path), crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                    box["crop"] = str(crop_path.relative_to(ROOT))
            rec = {
                "camera_id": "house6",
                "date": date,
                "path": str(path.relative_to(ROOT)),
                "status": str(result.status),
                "error": result.error,
                "n_raw": len(raw),
                "boxes": boxes,
                "label_source": "sam_bootstrap_not_gt",
            }
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            print(date, result.status, "raw", len(raw), "kept", len(boxes), flush=True)


if __name__ == "__main__":
    main()
