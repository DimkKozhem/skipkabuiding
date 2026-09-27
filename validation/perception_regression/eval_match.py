#!/usr/bin/env python3
"""Match equipment predictions to house6_earthworks GT. Experiment-only helper."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def iou(a: list[float], b: list[float]) -> float:
    x1 = max(a[0], b[0])
    y1 = max(a[1], b[1])
    x2 = min(a[2], b[2])
    y2 = min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / (aa + bb - inter) if (aa + bb - inter) > 0 else 0.0


def center(box: list[float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)


def in_zone(box: list[float], zone: list[float]) -> bool:
    cx, cy = center(box)
    return zone[0] <= cx <= zone[2] and zone[1] <= cy <= zone[3]


def bbox_list(item: dict[str, Any]) -> list[float] | None:
    if "xyxy" in item:
        return [float(x) for x in item["xyxy"]]
    bb = item.get("bbox")
    if isinstance(bb, dict):
        return [float(bb["x1"]), float(bb["y1"]), float(bb["x2"]), float(bb["y2"])]
    return None


def load_gt(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def match_frame(
    *,
    gt_objects: list[dict[str, Any]],
    exclude_zones: list[dict[str, Any]],
    preds: list[dict[str, Any]],
    iou_thr: float,
) -> dict[str, Any]:
    confirmed = [o for o in gt_objects if o.get("status") == "confirmed"]
    ambiguous = [o for o in gt_objects if o.get("status") == "ambiguous"]
    zones = [z["xyxy"] for z in exclude_zones]

    pred_boxes: list[tuple[str, list[float], float, dict]] = []
    for p in preds:
        box = bbox_list(p)
        if box is None:
            continue
        label = str(p.get("normalized_label") or p.get("class") or p.get("class_name") or "")
        score = float(p.get("score") or p.get("confidence") or 0.0)
        pred_boxes.append((label, box, score, p))

    used_pred: set[int] = set()
    tp: list[dict] = []
    fn: list[dict] = []
    for gt in confirmed:
        gbox = bbox_list(gt)
        assert gbox is not None
        best_i = -1
        best_iou = 0.0
        for i, (label, box, score, _raw) in enumerate(pred_boxes):
            if i in used_pred:
                continue
            if label != gt["class"]:
                continue
            val = iou(gbox, box)
            if val >= iou_thr and val > best_iou:
                best_iou = val
                best_i = i
        if best_i >= 0:
            used_pred.add(best_i)
            tp.append({"gt_id": gt["id"], "class": gt["class"], "iou": round(best_iou, 3)})
        else:
            fn.append({"gt_id": gt["id"], "class": gt["class"], "xyxy": gbox})

    fp: list[dict] = []
    ignored: list[dict] = []
    for i, (label, box, score, _raw) in enumerate(pred_boxes):
        if i in used_pred:
            continue
        if any(in_zone(box, z) for z in zones):
            ignored.append({"reason": "exclude_zone", "class": label, "xyxy": box, "score": score})
            continue
        hit_amb = False
        for amb in ambiguous:
            abox = bbox_list(amb)
            if abox is None:
                continue
            cands = set(amb.get("candidates") or [amb.get("class")])
            if iou(abox, box) >= iou_thr and (label in cands or amb.get("class") == "other"):
                ignored.append({"reason": "ambiguous_gt", "class": label, "xyxy": box, "score": score})
                hit_amb = True
                break
        if hit_amb:
            continue
        fp.append({"class": label, "xyxy": box, "score": score})

    per: dict[str, dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for row in tp:
        per[row["class"]]["tp"] += 1
    for row in fp:
        per[row["class"]]["fp"] += 1
    for row in fn:
        per[row["class"]]["fn"] += 1

    return {
        "tp": len(tp),
        "fp": len(fp),
        "fn": len(fn),
        "per_class": dict(per),
        "tp_rows": tp,
        "fp_rows": fp,
        "fn_rows": fn,
        "ignored": ignored,
        "n_pred": len(pred_boxes),
        "n_confirmed_gt": len(confirmed),
    }


def count_error(gt_objects: list[dict], pred_counts: dict[str, int]) -> dict[str, Any]:
    expected: dict[str, int] = defaultdict(int)
    for o in gt_objects:
        if o.get("status") == "confirmed":
            expected[str(o["class"])] += 1
    classes = sorted(set(expected) | set(pred_counts))
    rows = {}
    abs_err = 0
    for cls in classes:
        exp = expected.get(cls, 0)
        got = int(pred_counts.get(cls, 0))
        err = got - exp
        abs_err += abs(err)
        rows[cls] = {"expected": exp, "predicted": got, "error": err}
    return {"per_class": rows, "abs_count_error": abs_err}


def evaluate_predictions(
    gt_path: Path,
    predictions: dict[str, list[dict[str, Any]]],
    *,
    fusion_counts: dict[str, dict[str, int]] | None = None,
    iou_thr: float = 0.3,
) -> dict[str, Any]:
    gt = load_gt(gt_path)
    iou_thr = float((gt.get("matching") or {}).get("iou_threshold") or iou_thr)
    frames_out = []
    tot = {"tp": 0, "fp": 0, "fn": 0}
    per = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    for frame in gt["frames"]:
        day = frame["day"]
        preds = predictions.get(day) or predictions.get(frame["id"]) or []
        m = match_frame(
            gt_objects=frame["objects"],
            exclude_zones=frame.get("exclude_zones") or [],
            preds=preds,
            iou_thr=iou_thr,
        )
        for k in ("tp", "fp", "fn"):
            tot[k] += m[k]
        for cls, stats in m["per_class"].items():
            for k, v in stats.items():
                per[cls][k] += v
        fc = (fusion_counts or {}).get(day) or {}
        m["count_vs_gt"] = count_error(frame["objects"], fc)
        m["day"] = day
        frames_out.append(m)
    precision = tot["tp"] / (tot["tp"] + tot["fp"]) if (tot["tp"] + tot["fp"]) else 0.0
    recall = tot["tp"] / (tot["tp"] + tot["fn"]) if (tot["tp"] + tot["fn"]) else 0.0
    return {
        "gt": str(gt_path),
        "authorship": gt.get("authorship"),
        "iou_threshold": iou_thr,
        "totals": {**tot, "precision": round(precision, 4), "recall": round(recall, 4)},
        "per_class": dict(per),
        "frames": frames_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gt", default="validation/perception_regression/gt/house6_earthworks.json")
    parser.add_argument("--preds", required=True, help="JSON {day: [detections...]}")
    parser.add_argument("--fusion-counts", default=None)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    preds = json.loads(Path(args.preds).read_text(encoding="utf-8"))
    fusion = None
    if args.fusion_counts:
        fusion = json.loads(Path(args.fusion_counts).read_text(encoding="utf-8"))
    report = evaluate_predictions(Path(args.gt), preds, fusion_counts=fusion)
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
