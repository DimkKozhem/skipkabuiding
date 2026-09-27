"""Stdin/stdout worker for Grounding DINO. Runs in an interpreter that has transformers.

The parent process stays free of that dependency. A failure here is a JSON line, not a fact.
"""

from __future__ import annotations

import json
import os
import sys
import time

os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


def main() -> int:
    payload = json.load(sys.stdin)
    prompts = list(payload.get("prompts") or [])
    model_id = str(payload.get("model") or "IDEA-Research/grounding-dino-base")
    revision = str(payload.get("revision") or "")
    device = str(payload.get("device") or "cpu")
    started = time.perf_counter()
    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    except Exception as exc:  # noqa: BLE001
        _emit({"status": "unavailable", "error": f"grounding_dino_no_transformers:{exc}", "detections": []})
        return 0

    try:
        processor = AutoProcessor.from_pretrained(model_id, revision=revision or None)
        model = AutoModelForZeroShotObjectDetection.from_pretrained(model_id, revision=revision or None)
        model = model.to(device)
        model.eval()
        image = Image.open(payload["image"]).convert("RGB")
        text = " . ".join(prompts) + " ."
        inputs = processor(images=image, text=text, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=float(payload.get("box_threshold") or 0.35),
            text_threshold=float(payload.get("text_threshold") or 0.25),
            target_sizes=[image.size[::-1]],
        )[0]
        labels = results.get("labels") or results.get("text_labels") or []
        if hasattr(labels, "tolist"):
            labels = labels.tolist()
        boxes = results["boxes"].tolist()
        scores = results["scores"].tolist()
        detections = []
        for box, score, label in zip(boxes, scores, labels or ["?"] * len(boxes)):
            detections.append(
                {
                    "class_name": str(label),
                    "bbox": {"x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3]},
                    "confidence": float(score),
                    "model_name": "grounding_dino",
                    "model_version": revision or "n/a",
                    "extra": {"role": "shadow_candidate", "accepted_into_fact": False, "raw_label": str(label)},
                }
            )
        status = "success" if detections else "empty_success"
        _emit(
            {
                "status": status,
                "detections": detections,
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        )
        return 0
    except Exception as exc:  # noqa: BLE001
        _emit({"status": "failed", "error": f"grounding_dino_failed:{exc}", "detections": []})
        return 1


def _emit(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
