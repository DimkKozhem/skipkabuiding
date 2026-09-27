#!/usr/bin/env python3
"""MOCS metrics v2: size-bin eval with COCO-style ignore (no pycocotools).

Policy (relative_area bins; NOT coco_abs_*):
- Target GT = equipment boxes in the size bin.
- Ignore GT = equipment boxes outside the bin (same image).
- Pred matched to target (IoU≥0.5, 1-1) → TP.
- Pred matched to ignore (IoU≥0.5; ignore may absorb many) → not TP, not FP.
- Pred matched to neither → FP.
- Unmatched target GT → FN.

Class-agnostic: box IoU only; skip preds labeled Worker/Other vehicle/Hanging head.
Class-aware: pred.class must equal GT.class for TP; wrong type ≠ TP of that class.

Legacy by_relative_area (all preds vs size-filtered GT, cross-bin → FP) is
legacy_size_fp_inflation — do not use for «better on small» claims.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import Image

ROOT = Path("/home/dimk/my_project/LCT2026")
IOU_MATCH = 0.5
SIZE_BINS = {
    "relative_area_small": (0.0, 0.04),
    "relative_area_medium": (0.04, 0.16),
    "relative_area_large": (0.16, 1.0000001),
}
SKIP_PRED_CLASSES = {"worker", "other vehicle", "other_vehicle", "hanging head", "hanging_head", ""}
EQUIPMENT_CLASSES = [
    "bulldozer",
    "concrete_mixer",
    "crane",
    "excavator",
    "loader",
    "pile_driver",
    "pump_truck",
    "roller",
    "static_crane",
    "truck",
]


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    return inter / (area_a + area_b - inter + 1e-9)


def yolo_to_xyxy(box, w, h):
    xc, yc, bw, bh = box
    return [(xc - bw / 2) * w, (yc - bh / 2) * h, (xc + bw / 2) * w, (yc + bh / 2) * h]


def bin_of_area(area_ratio: float) -> str:
    if area_ratio < 0.04:
        return "relative_area_small"
    if area_ratio < 0.16:
        return "relative_area_medium"
    return "relative_area_large"


def is_skip_pred_class(cls: str | None) -> bool:
    if cls is None:
        return False
    return str(cls).lower().strip().replace("_", " ") in {
        "worker",
        "other vehicle",
        "hanging head",
    }


# Aliases / tokenizer debris → canonical mapped_class (class_mapping_mocs).
# Does NOT map crane↔static_crane or truck↔concrete_mixer (real confusions).
_PRED_ALIASES = {
    "pile driver": "pile_driver",
    "pile_driving": "pile_driver",
    "pile driving": "pile_driver",
    "static crane": "static_crane",
    "pump truck": "pump_truck",
    "concrete mixer": "concrete_mixer",
    "dump truck": "truck",
    "dump_truck": "truck",
}


def normalize_pred_class(raw: str | None) -> str | None:
    """Normalize pred label to equipment canonical name, or None if skip/unknown."""
    if raw is None:
        return None
    s = str(raw).strip().lower().replace("-", " ")
    s_us = s.replace(" ", "_")
    if is_skip_pred_class(s) or is_skip_pred_class(s_us):
        return None  # excluded — never TP equipment
    if s_us in EQUIPMENT_CLASSES:
        return s_us
    if s in _PRED_ALIASES:
        return _PRED_ALIASES[s]
    if s_us in _PRED_ALIASES:
        return _PRED_ALIASES[s_us]
    # Grounding DINO wordpiece debris (##dozer / ##vat …)
    compact = s.replace("##", "").replace(" ", "").replace("_", "")
    if "dozer" in compact and "vat" not in compact and "cav" not in compact:
        return "bulldozer"
    if "excavat" in compact or compact.endswith("vat") or "cavat" in compact:
        return "excavator"
    if compact in {"zer"} or compact.endswith("zer") and "excavat" not in compact:
        # "##zer" residual of bulldozer
        return "bulldozer"
    for c in EQUIPMENT_CLASSES:
        if c.replace("_", "") in compact or c in s_us:
            return c
    return s_us  # keep unknown string (will not match GT classes → FP if filtered)


def filter_equipment_preds(preds: list[dict]) -> list[dict]:
    """Drop skip-classes; attach normalized `class` for matching."""
    out = []
    for p in preds:
        norm = normalize_pred_class(p.get("class"))
        if norm is None:
            continue
        q = dict(p)
        q["class_raw"] = p.get("class")
        q["class"] = norm
        out.append(q)
    return out


def match_tp_fp_fn_ignore(
    target_gts: list[dict],
    ignore_gts: list[dict],
    preds: list[dict],
    iou_thr: float = IOU_MATCH,
    *,
    class_aware: bool = False,
) -> tuple[int, int, int, list]:
    """COCO-style ignore: match target 1-1; ignore absorbs many; else FP."""
    preds = sorted(preds, key=lambda p: -p["score"])
    used = set()
    tp = fp = 0
    pairs = []
    for p in preds:
        best_t, best_ti = 0.0, -1
        for i, g in enumerate(target_gts):
            if i in used:
                continue
            if class_aware and p.get("class") != g.get("class"):
                continue
            v = iou(p["bbox_xyxy"], g["bbox_xyxy"])
            if v > best_t:
                best_t, best_ti = v, i
        if class_aware:
            # size+class: only same-class out-of-bin boxes absorb
            best_ig = max(
                (
                    iou(p["bbox_xyxy"], g["bbox_xyxy"])
                    for g in ignore_gts
                    if p.get("class") == g.get("class")
                ),
                default=0.0,
            )
        else:
            best_ig = max(
                (iou(p["bbox_xyxy"], g["bbox_xyxy"]) for g in ignore_gts),
                default=0.0,
            )
        if best_ti >= 0 and best_t >= iou_thr:
            used.add(best_ti)
            tp += 1
            pairs.append((p, target_gts[best_ti], best_t))
        elif best_ig >= iou_thr:
            continue
        else:
            fp += 1
    fn = len(target_gts) - len(used)
    return tp, fp, fn, pairs


def ap_at_iou_ignore(
    target_by_img: dict[str, list],
    ignore_by_img: dict[str, list],
    preds_by_img: dict[str, list],
    iou_thr: float,
    *,
    class_aware: bool = False,
) -> float:
    n_gt = sum(len(v) for v in target_by_img.values())
    if n_gt == 0:
        return float("nan")
    used = {k: set() for k in target_by_img}
    flat = []
    for sid, preds in preds_by_img.items():
        for p in preds:
            flat.append((p["score"], sid, p))
    flat.sort(reverse=True)
    flags = []  # 1 TP, 0 FP; ignored omitted
    for score, sid, p in flat:
        gts = target_by_img.get(sid, [])
        best_t, best_ti = 0.0, -1
        for i, g in enumerate(gts):
            if i in used[sid]:
                continue
            if class_aware and p.get("class") != g.get("class"):
                continue
            v = iou(p["bbox_xyxy"], g["bbox_xyxy"])
            if v > best_t:
                best_t, best_ti = v, i
        ign = ignore_by_img.get(sid, [])
        if class_aware:
            best_ig = max(
                (
                    iou(p["bbox_xyxy"], g["bbox_xyxy"])
                    for g in ign
                    if p.get("class") == g.get("class")
                ),
                default=0.0,
            )
        else:
            best_ig = max((iou(p["bbox_xyxy"], g["bbox_xyxy"]) for g in ign), default=0.0)
        if best_ti >= 0 and best_t >= iou_thr:
            used[sid].add(best_ti)
            flags.append(1)
        elif best_ig >= iou_thr:
            continue
        else:
            flags.append(0)
    if not flags:
        return 0.0
    tp_cum = fp_cum = 0
    prec, rec = [], []
    for m in flags:
        if m:
            tp_cum += 1
        else:
            fp_cum += 1
        prec.append(tp_cum / (tp_cum + fp_cum))
        rec.append(tp_cum / n_gt)
    ap = 0.0
    for t in [i / 100 for i in range(101)]:
        p = max((pr for pr, rc in zip(prec, rec) if rc >= t), default=0.0)
        ap += p
    return ap / 101


def working_point(target_by_img, ignore_by_img, preds_by_img, *, class_aware=False):
    tp = fp = fn = 0
    for sid, gt in target_by_img.items():
        t, f, n, _ = match_tp_fp_fn_ignore(
            gt, ignore_by_img.get(sid, []), preds_by_img.get(sid, []), class_aware=class_aware
        )
        tp += t
        fp += f
        fn += n
    # preds on images with no target GT still count as FP unless ignored
    for sid, preds in preds_by_img.items():
        if sid in target_by_img:
            continue
        t, f, n, _ = match_tp_fp_fn_ignore(
            [], ignore_by_img.get(sid, []), preds, class_aware=class_aware
        )
        fp += f
    prec = tp / (tp + fp + 1e-9)
    rec = tp / (tp + fn + 1e-9)
    f1 = 2 * prec * rec / (prec + rec + 1e-9)
    return {
        "TP": tp,
        "FP": fp,
        "FN": fn,
        "precision": round(prec, 4),
        "recall": round(rec, 4),
        "f1": round(f1, 4),
        "n_gt": sum(len(v) for v in target_by_img.values()),
    }


def evaluate_class_agnostic(samples, preds_filtered):
    """Equipment detection; class ignored at match (skip non-equipment pred labels)."""
    gts = {s["sample_id"]: s["gt_boxes"] for s in samples}
    preds = {sid: filter_equipment_preds(preds_filtered.get(sid, [])) for sid in set(gts) | set(preds_filtered)}
    empty_ign = {sid: [] for sid in gts}
    ap50 = ap_at_iou_ignore(gts, empty_ign, preds, 0.5)
    aps = [ap_at_iou_ignore(gts, empty_ign, preds, t) for t in [x / 100 for x in range(50, 100, 5)]]
    wp = working_point(gts, empty_ign, preds)
    return {
        "label": "class_agnostic_AP50_equipment_detection",
        "note": "обнаружение машины; тип не требуется для TP; preds Worker/Other/Hanging head исключены",
        "AP50": ap50,
        "AP50_95_approx": sum(aps) / len(aps),
        "working_point_iou0.5": wp,
    }


def evaluate_by_class(samples, preds_filtered):
    """Class-aware; equal-weight macro over classes with n_gt>0."""
    by_class = {}
    ap50_list = []
    ap5095_list = []
    classes_without_gt = []
    for cls in EQUIPMENT_CLASSES:
        gts_c = {
            s["sample_id"]: [b for b in s["gt_boxes"] if b["class"] == cls] for s in samples
        }
        gts_c = {k: v for k, v in gts_c.items() if v}
        n_gt = sum(len(v) for v in gts_c.values())
        if n_gt == 0:
            classes_without_gt.append(cls)
            continue
        preds_c = {
            sid: [p for p in filter_equipment_preds(preds_filtered.get(sid, [])) if p.get("class") == cls]
            for sid in set(gts_c) | set(preds_filtered)
        }
        empty = {sid: [] for sid in gts_c}
        for sid in preds_c:
            empty.setdefault(sid, [])
        ap50 = ap_at_iou_ignore(gts_c, empty, preds_c, 0.5, class_aware=True)
        aps = [
            ap_at_iou_ignore(gts_c, empty, preds_c, t, class_aware=True)
            for t in [x / 100 for x in range(50, 100, 5)]
        ]
        ap5095 = sum(aps) / len(aps)
        wp = working_point(gts_c, {sid: [] for sid in preds_c}, preds_c, class_aware=True)
        by_class[cls] = {
            "n_gt": n_gt,
            "AP50": ap50,
            "AP50_95_approx": ap5095,
            "working_point_iou0.5": wp,
        }
        ap50_list.append(ap50)
        ap5095_list.append(ap5095)
    macro50 = sum(ap50_list) / len(ap50_list) if ap50_list else float("nan")
    macro5095 = sum(ap5095_list) / len(ap5095_list) if ap5095_list else float("nan")
    return {
        "macro_note": "equal weight per class with n_gt>0 only",
        "n_classes_in_macro": len(ap50_list),
        "classes_without_gt": classes_without_gt,
        "macro_AP50": macro50,
        "macro_AP50_95_approx": macro5095,
        "by_class": by_class,
    }


def geometric_type_confusion(samples, preds_filtered, iou_thr: float = IOU_MATCH) -> dict:
    """Match by box only; then compare GT class vs normalized pred class.

    Misses (GT unmatched) and orphans (pred unmatched) are separate — not in matrix.
    """
    from collections import Counter

    matrix = Counter()  # (gt, pred) among geometric matches
    n_correct = n_wrong = n_miss = n_orphan = 0
    n_gt = 0
    for s in samples:
        sid = s["sample_id"]
        gts = s["gt_boxes"]
        n_gt += len(gts)
        ps = sorted(filter_equipment_preds(preds_filtered.get(sid, [])), key=lambda p: -p["score"])
        used = set()
        used_p = set()
        for j, p in enumerate(ps):
            best_i, best = -1, 0.0
            for i, g in enumerate(gts):
                if i in used:
                    continue
                v = iou(p["bbox_xyxy"], g["bbox_xyxy"])
                if v > best:
                    best, best_i = v, i
            if best_i >= 0 and best >= iou_thr:
                used.add(best_i)
                used_p.add(j)
                gc = gts[best_i]["class"]
                pc = p.get("class")
                matrix[(gc, pc)] += 1
                if pc == gc:
                    n_correct += 1
                else:
                    n_wrong += 1
            else:
                n_orphan += 1
        n_miss += len(gts) - len(used)
    n_match = n_correct + n_wrong
    mat = {
        "rows_gt": EQUIPMENT_CLASSES,
        "cols_pred": EQUIPMENT_CLASSES,
        "counts": {f"{a}->{b}": n for (a, b), n in sorted(matrix.items(), key=lambda x: -x[1])},
        "grid": {
            gc: {pc: matrix.get((gc, pc), 0) for pc in EQUIPMENT_CLASSES} for gc in EQUIPMENT_CLASSES
        },
    }
    return {
        "n_gt": n_gt,
        "n_geometric_matches": n_match,
        "n_correct_type": n_correct,
        "n_wrong_type": n_wrong,
        "fraction_correct_among_matches": n_correct / n_match if n_match else float("nan"),
        "fraction_wrong_among_matches": n_wrong / n_match if n_match else float("nan"),
        "n_gt_miss_no_geom_match": n_miss,
        "n_pred_orphan_no_geom_match": n_orphan,
        "matrix": mat,
        "top_confusions_gt_to_pred": [
            {"gt": a, "pred": b, "n": n} for (a, b), n in matrix.most_common(15) if a != b
        ],
    }


def paired_bootstrap_delta_ap(
    samples,
    preds_a: dict,
    preds_b: dict,
    *,
    n_boot: int = 1000,
    seed: int = 20260927,
    mode: str = "class_agnostic",
) -> dict:
    """Paired bootstrap of AP(A)−AP(B) resampling the same episode set."""
    by_ep = defaultdict(list)
    for s in samples:
        by_ep[s.get("episode_block", s["sample_id"])].append(s)
    ep_ids = list(by_ep.keys())
    rng = random.Random(seed)

    def ap_for(sub_samples, preds):
        if mode == "class_agnostic":
            return evaluate_class_agnostic(sub_samples, preds)["AP50"]
        if mode == "macro":
            return evaluate_by_class(sub_samples, preds)["macro_AP50"]
        raise ValueError(mode)

    point = ap_for(samples, preds_a) - ap_for(samples, preds_b)
    deltas = []
    for _ in range(n_boot):
        drawn = [rng.choice(ep_ids) for _ in ep_ids]
        boot_s = []
        pa, pb = {}, {}
        for i, eid in enumerate(drawn):
            for s in by_ep[eid]:
                nid = f"{s['sample_id']}__b{i}"
                boot_s.append({**s, "sample_id": nid})
                pa[nid] = preds_a.get(s["sample_id"], [])
                pb[nid] = preds_b.get(s["sample_id"], [])
        d = ap_for(boot_s, pa) - ap_for(boot_s, pb)
        if not math.isnan(d):
            deltas.append(d)
    deltas.sort()
    if not deltas:
        return {"n_episodes": len(ep_ids), "point": point, "ci95": None, "frac_delta_gt_0": None}
    lo = deltas[int(0.025 * len(deltas))]
    hi = deltas[min(len(deltas) - 1, int(0.975 * len(deltas)))]
    return {
        "n_episodes": len(ep_ids),
        "n_boot": n_boot,
        "unit": "episode_block paired",
        "mode": mode,
        "point_delta_AP50": point,
        "mean_boot_delta": sum(deltas) / len(deltas),
        "ci95_delta": [lo, hi],
        "frac_bootstrap_delta_gt_0": sum(1 for d in deltas if d > 0) / len(deltas),
        "note": "paired; not marginal CI overlap test",
    }


def evaluate_by_relative_area_ignore(samples, preds_filtered):
    """Size bins with ignore outside-bin equipment GT."""
    out = {}
    for bin_name in SIZE_BINS:
        target = {}
        ignore = {}
        for s in samples:
            sid = s["sample_id"]
            t = [b for b in s["gt_boxes"] if b["relative_area_bin"] == bin_name]
            ig = [b for b in s["gt_boxes"] if b["relative_area_bin"] != bin_name]
            if t:
                target[sid] = t
            if ig:
                ignore[sid] = ig
            elif sid in target:
                ignore.setdefault(sid, [])
        # ensure ignore key for every target image
        for sid in target:
            ignore.setdefault(sid, [])
        preds = {
            sid: filter_equipment_preds(preds_filtered.get(sid, []))
            for sid in set(target) | set(preds_filtered) | set(ignore)
        }
        for sid in preds:
            ignore.setdefault(sid, [])
            # for images with only ignore GT (no target), still need ignore for FP suppression
            if sid not in target and sid not in ignore:
                ignore[sid] = []
        # also: images with only ignore boxes should suppress FP
        for s in samples:
            sid = s["sample_id"]
            if sid in target:
                continue
            ig = [b for b in s["gt_boxes"] if b["relative_area_bin"] != bin_name]
            # all boxes are "other" relative to empty target
            if s["gt_boxes"]:
                ignore[sid] = s["gt_boxes"]
        ap50 = ap_at_iou_ignore(target, ignore, preds, 0.5) if target else float("nan")
        wp = working_point(target, ignore, preds)
        out[bin_name] = {
            "n_gt": sum(len(v) for v in target.values()),
            "n_images_with_target": len(target),
            "AP50": ap50,
            "working_point_iou0.5": wp,
            "policy": "ignore_out_of_bin_equipment_gt",
        }
    return out


def load_samples_from_manifest(manifest_path: Path, splits: set[str]) -> list[dict]:
    man = json.loads(manifest_path.read_text())
    samples = []
    for s in man["samples"]:
        if s.get("diag_split") not in splits:
            continue
        img = ROOT / s["image"] if not Path(s["image"]).is_absolute() else Path(s["image"])
        im = Image.open(img)
        w, h = im.size
        boxes = []
        for b in s["boxes"]:
            if not b.get("in_equipment_eval"):
                continue
            boxes.append(
                {
                    "bbox_xyxy": yolo_to_xyxy(b["bbox_yolo_norm"], w, h),
                    "class": b["mapped_class"],
                    "area_ratio": b["area_ratio"],
                    "relative_area_bin": b["relative_area_bin"],
                }
            )
        samples.append(
            {
                **s,
                "image_path": str(img),
                "width": w,
                "height": h,
                "gt_boxes": boxes,
            }
        )
    return samples


def evaluate_model(samples, preds_filtered, meta: dict) -> dict:
    return {
        **meta,
        "class_agnostic": evaluate_class_agnostic(samples, preds_filtered),
        "by_class": evaluate_by_class(samples, preds_filtered),
        "by_relative_area_ignore": evaluate_by_relative_area_ignore(samples, preds_filtered),
    }


def bootstrap_ap_by_episode(samples, preds_filtered, n_boot: int = 1000, seed: int = 20260927):
    """Bootstrap class-agnostic AP50 resampling episodes (not boxes)."""
    by_ep = defaultdict(list)
    for s in samples:
        by_ep[s.get("episode_block", s["sample_id"])].append(s)
    ep_ids = list(by_ep.keys())
    if len(ep_ids) < 3:
        return {
            "n_episodes": len(ep_ids),
            "note": "слишком мало эпизодов для устойчивого интервала",
            "mean": None,
            "ci95": None,
        }
    rng = random.Random(seed)
    scores = []
    for _ in range(n_boot):
        drawn = [rng.choice(ep_ids) for _ in ep_ids]
        boot_samples = []
        for eid in drawn:
            boot_samples.extend(by_ep[eid])
        # re-key sample_ids to allow duplicates from same episode
        remapped = []
        preds_b = {}
        for i, s in enumerate(boot_samples):
            nid = f"{s['sample_id']}__b{i}"
            remapped.append({**s, "sample_id": nid})
            preds_b[nid] = preds_filtered.get(s["sample_id"], [])
        ap = evaluate_class_agnostic(remapped, preds_b)["AP50"]
        if not math.isnan(ap):
            scores.append(ap)
    scores.sort()
    if not scores:
        return {"n_episodes": len(ep_ids), "mean": None, "ci95": None}
    lo = scores[int(0.025 * len(scores))]
    hi = scores[min(len(scores) - 1, int(0.975 * len(scores)))]
    return {
        "n_episodes": len(ep_ids),
        "n_boot": n_boot,
        "unit": "episode_block (stem//20)",
        "mean_AP50": sum(scores) / len(scores),
        "ci95": [lo, hi],
        "point_AP50": evaluate_class_agnostic(samples, preds_filtered)["AP50"],
    }
