#!/usr/bin/env python3
"""Evaluate house6_earthworks perception predictions against GT.

Matching rules ( documented, fixed for this experiment ):
  Detector boxes
    - Same canonical class.
    - IoU >= 0.3.
    - Greedy highest-IoU one-to-one assignment.
  Fusion-confirmed equipment counts
    - Predicted count = count_visible when fusion confirms the class
      (status in {visible, partially_visible}, confidence >= 0.55,
       notes must not indicate vlm_only or conflict).
    - Else predicted count = 0 for that class.
    - Per class: TP=min(pred,gt), FP=max(0,pred-gt), FN=max(0,gt-pred).

Does not train, does not open holdout, does not mutate production config.

Examples
--------
  .venv/bin/python validation/perception_regression/eval_equipment.py \\
    --gt validation/perception_regression/gt/house6_earthworks.json \\
    --predictions validation/perception_regression/runs \\
    --out validation/perception_regression/overlays/metrics_baseline.json

  # Build SAM3 prompt list from experiment YAML (no inference):
  .venv/bin/python validation/perception_regression/eval_equipment.py \\
    --dump-prompts validation/perception_regression/experiments/narrow_prompts_v1.yaml
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GT = ROOT / "validation/perception_regression/gt/house6_earthworks.json"
DEFAULT_OVERLAY_DIR = ROOT / "validation/perception_regression/overlays"
IOU_THRESHOLD = 0.3
CONFIRM_MIN_CONFIDENCE = 0.55
EQUIPMENT_UNDER_TEST = (
    "excavator",
    "dump_truck",
    "truck",
    "bulldozer",
    "mobile_crane",
    "tower_crane",
    "loader",
)


def iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if inter <= 0:
        return 0.0
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    bb = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    denom = aa + bb - inter
    return inter / denom if denom > 0 else 0.0


def _as_xyxy(bbox: Any) -> list[float] | None:
    if bbox is None:
        return None
    if isinstance(bbox, dict):
        keys = ("x1", "y1", "x2", "y2")
        if all(k in bbox for k in keys):
            return [float(bbox[k]) for k in keys]
        return None
    if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        return [float(x) for x in bbox]
    return None


def load_gt(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "frames" not in data:
        raise ValueError(f"GT missing frames: {path}")
    return data


def resolve_image(gt_path: Path, frame: dict[str, Any]) -> Path | None:
    raw = frame.get("image")
    if not raw:
        return None
    p = Path(str(raw))
    if not p.is_absolute():
        p = (gt_path.parent / p).resolve()
    return p if p.is_file() else p


def find_frame_pred_dir(predictions_dir: Path, frame: dict[str, Any]) -> Path | None:
    """Locate per-frame prediction folder under predictions_dir.

    Accepts layouts:
      predictions/2026-01-02/{detections,observed_state}.json
      predictions/house6_2026-01-02/...
      predictions/<date>/...
    """
    candidates = [
        frame.get("date"),
        frame.get("id"),
        str(frame.get("date") or ""),
    ]
    for key in candidates:
        if not key:
            continue
        for name in (str(key), str(key).replace("house6_", "")):
            d = predictions_dir / name
            if d.is_dir():
                return d
    # flat files: detections_<date>.json
    date = frame.get("date")
    if date:
        flat = predictions_dir / f"detections_{date}.json"
        if flat.is_file():
            return predictions_dir
    return None


def load_detector_boxes(pred_dir: Path, frame: dict[str, Any]) -> list[dict[str, Any]]:
    date = frame.get("date")
    paths = [
        pred_dir / "detections.json",
        pred_dir / f"detections_{date}.json" if date else None,
    ]
    for path in paths:
        if path is None or not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        items = raw if isinstance(raw, list) else list(raw.get("detections") or raw.get("evidence") or [])
        boxes: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or item.get("metadata", {}).get("provider") or "")
            # Prefer SAM3 / detector boxes; skip VLM text-only evidence.
            if source in {"qwen_vl", "qwen"}:
                continue
            xyxy = _as_xyxy(item.get("bbox"))
            if xyxy is None:
                continue
            cls = str(
                item.get("normalized_label")
                or item.get("class_name")
                or item.get("class")
                or ""
            ).strip()
            if not cls:
                continue
            boxes.append(
                {
                    "class": cls,
                    "bbox": xyxy,
                    "score": float(item.get("score") or 0.0),
                    "source": source,
                }
            )
        return boxes
    return []


def _fusion_confirms(obs: dict[str, Any], *, min_conf: float = CONFIRM_MIN_CONFIDENCE) -> bool:
    status = str(obs.get("status") or "").lower()
    if status not in {"visible", "partially_visible"}:
        return False
    notes = [str(n) for n in (obs.get("notes") or [])]
    for note in notes:
        if note.startswith("agreement:vlm_only") or note.startswith("agreement:conflict"):
            return False
        if note == "vlm_only":
            return False
    conf = float(obs.get("confidence") or 0.0)
    return conf >= min_conf


def load_fusion_counts(pred_dir: Path, frame: dict[str, Any], classes: list[str]) -> dict[str, int]:
    date = frame.get("date")
    paths = [
        pred_dir / "observed_state.json",
        pred_dir / f"observed_state_{date}.json" if date else None,
    ]
    equipment: dict[str, Any] = {}
    for path in paths:
        if path is None or not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        equipment = dict(raw.get("equipment") or {})
        break

    out: dict[str, int] = {c: 0 for c in classes}
    for cls in classes:
        obs = equipment.get(cls)
        if not isinstance(obs, dict):
            continue
        if not _fusion_confirms(obs):
            continue
        count = obs.get("count_visible")
        if count is None:
            count = obs.get("value")
        if isinstance(count, (int, float)) and count is not None:
            out[cls] = max(0, int(count))
    return out


def match_boxes(
    gts: list[dict[str, Any]],
    preds: list[dict[str, Any]],
    *,
    iou_thr: float = IOU_THRESHOLD,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (tps, fps, fns) with match metadata."""
    pairs: list[tuple[float, int, int]] = []
    for gi, gt in enumerate(gts):
        gbox = _as_xyxy(gt.get("bbox"))
        if gbox is None:
            continue
        gcls = str(gt.get("class") or "")
        for pi, pred in enumerate(preds):
            if pred["class"] != gcls:
                continue
            score = iou(gbox, pred["bbox"])
            if score >= iou_thr:
                pairs.append((score, gi, pi))
    pairs.sort(reverse=True)
    used_g: set[int] = set()
    used_p: set[int] = set()
    tps: list[dict[str, Any]] = []
    for score, gi, pi in pairs:
        if gi in used_g or pi in used_p:
            continue
        used_g.add(gi)
        used_p.add(pi)
        gt = gts[gi]
        pred = preds[pi]
        tps.append(
            {
                "class": gt["class"],
                "gt_bbox": _as_xyxy(gt["bbox"]),
                "pred_bbox": pred["bbox"],
                "iou": round(score, 4),
                "score": pred.get("score"),
                "label": "TP",
            }
        )
    fns = []
    for gi, gt in enumerate(gts):
        if gi in used_g:
            continue
        fns.append(
            {
                "class": gt.get("class"),
                "gt_bbox": _as_xyxy(gt.get("bbox")),
                "label": "FN",
            }
        )
    fps = []
    for pi, pred in enumerate(preds):
        if pi in used_p:
            continue
        fps.append(
            {
                "class": pred["class"],
                "pred_bbox": pred["bbox"],
                "score": pred.get("score"),
                "label": "FP",
            }
        )
    return tps, fps, fns


def count_confusion(pred: int, gt: int) -> tuple[int, int, int]:
    tp = min(pred, gt)
    fp = max(0, pred - gt)
    fn = max(0, gt - pred)
    return tp, fp, fn


def _empty_class_stats(classes: list[str]) -> dict[str, dict[str, int]]:
    return {c: {"tp": 0, "fp": 0, "fn": 0} for c in classes}


def draw_overlays(
    image_path: Path,
    out_path: Path,
    *,
    tps: list[dict[str, Any]],
    fps: list[dict[str, Any]],
    fns: list[dict[str, Any]],
) -> bool:
    try:
        import cv2
    except ImportError:
        return False
    if not image_path.is_file():
        return False
    img = cv2.imread(str(image_path))
    if img is None:
        return False

    def _draw(box: list[float] | None, color: tuple[int, int, int], tag: str) -> None:
        if box is None:
            return
        x1, y1, x2, y2 = [int(round(v)) for v in box]
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, tag, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    for row in tps:
        _draw(row.get("pred_bbox"), (40, 180, 40), f"TP {row.get('class')}")
    for row in fps:
        _draw(row.get("pred_bbox"), (40, 40, 220), f"FP {row.get('class')}")
    for row in fns:
        _draw(row.get("gt_bbox"), (0, 165, 255), f"FN {row.get('class')}")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)
    return True


def load_experiment_prompts(path: Path) -> dict[str, str]:
    """Load equipment_prompts map from narrow_prompts YAML/JSON (no PyYAML required for JSON)."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise SystemExit("PyYAML required to read .yaml experiment files") from exc
        data = yaml.safe_load(text)
    # Prefer explicit equipment map; `classes` may be a dict alias or an unrelated list.
    candidates = [
        data.get("equipment_prompts"),
        data.get("classes") if isinstance(data.get("classes"), dict) else None,
        data.get("baseline_prompts"),
    ]
    prompts: dict[str, Any] = next((c for c in candidates if isinstance(c, dict) and c), {})
    return {str(k): str(v) for k, v in prompts.items() if not str(k).startswith("_")}


def build_sam_prompts_with_overrides(equipment_overrides: dict[str, str]) -> list[tuple[str, str]]:
    """Merge experiment equipment prompts into mvp SAM3 prompt list (structures unchanged)."""
    sys.path.insert(0, str(ROOT / "src"))
    from sitewatch.perception.ontology import mvp_class_list, prompts_for

    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for canonical in mvp_class_list():
        if canonical in equipment_overrides:
            prompt = equipment_overrides[canonical]
        else:
            plist = prompts_for(canonical)
            prompt = plist[0] if plist else canonical.replace("_", " ")
        if prompt in seen:
            continue
        seen.add(prompt)
        pairs.append((canonical, prompt))
    return pairs


def evaluate(
    *,
    gt: dict[str, Any],
    gt_path: Path,
    predictions_dir: Path,
    overlay_dir: Path,
    classes: list[str],
    iou_thr: float,
) -> dict[str, Any]:
    box_stats = _empty_class_stats(classes)
    count_stats = _empty_class_stats(classes)
    frames_out: list[dict[str, Any]] = []
    gt_ready = True

    for frame in gt.get("frames") or []:
        date = frame.get("date") or frame.get("id") or "unknown"
        gt_boxes_all = list(frame.get("boxes") or [])
        gt_boxes = [b for b in gt_boxes_all if str(b.get("class")) in classes]
        raw_counts = dict(frame.get("equipment_counts") or {})
        # null counts → treat as unlabeled (skip count metrics for that class)
        labeled_counts: dict[str, int] = {}
        for c in classes:
            v = raw_counts.get(c)
            if v is None:
                continue
            labeled_counts[c] = int(v)

        if frame.get("label_status") == "pending" or (not gt_boxes and not labeled_counts):
            gt_ready = False

        pred_dir = find_frame_pred_dir(predictions_dir, frame)
        preds = load_detector_boxes(pred_dir, frame) if pred_dir else []
        preds = [p for p in preds if p["class"] in classes]
        fusion_counts = load_fusion_counts(pred_dir, frame, classes) if pred_dir else {c: 0 for c in classes}

        tps, fps, fns = match_boxes(gt_boxes, preds, iou_thr=iou_thr)
        for row in tps:
            box_stats[str(row["class"])]["tp"] += 1
        for row in fps:
            box_stats[str(row["class"])]["fp"] += 1
        for row in fns:
            box_stats[str(row["class"])]["fn"] += 1

        frame_count: dict[str, dict[str, int]] = {}
        for c in classes:
            if c not in labeled_counts:
                continue
            tp, fp, fn = count_confusion(fusion_counts.get(c, 0), labeled_counts[c])
            count_stats[c]["tp"] += tp
            count_stats[c]["fp"] += fp
            count_stats[c]["fn"] += fn
            frame_count[c] = {
                "gt": labeled_counts[c],
                "pred_confirmed": fusion_counts.get(c, 0),
                "tp": tp,
                "fp": fp,
                "fn": fn,
            }

        image_path = resolve_image(gt_path, frame)
        overlay_path = overlay_dir / f"{date}_fp_fn.jpg"
        overlay_ok = False
        if image_path is not None:
            overlay_ok = draw_overlays(
                Path(image_path),
                overlay_path,
                tps=tps,
                fps=fps,
                fns=fns,
            )

        frames_out.append(
            {
                "id": frame.get("id"),
                "date": date,
                "pred_dir": str(pred_dir) if pred_dir else None,
                "n_gt_boxes": len(gt_boxes),
                "n_pred_boxes": len(preds),
                "box_tp": len(tps),
                "box_fp": len(fps),
                "box_fn": len(fns),
                "fusion_counts": frame_count,
                "overlay": str(overlay_path) if overlay_ok else None,
            }
        )

    def _prf(stats: dict[str, dict[str, int]]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        tot = {"tp": 0, "fp": 0, "fn": 0}
        for c, s in stats.items():
            tp, fp, fn = s["tp"], s["fp"], s["fn"]
            tot["tp"] += tp
            tot["fp"] += fp
            tot["fn"] += fn
            prec = tp / (tp + fp) if (tp + fp) else None
            rec = tp / (tp + fn) if (tp + fn) else None
            summary[c] = {
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "precision": None if prec is None else round(prec, 4),
                "recall": None if rec is None else round(rec, 4),
            }
        tp, fp, fn = tot["tp"], tot["fp"], tot["fn"]
        summary["_micro"] = {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
            "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        }
        return summary

    return {
        "episode": gt.get("episode"),
        "gt_path": str(gt_path),
        "gt_status": gt.get("status"),
        "gt_ready": gt_ready,
        "predictions_dir": str(predictions_dir),
        "matching": {
            "detector_boxes": f"same class + IoU >= {iou_thr}, greedy one-to-one",
            "fusion_counts": (
                "confirmed count_visible vs GT; "
                f"confirm_min_confidence={CONFIRM_MIN_CONFIDENCE}; "
                "TP=min(p,g) FP=max(0,p-g) FN=max(0,g-p)"
            ),
        },
        "classes": classes,
        "detector_boxes": _prf(box_stats),
        "fusion_confirmed_counts": _prf(count_stats),
        "frames": frames_out,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gt", type=Path, default=DEFAULT_GT, help="GT JSON path")
    parser.add_argument(
        "--predictions",
        type=Path,
        help="Predictions root (per-frame dirs with detections.json + observed_state.json)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Metrics JSON output path",
    )
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=DEFAULT_OVERLAY_DIR,
        help="Directory for FP/FN overlay images",
    )
    parser.add_argument(
        "--iou",
        type=float,
        default=IOU_THRESHOLD,
        help="Box match IoU threshold (default 0.3)",
    )
    parser.add_argument(
        "--dump-prompts",
        type=Path,
        help="Load experiment YAML and print merged SAM3 (canonical, prompt) pairs; exit",
    )
    args = parser.parse_args()

    if args.dump_prompts:
        overrides = load_experiment_prompts(args.dump_prompts)
        pairs = build_sam_prompts_with_overrides(overrides)
        for canonical, prompt in pairs:
            print(f"{canonical}\t{prompt}")
        return 0

    if not args.predictions:
        parser.error("--predictions is required unless --dump-prompts is set")

    gt = load_gt(args.gt)
    classes = list(gt.get("classes") or EQUIPMENT_UNDER_TEST)
    iou_thr = float(gt.get("iou_match_threshold") or args.iou)

    metrics = evaluate(
        gt=gt,
        gt_path=args.gt.resolve(),
        predictions_dir=args.predictions.resolve(),
        overlay_dir=args.overlay_dir.resolve(),
        classes=classes,
        iou_thr=iou_thr,
    )

    out_path = args.out
    if out_path is None:
        out_path = args.overlay_dir / "metrics.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(out_path), "gt_ready": metrics["gt_ready"]}, ensure_ascii=False))
    print("detector_boxes micro:", metrics["detector_boxes"]["_micro"])
    print("fusion_counts micro:", metrics["fusion_confirmed_counts"]["_micro"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
