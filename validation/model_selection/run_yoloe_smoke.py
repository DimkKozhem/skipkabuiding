"""One-frame YOLOE-11L text-prompt smoke. Does not write production DB."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw

ROOT = Path("/home/dimk/my_project/LCT2026")
CKPT = ROOT / "artifacts/model_selection/weights/yoloe-11l-seg.pt"
OUT = ROOT / "artifacts/model_selection/runs/yoloe11l_smoke"
MANIFEST = ROOT / "validation/model_selection/manifest.json"
SAMPLE_ID = "s-check-office-a"
# Frozen before the run. Spaces are rejected by YOLOE.set_classes.
CLASSES = ["window", "window_opening", "door", "column"]
IMGSZ = 640
CONF = 0.25
DEVICE = "cuda:1"
EXPECTED_BYTES = 70982416


def main() -> None:
    size = CKPT.stat().st_size
    if size != EXPECTED_BYTES:
        raise SystemExit(f"checkpoint size {size} != {EXPECTED_BYTES}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    sample = next(item for item in manifest["samples"] if item["sample_id"] == SAMPLE_ID)
    image_path = ROOT / sample["image"]
    OUT.mkdir(parents=True, exist_ok=True)
    sent = OUT / "sent.jpg"
    shutil.copyfile(image_path, sent)

    from ultralytics import YOLOE

    torch.cuda.set_device(DEVICE)
    torch.cuda.reset_peak_memory_stats(DEVICE)
    t0 = time.perf_counter()
    model = YOLOE(str(CKPT))
    model.to(DEVICE)
    model.set_classes(CLASSES)
    load_s = round(time.perf_counter() - t0, 2)

    started = time.perf_counter()
    results = model.predict(str(sent), imgsz=IMGSZ, conf=CONF, device=DEVICE, verbose=False)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    result = results[0]
    names = result.names
    dets = []
    image = Image.open(sent).convert("RGB")
    pen = ImageDraw.Draw(image)
    boxes = result.boxes
    if boxes is not None:
        for box in boxes:
            xyxy = [round(float(v), 1) for v in box.xyxy[0].tolist()]
            cls_id = int(box.cls[0])
            label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(names[cls_id])
            score = round(float(box.conf[0]), 4)
            dets.append({"label": label, "score": score, "bbox_xyxy": xyxy})
            pen.rectangle(xyxy, outline=(255, 160, 0), width=3)
            pen.text((xyxy[0], max(0, xyxy[1] - 12)), f"{label} {score}", fill=(255, 160, 0))
    overlay = OUT / "overlay.jpg"
    image.save(overlay, quality=90)
    peak = round(torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024), 1)
    payload = {
        "model_id": "yoloe-11l-seg",
        "checkpoint": str(CKPT.relative_to(ROOT)),
        "revision": "b584da188a198a2e6aa0e013d3fef6d55b212603",
        "sample_id": SAMPLE_ID,
        "image": sample["image"],
        "sha256_image": sample["sha256"],
        "classes": CLASSES,
        "imgsz": IMGSZ,
        "conf": CONF,
        "device": DEVICE,
        "load_s": load_s,
        "latency_ms": elapsed_ms,
        "peak_mib": peak,
        "n_detections": len(dets),
        "detections": dets,
        "sent": str(sent.relative_to(ROOT)),
        "overlay": str(overlay.relative_to(ROOT)),
        "mode": "text_prompt",
        "note": "Smoke only. Counts are not precision. window_opening has no space because set_classes rejects spaces.",
    }
    (OUT / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: payload[k] for k in ("sample_id", "n_detections", "latency_ms", "load_s", "peak_mib")}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
