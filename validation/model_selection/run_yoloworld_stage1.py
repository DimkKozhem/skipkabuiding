"""YOLO-World V2.1 L-stage1 inference.

checkpoint and input_resolution are separate fields.
This run uses l_stage1-7d280586.pth with the pretrain config whose
img_scale is 640. It does not load l_stage2 and does not use
yolov8l-worldv2.pt.

Official demo/image_demo.py filters scores after test_step, then draws
with cv2.imread(image_path). That name is not defined in the function
(the parameter is image), so this script follows the same init /
reparameterize / test_step path and draws with PIL.
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
YW = ROOT / "artifacts/model_selection/third_party/YOLO-World"
sys.path.insert(0, str(YW))
sys.path.insert(0, str(YW / "third_party/mmyolo"))

CKPT = ROOT / "artifacts/model_selection/weights/l_stage1-7d280586.pth"
CONFIG = (
    YW
    / "configs/pretrain/yolo_world_v2_l_vlpan_bn_2e-3_100e_4x8gpus_obj365v1_goldg_train_lvis_minival.py"
)
MANIFEST = ROOT / "validation/model_selection/manifest.json"
BUS = ROOT / "artifacts/model_selection/runs/yoloe11l_adapter/bus.jpg"
OUT = ROOT / "artifacts/model_selection/runs/yoloworld_v21_l_stage1_res640"
EXPECTED_BYTES = 441517208
EXPECTED_SHA = "7d2805862ce2000cceaf11b376f23f79609f03faaa2fbb1386c5757602272d70"
DEVICE = "cuda:1"
TEXTS = ["window", "window opening", "door", "column"]
CONTROL_TEXTS = ["person", "bus"]
CONTROL_POINT = 0.25
PROFILE = "stage1"
EXPECTED_SCALE = (640, 640)
CHECKPOINT_ID = "l_stage1-7d280586"


def _apply_profile() -> None:
    global CKPT, CONFIG, OUT, EXPECTED_BYTES, EXPECTED_SHA, PROFILE, EXPECTED_SCALE, CHECKPOINT_ID
    name = sys.argv[1] if len(sys.argv) > 1 else "stage1"
    if name == "stage1":
        return
    if name != "stage2":
        raise SystemExit(f"unknown profile {name}")
    PROFILE = "stage2"
    CHECKPOINT_ID = "l_stage2-b3e3dc3f"
    CKPT = ROOT / "artifacts/model_selection/weights/l_stage2-b3e3dc3f.pth"
    CONFIG = (
        YW
        / "configs/pretrain/yolo_world_v2_l_vlpan_bn_2e-3_100e_4x8gpus_obj365v1_goldg_train_1280ft_lvis_minival.py"
    )
    OUT = ROOT / "artifacts/model_selection/runs/yoloworld_v21_l_stage2_res1280"
    EXPECTED_BYTES = 441517219
    EXPECTED_SHA = "b3e3dc3fdc654b72dd35dcb4743fe4670718f510798729a057fa457fda4a83f6"
    EXPECTED_SCALE = (1280, 1280)


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _overlay(image_path: Path, dets: list[dict], dest: Path) -> None:
    from PIL import Image, ImageDraw

    image = Image.open(image_path).convert("RGB")
    pen = ImageDraw.Draw(image)
    for det in dets:
        x1, y1, x2, y2 = det["bbox_xyxy"]
        pen.rectangle([x1, y1, x2, y2], outline=(80, 180, 255), width=3)
        pen.text((x1, max(0, y1 - 12)), f"{det['text']} {det['score']}", fill=(80, 180, 255))
    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, quality=90)


def _instances_to_rows(pred, texts: list[list[str]], image_size: tuple[int, int]) -> list[dict]:
    width, height = image_size
    if len(pred) == 0:
        return []
    bboxes = pred.bboxes
    labels = pred.labels
    scores = pred.scores
    rows = []
    for index in range(len(scores)):
        xyxy = [round(float(v), 1) for v in bboxes[index].tolist()]
        class_id = int(labels[index])
        text = texts[class_id][0] if class_id < len(texts) else str(class_id)
        x1, y1, x2, y2 = xyxy
        rows.append(
            {
                "text": text,
                "class_id": class_id,
                "score": round(float(scores[index]), 4),
                "bbox_xyxy": xyxy,
                "inside_image": 0 <= x1 <= x2 <= width and 0 <= y1 <= y2 <= height,
            }
        )
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def _summarize(rows: list[dict]) -> dict:
    return {
        "n": len(rows),
        "n_inside": sum(1 for row in rows if row["inside_image"]),
        "max_score": max((row["score"] for row in rows), default=None),
        "by_text": {
            text: sum(1 for row in rows if row["text"] == text)
            for text in sorted({row["text"] for row in rows})
        },
    }


def main() -> None:
    _apply_profile()
    if CKPT.stat().st_size != EXPECTED_BYTES:
        raise SystemExit(f"unexpected checkpoint size {CKPT.stat().st_size}")
    digest = _sha256(CKPT)
    if digest != EXPECTED_SHA:
        raise SystemExit(f"checkpoint sha256 mismatch {digest}")
    if not BUS.is_file():
        raise SystemExit(f"missing control image {BUS}")

    import torch
    from mmengine.config import Config
    from mmengine.dataset import Compose
    from mmengine.runner.amp import autocast
    from mmdet.apis import init_detector
    from mmdet.utils import get_test_pipeline_cfg
    from PIL import Image

    import mmyolo  # noqa: F401  registers YOLOv8 modules used by the config
    import yolo_world  # noqa: F401

    cfg = Config.fromfile(str(CONFIG))
    img_scale = tuple(cfg.img_scale)
    if img_scale != EXPECTED_SCALE:
        raise SystemExit(f"{PROFILE} config img_scale is {img_scale}, expected {EXPECTED_SCALE}")
    cfg.load_from = str(CKPT)

    torch.cuda.set_device(DEVICE)
    torch.cuda.reset_peak_memory_stats(DEVICE)
    t0 = time.perf_counter()
    model = init_detector(cfg, checkpoint=str(CKPT), device=DEVICE, palette="random")
    load_s = round(time.perf_counter() - t0, 2)
    model.eval()

    test_pipeline = Compose(get_test_pipeline_cfg(cfg=cfg))
    # Model test_cfg already keeps score_thr 0.001, NMS iou 0.7, max_per_img 300.
    nms_cfg = dict(cfg.model_test_cfg)

    def predict(image_path: Path, phrases: list[str]) -> list[dict]:
        texts = [[phrase] for phrase in phrases] + [[" "]]
        model.reparameterize(texts)
        data_info = dict(img_id=0, img_path=str(image_path), texts=texts)
        data_info = test_pipeline(data_info)
        data_batch = dict(
            inputs=data_info["inputs"].unsqueeze(0),
            data_samples=[data_info["data_samples"]],
        )
        with autocast(enabled=False), torch.no_grad():
            output = model.test_step(data_batch)[0]
        pred = output.pred_instances.cpu()
        image = Image.open(image_path)
        return _instances_to_rows(pred, texts, image.size)

    def save_pair(image_path: Path, phrases: list[str], dest: Path, meta: dict) -> dict:
        started = time.perf_counter()
        rows = predict(image_path, phrases)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        kept = [row for row in rows if row["score"] >= CONTROL_POINT]
        dest.mkdir(parents=True, exist_ok=True)
        _overlay(image_path, rows[:30], dest / "overlay_post_nms.jpg")
        _overlay(image_path, kept, dest / "overlay_conf_0.25.jpg")
        payload = {
            **meta,
            "phrases": phrases,
            "checkpoint": str(CKPT.relative_to(ROOT)),
            "input_resolution": list(img_scale),
            "latency_ms": latency_ms,
            "nms": {
                "note": "test_step output is after NMS. score_thr 0.001 is the model filter before NMS, not raw logits.",
                "model_test_cfg": nms_cfg,
            },
            "post_nms": {**_summarize(rows), "detections": rows},
            "conf_0.25": {**_summarize(kept), "detections": kept},
            "tp_fp_fn": "not_applicable_no_human_box_gt",
        }
        (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "n_post_nms": payload["post_nms"]["n"],
            "max_post_nms": payload["post_nms"]["max_score"],
            "n_0.25": payload["conf_0.25"]["n"],
            "by_text_0.25": payload["conf_0.25"]["by_text"],
            "latency_ms": latency_ms,
        }

    OUT.mkdir(parents=True, exist_ok=True)
    control_brief = save_pair(
        BUS,
        CONTROL_TEXTS,
        OUT / "official_person_bus",
        {"role": "official_control", "image": str(BUS.relative_to(ROOT))},
    )
    control = json.loads((OUT / "official_person_bus" / "result.json").read_text(encoding="utf-8"))
    names_post = set(control["post_nms"]["by_text"])
    adapter_ok = (
        {"person", "bus"} <= names_post
        and control["post_nms"]["n_inside"] == control["post_nms"]["n"]
        and control["post_nms"]["n"] > 0
    )
    control["adapter_ok"] = adapter_ok
    (OUT / "official_person_bus" / "result.json").write_text(
        json.dumps(control, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps({"control": control_brief, "adapter_ok": adapter_ok}, ensure_ascii=False), flush=True)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    dev = [sample for sample in manifest["samples"] if sample["split"] == "dev"]
    if any(sample.get("split") == "holdout" for sample in dev):
        raise SystemExit("refusing holdout")
    dev_rows = []
    for sample in dev:
        image_path = ROOT / sample["image"]
        brief = save_pair(
            image_path,
            TEXTS,
            OUT / "dev" / sample["sample_id"],
            {
                "role": "dev",
                "sample_id": sample["sample_id"],
                "split": sample["split"],
                "image": sample["image"],
                "sha256_image": sample["sha256"],
            },
        )
        brief["sample_id"] = sample["sample_id"]
        dev_rows.append(brief)
        print(json.dumps(brief, ensure_ascii=False), flush=True)

    import mmcv
    import mmdet
    import mmengine

    peak = round(torch.cuda.max_memory_allocated(DEVICE) / (1024 * 1024), 1)
    summary = {
        "model_id": "yolo-world-v2.1-l",
        "checkpoint_id": CHECKPOINT_ID,
        "checkpoint": str(CKPT.relative_to(ROOT)),
        "bytes": EXPECTED_BYTES,
        "sha256": EXPECTED_SHA,
        "input_resolution": list(img_scale),
        "config": str(CONFIG.relative_to(ROOT)),
        "stage2_downloaded": PROFILE == "stage2",
        "baked_load_from_ignored": (
            "pretrained_models/yolo_world_v2_l_obj365v1_goldg_pretrain-a82b1fe3.pth"
            if PROFILE == "stage2"
            else None
        ),
        "input_resolution_note": "800 and 1280 on l_stage2 would be two modes of one checkpoint. This run is 1280 only.",
        "ultralytics_world_substituted": False,
        "source_syntax_fix": "yolo_world.py reparameterize assigned to None; changed the unused mask target to _. Checkpoint and config unchanged.",
        "init_palette": "random. Default palette=none builds the LVIS val set for colors only; that annotation is not on this machine. Palette does not change weights or texts.",
        "text_backbone": "openai/clip-vit-base-patch32",
        "padding_token": " ",
        "phrases_dev": TEXTS,
        "device": DEVICE,
        "load_s": load_s,
        "peak_mib": peak,
        "versions": {
            "torch": torch.__version__,
            "mmcv": mmcv.__version__,
            "mmdet": mmdet.__version__,
            "mmengine": mmengine.__version__,
            "mmyolo": mmyolo.__version__,
        },
        "mmdet_3_0_0_with_mmcv_2_1_0": "import failed: AssertionError MMCV==2.1.0 is used but incompatible. Please install mmcv>=2.0.0rc4, <2.1.0.",
        "env": ".venv-yoloworld",
        "main_venv_unchanged": True,
        "adapter_ok": adapter_ok,
        "control": control_brief,
        "dev": dev_rows,
        "split": "dev",
        "quality": "not_evaluated",
        "winner": None,
        "nms_note": "Saved boxes are post-NMS (model score_thr 0.001, iou 0.7, max_per_img 300). conf 0.25 is a filter of that set, not a second model.",
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if not adapter_ok:
        raise SystemExit("control image did not yield person and bus at conf 0.25")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "error.txt").write_text(traceback.format_exc(), encoding="utf-8")
        raise
