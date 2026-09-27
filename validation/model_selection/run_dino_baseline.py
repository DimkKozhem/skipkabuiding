"""Grounding DINO base on the frozen selection manifest only. Holdout frames are not opened."""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw

ROOT = Path("/home/dimk/my_project/LCT2026")
OUT = ROOT / "artifacts/model_selection/runs/dino_base_baseline"
MANIFEST = ROOT / "validation/model_selection/manifest.json"
MODEL_ID = "IDEA-Research/grounding-dino-base"
LABELS = ["window", "window opening", "door", "column"]
BOX_THRESHOLD = 0.35
TEXT_THRESHOLD = 0.25


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

    device = "cuda:1"
    torch.cuda.set_device(device)
    torch.cuda.reset_peak_memory_stats(device)
    t0 = time.perf_counter()
    processor = AutoProcessor.from_pretrained(MODEL_ID)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(MODEL_ID).to(device)
    model.eval()
    load_s = round(time.perf_counter() - t0, 2)
    rows = []
    for sample in manifest["samples"]:
        path = ROOT / sample["image"]
        image = Image.open(path).convert("RGB")
        w, h = image.size
        inputs = processor(images=image, text=[LABELS], return_tensors="pt").to(device)
        started = time.perf_counter()
        with torch.inference_mode():
            outputs = model(**inputs)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
        processed = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            threshold=BOX_THRESHOLD,
            text_threshold=TEXT_THRESHOLD,
            target_sizes=[(h, w)],
        )[0]
        boxes = processed["boxes"].detach().cpu().tolist()
        scores = processed["scores"].detach().cpu().tolist()
        text_labels = [str(x) for x in processed["text_labels"]]
        dets = []
        draw = image.copy()
        pen = ImageDraw.Draw(draw)
        for box, score, label in zip(boxes, scores, text_labels):
            det = {"label": label, "score": round(float(score), 4), "bbox_xyxy": [round(float(v), 1) for v in box]}
            dets.append(det)
            x1, y1, x2, y2 = box
            pen.rectangle([x1, y1, x2, y2], outline=(255, 180, 0), width=3)
            pen.text((x1, max(0, y1 - 12)), f"{label} {det['score']}", fill=(255, 180, 0))
        frame_dir = OUT / sample["sample_id"]
        frame_dir.mkdir(parents=True, exist_ok=True)
        overlay = frame_dir / "overlay.jpg"
        draw.save(overlay, quality=90)
        row = {
            "sample_id": sample["sample_id"],
            "image": sample["image"],
            "sha256": sample["sha256"],
            "status": "success",
            "latency_ms": elapsed_ms,
            "n_detections": len(dets),
            "detections": dets,
            "overlay": str(overlay.relative_to(ROOT)),
        }
        (frame_dir / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({key: row[key] for key in ("sample_id", "status", "latency_ms", "n_detections")})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    summary = {
        "model": MODEL_ID,
        "revision": "12bdfa3120f3e7ec7b434d90674b3396eccf88eb",
        "sha256": "5548f844c928c4b6f411fa8cbcc2bfa8dbbba437cb1d513975519f93c2a9ed21",
        "device": device,
        "labels": LABELS,
        "box_threshold": BOX_THRESHOLD,
        "text_threshold": TEXT_THRESHOLD,
        "load_s": load_s,
        "peak_vram_mib": round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 1),
        "frames": rows,
        "note": "Frozen text list from artifacts/model_compare/protocol.json. Holdout frames were not read.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT / "summary.json"), "load_s": load_s, "peak_vram_mib": summary["peak_vram_mib"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
