"""Центры сохранённых рамок CountGD как точки. Новый inference не делается.

Метрика — попадание центра в объект XML тем же matcher, что у MolmoPoint.
bbox IoU ≥ 0.3 этим файлом не заменяется и не пересчитывается.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path("/home/dimk/my_project/LCT2026")
sys.path.insert(0, str(ROOT / "validation/model_selection"))
from cmp_point_eval import score_points

SUB = json.loads((ROOT / "validation/model_selection/cmp_facade_subset_frozen.json").read_text())
IOU = json.loads((ROOT / "artifacts/model_selection/runs/cmp_facade_scores.json").read_text())
MOLMO = ROOT / "artifacts/model_selection/runs/molmopoint_cmp_facade"
COUNT = ROOT / "artifacts/model_selection/runs/countgd_cmp_facade/text"
IMG = ROOT / "artifacts/model_selection/external/cmp_facade/subset/base"

COMPLETE = {
    ("cmp_b0001", "window"),
    ("cmp_b0001", "door"),
    ("cmp_b0002", "door"),
}
TRUNCATED = {("cmp_b0002", "window")}


def gt_boxes(sample: dict, label: str) -> list[tuple[float, float, float, float]]:
    return [tuple(box["xyxy_norm"]) for box in sample["boxes"] if box["label"] == label]


def centers(path: Path, width: int, height: int) -> list[tuple[float, float]]:
    boxes = json.loads(path.read_text())["xyxy_px"]
    points = []
    for x0, y0, x1, y1 in boxes:
        points.append((((x0 + x1) / 2) / width, ((y0 + y1) / 2) / height))
    return points


def public(scored: dict) -> dict:
    n_pred = scored["n_pred"]
    n_gt = scored["n_gt"]
    return {
        "tp": scored["tp"],
        "fp": scored["fp"],
        "fn": scored["fn"],
        "n_pred": n_pred,
        "n_gt": n_gt,
        "precision": None if n_pred == 0 else round(scored["tp"] / n_pred, 4),
        "recall": None if n_gt == 0 else round(scored["tp"] / n_gt, 4),
        "identity_ambiguous_count": scored["identity_ambiguous_count"],
        "count_error": scored["count_error"],
    }


def main() -> None:
    iou_by_id = {row["sample_id"]: row for row in IOU["samples"]}
    per_image = []
    common = []
    availability = []
    for sample in SUB["samples"]:
        sample_id = sample["sample_id"]
        with Image.open(IMG / f"{sample_id}.jpg") as image:
            width, height = image.size
        image_row = {"sample_id": sample_id, "width": width, "height": height, "tasks": {}}
        for task in ("window", "door"):
            refs = gt_boxes(sample, task)
            count_path = COUNT / sample_id / task / "result.json"
            molmo_path = MOLMO / sample_id / task / "result.json"
            key = (sample_id, task)
            if key in COMPLETE:
                molmo_state = "complete"
            elif key in TRUNCATED:
                molmo_state = "truncated"
            elif molmo_path.exists():
                molmo_state = "present_unclassified"
            else:
                molmo_state = "not_run_oom_stopped_batch"
            slot = {
                "task": task,
                "countgd_text": "saved" if count_path.exists() else "missing",
                "molmo": molmo_state,
                "counts_as_visual_fn": False,
                "silently_excluded": False,
            }
            if count_path.exists():
                scored = score_points(centers(count_path, width, height), refs)
                slot["countgd_center_hit"] = public(scored)
                iou_key = f"countgd_text_{task}"
                slot["countgd_bbox_iou_0_3"] = iou_by_id[sample_id].get(iou_key)
            if molmo_path.exists():
                payload = json.loads(molmo_path.read_text())
                points = [(row[2] / width, row[3] / height) for row in payload["points"]]
                slot["molmo_point_hit"] = public(score_points(points, refs))
                slot["molmo_point_hit"]["hit_token_cap"] = payload["hit_token_cap"]
                slot["molmo_point_hit"]["answer_status"] = molmo_state
            availability.append({"sample_id": sample_id, **slot})
            image_row["tasks"][task] = {
                "countgd_center_hit": slot.get("countgd_center_hit"),
                "countgd_bbox_iou_0_3": slot.get("countgd_bbox_iou_0_3"),
            }
            if key in COMPLETE:
                common.append(
                    {
                        "sample_id": sample_id,
                        "task": task,
                        "pair": "complete",
                        "metric": "maximum_cardinality_point_in_object",
                        "countgd_center_hit": slot["countgd_center_hit"],
                        "molmo_point_hit": slot["molmo_point_hit"],
                        "winner": None,
                    }
                )
        per_image.append(image_row)

    def totals(task: str) -> dict:
        rows = [item for item in availability if item["task"] == task and "countgd_center_hit" in item]
        tp = sum(item["countgd_center_hit"]["tp"] for item in rows)
        fp = sum(item["countgd_center_hit"]["fp"] for item in rows)
        fn = sum(item["countgd_center_hit"]["fn"] for item in rows)
        n_pred = sum(item["countgd_center_hit"]["n_pred"] for item in rows)
        n_gt = sum(item["countgd_center_hit"]["n_gt"] for item in rows)
        ambiguous = sum(item["countgd_center_hit"]["identity_ambiguous_count"] for item in rows)
        return {
            "frames": len(rows),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "n_pred": n_pred,
            "n_gt": n_gt,
            "precision": round(tp / n_pred, 4),
            "recall": round(tp / n_gt, 4),
            "identity_ambiguous_count": ambiguous,
            "not_comparable_to_partial_molmo": True,
        }

    center_report = {
        "metric": "maximum_cardinality_point_in_object",
        "evaluator": "validation/model_selection/cmp_point_eval.py",
        "prediction": "center of each saved CountGD text-only box",
        "replaces_bbox_iou": False,
        "new_inference": False,
        "bbox_iou_record": "artifacts/model_selection/runs/cmp_facade_scores.json",
        "scope": "first eight base images, text-only. Not a comparison with MolmoPoint.",
        "windows": totals("window"),
        "doors": totals("door"),
        "per_image": per_image,
    }
    comparison = {
        "winner": None,
        "reason": "MolmoPoint has three complete answers, one truncated answer, and an OOM stop. Eight-frame CountGD totals are not compared with MolmoPoint on one frame.",
        "common_metric": "maximum_cardinality_point_in_object",
        "common_metric_note": "CountGD contributes box centers. MolmoPoint contributes decoded points. bbox IoU stays in cmp_facade_scores.json.",
        "complete_pairs_only": common,
        "truncated_not_in_complete_pairs": [
            item for item in availability if item["molmo"] == "truncated"
        ],
        "package_availability": availability,
        "planned_package": "first eight base, window and door, 16 tasks",
        "owner_tech_package": "not this comparison; not run",
    }
    out_center = ROOT / "artifacts/model_selection/runs/countgd_center_point_matching.json"
    out_cmp = ROOT / "artifacts/model_selection/runs/common_task_comparison.json"
    out_center.write_text(json.dumps(center_report, ensure_ascii=False, indent=2), encoding="utf-8")
    out_cmp.write_text(json.dumps(comparison, ensure_ascii=False, indent=2), encoding="utf-8")
    print(out_center)
    print(out_cmp)
    for row in common:
        print(row["sample_id"], row["task"], "countgd", row["countgd_center_hit"], "molmo", row["molmo_point_hit"])
    print("windows", center_report["windows"])
    print("doors", center_report["doors"])


if __name__ == "__main__":
    main()
