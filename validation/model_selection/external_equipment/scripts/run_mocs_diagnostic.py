#!/usr/bin/env python3
"""MOCS diagnostic compare: DINO + YOLOE-26L + SAM3.1 + YOLO-World.

- Separate from miniexcav / Skripka.
- Thresholds locked on diag tune only (NOT miniexcav 0.4/0.1).
- Device preference: cuda:1.
- YOLOE-11L excluded (baseline-frozen).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import torch
from PIL import Image

ROOT = Path("/home/dimk/my_project/LCT2026")
sys.path.insert(0, str(ROOT / "validation/model_selection/external_equipment/scripts"))
import run_compare_miniexcav as base  # noqa: E402

DEVICE = "cuda:1"
IOU_MATCH = 0.5
OUT = ROOT / "artifacts/model_selection/runs/external_equipment/mocs_diagnostic"
REPORT = ROOT / "validation/model_selection/external_equipment/reports"


def yolo_to_xyxy(box, w, h):
    xc, yc, bw, bh = box
    x1 = (xc - bw / 2) * w
    y1 = (yc - bh / 2) * h
    x2 = (xc + bw / 2) * w
    y2 = (yc + bh / 2) * h
    return [x1, y1, x2, y2]


def load_manifest(path: Path):
    man = json.loads(path.read_text())
    samples = []
    for s in man["samples"]:
        if s.get("diag_split") not in {"tune", "diag_test"}:
            continue
        img = ROOT / s["image"] if not Path(s["image"]).is_absolute() else Path(s["image"])
        im = Image.open(img)
        w, h = im.size
        boxes = []
        for b in s["boxes"]:
            if not b.get("in_equipment_eval"):
                continue
            xyxy = yolo_to_xyxy(b["bbox_yolo_norm"], w, h)
            boxes.append(
                {
                    "bbox_xyxy": xyxy,
                    "class": b["mapped_class"],
                    "area_ratio": b["area_ratio"],
                    "relative_area_bin": b["relative_area_bin"],
                    "pixel_wh": [xyxy[2] - xyxy[0], xyxy[3] - xyxy[1]],
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
    return man, samples


def lock_threshold(samples_tune, preds_tune, candidates):
    best = None
    for thr in candidates:
        gts = {s["sample_id"]: s["gt_boxes"] for s in samples_tune}
        preds = {
            sid: [p for p in preds_tune.get(sid, []) if p["score"] >= thr]
            for sid in gts
        }
        # class-agnostic equipment for lock (multi-class AP later)
        tp = fp = fn = 0
        for sid, gt in gts.items():
            t, f, n, _ = base.match_tp_fp_fn(gt, preds.get(sid, []))
            tp += t
            fp += f
            fn += n
        prec = tp / (tp + fp + 1e-9)
        rec = tp / (tp + fn + 1e-9)
        f1 = 2 * prec * rec / (prec + rec + 1e-9)
        row = {"thr": thr, "TP": tp, "FP": fp, "FN": fn, "precision": round(prec, 4), "recall": round(rec, 4), "f1": round(f1, 4)}
        if best is None or row["f1"] > best["f1"]:
            best = row
    return best


def evaluate_multiclass(samples, preds_filtered, meta):
    # overall + by class + by relative_area
    gts_all = {s["sample_id"]: s["gt_boxes"] for s in samples}
    ap50 = base.ap_at_iou(gts_all, preds_filtered, 0.5)
    aps = [base.ap_at_iou(gts_all, preds_filtered, t) for t in [x / 100 for x in range(50, 100, 5)]]
    tp = fp = fn = 0
    for sid, gt in gts_all.items():
        t, f, n, _ = base.match_tp_fp_fn(gt, preds_filtered.get(sid, []))
        tp += t
        fp += f
        fn += n
    prec = tp / (tp + fp + 1e-9)
    rec = tp / (tp + fn + 1e-9)
    f1 = 2 * prec * rec / (prec + rec + 1e-9)

    by_class = {}
    classes = sorted({b["class"] for s in samples for b in s["gt_boxes"]})
    for cls in classes:
        gts_c = {s["sample_id"]: [b for b in s["gt_boxes"] if b["class"] == cls] for s in samples}
        gts_c = {k: v for k, v in gts_c.items() if v}
        preds_c = {
            sid: [p for p in preds_filtered.get(sid, []) if p.get("class") == cls]
            for sid in gts_c
        }
        # also allow preds without class filter if open-vocab same prompt set
        if not any(preds_c.values()):
            preds_c = {sid: preds_filtered.get(sid, []) for sid in gts_c}
        ap = base.ap_at_iou(gts_c, preds_c, 0.5) if gts_c else float("nan")
        t = f = n = 0
        for sid, gt in gts_c.items():
            tt, ff, nn, _ = base.match_tp_fp_fn(gt, preds_c.get(sid, []))
            t += tt
            f += ff
            n += nn
        by_class[cls] = {"n_gt": sum(len(v) for v in gts_c.values()), "AP50": ap, "TP": t, "FP": f, "FN": n}

    by_size = {}
    for bin_name in ("relative_area_small", "relative_area_medium", "relative_area_large"):
        gts_b = {s["sample_id"]: [b for b in s["gt_boxes"] if b["relative_area_bin"] == bin_name] for s in samples}
        gts_b = {k: v for k, v in gts_b.items() if v}
        preds_b = {sid: preds_filtered.get(sid, []) for sid in gts_b}
        ap = base.ap_at_iou(gts_b, preds_b, 0.5) if gts_b else float("nan")
        t = f = n = 0
        for sid, gt in gts_b.items():
            tt, ff, nn, _ = base.match_tp_fp_fn(gt, preds_b.get(sid, []))
            t += tt
            f += ff
            n += nn
        by_size[bin_name] = {"n_gt": sum(len(v) for v in gts_b.values()), "AP50": ap, "TP": t, "FP": f, "FN": n}

    return {
        **meta,
        "AP50": ap50,
        "AP50_95_approx": sum(aps) / len(aps),
        "working_point_iou0.5": {
            "TP": tp,
            "FP": fp,
            "FN": fn,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        },
        "by_class": by_class,
        "by_relative_area": by_size,
    }


def run_yoloe26(samples, prompts):
    from ultralytics import YOLO

    weights = ROOT / "artifacts/model_selection/weights/yoloe-26l-seg.pt"
    model = YOLO(str(weights))
    # text prompt path
    try:
        model.set_classes(prompts)
    except Exception:
        pass
    raw = {}
    times = []
    for s in samples:
        t0 = time.perf_counter()
        res = model.predict(s["image_path"], conf=0.01, imgsz=640, device=DEVICE, verbose=False)[0]
        times.append((time.perf_counter() - t0) * 1000)
        dets = []
        if res.boxes is not None and len(res.boxes):
            for b in res.boxes:
                cls_i = int(b.cls.item()) if b.cls is not None else 0
                name = prompts[cls_i] if cls_i < len(prompts) else str(cls_i)
                xyxy = b.xyxy[0].tolist()
                dets.append({"bbox_xyxy": xyxy, "score": float(b.conf.item()), "class": name})
        raw[s["sample_id"]] = dets
    return raw, {"mean_ms": sum(times) / len(times), "imgsz": 640, "device": DEVICE, "env": "LCT2026/.venv", "weights": str(weights)}


def run_dino(samples, prompts):
    # experimental myenv path via subprocess to avoid import clash — or try import
    import subprocess
    import tempfile

    payload = {
        "samples": [{"sample_id": s["sample_id"], "image": s["image_path"]} for s in samples],
        "prompts": prompts,
        "device": DEVICE,
        "box_threshold": 0.15,
        "text_threshold": 0.20,
    }
    script = r'''
import json, sys, time, torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

payload=json.load(sys.stdin)
device=payload["device"]
prompts=payload["prompts"]
proc=AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-base")
model=AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-base").to(device)
model.eval()
text=" . ".join(prompts)+" ."
out={}
times=[]
for s in payload["samples"]:
    im=Image.open(s["image"]).convert("RGB")
    inputs=proc(images=im, text=text, return_tensors="pt").to(device)
    t0=time.perf_counter()
    with torch.no_grad():
        outputs=model(**inputs)
    times.append((time.perf_counter()-t0)*1000)
    results=proc.post_process_grounded_object_detection(
        outputs, inputs.input_ids, box_threshold=payload["box_threshold"],
        text_threshold=payload["text_threshold"], target_sizes=[im.size[::-1]]
    )[0]
    dets=[]
    boxes=results["boxes"].tolist()
    scores=results["scores"].tolist()
    labels=results.get("labels") or results.get("text_labels") or []
    if hasattr(labels, "tolist"):
        labels=labels.tolist()
    for box, score, lab in zip(boxes, scores, labels if labels else ["?"]*len(boxes)):
        # normalize label to prompt token
        lab_s=str(lab).lower().strip()
        mapped=None
        for p in prompts:
            if p.lower() in lab_s or lab_s in p.lower():
                mapped=p; break
        dets.append({"bbox_xyxy": box, "score": float(score), "class": mapped or lab_s})
    out[s["sample_id"]]=dets
print(json.dumps({"raw": out, "mean_ms": sum(times)/len(times) if times else None}))
'''
    py = Path("/home/dimk/my_project/myenv/bin/python")
    proc = subprocess.run(
        [str(py), "-c", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), "CUDA_VISIBLE_DEVICES": "1"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"DINO failed: {proc.stderr[-2000:]}")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    # remap device note: with CUDA_VISIBLE_DEVICES=1, cuda:0 inside is physical 1
    return data["raw"], {
        "mean_ms": data["mean_ms"],
        "imgsz": "native/processor",
        "device": "cuda:1 via CUDA_VISIBLE_DEVICES=1",
        "env": "myenv (experimental)",
        "weights": "IDEA-Research/grounding-dino-base",
        "infer_box_threshold": 0.15,
    }


def run_sam3(samples, prompts):
    ckpt = ROOT / "models/sam3.1_multiplex.pt"
    if not ckpt.is_file() and not ckpt.resolve().is_file():
        raise FileNotFoundError(f"SAM weights missing: {ckpt}")
    # Use ultralytics SAM3 if available
    try:
        from ultralytics.models.sam import SAM3SemanticPredictor
    except Exception as e:
        raise RuntimeError(f"SAM3SemanticPredictor import failed: {e}") from e

    # Minimal text prompts batch
    raw = {}
    times = []
    # Fall back: SAM as segment anything with class prompts via predictor API varies by version
    from ultralytics import SAM

    model = SAM(str(ckpt.resolve()))
    for s in samples:
        t0 = time.perf_counter()
        dets = []
        try:
            # text prompts if supported
            res = model.predict(s["image_path"], texts=prompts, conf=0.01, device=DEVICE, verbose=False)
            r0 = res[0] if isinstance(res, list) else res
            if hasattr(r0, "boxes") and r0.boxes is not None:
                for b in r0.boxes:
                    cls_i = int(b.cls.item()) if b.cls is not None else 0
                    name = prompts[cls_i] if cls_i < len(prompts) else "unknown"
                    dets.append({"bbox_xyxy": b.xyxy[0].tolist(), "score": float(b.conf.item()), "class": name})
        except TypeError:
            # texts unsupported — blocker for open-vocab external classes
            raise RuntimeError("SAM3 predict(texts=...) unsupported in this ultralytics build for external prompts")
        times.append((time.perf_counter() - t0) * 1000)
        raw[s["sample_id"]] = dets
    return raw, {
        "mean_ms": sum(times) / len(times) if times else None,
        "imgsz": 720,
        "device": DEVICE,
        "env": "LCT2026/.venv",
        "weights": str(ckpt.resolve()),
    }


def run_yoloworld(samples, prompts):
    yw_py = ROOT / ".venv-yoloworld/bin/python"
    if not yw_py.is_file():
        raise FileNotFoundError(f"missing {yw_py}")
    # Use ultralytics YOLOWorld if available in yw venv, else mmdet path
    import subprocess

    payload = {
        "samples": [{"sample_id": s["sample_id"], "image": s["image_path"]} for s in samples],
        "prompts": prompts,
        "device": "cuda:0",  # inside CUDA_VISIBLE_DEVICES=1
        "weights": str(ROOT / "artifacts/model_selection/weights/l_stage2-b3e3dc3f.pth"),
        "repo": str(ROOT / "artifacts/model_selection/third_party/YOLO-World"),
    }
    script = r'''
import json, sys, time, os
from pathlib import Path
payload=json.load(sys.stdin)
sys.path.insert(0, payload["repo"])
# Prefer ultralytics YOLOWorld if present
raw={}; times=[]; err=None
try:
    from ultralytics import YOLO
    # try world weights naming — may fail
    raise RuntimeError("skip ultralytics world weights path")
except Exception:
    pass
try:
    from mmdet.apis import init_detector, inference_detector
    import torch
    # find a config
    repo=Path(payload["repo"])
    cfg=repo/"configs/pretrain/yolo_world_v2_l_vlpan_bn_2e-3_100e_4x8gpus_obj365v1_goldg_train_lvis_minival.py"
    if not cfg.is_file():
        raise FileNotFoundError(cfg)
    model=init_detector(str(cfg), payload["weights"], device=payload["device"], palette="random")
    # set classes if API exists
    if hasattr(model, "reparameterize"):
        pass
    texts=[[p] for p in payload["prompts"]]
    if hasattr(model, "set_classes"):
        model.set_classes(payload["prompts"])
    for s in payload["samples"]:
        t0=time.perf_counter()
        result=inference_detector(model, s["image"])
        times.append((time.perf_counter()-t0)*1000)
        dets=[]
        # mmdet 3.x DetDataSample
        if hasattr(result, "pred_instances"):
            inst=result.pred_instances
            boxes=inst.bboxes.cpu().numpy()
            scores=inst.scores.cpu().numpy()
            labels=inst.labels.cpu().numpy()
            for box, score, lab in zip(boxes, scores, labels):
                if float(score)<0.01: continue
                name=payload["prompts"][int(lab)] if int(lab)<len(payload["prompts"]) else str(int(lab))
                dets.append({"bbox_xyxy": box.tolist(), "score": float(score), "class": name})
        raw[s["sample_id"]]=dets
except Exception as e:
    err=f"{type(e).__name__}: {e}"
print(json.dumps({"raw": raw, "mean_ms": (sum(times)/len(times) if times else None), "error": err}))
'''
    proc = subprocess.run(
        [str(yw_py), "-c", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        env={**{k: v for k, v in __import__("os").environ.items()}, "CUDA_VISIBLE_DEVICES": "1"},
    )
    if proc.returncode != 0:
        raise RuntimeError(f"YOLO-World failed rc={proc.returncode}: {proc.stderr[-2500:]}")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    if data.get("error") and not data.get("raw"):
        raise RuntimeError(data["error"])
    return data["raw"], {
        "mean_ms": data.get("mean_ms"),
        "imgsz": "config-default",
        "device": "cuda:1 via CUDA_VISIBLE_DEVICES=1",
        "env": ".venv-yoloworld",
        "weights": payload["weights"],
        "warning": data.get("error"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--models", default="yoloe26,dino,sam,yoloworld")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    man, samples = load_manifest(args.manifest)
    tune = [s for s in samples if s["diag_split"] == "tune"]
    test = [s for s in samples if s["diag_split"] == "diag_test"]
    prompts = sorted({b["class"] for s in samples for b in s["gt_boxes"] if b["class"]})
    print("n_tune", len(tune), "n_test", len(test), "prompts", prompts)

    # sanity: coords
    for s in samples[:3]:
        for b in s["gt_boxes"]:
            x1, y1, x2, y2 = b["bbox_xyxy"]
            assert 0 <= x1 < x2 <= s["width"] + 1
            assert 0 <= y1 < y2 <= s["height"] + 1

    wanted = set(args.models.split(","))
    runners = {
        "yoloe26": ("yoloe-26l-seg", run_yoloe26, [0.05, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4]),
        "dino": ("grounding-dino-base", run_dino, [0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5]),
        "sam": ("sam3.1-multiplex", run_sam3, [0.1, 0.2, 0.3, 0.35, 0.4, 0.5]),
        "yoloworld": ("yolo-world-v2.1-l", run_yoloworld, [0.05, 0.1, 0.15, 0.2, 0.3, 0.4]),
    }
    results = {"manifest": str(args.manifest), "prompts": prompts, "models": {}, "blockers": {}}
    for key, (mid, fn, cands) in runners.items():
        if key not in wanted:
            continue
        print("===", mid)
        try:
            raw_all, runtime = fn(samples, prompts)
            # split
            raw_tune = {s["sample_id"]: raw_all[s["sample_id"]] for s in tune}
            raw_test = {s["sample_id"]: raw_all[s["sample_id"]] for s in test}
            lock = lock_threshold(tune, raw_tune, cands)
            thr = lock["thr"]
            filt = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in raw_test.items()}
            ev = evaluate_multiclass(test, filt, {"runtime": runtime, "locked_thr": thr, "tune_lock": lock})
            results["models"][mid] = ev
            (OUT / f"{key}_raw_predictions.json").write_text(
                json.dumps(
                    {
                        "model": mid,
                        "locked_thr": thr,
                        "tune_lock": lock,
                        "runtime": runtime,
                        "test_raw": raw_test,
                        "test_filtered": filt,
                        "resize_note": runtime.get("imgsz"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            print(mid, "AP50", ev["AP50"], "lock", lock)
        except Exception as e:
            results["blockers"][mid] = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2000:]}
            print("BLOCKED", mid, e)

    out_path = REPORT / "metrics_mocs_diagnostic_v1.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print("WROTE", out_path)


if __name__ == "__main__":
    main()
