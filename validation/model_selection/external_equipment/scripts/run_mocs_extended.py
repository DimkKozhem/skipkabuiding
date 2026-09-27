#!/usr/bin/env python3
"""MOCS extended eval: DINO + YOLOE-26L with LOCKED diagnostic thresholds.

- Does not retune on extended_eval or on diagnostic diag_test.
- Raw → artifacts/.../mocs_extended/ (does not overwrite mocs_diagnostic/).
- Resize = lock (YOLOE 640, DINO long_edge 800).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import torch
from PIL import Image

ROOT = Path("/home/dimk/my_project/LCT2026")
sys.path.insert(0, str(ROOT / "validation/model_selection/external_equipment/scripts"))
import run_mocs_diagnostic as diag  # noqa: E402
import run_compare_miniexcav as base  # noqa: E402

OUT = ROOT / "artifacts/model_selection/runs/external_equipment/mocs_extended"
REPORT = ROOT / "validation/model_selection/external_equipment/reports"
LOCK_THR = {"grounding-dino-base": 0.2, "yoloe-26l-seg": 0.2}
PROMPTS = [
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


def load_extended(path: Path):
    man = json.loads(path.read_text())
    samples = []
    for s in man["samples"]:
        if s.get("diag_split") not in {"extended_tune", "extended_eval"}:
            continue
        img = ROOT / s["image"]
        im = Image.open(img)
        w, h = im.size
        boxes = []
        for b in s["boxes"]:
            if not b.get("in_equipment_eval"):
                continue
            boxes.append(
                {
                    "bbox_xyxy": diag.yolo_to_xyxy(b["bbox_yolo_norm"], w, h),
                    "class": b["mapped_class"],
                    "area_ratio": b["area_ratio"],
                    "relative_area_bin": b["relative_area_bin"],
                }
            )
        samples.append({**s, "image_path": str(img), "width": w, "height": h, "gt_boxes": boxes})
    return man, samples


def run_yoloe26(samples, prompts, device: str, imgsz: int = 640):
    from ultralytics import YOLO

    weights = ROOT / "artifacts/model_selection/weights/yoloe-26l-seg.pt"
    model = YOLO(str(weights))
    try:
        model.set_classes(prompts)
    except Exception:
        pass
    if device.startswith("cuda"):
        torch.cuda.set_device(int(device.split(":")[1]))
        torch.cuda.reset_peak_memory_stats()
    raw = {}
    times = []
    for s in samples:
        t0 = time.perf_counter()
        res = model.predict(s["image_path"], conf=0.01, imgsz=imgsz, device=device, verbose=False)[0]
        times.append((time.perf_counter() - t0) * 1000)
        dets = []
        if res.boxes is not None and len(res.boxes):
            for b in res.boxes:
                cls_i = int(b.cls.item()) if b.cls is not None else 0
                name = prompts[cls_i] if cls_i < len(prompts) else str(cls_i)
                dets.append({"bbox_xyxy": b.xyxy[0].tolist(), "score": float(b.conf.item()), "class": name})
        raw[s["sample_id"]] = dets
    peak = None
    if device.startswith("cuda"):
        peak = torch.cuda.max_memory_allocated() / (1024 * 1024)
    return raw, {
        "mean_ms": sum(times) / len(times) if times else None,
        "imgsz": imgsz,
        "device": device,
        "env": "LCT2026/.venv",
        "weights": str(weights),
        "peak_mib": peak,
    }


def run_dino_longedge(samples, prompts, device_phys: str, long_edge: int = 800):
    """DINO via myenv; resize long-edge then scale boxes back (lock)."""
    payload = {
        "samples": [{"sample_id": s["sample_id"], "image": s["image_path"]} for s in samples],
        "prompts": prompts,
        "long_edge": long_edge,
        "box_threshold": 0.15,
        "text_threshold": 0.20,
    }
    # map physical GPU via CUDA_VISIBLE_DEVICES
    phys = device_phys.split(":")[-1] if ":" in device_phys else "0"
    script = r'''
import json, sys, time, torch
from PIL import Image
from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

payload=json.load(sys.stdin)
prompts=payload["prompts"]
long_edge=int(payload["long_edge"])
device="cuda:0"  # after CUDA_VISIBLE_DEVICES
proc=AutoProcessor.from_pretrained("IDEA-Research/grounding-dino-base")
model=AutoModelForZeroShotObjectDetection.from_pretrained("IDEA-Research/grounding-dino-base").to(device)
model.eval()
text=" . ".join(prompts)+" ."
out={}; times=[]
if torch.cuda.is_available():
    torch.cuda.reset_peak_memory_stats()
for s in payload["samples"]:
    im0=Image.open(s["image"]).convert("RGB")
    w0,h0=im0.size
    scale=long_edge/max(w0,h0)
    if scale<1.0:
        im=im0.resize((max(1,int(w0*scale)), max(1,int(h0*scale))), Image.BICUBIC)
        inv=1.0/scale
    else:
        im=im0; inv=1.0
    inputs=proc(images=im, text=text, return_tensors="pt").to(device)
    t0=time.perf_counter()
    with torch.no_grad():
        outputs=model(**inputs)
    times.append((time.perf_counter()-t0)*1000)
    # transformers≥4.x/5.x: threshold (was box_threshold in older API)
    results=proc.post_process_grounded_object_detection(
        outputs, inputs.input_ids, threshold=payload["box_threshold"],
        text_threshold=payload["text_threshold"], target_sizes=[im.size[::-1]]
    )[0]
    dets=[]
    boxes=results["boxes"].tolist()
    scores=results["scores"].tolist()
    labels=results.get("labels") or results.get("text_labels") or []
    if hasattr(labels, "tolist"):
        labels=labels.tolist()
    for box, score, lab in zip(boxes, scores, labels if labels else ["?"]*len(boxes)):
        lab_s=str(lab).lower().strip()
        mapped=None
        for p in prompts:
            if p.lower() in lab_s or lab_s in p.lower():
                mapped=p; break
        x1,y1,x2,y2=box
        dets.append({"bbox_xyxy":[x1*inv,y1*inv,x2*inv,y2*inv], "score": float(score), "class": mapped or lab_s})
    out[s["sample_id"]]=dets
peak=torch.cuda.max_memory_allocated()/(1024*1024) if torch.cuda.is_available() else None
print(json.dumps({"raw": out, "mean_ms": sum(times)/len(times) if times else None, "peak_mib": peak}))
'''
    py = Path("/home/dimk/my_project/myenv/bin/python")
    env = {**os.environ, "CUDA_VISIBLE_DEVICES": phys}
    proc = subprocess.run(
        [str(py), "-c", script],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=str(ROOT),
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"DINO failed: {proc.stderr[-2500:]}")
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    return data["raw"], {
        "mean_ms": data["mean_ms"],
        "imgsz": f"long_edge={long_edge} then DINO processor",
        "device": f"{device_phys} via CUDA_VISIBLE_DEVICES={phys}",
        "env": "myenv (experimental)",
        "weights": "IDEA-Research/grounding-dino-base",
        "infer_box_threshold": 0.15,
        "peak_mib": data.get("peak_mib"),
        "note": "resized long-edge; boxes scaled back to original",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/manifests/mocs_extended_v1.json",
    )
    ap.add_argument("--models", default="yoloe26,dino")
    ap.add_argument("--yoloe-device", default="cuda:1")
    ap.add_argument("--dino-device", default="cuda:1")
    ap.add_argument("--yoloe-imgsz", type=int, default=640)
    ap.add_argument("--dino-long-edge", type=int, default=800)
    ap.add_argument("--eval-only", action="store_true", help="infer only extended_eval (still need tune ids in raw empty)")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    man, samples = load_extended(args.manifest)
    tune = [s for s in samples if s["diag_split"] == "extended_tune"]
    ev = [s for s in samples if s["diag_split"] == "extended_eval"]
    run_samples = ev if args.eval_only else samples
    print("tune", len(tune), "eval", len(ev), "run", len(run_samples))

    out_path = REPORT / "metrics_mocs_extended_v1.json"
    if out_path.is_file():
        results = json.loads(out_path.read_text())
        results.setdefault("models", {})
        results.setdefault("blockers", {})
        results["locked_thresholds"] = LOCK_THR
        results["prompts"] = PROMPTS
        results["note"] = "thresholds from diagnostic tune; NOT retuned on extended_eval"
    else:
        results = {
            "manifest": str(args.manifest),
            "protocol": "extended-multiclass-v1",
            "locked_thresholds": LOCK_THR,
            "prompts": PROMPTS,
            "models": {},
            "blockers": {},
            "note": "thresholds from diagnostic tune; NOT retuned on extended_eval",
        }

    runners = {
        "yoloe26": (
            "yoloe-26l-seg",
            lambda smp: run_yoloe26(smp, PROMPTS, args.yoloe_device, args.yoloe_imgsz),
        ),
        "dino": (
            "grounding-dino-base",
            lambda smp: run_dino_longedge(smp, PROMPTS, args.dino_device, args.dino_long_edge),
        ),
    }
    wanted = set(args.models.split(","))
    for key, (mid, fn) in runners.items():
        if key not in wanted:
            continue
        print("===", mid, flush=True)
        try:
            raw_all, runtime = fn(run_samples)
            thr = LOCK_THR[mid]
            raw_eval = {s["sample_id"]: raw_all.get(s["sample_id"], []) for s in ev}
            filt = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in raw_eval.items()}
            metrics = diag.evaluate_multiclass(
                ev, filt, {"runtime": runtime, "locked_thr": thr, "thr_source": "diagnostic_tune_lock"}
            )
            # strict per-class P/R including FP outside GT images
            by_strict = {}
            classes = sorted({b["class"] for s in ev for b in s["gt_boxes"]})
            for cls in classes:
                gts_c = {s["sample_id"]: [b for b in s["gt_boxes"] if b["class"] == cls] for s in ev}
                gts_c = {k: v for k, v in gts_c.items() if v}
                preds_c = {sid: [p for p in filt.get(sid, []) if p.get("class") == cls] for sid in gts_c}
                ap = base.ap_at_iou(gts_c, preds_c, 0.5) if gts_c else float("nan")
                tp = fp = fn = 0
                for sid, gt in gts_c.items():
                    t, f, n, _ = base.match_tp_fp_fn(gt, preds_c.get(sid, []))
                    tp += t
                    fp += f
                    fn += n
                for sid, preds in filt.items():
                    if sid in gts_c:
                        continue
                    fp += sum(1 for p in preds if p.get("class") == cls)
                prec = tp / (tp + fp + 1e-9)
                rec = tp / (tp + fn + 1e-9)
                by_strict[cls] = {
                    "n_gt": sum(len(v) for v in gts_c.values()),
                    "AP50": ap,
                    "TP": tp,
                    "FP": fp,
                    "FN": fn,
                    "precision": round(prec, 4),
                    "recall": round(rec, 4),
                }
            metrics["by_class_strict"] = by_strict
            results["models"][mid] = metrics
            (OUT / f"{key}_raw_predictions.json").write_text(
                json.dumps(
                    {
                        "model": mid,
                        "locked_thr": thr,
                        "thr_source": "diagnostic_tune_lock",
                        "runtime": runtime,
                        "eval_raw": raw_eval,
                        "eval_filtered": filt,
                        "tune_raw": {s["sample_id"]: raw_all.get(s["sample_id"], []) for s in tune}
                        if not args.eval_only
                        else {},
                        "resize_note": runtime.get("imgsz"),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )
            print(mid, "AP50", metrics["AP50"], "F1", metrics["working_point_iou0.5"]["f1"], "runtime", runtime, flush=True)
        except Exception as e:
            results["blockers"][mid] = {"error": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-2500:]}
            print("BLOCKED", mid, e, flush=True)

    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
    print("WROTE", out_path)


if __name__ == "__main__":
    main()
