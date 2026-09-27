"""YOLOE-11L with the same phrases, frames and thresholds as YOLOE-26L.

New configuration. Does not replace yoloe11l_text_v1.
conf 0.001 results are post-NMS, not raw scores before NMS.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw

ROOT = Path("/home/dimk/my_project/LCT2026")
CKPT = ROOT / "artifacts/model_selection/weights/yoloe-11l-seg.pt"
CLIP = ROOT / "artifacts/model_selection/weights/mobileclip_blt.ts"
MANIFEST = ROOT / "validation/model_selection/manifest.json"
BUS = ROOT / "artifacts/model_selection/runs/yoloe11l_adapter/bus.jpg"
OUT = ROOT / "artifacts/model_selection/runs/yoloe11l_text_natural_v1"
EXPECTED_BYTES = 70982416
EXPECTED_SHA = "a993fb0fc7c8830939ae14e6434a925dd1179428158c2761482eb8a8d8a3699f"
DEVICE = "cuda:1"
IMGSZ = 640
IOU = 0.7
MAX_DET = 300
# Natural phrases. Internal class ids are stored separately after set_classes.
TEXTS = ["window", "window opening", "door", "column"]
CONTROL_TEXTS = ["person", "bus"]


def _rows(result, image_size: tuple[int, int]) -> list[dict]:
    width, height = image_size
    names = result.names
    boxes = result.boxes
    if boxes is None:
        return []
    dets = []
    for box in boxes:
        xyxy = [round(float(v), 1) for v in box.xyxy[0].tolist()]
        class_id = int(box.cls[0])
        text = names.get(class_id, str(class_id)) if isinstance(names, dict) else str(names[class_id])
        x1, y1, x2, y2 = xyxy
        dets.append(
            {
                "text": text,
                "class_id": class_id,
                "score": round(float(box.conf[0]), 4),
                "bbox_xyxy": xyxy,
                "inside_image": 0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height,
            }
        )
    return dets


def _overlay(image_path: Path, dets: list[dict], dest: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    pen = ImageDraw.Draw(image)
    for det in dets:
        x1, y1, x2, y2 = det["bbox_xyxy"]
        pen.rectangle([x1, y1, x2, y2], outline=(80, 180, 255), width=3)
        pen.text((x1, max(0, y1 - 12)), f"{det['text']} {det['score']}", fill=(80, 180, 255))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, quality=90)


def _predict(model, source: Path, texts: list[str], conf: float) -> dict:
    model.set_classes(texts, model.get_text_pe(texts))
    names = model.model.names
    started = time.perf_counter()
    result = model.predict(
        str(source), imgsz=IMGSZ, conf=conf, iou=IOU, max_det=MAX_DET, device=DEVICE, verbose=False
    )[0]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    image = Image.open(source)
    dets = _rows(result, image.size)
    return {
        "texts": list(names.values()) if isinstance(names, dict) else list(names),
        "text_model": getattr(model.model, "text_model", None),
        "pe_shape": list(model.model.pe.shape),
        "latency_ms": elapsed_ms,
        "n": len(dets),
        "n_inside": sum(1 for det in dets if det["inside_image"]),
        "max_score": max((det["score"] for det in dets), default=None),
        "detections": dets,
    }


def _save_frame(model, sample: dict, conf: float, config_id: str) -> dict:
    image_path = ROOT / sample["image"]
    frame_dir = OUT / config_id / sample["sample_id"]
    frame_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image_path, frame_dir / "sent.jpg")
    pred = _predict(model, image_path, TEXTS, conf)
    _overlay(image_path, pred["detections"], frame_dir / "overlay.jpg")
    row = {
        "config_id": config_id,
        "sample_id": sample["sample_id"],
        "split": sample["split"],
        "image": sample["image"],
        "sha256_image": sample["sha256"],
        "texts": TEXTS,
        "class_ids": {text: index for index, text in enumerate(pred["texts"])},
        "imgsz": IMGSZ,
        "conf": conf,
        "iou": IOU,
        "max_det": MAX_DET,
        "text_model": pred["text_model"],
        "n_detections": pred["n"],
        "n_inside": pred["n_inside"],
        "max_score": pred["max_score"],
        "latency_ms": pred["latency_ms"],
        "detections": pred["detections"],
        "tp_fp_fn": "not_applicable_no_human_box_gt",
    }
    (frame_dir / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
    return {k: row[k] for k in row if k != "detections"}


def main() -> None:
    os.chdir(CLIP.parent)
    if CKPT.stat().st_size != EXPECTED_BYTES:
        raise SystemExit(f"unexpected checkpoint size {CKPT.stat().st_size}")
    if not CLIP.is_file():
        raise SystemExit(f"missing text encoder {CLIP}")
    from ultralytics import YOLOE, __version__ as ultralytics_version

    torch.cuda.set_device(DEVICE)
    torch.cuda.reset_peak_memory_stats(DEVICE)
    t0 = time.perf_counter()
    model = YOLOE(str(CKPT))
    model.to(DEVICE)
    load_s = round(time.perf_counter() - t0, 2)
    head = model.model.model[-1]
    if hasattr(head, "lrpc"):
        raise SystemExit("prompt-free checkpoint is not this comparison")
    text_model = getattr(model.model, "text_model", None)
    if text_model == "mobileclip2:b":
        raise SystemExit("this configuration must use the YOLOE-11 encoder, not mobileclip2")

    control = _predict(model, BUS, CONTROL_TEXTS, 0.25)
    control_dir = OUT / "official_person_bus"
    control_dir.mkdir(parents=True, exist_ok=True)
    _overlay(BUS, control["detections"], control_dir / "overlay.jpg")
    adapter_ok = control["texts"] == CONTROL_TEXTS and control["n"] > 0 and control["n"] == control["n_inside"]
    (control_dir / "control.json").write_text(
        json.dumps(
            {
                "texts": CONTROL_TEXTS,
                "text_model": control["text_model"],
                "pe_shape": control["pe_shape"],
                "n": control["n"],
                "max_score": control["max_score"],
                "detections": control["detections"],
                "adapter_ok": adapter_ok,
                "ultralytics": ultralytics_version,
                "load_s": load_s,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(json.dumps({"control_n": control["n"], "text_model": control["text_model"], "adapter_ok": adapter_ok}, ensure_ascii=False), flush=True)
    if not adapter_ok:
        raise SystemExit("official person/bus example failed")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev = [sample for sample in manifest["samples"] if sample["split"] == "dev"]
    low = [_save_frame(model, sample, 0.001, "conf_0.001") for sample in dev]
    high = [_save_frame(model, sample, 0.25, "conf_0.25") for sample in dev]
    for row in high:
        print(json.dumps({"sample_id": row["sample_id"], "conf": 0.25, "n": row["n_detections"], "max_from_low": None}, ensure_ascii=False), flush=True)
    peak = round(torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024), 1)
    summary = {
        "model_id": "yoloe-11l-seg",
        "checkpoint": str(CKPT.relative_to(ROOT)),
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA,
        "source": "https://huggingface.co/jameslahm/yoloe/resolve/main/yoloe-11l-seg.pt",
        "text_encoder": "mobileclip_blt.ts",
        "text_model": text_model,
        "ultralytics": ultralytics_version,
        "nms_note": "conf 0.001 rows are Ultralytics NMS output, not raw scores before NMS.",
        "baseline_untouched": "artifacts/model_selection/runs/yoloe11l_text_v1",
        "mode": "text_prompt",
        "prompt_free": False,
        "imgsz": IMGSZ,
        "iou": IOU,
        "device": DEVICE,
        "load_s": load_s,
        "peak_mib": peak,
        "split": "dev",
        "quality": "not_evaluated",
        "winner": None,
        "low_conf": low,
        "conf_0.25": high,
        "prompt_texts": TEXTS,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
