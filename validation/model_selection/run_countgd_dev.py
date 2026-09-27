"""CountGD on the five diagnostic frames.

text: empty exemplars, frozen captions. This is the automatic mode.
visual: one box on the same query image, recorded with its origin.
A box taken from the test image is an interactive setup. It is not ground truth.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
COUNTGD = ROOT / "artifacts/model_selection/third_party/CountGD"
os.chdir(COUNTGD)
sys.path.insert(0, str(COUNTGD))

import numpy as np
import torch
from PIL import Image, ImageDraw

import datasets_inference.transforms as T
from util.box_ops import box_cxcywh_to_xyxy
from util.slconfig import SLConfig

MANIFEST = json.loads((ROOT / "validation/model_selection/manifest.json").read_text())
TASKS = json.loads((ROOT / "validation/model_selection/localization_tasks_frozen.json").read_text())
CKPT = COUNTGD / "checkpoints/checkpoint_fsc147_best.pth"
CONFIDENCE = 0.23


def build(device):
    normalize = T.Compose(
        [T.ToTensor(), T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225])]
    )
    transform = T.Compose([T.RandomResize([800], max_size=1333), normalize])
    cfg = SLConfig.fromfile("./config/cfg_fsc147_vit_b.py")
    cfg.merge_from_dict({"text_encoder_type": "checkpoints/bert-base-uncased"})
    args = argparse_namespace(cfg, device)
    from models.registry import MODULE_BUILD_FUNCS

    build_func = MODULE_BUILD_FUNCS.get(args.modelname)
    model, _, _ = build_func(args)
    model.to(device)
    checkpoint = torch.load(CKPT, map_location="cpu")["model"]
    model.load_state_dict(checkpoint, strict=False)
    model.eval()
    return model, transform


def argparse_namespace(cfg, device):
    class Args:
        pass

    args = Args()
    args.device = device
    args.modelname = None
    for key, value in cfg._cfg_dict.to_dict().items():
        setattr(args, key, value)
    return args


def samples():
    wanted = set(TASKS["diagnostic_frames"])
    found = [row for row in MANIFEST["samples"] if row["sample_id"] in wanted]
    if len(found) != 5:
        raise SystemExit(f"expected 5 dev frames, got {len(found)}")
    return found


def predict(model, transform, image, text, exemplars, device):
    tensor = torch.tensor(exemplars, dtype=torch.float32) if exemplars else torch.zeros((0, 4))
    input_image, target = transform(image, {"exemplars": tensor})
    with torch.no_grad():
        output = model(
            input_image.unsqueeze(0).to(device),
            [target["exemplars"].to(device)],
            [torch.tensor([0]).to(device)],
            captions=[text + " ."],
        )
    logits = output["pred_logits"][0].sigmoid()
    boxes = output["pred_boxes"][0]
    scores = logits.max(dim=-1).values
    keep = scores > CONFIDENCE
    return boxes[keep].detach().cpu(), scores[keep].detach().cpu(), float(scores.max()) if scores.numel() else None


def draw(image, xyxy, dest, exemplar=None):
    canvas = image.copy()
    pen = ImageDraw.Draw(canvas)
    for box in xyxy:
        pen.rectangle(list(box), outline=(255, 40, 40), width=3)
    if exemplar is not None:
        pen.rectangle(list(exemplar), outline=(40, 180, 255), width=3)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, quality=90)


def run_text(model, transform, device):
    out = ROOT / "artifacts/model_selection/runs/countgd_text_windows_dev"
    rows = []
    for sample in samples():
        image = Image.open(ROOT / sample["image"]).convert("RGB")
        width, height = image.size
        clean = out / sample["sample_id"] / "clean.jpg"
        clean.parent.mkdir(parents=True, exist_ok=True)
        if not clean.exists():
            image.save(clean, quality=90)
        for task in TASKS["tasks"]:
            boxes, scores, max_score = predict(model, transform, image, task["countgd_text"], [], device)
            xyxy = []
            if len(boxes):
                absolute = box_cxcywh_to_xyxy(boxes).numpy()
                absolute[:, [0, 2]] *= width
                absolute[:, [1, 3]] *= height
                xyxy = np.round(absolute, 1).tolist()
            dest = out / sample["sample_id"] / task["task_id"]
            draw(image, xyxy, dest / "overlay.jpg")
            payload = {
                "model": "CountGD",
                "mode": "text_only",
                "automatic": True,
                "exemplars": [],
                "device": device,
                "attention": "pure pytorch deformable attention; nvcc is not installed, so the CUDA op was not compiled" if device == "cpu" else "cuda",
                "sample_id": sample["sample_id"],
                "image": sample["image"],
                "task_id": task["task_id"],
                "text": task["countgd_text"],
                "caption_sent": task["countgd_text"] + " .",
                "confidence_thresh": CONFIDENCE,
                "filter_name": "sigmoid max logit > 0.23, official single_image_inference default",
                "max_score_before_filter": max_score,
                "raw_cxcywh_norm": np.round(boxes.numpy(), 4).tolist() if len(boxes) else [],
                "xyxy_px": xyxy,
                "scores": [round(float(s), 4) for s in scores],
                "n_boxes": len(xyxy),
                "not_floor_count": True,
                "not_ground_truth": True,
                "result_kind": "diagnostic_only",
            }
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            brief = {"sample_id": sample["sample_id"], "task_id": task["task_id"], "n_boxes": len(xyxy), "max_score": max_score}
            rows.append(brief)
            print(json.dumps(brief), flush=True)
    summary = {"mode": "text_only", "status": "diagnostic_only", "rows": rows, "not_floor_count": True}
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("COUNTGD_TEXT_OK", flush=True)


def run_visual(model, transform, device):
    spec_path = ROOT / "validation/model_selection/countgd_visual_exemplars.json"
    spec = json.loads(spec_path.read_text())
    out = ROOT / "artifacts/model_selection/runs/countgd_visual_windows_dev"
    rows = []
    for sample in samples():
        image = Image.open(ROOT / sample["image"]).convert("RGB")
        width, height = image.size
        for task in TASKS["tasks"]:
            key = f"{sample['sample_id']}:{task['task_id']}"
            entry = spec["entries"].get(key)
            dest = out / sample["sample_id"] / task["task_id"]
            dest.mkdir(parents=True, exist_ok=True)
            if not entry or entry.get("status") == "no_exemplar_marked":
                payload = {
                    "mode": "visual_exemplar",
                    "automatic": False,
                    "interactive": True,
                    "status": "no_exemplar_marked",
                    "sample_id": sample["sample_id"],
                    "task_id": task["task_id"],
                    "reason": (entry or {}).get("reason", "no honest instance marked on this query image"),
                    "n_boxes": None,
                    "not_ground_truth": True,
                    "result_kind": "diagnostic_only",
                }
                (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                rows.append({"sample_id": sample["sample_id"], "task_id": task["task_id"], "status": "no_exemplar_marked"})
                print(json.dumps(rows[-1]), flush=True)
                continue
            box = entry["xyxy_px"]
            boxes, scores, max_score = predict(model, transform, image, task["countgd_text"], [box], device)
            xyxy = []
            if len(boxes):
                absolute = box_cxcywh_to_xyxy(boxes).numpy()
                absolute[:, [0, 2]] *= width
                absolute[:, [1, 3]] *= height
                xyxy = np.round(absolute, 1).tolist()
            draw(image, xyxy, dest / "overlay.jpg", exemplar=box)
            payload = {
                "mode": "visual_exemplar",
                "automatic": False,
                "interactive": True,
                "exemplar_xyxy_px": box,
                "exemplar_origin": entry["origin"],
                "exemplar_is_not_ground_truth_for_other_objects": True,
                "text": task["countgd_text"],
                "confidence_thresh": CONFIDENCE,
                "max_score_before_filter": max_score,
                "xyxy_px": xyxy,
                "scores": [round(float(s), 4) for s in scores],
                "n_boxes": len(xyxy),
                "sample_id": sample["sample_id"],
                "task_id": task["task_id"],
                "not_floor_count": True,
                "result_kind": "diagnostic_only",
            }
            (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            brief = {"sample_id": sample["sample_id"], "task_id": task["task_id"], "status": "interactive", "n_boxes": len(xyxy)}
            rows.append(brief)
            print(json.dumps(brief), flush=True)
    (out / "summary.json").write_text(
        json.dumps({"mode": "visual_exemplar", "interactive": True, "rows": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("COUNTGD_VISUAL_OK", flush=True)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "text"
    device = sys.argv[2] if len(sys.argv) > 2 else "cpu"
    model, transform = build(device)
    if mode == "text":
        run_text(model, transform, device)
    elif mode == "visual":
        run_visual(model, transform, device)
    else:
        raise SystemExit("mode must be text or visual")
