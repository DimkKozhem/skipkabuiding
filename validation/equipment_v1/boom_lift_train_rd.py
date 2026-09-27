"""Train RD: same YOLO26m recipe as Model ED, plus the December house6 episode.

Does not resume or overwrite R0 / ED weights. Checkpoint selection uses the
existing ED val split, which is not the boom-lift holdout and not the 17 control days.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")

ROOT = Path("/home/dimk/my_project/LCT2026")
EXT = ROOT / "data/external/construction_equipment_v1"
OUT = ROOT / "validation/equipment_v1"
YOLO = OUT / "boom_lift_yolo"
MANIFEST = OUT / "boom_lift_manifest.jsonl"
ED_TRAIN = EXT / "yolo_ed/train.txt"
ED_VAL = EXT / "yolo_ed/val.txt"
PRETRAINED = EXT / "weights/yolo26m.pt"


def yolo_line(cls: int, bbox, w: int = 1920, h: int = 1080) -> str:
    x1, y1, x2, y2 = bbox
    cx = ((x1 + x2) / 2) / w
    cy = ((y1 + y2) / 2) / h
    bw = (x2 - x1) / w
    bh = (y2 - y1) / h
    return f"{cls} {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}\n"


def build() -> Path:
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    train_rows = [r for r in rows if r["split"] == "train"]
    img_dir = YOLO / "images/train"
    lbl_dir = YOLO / "labels/train"
    img_dir.mkdir(parents=True, exist_ok=True)
    lbl_dir.mkdir(parents=True, exist_ok=True)
    by_date: dict[str, list] = {}
    for row in train_rows:
        by_date.setdefault(row["date"], []).append(row)
    new_images = []
    for date, items in sorted(by_date.items()):
        src = ROOT / items[0]["path"]
        dst = img_dir / f"house6_{date}.jpg"
        if dst.exists() or dst.is_symlink():
            dst.unlink()
        dst.symlink_to(src)
        lines = []
        for item in items:
            if item["negative"] or item["bbox"] is None:
                continue
            lines.append(yolo_line(8, item["bbox"]))
        (lbl_dir / f"house6_{date}.txt").write_text("".join(lines))
        new_images.append(dst.resolve())
    train_list = ED_TRAIN.read_text().splitlines()
    train_list = [line for line in train_list if line.strip() and "house6_" not in line]
    train_list.extend(str(p) for p in new_images)
    (YOLO / "train.txt").write_text("\n".join(train_list) + "\n")
    (YOLO / "val.txt").write_text(ED_VAL.read_text())
    (YOLO / "data.yaml").write_text(
        "\n".join([
            f"path: {YOLO}",
            "train: train.txt",
            "val: val.txt",
            "names:",
            "  0: excavator",
            "  1: bulldozer",
            "  2: loader",
            "  3: truck",
            "  4: dump_truck",
            "  5: tower_crane",
            "  6: mobile_crane",
            "  7: concrete_pump",
            "  8: aerial_work_platform",
            "  9: concrete_mixer",
            "  10: person",
            "",
        ])
    )
    holdout_dates = sorted({r["date"] for r in rows if r["split"] == "holdout"})
    leaked = [p for p in new_images if p.stem.replace("house6_", "") in holdout_dates]
    if leaked:
        raise SystemExit(f"train image is in holdout: {leaked}")
    return YOLO / "data.yaml"


def main() -> None:
    data = build()
    from ultralytics import YOLO

    model = YOLO(str(PRETRAINED))
    model.train(
        data=str(data),
        epochs=30,
        imgsz=640,
        batch=8,
        amp=False,
        seed=0,
        deterministic=True,
        device=0,
        optimizer="auto",
        lr0=0.01,
        lrf=0.01,
        momentum=0.937,
        weight_decay=0.0005,
        warmup_epochs=3.0,
        hsv_h=0.015,
        hsv_s=0.7,
        hsv_v=0.4,
        degrees=0.0,
        translate=0.2,
        scale=0.5,
        shear=0.0,
        perspective=0.0,
        flipud=0.0,
        fliplr=0.5,
        mosaic=1.0,
        mixup=0.0,
        close_mosaic=10,
        erasing=0.4,
        auto_augment="randaugment",
        patience=100,
        workers=4,
        pretrained=True,
        plots=False,
        project=str(OUT / "runs"),
        name="yolo26m_boom_rd",
        exist_ok=False,
    )


if __name__ == "__main__":
    main()
