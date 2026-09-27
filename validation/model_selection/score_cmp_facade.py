"""Scores the first-eight base images (experiment B), not the owner tech package.

Point counts call validation/model_selection/cmp_point_eval.py, the owner
matcher. Box counts stay IoU >= 0.3. The earlier exclusive-inside point rule
is not this file; its numbers for the saved points are in
cmp_protocol_reconciliation.json. cmp_b0003 is a test id that this experiment
already opened.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
sys_path = ROOT / "validation/model_selection"
import sys

sys.path.insert(0, str(sys_path))
from cmp_point_eval import score_points as match_points
SUB = json.loads((ROOT / "validation/model_selection/cmp_facade_subset_frozen.json").read_text())
OUT = ROOT / "artifacts/model_selection/runs/cmp_facade_scores.json"


def iou(a, b):
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax1 - ax0) * max(0.0, ay1 - ay0)
    area_b = max(0.0, bx1 - bx0) * max(0.0, by1 - by0)
    return inter / (area_a + area_b - inter + 1e-9)


def gt_boxes(sample, label, exclude_first=False):
    boxes = [box["xyxy_norm"] for box in sample["boxes"] if box["label"] == label]
    if exclude_first and boxes:
        return boxes[1:]
    return boxes


def score_boxes(preds, refs):
    used = set()
    tp = 0
    for pred in preds:
        best_i, best = None, 0.0
        for i, ref in enumerate(refs):
            if i in used:
                continue
            value = iou(pred, ref)
            if value > best:
                best, best_i = value, i
        if best_i is not None and best >= 0.3:
            used.add(best_i)
            tp += 1
    return {"tp": tp, "fp": len(preds) - tp, "fn": len(refs) - tp, "n_gt": len(refs), "n_pred": len(preds)}


def score_points(points, refs, width, height):
    normalized = [(row[2] / width, row[3] / height) for row in points]
    return match_points(normalized, [tuple(box) for box in refs])


def image_size(sample_id):
    from PIL import Image

    path = ROOT / "artifacts/model_selection/external/cmp_facade/subset/base" / f"{sample_id}.jpg"
    with Image.open(path) as image:
        return image.size


def main() -> None:
    report = {"iou_threshold_for_boxes": 0.3, "point_rule": "maximum cardinality, intersections stay in the denominator", "no_bbox_ap_from_points": True, "count_error_is_separate": True, "samples": []}
    for sample in SUB["samples"]:
        width, height = image_size(sample["sample_id"])
        row = {"sample_id": sample["sample_id"]}
        for task in ("window", "door"):
            refs = gt_boxes(sample, task)
            count_path = ROOT / f"artifacts/model_selection/runs/countgd_cmp_facade/text/{sample['sample_id']}/{task}/result.json"
            molmo_path = ROOT / f"artifacts/model_selection/runs/molmopoint_cmp_facade/{sample['sample_id']}/{task}/result.json"
            if count_path.exists():
                preds = json.loads(count_path.read_text())["xyxy_px"]
                norm = [[b[0] / width, b[1] / height, b[2] / width, b[3] / height] for b in preds]
                row[f"countgd_text_{task}"] = score_boxes(norm, refs)
            visual_path = ROOT / f"artifacts/model_selection/runs/countgd_cmp_facade/visual/{sample['sample_id']}/{task}/result.json"
            if visual_path.exists():
                preds = json.loads(visual_path.read_text())["xyxy_px"]
                norm = [[b[0] / width, b[1] / height, b[2] / width, b[3] / height] for b in preds]
                row[f"countgd_visual_{task}"] = score_boxes(norm, gt_boxes(sample, task, exclude_first=True))
                row[f"countgd_visual_{task}"]["excluded_exemplar"] = True
            if molmo_path.exists():
                points = json.loads(molmo_path.read_text())["points"]
                row[f"molmo_{task}"] = score_points(points, refs, width, height)
        report["samples"].append(row)
        print(sample["sample_id"], {k: v for k, v in row.items() if k != "sample_id"}, flush=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
