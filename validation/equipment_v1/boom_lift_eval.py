"""Closed-holdout evaluation. Does not recompute an existing prediction file.

TP requires the same class and IoU >= 0.3. NMS iou 0.5, conf 0.25, imgsz 640.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
OUT = ROOT / "validation/equipment_v1"
MANIFEST = OUT / "boom_lift_manifest.jsonl"
BINS = ("<0.2%", "0.2–0.5%", "0.5–1%", "1–2%", ">2%")


def iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / (aa + bb - inter)


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


def load_split(split: str) -> list[dict]:
    rows = [json.loads(line) for line in MANIFEST.read_text().splitlines() if line.strip()]
    return [r for r in rows if r["split"] == split]


def predict(weights: Path, images: list[Path]) -> dict[str, list[dict]]:
    from ultralytics import YOLO

    model = YOLO(str(weights))
    names = model.names
    out: dict[str, list[dict]] = {str(p): [] for p in images}
    results = model.predict(
        [str(p) for p in images],
        imgsz=640,
        conf=0.25,
        iou=0.5,
        device=0,
        verbose=False,
        stream=True,
    )
    for path, result in zip(images, results):
        boxes = []
        if result.boxes is not None and len(result.boxes):
            xyxy = result.boxes.xyxy.cpu().tolist()
            confs = result.boxes.conf.cpu().tolist()
            clss = result.boxes.cls.cpu().tolist()
            for box, conf, cls_i in zip(xyxy, confs, clss):
                boxes.append({
                    "class": names[int(cls_i)],
                    "confidence": round(float(conf), 4),
                    "bbox": [round(float(v), 1) for v in box],
                })
        out[str(path)] = boxes
    return out


def match_image(gts: list[dict], preds: list[dict]) -> tuple[list[dict], list[dict]]:
    pairs = []
    for gi, gt in enumerate(gts):
        for pi, pred in enumerate(preds):
            if pred["class"] != gt["class"]:
                continue
            score = iou(gt["bbox"], pred["bbox"])
            if score >= 0.3:
                pairs.append((score, gi, pi))
    pairs.sort(reverse=True)
    used_g, used_p = set(), set()
    matched = {}
    for score, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        matched[gi] = (pi, score)
    rows = []
    for gi, gt in enumerate(gts):
        if gi in matched:
            pi, score = matched[gi]
            pred = preds[pi]
            rows.append({
                "image": gt["path"],
                "date": gt["date"],
                "class": gt["class"],
                "bbox": gt["bbox"],
                "area_frac": gt["area_frac"],
                "prediction_class": pred["class"],
                "confidence": pred["confidence"],
                "prediction_bbox": pred["bbox"],
                "iou": round(score, 4),
                "label": "TP",
            })
        else:
            # nearest any-class pred, recorded but not a TP
            best = None
            for pred in preds:
                score = iou(gt["bbox"], pred["bbox"])
                if best is None or score > best[0]:
                    best = (score, pred)
            rows.append({
                "image": gt["path"],
                "date": gt["date"],
                "class": gt["class"],
                "bbox": gt["bbox"],
                "area_frac": gt["area_frac"],
                "prediction_class": None if best is None or best[0] < 0.3 else best[1]["class"],
                "confidence": None if best is None or best[0] < 0.3 else best[1]["confidence"],
                "prediction_bbox": None if best is None or best[0] < 0.3 else best[1]["bbox"],
                "iou": None if best is None else round(best[0], 4),
                "label": "FN",
            })
    fps = []
    for pi, pred in enumerate(preds):
        if pi in used_p:
            continue
        fps.append({
            "image": gts[0]["path"] if gts else None,
            "prediction_class": pred["class"],
            "confidence": pred["confidence"],
            "prediction_bbox": pred["bbox"],
            "label": "FP",
        })
    return rows, fps


def pr(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall}


def ap50(rows: list[dict], fps: list[dict], cls: str) -> float | None:
    pos = [r for r in rows if r["class"] == cls]
    if not pos:
        return None
    scored = []
    for r in pos:
        if r["label"] == "TP":
            scored.append((r["confidence"], 1))
    for fp in fps:
        if fp["prediction_class"] == cls:
            scored.append((fp["confidence"], 0))
    if not scored:
        return 0.0
    scored.sort(key=lambda z: z[0], reverse=True)
    tp = 0
    fp = 0
    npos = len(pos)
    points = []
    for conf, hit in scored:
        if hit:
            tp += 1
        else:
            fp += 1
        points.append((tp / (tp + fp), tp / npos))
    # 101-point interpolation
    acc = 0.0
    for i in range(101):
        recall_level = i / 100
        prec = max((p for p, r in points if r >= recall_level), default=0.0)
        acc += prec
    return acc / 101


def summarize(rows: list[dict], fps: list[dict], model: str) -> dict:
    by_class = defaultdict(lambda: {"tp": 0, "fn": 0, "fp": 0, "n": 0})
    by_bin = defaultdict(lambda: {"tp": 0, "fn": 0, "n": 0})
    for r in rows:
        slot = by_class[r["class"]]
        slot["n"] += 1
        if r["label"] == "TP":
            slot["tp"] += 1
        else:
            slot["fn"] += 1
        b = by_bin[bin_name(r["area_frac"])]
        b["n"] += 1
        if r["label"] == "TP":
            b["tp"] += 1
        else:
            b["fn"] += 1
    for fp in fps:
        by_class[fp["prediction_class"]]["fp"] += 1
    tp = sum(v["tp"] for v in by_class.values() if v["n"])
    fn = sum(v["fn"] for v in by_class.values())
    fp = sum(1 for f in fps if f["prediction_class"] == "aerial_work_platform")
    return {
        "model": model,
        "operating_point": {"conf": 0.25, "imgsz": 640, "nms_iou": 0.5, "match_iou": 0.3},
        "overall_aerial_work_platform": pr(tp, fp, fn),
        "map50_aerial_work_platform": ap50(rows, fps, "aerial_work_platform"),
        "by_class": {k: {**v, **pr(v["tp"], v["fp"], v["fn"])} for k, v in sorted(by_class.items())},
        "by_area": {k: {**by_bin[k], "recall": (by_bin[k]["tp"] / by_bin[k]["n"] if by_bin[k]["n"] else None)} for k in BINS},
        "fp_by_class": dict(sorted(
            ((k, v["fp"]) for k, v in by_class.items() if v["fp"]),
            key=lambda kv: -kv[1],
        )),
        "n_gt": len(rows),
        "n_images": len({r["image"] for r in rows} | {f["image"] for f in fps}),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--weights", required=True)
    parser.add_argument("--split", default="holdout")
    args = parser.parse_args()
    pred_path = OUT / f"boom_lift_predictions_{args.name}.jsonl"
    summary_path = OUT / f"boom_lift_metrics_{args.name}.json"
    if pred_path.exists():
        raise SystemExit(f"refusing to recompute {pred_path}")
    rows = load_split(args.split)
    by_image: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_image[str(ROOT / row["path"])].append(row)
    images = [Path(p) for p in sorted(by_image)]
    raw = predict(Path(args.weights), images)
    gt_rows = []
    fp_rows = []
    for path in images:
        gts = [r for r in by_image[str(path)] if not r["negative"]]
        preds = raw[str(path)]
        matched, fps = match_image(gts, preds)
        for fp in fps:
            fp["image"] = str(Path(path).relative_to(ROOT))
            fp["date"] = path.stem
        for row in matched:
            row["image"] = str(Path(path).relative_to(ROOT))
        gt_rows.extend(matched)
        fp_rows.extend(fps)
        # keep raw preds for the contact sheets
    payload_rows = gt_rows + fp_rows
    pred_path.write_text("".join(json.dumps(r) + "\n" for r in payload_rows))
    (OUT / f"boom_lift_rawpred_{args.name}.json").write_text(json.dumps({
        str(Path(p).relative_to(ROOT)): raw[str(p)] for p in images
    }))
    summary = summarize(gt_rows, fp_rows, args.name)
    summary["weights"] = args.weights
    summary["split"] = args.split
    summary_path.write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["overall_aerial_work_platform"], indent=2))
    print("map50", summary["map50_aerial_work_platform"])
    print("fp_by_class", summary["fp_by_class"])


if __name__ == "__main__":
    main()
