"""Тест ignore-политики размерных групп (legacy FP-inflation не допускается)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
import mocs_eval_v2 as ev  # noqa: E402


def test_correct_large_detection_does_not_fp_small_bin():
    """Кадр: малая + крупная. Pred только на крупную → small: FP=0, FN=1 (пропуск малой)."""
    small = {
        "bbox_xyxy": [10.0, 10.0, 30.0, 30.0],
        "class": "excavator",
        "relative_area_bin": "relative_area_small",
        "area_ratio": 0.01,
    }
    large = {
        "bbox_xyxy": [100.0, 100.0, 400.0, 400.0],
        "class": "truck",
        "relative_area_bin": "relative_area_large",
        "area_ratio": 0.25,
    }
    pred_large = {
        "bbox_xyxy": [105.0, 105.0, 395.0, 395.0],
        "score": 0.9,
        "class": "truck",
    }
    samples = [
        {
            "sample_id": "frame0",
            "episode_block": 0,
            "gt_boxes": [small, large],
        }
    ]
    preds = {"frame0": [pred_large]}
    by_size = ev.evaluate_by_relative_area_ignore(samples, preds)
    small_m = by_size["relative_area_small"]
    assert small_m["n_gt"] == 1
    wp = small_m["working_point_iou0.5"]
    assert wp["FP"] == 0, f"large TP must not become small FP; got {wp}"
    assert wp["FN"] == 1, f"missed small must be FN; got {wp}"
    assert wp["TP"] == 0
    # large bin: the pred is TP
    large_m = by_size["relative_area_large"]
    assert large_m["working_point_iou0.5"]["TP"] == 1
    assert large_m["working_point_iou0.5"]["FN"] == 0


def test_unmatched_pred_still_fp_in_small():
    """Pred без IoU ни с small, ни с ignore → FP в small."""
    small = {
        "bbox_xyxy": [10.0, 10.0, 30.0, 30.0],
        "class": "excavator",
        "relative_area_bin": "relative_area_small",
        "area_ratio": 0.01,
    }
    large = {
        "bbox_xyxy": [100.0, 100.0, 400.0, 400.0],
        "class": "truck",
        "relative_area_bin": "relative_area_large",
        "area_ratio": 0.25,
    }
    stray = {"bbox_xyxy": [500.0, 500.0, 520.0, 520.0], "score": 0.8, "class": "crane"}
    samples = [{"sample_id": "frame0", "episode_block": 0, "gt_boxes": [small, large]}]
    preds = {"frame0": [stray]}
    wp = ev.evaluate_by_relative_area_ignore(samples, preds)["relative_area_small"]["working_point_iou0.5"]
    assert wp["FP"] == 1
    assert wp["FN"] == 1


def test_class_aware_correct_type_is_tp():
    """Геометрический TP + верный класс → TP класса excavator."""
    gt = {
        "bbox_xyxy": [10.0, 10.0, 100.0, 100.0],
        "class": "excavator",
        "relative_area_bin": "relative_area_medium",
        "area_ratio": 0.08,
    }
    pred = {"bbox_xyxy": [12.0, 12.0, 98.0, 98.0], "score": 0.9, "class": "excavator"}
    samples = [{"sample_id": "f0", "episode_block": 0, "gt_boxes": [gt]}]
    bc = ev.evaluate_by_class(samples, {"f0": [pred]})
    wp = bc["by_class"]["excavator"]["working_point_iou0.5"]
    assert wp["TP"] == 1 and wp["FN"] == 0 and wp["FP"] == 0


def test_class_aware_wrong_type_not_tp():
    """Геометрический TP + чужой класс → не TP excavator (FN), FP truck."""
    gt = {
        "bbox_xyxy": [10.0, 10.0, 100.0, 100.0],
        "class": "excavator",
        "relative_area_bin": "relative_area_medium",
        "area_ratio": 0.08,
    }
    pred = {"bbox_xyxy": [12.0, 12.0, 98.0, 98.0], "score": 0.9, "class": "truck"}
    samples = [{"sample_id": "f0", "episode_block": 0, "gt_boxes": [gt]}]
    preds = {"f0": [pred]}
    bc = ev.evaluate_by_class(samples, preds)
    wp_ex = bc["by_class"]["excavator"]["working_point_iou0.5"]
    assert wp_ex["TP"] == 0 and wp_ex["FN"] == 1
    # truck has n_gt=0 → in classes_without_gt; FP of truck on images without truck GT
    # evaluate truck slice manually
    gts_t = {}
    preds_t = {"f0": [p for p in ev.filter_equipment_preds(preds["f0"]) if p["class"] == "truck"]}
    wp_tr = ev.working_point(gts_t, {"f0": []}, preds_t, class_aware=True)
    assert wp_tr["FP"] == 1


def test_dino_token_debris_normalized():
    assert ev.normalize_pred_class("##dozer") == "bulldozer"
    assert ev.normalize_pred_class("pile driver") == "pile_driver"
    assert ev.normalize_pred_class("Worker") is None
    assert ev.normalize_pred_class("excavator") == "excavator"


def test_yoloe_prompt_index_names_are_canonical():
    """Lock prompts order maps index→name; names are GT mapped_class strings (no id swap)."""
    prompts = ev.EQUIPMENT_CLASSES  # same sorted list as lock
    assert prompts[3] == "excavator"
    assert prompts[9] == "truck"
    assert "static_crane" in prompts and "crane" in prompts


if __name__ == "__main__":
    test_correct_large_detection_does_not_fp_small_bin()
    test_unmatched_pred_still_fp_in_small()
    test_class_aware_correct_type_is_tp()
    test_class_aware_wrong_type_not_tp()
    test_dino_token_debris_normalized()
    test_yoloe_prompt_index_names_are_canonical()
    print("OK")
