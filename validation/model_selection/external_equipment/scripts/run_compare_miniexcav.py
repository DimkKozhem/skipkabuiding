#!/usr/bin/env python3
"""External equipment benchmark: YOLOE-11L + Grounding DINO on miniexcav.

- Does not touch production DB or Skripka manifest.
- Thresholds locked on tune split only.
- DINO uses myenv (transformers); documented as experimental env.
- Device: cuda:1 (do not unload Qwen on cuda:0).
"""

from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import torch
from PIL import Image

ROOT = Path("/home/dimk/my_project/LCT2026")
MANIFEST = ROOT / "validation/model_selection/external_equipment/manifest.json"
OUT = ROOT / "artifacts/model_selection/runs/external_equipment"
REPORT = ROOT / "validation/model_selection/external_equipment/reports"
YOLOE_CKPT = ROOT / "artifacts/model_selection/weights/yoloe-11l-seg.pt"
DEVICE = "cuda:1"
IMGSZ = 640
IOU_MATCH = 0.5
# Primary AP uses excavator predictions only.
TARGET = "excavator"


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


def match_tp_fp_fn(gts, preds, iou_thr=IOU_MATCH):
    """Greedy match by score desc. preds/gts: list of xyxy."""
    preds = sorted(preds, key=lambda p: -p["score"])
    used = set()
    tp = fp = 0
    pairs = []
    for p in preds:
        best_i, best = -1, 0.0
        for i, g in enumerate(gts):
            if i in used:
                continue
            v = iou(p["bbox_xyxy"], g["bbox_xyxy"])
            if v > best:
                best, best_i = v, i
        if best_i >= 0 and best >= iou_thr:
            used.add(best_i)
            tp += 1
            pairs.append((p, gts[best_i], best))
        else:
            fp += 1
    fn = len(gts) - len(used)
    return tp, fp, fn, pairs


def ap_at_iou(gts_by_img, preds_by_img, iou_thr: float) -> float:
    """VOC-style AP for single class."""
    scores = []
    matched_flags = []
    n_gt = sum(len(v) for v in gts_by_img.values())
    if n_gt == 0:
        return float("nan")
    used = {k: set() for k in gts_by_img}
    flat = []
    for sid, preds in preds_by_img.items():
        for p in preds:
            flat.append((p["score"], sid, p))
    flat.sort(reverse=True)
    for score, sid, p in flat:
        gts = gts_by_img.get(sid, [])
        best_i, best = -1, 0.0
        for i, g in enumerate(gts):
            if i in used[sid]:
                continue
            v = iou(p["bbox_xyxy"], g["bbox_xyxy"])
            if v > best:
                best, best_i = v, i
        if best_i >= 0 and best >= iou_thr:
            used[sid].add(best_i)
            scores.append(score)
            matched_flags.append(1)
        else:
            scores.append(score)
            matched_flags.append(0)
    if not matched_flags:
        return 0.0
    tp_cum = 0
    fp_cum = 0
    prec = []
    rec = []
    for m in matched_flags:
        if m:
            tp_cum += 1
        else:
            fp_cum += 1
        prec.append(tp_cum / (tp_cum + fp_cum))
        rec.append(tp_cum / n_gt)
    # 101-point interpolation
    ap = 0.0
    for t in [i / 100 for i in range(101)]:
        p = max((pr for pr, rc in zip(prec, rec) if rc >= t), default=0.0)
        ap += p
    return ap / 101


def ap50_95(gts_by_img, preds_by_img) -> float:
    vals = [ap_at_iou(gts_by_img, preds_by_img, thr) for thr in [0.5 + 0.05 * i for i in range(10)]]
    vals = [v for v in vals if v == v]
    return sum(vals) / len(vals) if vals else float("nan")


def run_yoloe(samples, conf: float):
    from ultralytics import YOLOE

    torch.cuda.set_device(DEVICE)
    torch.cuda.reset_peak_memory_stats(DEVICE)
    t0 = time.perf_counter()
    model = YOLOE(str(YOLOE_CKPT))
    model.to(DEVICE)
    model.set_classes([TARGET])
    load_s = time.perf_counter() - t0
    out = {}
    lat = []
    for s in samples:
        path = ROOT / s["image"]
        t1 = time.perf_counter()
        results = model.predict(str(path), imgsz=IMGSZ, conf=conf, device=DEVICE, verbose=False)
        lat.append((time.perf_counter() - t1) * 1000)
        result = results[0]
        dets = []
        if result.boxes is not None:
            for box in result.boxes:
                dets.append(
                    {
                        "label": TARGET,
                        "score": float(box.conf[0]),
                        "bbox_xyxy": [float(v) for v in box.xyxy[0].tolist()],
                    }
                )
        out[s["sample_id"]] = dets
    peak = torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024)
    return out, {"load_s": round(load_s, 2), "mean_latency_ms": round(sum(lat) / max(1, len(lat)), 1), "peak_vram_mib": round(peak, 1), "conf": conf, "device": DEVICE, "env": "LCT2026/.venv"}


def run_dino(samples, box_threshold: float, text_threshold: float = 0.25):
    # Import path note: caller should use myenv python if .venv lacks transformers.
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    model_id = "IDEA-Research/grounding-dino-base"
    torch.cuda.set_device(DEVICE)
    torch.cuda.reset_peak_memory_stats(DEVICE)
    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(model_id)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id).to(DEVICE)
    model.eval()
    load_s = time.perf_counter() - t0
    out = {}
    lat = []
    labels = [TARGET]
    for s in samples:
        path = ROOT / s["image"]
        image = Image.open(path).convert("RGB")
        w, h = image.size
        inputs = processor(images=image, text=[labels], return_tensors="pt").to(DEVICE)
        t1 = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
        lat.append((time.perf_counter() - t1) * 1000)
        processed = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=box_threshold,
            text_threshold=text_threshold,
            target_sizes=[(h, w)],
        )[0]
        dets = []
        for box, score, lab in zip(
            processed["boxes"].detach().cpu().tolist(),
            processed["scores"].detach().cpu().tolist(),
            [str(x) for x in processed["text_labels"]],
        ):
            # Keep only excavator-ish labels
            if "excav" not in lab.lower() and lab.lower() != TARGET:
                # Still count as prediction for excavator prompt; DINO sometimes returns the prompt text
                pass
            dets.append({"label": TARGET, "score": float(score), "bbox_xyxy": [float(v) for v in box], "raw_label": lab})
        out[s["sample_id"]] = dets
    peak = torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024)
    return out, {
        "load_s": round(load_s, 2),
        "mean_latency_ms": round(sum(lat) / max(1, len(lat)), 1),
        "peak_vram_mib": round(peak, 1),
        "box_threshold": box_threshold,
        "text_threshold": text_threshold,
        "device": DEVICE,
        "env": "myenv (experimental; LCT2026/.venv lacks transformers)",
        "model": model_id,
    }


def gts_maps(samples):
    by = {}
    by_size = defaultdict(lambda: defaultdict(list))
    for s in samples:
        boxes = [b for b in s["boxes"] if b["mapped_class"] == TARGET]
        by[s["sample_id"]] = boxes
        for b in boxes:
            by_size[b["size_bin"]][s["sample_id"]].append(b)
    return by, by_size


def working_point(gts_by_img, preds_by_img):
    tp = fp = fn = 0
    for sid, gts in gts_by_img.items():
        t, f, n, _ = match_tp_fp_fn(gts, preds_by_img.get(sid, []))
        tp += t
        fp += f
        fn += n
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}


def filter_conf(preds_by_img, conf: float):
    return {sid: [p for p in preds if p["score"] >= conf] for sid, preds in preds_by_img.items()}


def tune_conf(gts, raw_preds, candidates):
    best = None
    for c in candidates:
        filt = filter_conf(raw_preds, c)
        wp = working_point(gts, filt)
        row = {"conf": c, **wp}
        if best is None or row["f1"] > best["f1"] or (row["f1"] == best["f1"] and row["precision"] > best["precision"]):
            best = row
    return best


def evaluate(name, samples_test, gts_test, preds, meta, by_size_gt):
    wp = working_point(gts_test, preds)
    # size slice: restrict GT to bin; preds still full image then match only those GT
    size_rows = {}
    for bin_name in ("small", "medium", "large"):
        gts_bin = by_size_gt.get(bin_name, {})
        # only images that have GT in this bin
        if not gts_bin:
            size_rows[bin_name] = {"n_gt": 0, "note": "no GT boxes in bin"}
            continue
        preds_bin = {sid: preds.get(sid, []) for sid in gts_bin}
        size_rows[bin_name] = {
            "n_gt": sum(len(v) for v in gts_bin.values()),
            **working_point(gts_bin, preds_bin),
            "AP50": round(ap_at_iou(gts_bin, preds_bin, 0.5), 4),
        }
    return {
        "model": name,
        "n_images": len(samples_test),
        "AP50": round(ap_at_iou(gts_test, preds, 0.5), 4),
        "AP50_95": round(ap50_95(gts_test, preds), 4),
        "working_point_iou0.5": wp,
        "by_size": size_rows,
        "runtime": meta,
    }


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    samples = manifest["samples"]
    tune = [s for s in samples if s["split"] == "tune"]
    test = [s for s in samples if s["split"] == "test"]
    OUT.mkdir(parents=True, exist_ok=True)
    REPORT.mkdir(parents=True, exist_ok=True)

    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = {}

    if which in ("yoloe", "all"):
        # Low conf for raw scores; tune selects working point
        raw_tune, meta_load = run_yoloe(tune, conf=0.01)
        gts_tune, _ = gts_maps(tune)
        best = tune_conf(gts_tune, raw_tune, [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5])
        locked = best["conf"]
        (OUT / "yoloe11l_tune_lock.json").write_text(
            json.dumps({"locked_on": "tune", "candidates": [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5], "best": best}, indent=2),
            encoding="utf-8",
        )
        raw_test, meta_test = run_yoloe(test, conf=0.01)
        preds = filter_conf(raw_test, locked)
        gts_test, by_size = gts_maps(test)
        # save raw
        raw_path = OUT / "yoloe11l_raw_predictions.json"
        raw_path.write_text(
            json.dumps(
                {
                    "model": "yoloe-11l-seg",
                    "locked_conf": locked,
                    "tune_lock": best,
                    "tune_raw": raw_tune,
                    "test_raw_conf0.01": raw_test,
                    "test_filtered": preds,
                    "runtime_test": meta_test,
                    "runtime_tune_load": meta_load,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        results["yoloe-11l"] = evaluate("yoloe-11l-seg", test, gts_test, preds, {**meta_test, "locked_conf": locked, "tune_f1": best}, by_size)
        print(json.dumps(results["yoloe-11l"], ensure_ascii=False, indent=2), flush=True)

    if which in ("dino", "all"):
        # DINO thresholds tuned on tune
        cand = [0.15, 0.2, 0.25, 0.3, 0.35, 0.4]
        # Run once at low threshold then filter by score
        raw_tune, meta_load = run_dino(tune, box_threshold=0.15, text_threshold=0.20)
        gts_tune, _ = gts_maps(tune)
        best = tune_conf(gts_tune, raw_tune, cand)
        locked = best["conf"]
        (OUT / "dino_tune_lock.json").write_text(
            json.dumps({"locked_on": "tune", "candidates": cand, "best": best, "infer_box_threshold": 0.15}, indent=2),
            encoding="utf-8",
        )
        raw_test, meta_test = run_dino(test, box_threshold=0.15, text_threshold=0.20)
        preds = filter_conf(raw_test, locked)
        gts_test, by_size = gts_maps(test)
        (OUT / "dino_raw_predictions.json").write_text(
            json.dumps(
                {
                    "model": "grounding-dino-base",
                    "locked_score": locked,
                    "tune_lock": best,
                    "tune_raw": raw_tune,
                    "test_raw": raw_test,
                    "test_filtered": preds,
                    "runtime_test": meta_test,
                    "runtime_tune_load": meta_load,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        results["grounding-dino-base"] = evaluate(
            "grounding-dino-base", test, gts_test, preds, {**meta_test, "locked_score": locked, "tune_f1": best}, by_size
        )
        print(json.dumps(results["grounding-dino-base"], ensure_ascii=False, indent=2), flush=True)

    if results:
        summary = {
            "dataset": "miniexcav_excavator_v1",
            "manifest": str(MANIFEST.relative_to(ROOT)),
            "n_tune": len(tune),
            "n_test": len(test),
            "models": results,
            "note": "External benchmark only. Not Skripka camera accuracy. Dataset is close-up excavators.",
        }
        (REPORT / "metrics_miniexcav_v1.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("WROTE", REPORT / "metrics_miniexcav_v1.json")


if __name__ == "__main__":
    main()
