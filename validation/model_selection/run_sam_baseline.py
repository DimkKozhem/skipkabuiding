"""SAM 3.1 baseline on the frozen selection manifest. Does not write production DB."""

from __future__ import annotations

import json
import time
from pathlib import Path

import torch
from PIL import Image, ImageDraw

from sitewatch.perception.providers.sam3 import Sam3Provider, build_sam_prompts_from_ontology

ROOT = Path("/home/dimk/my_project/LCT2026")
OUT = ROOT / "artifacts/model_selection/runs/sam31_baseline"
MANIFEST = ROOT / "validation/model_selection/manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    pairs = build_sam_prompts_from_ontology(mvp_only=True)
    prompts = [prompt for _, prompt in pairs]
    OUT.mkdir(parents=True, exist_ok=True)
    provider = Sam3Provider(enabled=True)
    provider.device = "cuda:1"
    started = time.perf_counter()
    rows = []
    for index, sample in enumerate(manifest["samples"]):
        image = ROOT / sample["image"]
        frame_dir = OUT / sample["sample_id"]
        frame_dir.mkdir(parents=True, exist_ok=True)
        result = provider.segment(image, prompts, artifact_dir=frame_dir)
        dets = []
        for ev in result.evidence:
            box = ev.bbox
            dets.append(
                {
                    "raw_label": ev.raw_label,
                    "class_name": ev.class_name,
                    "score": round(float(ev.score or 0), 4),
                    "bbox_xyxy": [round(box.x1, 1), round(box.y1, 1), round(box.x2, 1), round(box.y2, 1)],
                }
            )
        overlay = Image.open(image).convert("RGB")
        pen = ImageDraw.Draw(overlay)
        for det in dets:
            x1, y1, x2, y2 = det["bbox_xyxy"]
            pen.rectangle([x1, y1, x2, y2], outline=(0, 200, 255), width=3)
            pen.text((x1, max(0, y1 - 12)), f"{det['class_name']} {det['score']}", fill=(0, 200, 255))
        overlay_path = frame_dir / "overlay.jpg"
        overlay.save(overlay_path, quality=90)
        row = {
            "sample_id": sample["sample_id"],
            "image": sample["image"],
            "sha256": sample["sha256"],
            "status": result.status.value,
            "error": result.error,
            "latency_ms": result.latency_ms,
            "n_detections": len(dets),
            "detections": dets,
            "overlay": str(overlay_path.relative_to(ROOT)),
            "extras": result.extras,
        }
        (frame_dir / "result.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        rows.append({key: row[key] for key in row if key != "detections"})
        print(json.dumps({"i": index, "sample_id": sample["sample_id"], "status": row["status"], "n": len(dets), "ms": result.latency_ms, "error": result.error}, ensure_ascii=False), flush=True)
        if result.status.value != "success":
            break
    device = torch.device("cuda:1")
    summary = {
        "model": "facebook/sam3.1",
        "checkpoint": "models/sam3.1_multiplex.pt",
        "sha256": "0567debeec80ba4ac6369540c6c248025283cb3ff2b92827509e57e2b3541cb6",
        "ultralytics": "8.4.146",
        "device": "cuda:1",
        "imgsz": provider.imgsz,
        "threshold": provider.threshold,
        "iou_nms": provider.iou_nms,
        "prompts": prompts,
        "prompt_pairs": pairs,
        "frames": rows,
        "elapsed_s": round(time.perf_counter() - started, 2),
        "peak_vram_mib": round(torch.cuda.max_memory_allocated(device) / (1024 * 1024), 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"wrote": str(OUT / "summary.json"), "frames": len(rows), "peak_vram_mib": summary["peak_vram_mib"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
