"""CountGD text-only and one interactive exemplar on the frozen CMP subset."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
spec = importlib.util.spec_from_file_location(
    "countgd_dev", ROOT / "validation/model_selection/run_countgd_dev.py"
)
cg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cg)

SUB = json.loads((ROOT / "validation/model_selection/cmp_facade_subset_frozen.json").read_text())
IMG_ROOT = ROOT / "artifacts/model_selection/external/cmp_facade/subset"
OUT = ROOT / "artifacts/model_selection/runs/countgd_cmp_facade"
TASKS = ("window", "door")


def xyxy_of(boxes, width, height):
    import numpy as np
    from util.box_ops import box_cxcywh_to_xyxy

    if len(boxes) == 0:
        return []
    absolute = box_cxcywh_to_xyxy(boxes).numpy()
    absolute[:, [0, 2]] *= width
    absolute[:, [1, 3]] *= height
    return np.round(absolute, 1).tolist()


def main() -> None:
    device = "cpu"
    model, transform = cg.build(device)
    rows = []
    for sample in SUB["samples"]:
        image = __import__("PIL").Image.open(IMG_ROOT / sample["image"]).convert("RGB")
        width, height = image.size
        windows = [box["xyxy_norm"] for box in sample["boxes"] if box["label"] == "window"]
        exemplar = None
        if windows:
            x0, y0, x1, y1 = windows[0]
            exemplar = [x0 * width, y0 * height, x1 * width, y1 * height]
        for task in TASKS:
            boxes, scores, max_score = cg.predict(model, transform, image, task, [], device)
            xyxy = xyxy_of(boxes, width, height)
            dest = OUT / "text" / sample["sample_id"] / task
            cg.draw(image, xyxy, dest / "overlay.jpg")
            payload = {
                "mode": "text_only",
                "automatic": True,
                "sample_id": sample["sample_id"],
                "task_id": task,
                "text": task,
                "confidence_thresh": cg.CONFIDENCE,
                "n_boxes": len(xyxy),
                "xyxy_px": xyxy,
                "scores": [round(float(s), 4) for s in scores],
                "max_score_before_filter": max_score,
                "device": device,
                "attention": "pure pytorch, CUDA op not compiled",
            }
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "result.json").write_text(json.dumps(payload), encoding="utf-8")
            rows.append({"mode": "text", "sample_id": sample["sample_id"], "task_id": task, "n_boxes": len(xyxy)})
            print(json.dumps(rows[-1]), flush=True)
            if task != "window" or exemplar is None:
                continue
            boxes, scores, max_score = cg.predict(model, transform, image, task, [exemplar], device)
            xyxy = xyxy_of(boxes, width, height)
            dest = OUT / "visual" / sample["sample_id"] / task
            cg.draw(image, xyxy, dest / "overlay.jpg", exemplar=exemplar)
            payload = {
                "mode": "visual_exemplar",
                "automatic": False,
                "interactive": True,
                "exemplar_xyxy_px": [round(v, 1) for v in exemplar],
                "exemplar_origin": "first window rectangle in this image's CMP xml; excluded from the reference set",
                "exemplar_is_not_ground_truth_for_other_objects": True,
                "sample_id": sample["sample_id"],
                "task_id": task,
                "n_boxes": len(xyxy),
                "xyxy_px": xyxy,
                "scores": [round(float(s), 4) for s in scores],
                "max_score_before_filter": max_score,
            }
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "result.json").write_text(json.dumps(payload), encoding="utf-8")
            rows.append({"mode": "visual", "sample_id": sample["sample_id"], "task_id": task, "n_boxes": len(xyxy)})
            print(json.dumps(rows[-1]), flush=True)
    (OUT / "summary.json").write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print("COUNTGD_CMP_OK", flush=True)


if __name__ == "__main__":
    main()
