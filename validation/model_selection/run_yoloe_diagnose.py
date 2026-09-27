"""YOLOE-11L adapter check, then the frozen diagnostic split.

The office smoke at conf 0.25 stays as its own result. This script does not
retune that threshold. A low-confidence pass is a separate configuration.
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
OFFICE = ROOT / "data/sources/office_domodedovo/frames/2022-08-08.jpg"
EXPECTED_BYTES = 70982416
EXPECTED_SHA = "a993fb0fc7c8830939ae14e6434a925dd1179428158c2761482eb8a8d8a3699f"
DEVICE = "cuda:1"
IMGSZ = 640
IOU = 0.7
MAX_DET = 300
# Same list as the office smoke. Not changed after seeing that frame.
DIAG_CLASSES = ["window", "window_opening", "door", "column"]
DIAG_CONF = 0.25
# Official Ultralytics text-prompt example. Not a construction class list.
CONTROL_CLASSES = ["person", "bus"]
CONTROL_CONF = 0.25
PREFILTER_CONF = 0.001


def _boxes(result, image_size: tuple[int, int]) -> list[dict]:
    width, height = image_size
    names = result.names
    rows = []
    boxes = result.boxes
    if boxes is None:
        return rows
    for box in boxes:
        xyxy = [round(float(v), 1) for v in box.xyxy[0].tolist()]
        cls_id = int(box.cls[0])
        label = names.get(cls_id, str(cls_id)) if isinstance(names, dict) else str(names[cls_id])
        x1, y1, x2, y2 = xyxy
        rows.append(
            {
                "label": label,
                "class_id": cls_id,
                "score": round(float(box.conf[0]), 4),
                "bbox_xyxy": xyxy,
                "inside_image": 0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height,
            }
        )
    return rows


def _overlay(image_path: Path, dets: list[dict], dest: Path) -> None:
    image = Image.open(image_path).convert("RGB")
    pen = ImageDraw.Draw(image)
    for det in dets:
        x1, y1, x2, y2 = det["bbox_xyxy"]
        pen.rectangle([x1, y1, x2, y2], outline=(255, 160, 0), width=3)
        pen.text((x1, max(0, y1 - 12)), f"{det['label']} {det['score']}", fill=(255, 160, 0))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, quality=90)


def _predict(model, source: Path, classes: list[str], conf: float):
    model.set_classes(classes, model.get_text_pe(classes))
    names = model.model.names
    pe = model.model.pe
    started = time.perf_counter()
    result = model.predict(
        str(source),
        imgsz=IMGSZ,
        conf=conf,
        iou=IOU,
        max_det=MAX_DET,
        device=DEVICE,
        verbose=False,
    )[0]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    image = Image.open(source)
    dets = _boxes(result, image.size)
    return {
        "names_after": list(names.values()) if isinstance(names, dict) else list(names),
        "pe_shape": list(pe.shape) if pe is not None else None,
        "orig_shape": list(result.orig_shape),
        "latency_ms": elapsed_ms,
        "n": len(dets),
        "n_inside": sum(1 for det in dets if det["inside_image"]),
        "max_score": max((det["score"] for det in dets), default=None),
        "detections": dets,
    }


def main() -> None:
    os.chdir(CLIP.parent)
    size = CKPT.stat().st_size
    if size != EXPECTED_BYTES:
        raise SystemExit(f"checkpoint size {size} != {EXPECTED_BYTES}")
    if not CLIP.is_file():
        raise SystemExit(f"missing text encoder {CLIP}")
    if not BUS.is_file():
        raise SystemExit(f"missing official example image {BUS}")

    from ultralytics import YOLOE, __version__ as ultralytics_version

    torch.cuda.set_device(DEVICE)
    torch.cuda.reset_peak_memory_stats(DEVICE)
    t0 = time.perf_counter()
    model = YOLOE(str(CKPT))
    model.to(DEVICE)
    load_s = round(time.perf_counter() - t0, 2)
    head = model.model.model[-1]
    prompt_free = hasattr(head, "lrpc")
    names_before = list(model.names.values()) if isinstance(model.names, dict) else list(model.names)
    identity = {
        "checkpoint": str(CKPT.relative_to(ROOT)),
        "bytes": size,
        "sha256": EXPECTED_SHA,
        "source": "https://huggingface.co/jameslahm/yoloe/resolve/main/yoloe-11l-seg.pt",
        "revision": "b584da188a198a2e6aa0e013d3fef6d55b212603",
        "ultralytics": ultralytics_version,
        "task": model.task,
        "prompt_free": prompt_free,
        "text_model": getattr(model.model, "text_model", "mobileclip:blt"),
        "names_before_set_classes_count": len(names_before),
        "load_s": load_s,
    }
    if prompt_free:
        identity["adapter"] = "blocked_prompt_free_checkpoint"
        out = ROOT / "artifacts/model_selection/runs/yoloe11l_adapter/adapter.json"
        out.write_text(json.dumps(identity, ensure_ascii=False, indent=2), encoding="utf-8")
        raise SystemExit("checkpoint is prompt-free and cannot take text classes")

    control = _predict(model, BUS, CONTROL_CLASSES, CONTROL_CONF)
    control_dir = ROOT / "artifacts/model_selection/runs/yoloe11l_adapter"
    _overlay(BUS, control["detections"], control_dir / "bus_overlay.jpg")
    control_payload = {
        **identity,
        "config_id": "official_text_person_bus_v1",
        "mode": "text_prompt",
        "source_image": "https://ultralytics.com/images/bus.jpg",
        "classes": CONTROL_CLASSES,
        "imgsz": IMGSZ,
        "conf": CONTROL_CONF,
        "iou": IOU,
        "max_det": MAX_DET,
        "postprocess": "ultralytics conf filter then class-aware NMS; boxes are xyxy in the original image",
        **{k: control[k] for k in ("names_after", "pe_shape", "orig_shape", "latency_ms", "n", "n_inside", "max_score", "detections")},
    }
    (control_dir / "control.json").write_text(json.dumps(control_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    classes_applied = control["names_after"] == CONTROL_CLASSES and control["pe_shape"][1] == len(CONTROL_CLASSES)
    adapter_ok = classes_applied and control["n"] > 0 and control["n"] == control["n_inside"]
    print(json.dumps({"control_n": control["n"], "classes_applied": classes_applied, "adapter_ok": adapter_ok}, ensure_ascii=False), flush=True)
    if not adapter_ok:
        raise SystemExit("official text-prompt example did not return in-image boxes")

    pre = _predict(model, OFFICE, DIAG_CLASSES, PREFILTER_CONF)
    pre_dir = ROOT / "artifacts/model_selection/runs/yoloe11l_text_prefilter_v1"
    pre_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(OFFICE, pre_dir / "sent.jpg")
    _overlay(OFFICE, pre["detections"], pre_dir / "overlay.jpg")
    scores = [det["score"] for det in pre["detections"]]
    pre_payload = {
        "config_id": "yoloe11l_text_prefilter_v1",
        "purpose": "scores before the frozen conf 0.25 filter; not a selection threshold",
        "sample_id": "s-check-office-a",
        "classes": DIAG_CLASSES,
        "imgsz": IMGSZ,
        "conf": PREFILTER_CONF,
        "iou": IOU,
        "max_det": MAX_DET,
        "names_after": pre["names_after"],
        "pe_shape": pre["pe_shape"],
        "n": pre["n"],
        "n_inside": pre["n_inside"],
        "max_score": pre["max_score"],
        "n_score_ge_0.25": sum(score >= 0.25 for score in scores),
        "n_score_ge_0.05": sum(score >= 0.05 for score in scores),
        "detections": pre["detections"],
        "recall": "not_applicable_no_human_box_gt",
    }
    (pre_dir / "result.json").write_text(json.dumps(pre_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"prefilter_n": pre["n"], "max_score": pre["max_score"], "n_ge_0.25": pre_payload["n_score_ge_0.25"]}, ensure_ascii=False), flush=True)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    out = ROOT / "artifacts/model_selection/runs/yoloe11l_text_v1"
    rows = []
    for sample in manifest["samples"]:
        if sample["split"] != "dev":
            continue
        image_path = ROOT / sample["image"]
        frame_dir = out / sample["sample_id"]
        frame_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, frame_dir / "sent.jpg")
        pred = _predict(model, image_path, DIAG_CLASSES, DIAG_CONF)
        _overlay(image_path, pred["detections"], frame_dir / "overlay.jpg")
        row = {
            "config_id": "yoloe11l_text_v1",
            "sample_id": sample["sample_id"],
            "split": sample["split"],
            "image": sample["image"],
            "sha256_image": sample["sha256"],
            "classes": DIAG_CLASSES,
            "imgsz": IMGSZ,
            "conf": DIAG_CONF,
            "iou": IOU,
            "max_det": MAX_DET,
            "names_after": pred["names_after"],
            "n_detections": pred["n"],
            "n_inside": pred["n_inside"],
            "max_score": pred["max_score"],
            "latency_ms": pred["latency_ms"],
            "detections": pred["detections"],
            "recall": "not_applicable_no_human_box_gt",
        }
        (frame_dir / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({k: row[k] for k in row if k != "detections"})
        print(json.dumps({"sample_id": sample["sample_id"], "n": pred["n"], "max_score": pred["max_score"]}, ensure_ascii=False), flush=True)
    peak = round(torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024), 1)
    summary = {
        "config_id": "yoloe11l_text_v1",
        "status": "smoke_passed",
        "quality": "not_evaluated",
        "checkpoint": identity,
        "mode": "text_prompt",
        "classes": DIAG_CLASSES,
        "imgsz": IMGSZ,
        "conf": DIAG_CONF,
        "iou": IOU,
        "max_det": MAX_DET,
        "device": DEVICE,
        "split": "dev",
        "n_frames": len(rows),
        "frames": rows,
        "peak_mib": peak,
        "gt": "no human box labels; agent labels are not used as FN",
    }
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
