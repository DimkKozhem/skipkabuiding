"""Build construction_equipment_v1 YOLO split. house6 is not an input."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import cv2

ROOT = Path("/home/dimk/my_project/LCT2026/data/external/construction_equipment_v1")
OUT = ROOT / "yolo"
CLASSES = [
    "excavator", "bulldozer", "loader", "truck", "dump_truck",
    "tower_crane", "mobile_crane", "concrete_pump",
    "aerial_work_platform", "concrete_mixer", "person",
]
SAFETY_MAP = {
    "excavators": "excavator",
    "dump truck": "dump_truck",
    "truck": "truck",
    "wheel loader": "loader",
    "person": "person",
}
SAFETY_ZIP = Path(
    "/home/dimk/.cache/huggingface/hub/datasets--keremberke--construction-safety-object-detection"
    "/snapshots/a19eace121442bce60da9f5036dc16bf9f2f6fa6/data/train.zip"
)


def group_key(name: str) -> str:
    stem = Path(name).stem
    import re
    return re.sub(r"([_-](p)?\d{1,2})+$", "", stem, flags=re.I)


def split_of(key: str) -> str:
    digest = hashlib.sha1(group_key(key).encode()).hexdigest()
    return "val" if int(digest[:2], 16) < 51 else "train"  # ~20%


def yolo_line(cls: str, xyxy, w: int, h: int) -> str:
    x1, y1, x2, y2 = xyxy
    bw = max(1.0, x2 - x1)
    bh = max(1.0, y2 - y1)
    cx = (x1 + x2) / 2 / w
    cy = (y1 + y2) / 2 / h
    return f"{CLASSES.index(cls)} {cx:.6f} {cy:.6f} {bw / w:.6f} {bh / h:.6f}"


def area_ratio(xyxy, w, h) -> float:
    return max(0.0, xyxy[2] - xyxy[0]) * max(0.0, xyxy[3] - xyxy[1]) / (w * h)


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    for part in ("train", "val"):
        (OUT / "images" / part).mkdir(parents=True)
        (OUT / "labels" / part).mkdir(parents=True)
    stats = Counter()
    areas = defaultdict(list)
    sources = Counter()
    ambiguous = 0
    ignored = 0

    rows = []
    proposals = ROOT / "proposals.jsonl"
    if proposals.exists():
        rows = [json.loads(line) for line in proposals.read_text().splitlines() if line.strip()]
    for rec in rows:
        src = ROOT / rec["file"]
        img = cv2.imread(str(src))
        if img is None:
            continue
        h, w = img.shape[:2]
        hint = rec["hint"]
        if rec["status"] == "no_box":
            ignored += 1
            continue
        # Pump/crane rival scores are the confusion we must teach.
        # Spot-check of review sheets: orange boxes on these two hints are the machine.
        accept_ambiguous = hint in {"concrete_pump", "mobile_crane"} and rec["status"] == "ambiguous"
        if rec["status"] == "ambiguous" and not accept_ambiguous:
            ambiguous += 1
            continue
        lines = []
        if hint == "negative" and rec["status"] == "negative_candidate":
            part = split_of(rec["file"])
        elif rec["status"] in {"proposal", "ambiguous"} and hint in CLASSES:
            min_score = 0.4 if accept_ambiguous else 0.5
            for box in rec["primary"]:
                if box["score"] < min_score:
                    continue
                ratio = area_ratio(box["xyxy"], w, h)
                if ratio < 0.012 or ratio > 0.72:
                    ignored += 1
                    continue
                lines.append(yolo_line(hint, box["xyxy"], w, h))
                areas[hint].append(ratio)
                stats[hint] += 1
            if not lines:
                continue
            part = split_of(rec["file"])
        else:
            continue
        name = f"commons_{Path(rec['file']).name}"
        shutil.copy(src, OUT / "images" / part / name)
        (OUT / "labels" / part / (Path(name).stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
        sources[f"commons_{hint}_{part}"] += 1

    if SAFETY_ZIP.is_file():
        with zipfile.ZipFile(SAFETY_ZIP) as zf:
            coco = json.loads(zf.read("_annotations.coco.json"))
        cats = {c["id"]: c["name"] for c in coco["categories"]}
        by_image = defaultdict(list)
        for ann in coco["annotations"]:
            name = SAFETY_MAP.get(cats[ann["category_id"]])
            if name:
                by_image[ann["image_id"]].append((name, ann["bbox"]))
        images = {im["id"]: im for im in coco["images"]}
        with zipfile.ZipFile(SAFETY_ZIP) as zf:
            for image_id, boxes in by_image.items():
                im = images[image_id]
                dest = OUT / "images" / "train" / f"safety_{im['file_name']}"
                dest.write_bytes(zf.read(im["file_name"]))
                img = cv2.imread(str(dest))
                if img is None:
                    dest.unlink(missing_ok=True)
                    continue
                h, w = img.shape[:2]
                lines = []
                for name, (x, y, bw, bh) in boxes:
                    xyxy = [x, y, x + bw, y + bh]
                    ratio = area_ratio(xyxy, w, h)
                    lines.append(yolo_line(name, xyxy, w, h))
                    areas[name].append(ratio)
                    stats[name] += 1
                (OUT / "labels" / "train" / (dest.stem + ".txt")).write_text("\n".join(lines) + "\n")
                sources["safety_train"] += 1

    (OUT / "data.yaml").write_text(
        "path: " + str(OUT) + "\n"
        "train: images/train\nval: images/val\n"
        "names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES))
    )
    summary = {
        "classes": CLASSES,
        "objects": dict(stats),
        "images": dict(sources),
        "ambiguous_excluded": ambiguous,
        "boxes_rejected_by_size_or_score": ignored,
        "area_ratio_p50": {k: round(sorted(v)[len(v)//2], 4) for k, v in areas.items() if v},
        "house6_used": False,
        "split": "commons by sha1 of file (~20% val); construction-safety youtube frames all in train",
    }
    (ROOT / "dataset_v1_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
