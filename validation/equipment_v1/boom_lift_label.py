"""Human-confirmed house6 boom-lift manifest.

SAM boxes are a bootstrap. Indices below were accepted after looking at
contact sheets and crops. Tower cranes, masts, trucks, excavators,
telehandlers, containers and boom fragments without a machine are omitted.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
OUT = ROOT / "validation/equipment_v1"
PROPOSALS = OUT / "boom_lift_sam_proposals.jsonl"
MANIFEST = OUT / "boom_lift_manifest.jsonl"
SPLIT = OUT / "boom_lift_split.json"
W, H = 1920, 1080

# (date, proposal index) kept after visual review.
KEEP = {
    ("2026-08-02", 0), ("2026-08-02", 2),
    ("2026-08-03", 0),
    ("2026-08-04", 1),
    ("2026-08-05", 0), ("2026-08-05", 1),
    ("2026-08-07", 1),
    ("2026-08-10", 0),
    ("2026-08-11", 0),
    ("2026-08-12", 1),
    ("2026-08-13", 1),
    ("2026-08-15", 1),
    ("2026-08-16", 0), ("2026-08-16", 2),
    ("2026-08-17", 0), ("2026-08-17", 1),
    ("2026-08-18", 0), ("2026-08-18", 1), ("2026-08-18", 2),
    ("2026-08-19", 0), ("2026-08-19", 2), ("2026-08-19", 3),
    ("2026-08-20", 1),
    ("2026-08-21", 1),
    ("2026-08-22", 0),
    ("2026-08-23", 0), ("2026-08-23", 2),
    ("2026-08-25", 0),
    ("2026-08-26", 1),
    ("2026-08-27", 2), ("2026-08-27", 3),
    ("2026-08-29", 0),
    ("2026-08-30", 1),
    ("2026-08-31", 0),
    ("2026-09-02", 1),
    ("2026-09-03", 1),
    ("2026-09-04", 0),
    ("2026-09-05", 0), ("2026-09-05", 1),
    ("2026-09-07", 0),
    ("2026-09-14", 0),
    ("2026-09-15", 0),
    ("2026-09-16", 0),
    ("2026-09-17", 0),
    ("2026-09-19", 0), ("2026-09-19", 1),
    ("2026-09-20", 0), ("2026-09-20", 1),
    ("2026-09-21", 0), ("2026-09-21", 1),
    ("2026-09-22", 0), ("2026-09-22", 1),
    ("2026-09-23", 0), ("2026-09-23", 1),
    ("2026-09-24", 0), ("2026-09-24", 1),
    ("2026-09-25", 0),
    ("2026-09-26", 0), ("2026-09-26", 1),
    ("2026-09-27", 0),
    ("2026-09-28", 0), ("2026-09-28", 1),
    ("2026-09-29", 0), ("2026-09-29", 1),
    ("2026-09-30", 0), ("2026-09-30", 1),
    ("2026-10-02", 0), ("2026-10-02", 1),
    ("2026-10-03", 0), ("2026-10-03", 1),
    ("2026-10-04", 0),
    ("2026-10-05", 0), ("2026-10-05", 1),
    ("2026-10-06", 0), ("2026-10-06", 1),
    ("2026-10-08", 1),
    ("2026-10-09", 0), ("2026-10-09", 1),
    ("2026-10-10", 0), ("2026-10-10", 1),
    ("2026-10-11", 0), ("2026-10-11", 1),
    ("2026-10-12", 0),
    ("2026-10-13", 0), ("2026-10-13", 2),
    ("2026-10-14", 0), ("2026-10-14", 1),
    ("2026-10-15", 0),
    ("2026-10-16", 0), ("2026-10-16", 1),
    ("2026-10-17", 0), ("2026-10-17", 1),
    ("2026-10-19", 0),
    ("2026-10-21", 0),
    ("2026-10-23", 0),
    ("2026-10-24", 0),
    ("2026-10-25", 0),
    ("2026-10-26", 0), ("2026-10-26", 2),
    ("2026-10-27", 0),
    ("2026-10-28", 0),
    ("2026-10-30", 0),
    ("2026-10-31", 0),
    ("2026-11-01", 1),
    ("2026-11-02", 0),
    ("2026-11-04", 0), ("2026-11-04", 1),
    ("2026-11-06", 0), ("2026-11-06", 1),
    ("2026-11-07", 0), ("2026-11-07", 1),
    ("2026-11-08", 0), ("2026-11-08", 1),
    ("2026-11-09", 0), ("2026-11-09", 1), ("2026-11-09", 2),
    ("2026-11-10", 0),
    ("2026-11-11", 0), ("2026-11-11", 1),
    ("2026-11-12", 0), ("2026-11-12", 2),
    ("2026-11-13", 0), ("2026-11-13", 1),
    ("2026-11-14", 0), ("2026-11-14", 1),
    ("2026-11-15", 1),
    ("2026-11-16", 0), ("2026-11-16", 1), ("2026-11-16", 2),
    ("2026-11-17", 0),
    ("2026-11-20", 0),
    ("2026-11-21", 0),
    ("2026-11-22", 0),
    ("2026-11-23", 0),
    ("2026-11-27", 0),
    ("2026-11-28", 0),
    ("2026-11-30", 0), ("2026-11-30", 1),
    ("2026-12-04", 0),
    ("2026-12-12", 0),
    ("2026-12-13", 0),
    ("2026-12-14", 0),
    ("2026-12-16", 0),
}

# Low-confidence SAM boxes accepted on days the first pass missed.
EXTRA = [
    {"date": "2026-09-08", "xyxy": [1561.0, 743.0, 1673.0, 825.0], "note": "blue boom lift base and boom"},
    {"date": "2026-09-09", "xyxy": [1449.0, 714.0, 1614.0, 836.0], "note": "blue telescopic boom lift"},
    {"date": "2026-09-13", "xyxy": [1171.0, 782.0, 1409.0, 875.0], "note": "Genie telescopic boom lift"},
]

# Days opened on a contact sheet and confirmed to have no aerial_work_platform.
CONFIRMED_EMPTY = {
    "2026-08-24", "2026-09-06", "2026-09-12",
    "2026-12-01", "2026-12-02", "2026-12-03",
    "2026-12-06", "2026-12-07", "2026-12-08", "2026-12-09", "2026-12-10", "2026-12-11",
    "2026-12-15", "2026-12-17", "2026-12-18",
}

# Long facade visit cannot be cut. December return is the other episode.
# The week 12-05..12-11 is the gap and stays out of both splits.
HOLDOUT_END = "2026-12-04"
TRAIN_DAYS = {"2026-12-12", "2026-12-13", "2026-12-14", "2026-12-15", "2026-12-16"}
EP_HOLDOUT = "h6_aug_dec04"
EP_TRAIN = "h6_dec12_16"


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / (aa + bb - inter)


def area_frac(xyxy) -> float:
    return max(0.0, xyxy[2] - xyxy[0]) * max(0.0, xyxy[3] - xyxy[1]) / (W * H)


# Confirmed on the kept-box sheets: tower-crane jibs, one telehandler, one truck, one doubtful handler, one boom with the base outside the box.
DROP_BBOX = {
    ("2026-08-10", (896.0, -0.1, 1339.0, 315.8)),
    ("2026-08-23", (738.5, 27.7, 1569.0, 312.0)),
    ("2026-08-25", (737.3, 35.8, 1491.6, 332.9)),
    ("2026-08-19", (1314.0, 928.7, 1463.1, 1039.8)),
    ("2026-10-26", (456.2, 972.7, 633.9, 1066.4)),
    ("2026-11-09", (1543.0, 686.6, 1716.2, 800.6)),
    ("2026-11-30", (1579.0, 623.7, 1656.3, 777.7)),
}


def dedupe(boxes: list[dict]) -> list[dict]:
    ordered = sorted(boxes, key=lambda b: b["area_frac"])
    kept: list[dict] = []
    for box in ordered:
        if any(iou(box["bbox"], prev["bbox"]) >= 0.3 for prev in kept):
            continue
        kept.append(box)
    return kept


def assign(date: str) -> tuple[str, str]:
    if date in TRAIN_DAYS:
        return EP_TRAIN, "train"
    if date <= HOLDOUT_END and date >= "2026-08-02":
        return EP_HOLDOUT, "holdout"
    return "excluded", "excluded"


def main() -> None:
    proposals = [json.loads(line) for line in PROPOSALS.read_text().splitlines() if line.strip()]
    by_date = {rec["date"]: rec for rec in proposals}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for date, rec in by_date.items():
        for i, box in enumerate(rec["boxes"]):
            if (date, i) not in KEEP:
                continue
            xyxy = [float(v) for v in box["xyxy"]]
            grouped[date].append({
                "bbox": [round(v, 1) for v in xyxy],
                "area_frac": round(area_frac(xyxy), 6),
                "sam_score": box["score"],
                "sam_prompt": box["prompt"],
            })
    for extra in EXTRA:
        xyxy = extra["xyxy"]
        grouped[extra["date"]].append({
            "bbox": [round(v, 1) for v in xyxy],
            "area_frac": round(area_frac(xyxy), 6),
            "sam_score": None,
            "sam_prompt": "boom lift",
            "note": extra["note"],
        })

    rows = []
    for date in sorted(set(grouped) | CONFIRMED_EMPTY):
        episode_id, split = assign(date)
        if split == "excluded":
            continue
        path = f"data/source/site_001/{date}.jpg"
        boxes = [
            box for box in dedupe(grouped.get(date, []))
            if (date, tuple(box["bbox"])) not in DROP_BBOX and box["bbox"][1] >= 80
        ]
        if not boxes:
            rows.append({
                "camera_id": "house6",
                "date": date,
                "frame_id": f"house6_{date}",
                "path": path,
                "class": None,
                "bbox": None,
                "area_frac": None,
                "label_source": "human",
                "episode_id": episode_id,
                "split": split,
                "negative": True,
            })
            continue
        for j, box in enumerate(boxes):
            rows.append({
                "camera_id": "house6",
                "date": date,
                "frame_id": f"house6_{date}_{j:02d}",
                "path": path,
                "class": "aerial_work_platform",
                "bbox": box["bbox"],
                "area_frac": box["area_frac"],
                "label_source": "human",
                "episode_id": episode_id,
                "split": split,
                "negative": False,
                "sam_score": box["sam_score"],
                "sam_prompt": box["sam_prompt"],
            })

    MANIFEST.write_text("".join(json.dumps(r) + "\n" for r in rows))
    summary = summarize(rows, proposals)
    SPLIT.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("train", "holdout", "stop")}, indent=2))


def bin_name(area: float) -> str:
    if area < 0.002:
        return "<0.2%"
    if area < 0.005:
        return "0.2–0.5%"
    if area < 0.01:
        return "0.5–1%"
    if area < 0.02:
        return "1–2%"
    return ">2%"


def pack(rows: list[dict]) -> dict:
    pos = [r for r in rows if not r["negative"]]
    images = sorted({r["date"] for r in rows})
    pos_images = sorted({r["date"] for r in pos})
    bins = {k: 0 for k in ("<0.2%", "0.2–0.5%", "0.5–1%", "1–2%", ">2%")}
    for r in pos:
        bins[bin_name(r["area_frac"])] += 1
    n = len(pos)
    return {
        "episodes": sorted({r["episode_id"] for r in rows}),
        "images": len(images),
        "positive_images": len(pos_images),
        "negative_images": len(images) - len(pos_images),
        "objects": n,
        "classes": {"aerial_work_platform": n},
        "days": images,
        "area_bins": bins,
        "cumulative": {
            "<2%": sum(1 for r in pos if r["area_frac"] < 0.02),
            "<1%": sum(1 for r in pos if r["area_frac"] < 0.01),
            "<0.5%": sum(1 for r in pos if r["area_frac"] < 0.005),
            "<0.2%": sum(1 for r in pos if r["area_frac"] < 0.002),
        },
    }


def summarize(rows: list[dict], proposals: list[dict]) -> dict:
    train = pack([r for r in rows if r["split"] == "train"])
    holdout = pack([r for r in rows if r["split"] == "holdout"])
    return {
        "camera_id": "house6",
        "question": "aerial_work_platform across temporally separated episodes of one camera",
        "label_source": "human",
        "sam_role": "bootstrap only",
        "control_days_excluded": True,
        "domain_holdout_json_unchanged": True,
        "domain_split_json_unchanged": True,
        "episode_rule": "A continuous run of days with the same boom-lift group stays in one split. Aug 2-Dec 4 has no multi-day absence, so it is one episode. Dec 5-11 are empty of confirmed lifts and are the gap. Dec 12-16 is the other episode.",
        "val_for_checkpoint": "existing ED val (February house6 days in yolo_ed/val.txt). Not this holdout and not the 17 control days. The December train episode is not split to make a val day.",
        "train": train,
        "holdout": holdout,
        "stop": holdout["objects"] < 20,
        "proposal_days": len(proposals),
        "unreviewed_zero_box_days_excluded": [
            rec["date"] for rec in proposals
            if not rec["boxes"] and rec["date"] not in CONFIRMED_EMPTY and rec["date"] not in TRAIN_DAYS
        ],
    }


if __name__ == "__main__":
    main()
