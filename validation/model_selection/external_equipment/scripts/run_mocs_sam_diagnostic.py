#!/usr/bin/env python3
"""SAM 3.1 on MOCS diagnostic set — experiment adapter (not production perception).

Fix for KeyError language_features:
  Wrong: ultralytics.SAM(...).predict(..., texts=) without set_image / text embeddings.
  Right: SAM3SemanticPredictor → set_image → predictor(text=chunk)  [same as Sam3Provider].

Does not modify config/perception.yaml.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import torch

ROOT = Path("/home/dimk/my_project/LCT2026")
sys.path.insert(0, str(ROOT / "validation/model_selection/external_equipment/scripts"))
import run_mocs_diagnostic as diag  # noqa: E402

OUT = ROOT / "artifacts/model_selection/runs/external_equipment/mocs_diagnostic_sam"
REPORT = ROOT / "validation/model_selection/external_equipment/reports"
CKPT = ROOT / "models/sam3.1_multiplex.pt"
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


def _boxes_from_grounding(predictor, features, chunk, conf: float, src_hw: tuple[int, int]):
    """Box-only decode: avoids full-res mask upsample (CPU RAM / VRAM spike)."""
    import torchvision
    from ultralytics.utils import ops

    outputs = predictor._inference_features(features, text=chunk)
    pred_boxes = outputs["pred_boxes"]  # (nc, q, 4) xywh norm
    pred_logits = outputs["pred_logits"]
    pred_scores = pred_logits.sigmoid()
    presence = outputs["presence_logit_dec"].sigmoid().unsqueeze(1)
    pred_scores = (pred_scores * presence).squeeze(-1)
    nc, nq = pred_scores.shape
    pred_cls = torch.arange(nc, device=pred_scores.device, dtype=pred_scores.dtype)[:, None].expand(nc, nq)
    boxes = torch.cat([pred_boxes, pred_scores[..., None], pred_cls[..., None]], dim=-1)
    keep = pred_scores > conf
    boxes = boxes[keep]
    if boxes.numel() == 0:
        return []
    boxes = boxes.clone()
    boxes[:, :4] = ops.xywh2xyxy(boxes[:, :4])
    c = boxes[:, 5:6] * 7680.0
    keep_i = torchvision.ops.nms(boxes[:, :4] + c, boxes[:, 4], predictor.args.iou)
    boxes = boxes[keep_i]
    h, w = src_hw
    dets = []
    for row in boxes:
        x1, y1, x2, y2, score, cls_i = row.tolist()
        idx = int(cls_i)
        name = chunk[idx] if 0 <= idx < len(chunk) else str(idx)
        dets.append(
            {
                "bbox_xyxy": [x1 * w, y1 * h, x2 * w, y2 * h],
                "score": float(score),
                "class": name,
            }
        )
    return dets


def run_sam(samples, prompts, device: str, imgsz: int = 720, prompt_batch: int = 4, conf: float = 0.01):
    from ultralytics.models.sam import SAM3SemanticPredictor

    if not CKPT.is_file():
        raise FileNotFoundError(CKPT)
    ul_device = device.split(":")[-1] if device.startswith("cuda:") else device
    overrides = dict(
        conf=conf,
        iou=0.5,
        task="segment",
        mode="predict",
        model=str(CKPT.resolve()),
        imgsz=imgsz,
        save=False,
        verbose=False,
        device=ul_device,
    )
    predictor = SAM3SemanticPredictor(overrides=overrides)
    # Ultralytics leaves .model=None until setup_model; bare access does NOT build.
    predictor.setup_model(model=None)
    if predictor.model is None:
        raise RuntimeError("SAM3SemanticPredictor.setup_model left model=None")
    if not hasattr(predictor.model, "text_embeddings") or predictor.model.text_embeddings is None:
        predictor.model.text_embeddings = {}

    if device.startswith("cuda"):
        torch.cuda.set_device(int(ul_device))
        torch.cuda.reset_peak_memory_stats()

    raw = {}
    times = []
    for s in samples:
        t0 = time.perf_counter()
        dets = []
        predictor.set_image(s["image_path"])
        # cached image features from set_image
        features = predictor.features if hasattr(predictor, "features") else None
        if features is None:
            # fallback: public API (may upsample masks — prefer box path)
            for offset in range(0, len(prompts), prompt_batch):
                chunk = prompts[offset : offset + prompt_batch]
                results = predictor(text=chunk)
                for res in results or []:
                    if res.boxes is None or len(res.boxes) == 0:
                        continue
                    for b in res.boxes:
                        cls_i = int(b.cls.item()) if b.cls is not None else 0
                        name = chunk[cls_i] if 0 <= cls_i < len(chunk) else str(cls_i)
                        dets.append(
                            {
                                "bbox_xyxy": b.xyxy[0].tolist(),
                                "score": float(b.conf.item()),
                                "class": name,
                            }
                        )
        else:
            from PIL import Image as _Image

            im0 = _Image.open(s["image_path"])
            src_hw = (im0.height, im0.width)
            for offset in range(0, len(prompts), prompt_batch):
                chunk = prompts[offset : offset + prompt_batch]
                dets.extend(_boxes_from_grounding(predictor, features, chunk, conf, src_hw))
        if device.startswith("cuda") and torch.cuda.is_available():
            torch.cuda.empty_cache()
        if hasattr(predictor, "reset_prompts"):
            predictor.reset_prompts()
        times.append((time.perf_counter() - t0) * 1000)
        raw[s["sample_id"]] = dets
    peak = torch.cuda.max_memory_allocated() / (1024 * 1024) if device.startswith("cuda") else None
    return raw, {
        "mean_ms": sum(times) / len(times) if times else None,
        "imgsz": imgsz,
        "device": device,
        "env": "LCT2026/.venv",
        "weights": str(CKPT.resolve()),
        "sha256": "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6",
        "peak_mib": peak,
        "adapter": "SAM3SemanticPredictor.setup_model + set_image + box-only forward_grounding (text=)",
        "prompt_batch_size": prompt_batch,
    }


def smoke(device: str, imgsz: int):
    from PIL import Image

    img = next((ROOT / "data/external/benchmark_sources/mocs_yolo_hf/images/val").glob("*.jpg"))
    samples = [{"sample_id": "smoke", "image_path": str(img)}]
    raw, runtime = run_sam(samples, ["excavator", "truck"], device=device, imgsz=imgsz, prompt_batch=2)
    n = len(raw["smoke"])
    print("SMOKE", "n_dets", n, "runtime", runtime)
    if n == 0:
        print("SMOKE_EMPTY_OK_IF_NO_EQUIPMENT_IN_FRAME", img.name)
    return n, runtime


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/manifests/mocs_diagnostic_v1.json",
    )
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--imgsz", type=int, default=720)
    ap.add_argument("--smoke-only", action="store_true")
    ap.add_argument("--skip-smoke", action="store_true", help="skip smoke if prior smoke already proved text path")
    ap.add_argument("--thr-candidates", default="0.1,0.2,0.3,0.35,0.4,0.5")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)

    n, smoke_rt = None, None
    if not args.skip_smoke:
        print("=== SAM smoke ===", flush=True)
        try:
            n, smoke_rt = smoke(args.device, args.imgsz)
        except Exception as e:
            blocker = {
                "status": "blocked_runtime",
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-3000:],
                "cause": (
                    "If KeyError language_features persists after SAM3SemanticPredictor(text=), "
                    "check language_backbone weights load and set_classes/forward_text. "
                    "If OOM — need free VRAM (do not kill Qwen/InternVL/Molmo)."
                ),
            }
            (OUT / "blocker.json").write_text(json.dumps(blocker, ensure_ascii=False, indent=2) + "\n")
            print("SMOKE_BLOCKED", e)
            return

        if args.smoke_only:
            (OUT / "smoke.json").write_text(json.dumps({"n_dets": n, "runtime": smoke_rt}, indent=2) + "\n")
            return
    else:
        print("=== SAM smoke skipped (prior proof exists) ===", flush=True)
        n = -1

    man, samples = diag.load_manifest(args.manifest)
    tune = [s for s in samples if s["diag_split"] == "tune"]
    test = [s for s in samples if s["diag_split"] == "diag_test"]
    print("n_tune", len(tune), "n_test", len(test), flush=True)

    try:
        raw_all, runtime = run_sam(samples, PROMPTS, device=args.device, imgsz=args.imgsz)
        cands = [float(x) for x in args.thr_candidates.split(",")]
        raw_tune = {s["sample_id"]: raw_all[s["sample_id"]] for s in tune}
        lock = diag.lock_threshold(tune, raw_tune, cands)
        thr = lock["thr"]
        filt = {s["sample_id"]: [p for p in raw_all[s["sample_id"]] if p["score"] >= thr] for s in test}
        filt = {sid: dets for sid, dets in filt.items()}
        ev = diag.evaluate_multiclass(test, filt, {"runtime": runtime, "locked_thr": thr, "tune_lock": lock})
        results = {
            "model": "sam3.1-multiplex",
            "status": "ok",
            "metrics": ev,
            "smoke_n_dets": n,
        }
        (OUT / "sam_raw_predictions.json").write_text(
            json.dumps(
                {
                    "model": "sam3.1-multiplex",
                    "locked_thr": thr,
                    "tune_lock": lock,
                    "runtime": runtime,
                    "test_raw": {s["sample_id"]: raw_all[s["sample_id"]] for s in test},
                    "test_filtered": filt,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )
        (REPORT / "metrics_mocs_diagnostic_sam_v1.json").write_text(
            json.dumps(results, ensure_ascii=False, indent=2) + "\n"
        )
        print("SAM AP50", ev["AP50"], "lock", lock, flush=True)
    except Exception as e:
        blocker = {
            "status": "blocked_runtime",
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-3000:],
        }
        (OUT / "blocker.json").write_text(json.dumps(blocker, ensure_ascii=False, indent=2) + "\n")
        print("SAM_BLOCKED", e)


if __name__ == "__main__":
    main()
