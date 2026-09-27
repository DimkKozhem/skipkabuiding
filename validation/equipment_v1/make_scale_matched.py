"""Downscale external equipment onto construction backgrounds.

house6 paths are refused. Synthetic children stay in the split of their source image.
"""

from __future__ import annotations

import json
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

ROOT = Path("/home/dimk/my_project/LCT2026/data/external/construction_equipment_v1")
SRC = ROOT / "yolo"
OUT = ROOT / "yolo_scale"
CLASSES = [
    "excavator", "bulldozer", "loader", "truck", "dump_truck",
    "tower_crane", "mobile_crane", "concrete_pump",
    "aerial_work_platform", "concrete_mixer", "person",
]
BINS = [
    (0, 0.002, "<0.2%"),
    (0.002, 0.005, "0.2–0.5%"),
    (0.005, 0.01, "0.5–1%"),
    (0.01, 0.02, "1–2%"),
    (0.02, 0.05, "2–5%"),
    (0.05, 1.1, ">5%"),
]
CANVAS = (1280, 720)  # w, h — stationary-camera frame, not a catalog crop
RNG = random.Random(20260925)


def bin_of(area: float) -> str:
    for lo, hi, name in BINS:
        if lo <= area < hi:
            return name
    return ">5%"


def read_labels(path: Path) -> list[tuple[int, float, float, float, float]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    rows = []
    for line in path.read_text().splitlines():
        p = line.split()
        if len(p) < 5:
            continue
        rows.append((int(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    return rows


def xyxy(cx, cy, w, h, W, H):
    x1 = int((cx - w / 2) * W)
    y1 = int((cy - h / 2) * H)
    x2 = int((cx + w / 2) * W)
    y2 = int((cy + h / 2) * H)
    return max(0, x1), max(0, y1), min(W - 1, x2), min(H - 1, y2)


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    aa = max(1, a[2] - a[0]) * max(1, a[3] - a[1])
    bb = max(1, b[2] - b[0]) * max(1, b[3] - b[1])
    return inter / (aa + bb - inter)


def load_split(part: str):
    images = []
    for img in sorted((SRC / "images" / part).iterdir()):
        if "house6" in str(img) or "site_001" in str(img):
            raise SystemExit(f"refusing house6 path {img}")
        lab = SRC / "labels" / part / (img.stem + ".txt")
        labels = read_labels(lab)
        images.append({"path": img, "labels": labels, "part": part})
    return images


def target_area(cls_name: str) -> float:
    if cls_name == "person":
        return float(np.exp(RNG.uniform(np.log(0.0008), np.log(0.004))))
    # 75% in the SiteWatch band, 25% medium so large examples are not the only ones left
    if RNG.random() < 0.75:
        return float(np.exp(RNG.uniform(np.log(0.002), np.log(0.02))))
    return float(np.exp(RNG.uniform(np.log(0.02), np.log(0.05))))


def pull_back(img, labels):
    """Shrink a whole labeled photo onto a sky/ground canvas. One coherent scene."""
    H, W = img.shape[:2]
    if not labels:
        return None
    areas = [w * h for _c, _x, _y, w, h in labels]
    largest = max(areas)
    # aim the biggest machine at the SiteWatch band; people ride along at the same scale
    target = float(np.exp(RNG.uniform(np.log(0.004), np.log(0.02))))
    scale = (target / max(largest, 1e-6)) ** 0.5
    scale = float(np.clip(scale, 0.08, 0.55))
    nw, nh = max(20, int(W * scale)), max(20, int(H * scale))
    if nh > int(0.7 * CANVAS[1]):
        fit = 0.7 * CANVAS[1] / H
        scale = min(scale, fit)
        nw, nh = max(20, int(W * scale)), max(20, int(H * scale))
    small = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_AREA)
    cw, ch = CANVAS
    canvas = np.zeros((ch, cw, 3), np.uint8)
    sky = small[: max(1, nh // 10)].mean(axis=(0, 1))
    ground = small[-max(1, nh // 8) :].mean(axis=(0, 1))
    canvas[:, :] = sky
    horizon = int(ch * 0.58)
    canvas[horizon:] = ground
    bottom = int(RNG.uniform(0.80, 0.96) * ch)
    top = bottom - nh
    if top < int(0.05 * ch):
        return None
    left = int(RNG.uniform(0, max(1, cw - nw)))
    canvas[top:bottom, left : left + nw] = small
    lines = []
    for cls_i, cx, cy, w, h in labels:
        ncx = (cx * nw + left) / cw
        ncy = (cy * nh + top) / ch
        nw_ = w * nw / cw
        nh_ = h * nh / ch
        if nw_ < 0.004 or nh_ < 0.004:
            continue
        lines.append(f"{cls_i} {ncx:.6f} {ncy:.6f} {nw_:.6f} {nh_:.6f}")
    if not lines:
        return None
    return canvas, lines


def paste_one(canvas, crop, cls_name, placed) -> str | None:
    H, W = canvas.shape[:2]
    ch, cw = crop.shape[:2]
    if ch < 24 or cw < 24:
        return None
    area = target_area(cls_name)
    aspect = cw / ch
    bh = (area * W * H / aspect) ** 0.5
    bw = bh * aspect
    if cls_name == "person":
        bh = min(bh, 0.12 * H)
        bw = bh * aspect
    else:
        bh = min(bh, 0.55 * H)
        bw = min(bw, 0.7 * W)
        bh = bw / aspect
    bw, bh = int(bw), int(bh)
    if bw < 12 or bh < 12:
        return None
    resized = cv2.resize(crop, (bw, bh), interpolation=cv2.INTER_AREA)
    for _ in range(12):
        bottom = int(RNG.uniform(0.62, 0.94) * H)
        top = bottom - bh
        if top < int(0.08 * H):
            continue
        left = int(RNG.uniform(0.02 * W, max(0.03 * W, W - bw - 0.02 * W)))
        box = (left, top, left + bw, bottom)
        if any(iou(box, prev[0]) > 0.15 for prev in placed):
            continue
        canvas[top:bottom, left:left + bw] = resized
        placed.append((box, cls_name))
        return f"{CLASSES.index(cls_name)} {(left + bw / 2) / W:.6f} {(top + bh / 2) / H:.6f} {bw / W:.6f} {bh / H:.6f}"
    return None


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    by_part = {part: load_split(part) for part in ("train", "val")}
    for part, items in by_part.items():
        print(part, "images", len(items), "labeled", sum(1 for it in items if it["labels"]))

    bins = defaultdict(Counter)
    per_image = []
    for part, items in by_part.items():
        (OUT / "images" / part).mkdir(parents=True)
        (OUT / "labels" / part).mkdir(parents=True)
        made = 0
        labeled = [it for it in items if it["labels"]]
        RNG.shuffle(labeled)
        for it in labeled:
            img = cv2.imread(str(it["path"]))
            if img is None:
                continue
            pulled = pull_back(img, it["labels"])
            if pulled is None:
                continue
            canvas, lines = pulled
            name = f"scale_{part}_{made:04d}.jpg"
            cv2.imwrite(str(OUT / "images" / part / name), canvas, [cv2.IMWRITE_JPEG_QUALITY, 90])
            (OUT / "labels" / part / f"scale_{part}_{made:04d}.txt").write_text("\n".join(lines) + "\n")
            for line in lines:
                p = line.split()
                area = float(p[3]) * float(p[4])
                bins[CLASSES[int(p[0])]][bin_of(area)] += 1
            per_image.append(len(lines))
            made += 1
        print("wrote", part, made)

    # copy originals beside synthetic, same split
    for part in ("train", "val"):
        for img in (SRC / "images" / part).iterdir():
            shutil.copy(img, OUT / "images" / part / img.name)
            lab = SRC / "labels" / part / (img.stem + ".txt")
            dest = OUT / "labels" / part / (img.stem + ".txt")
            if lab.exists():
                shutil.copy(lab, dest)
            else:
                dest.write_text("")
            for cls_i, _cx, _cy, w, h in read_labels(lab):
                bins[CLASSES[cls_i]][bin_of(w * h)] += 1

    names = "\n".join(f"  {i}: {n}" for i, n in enumerate(CLASSES))
    (OUT / "data.yaml").write_text(
        f"path: {OUT}\ntrain: images/train\nval: images/val\nnames:\n{names}\n"
    )
    order = [name for _lo, _hi, name in BINS]
    summary = {
        "house6_used": False,
        "canvas": CANVAS,
        "objects_per_synthetic_image_mean": round(sum(per_image) / max(1, len(per_image)), 2),
        "bins": {cls: {k: bins[cls][k] for k in order} for cls in CLASSES},
        "selection_rule": "best.pt by Ultralytics fitness on val = original generic val + synthetic small-site val from val sources only",
    }
    (ROOT / "scale_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(json.dumps(summary["bins"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
