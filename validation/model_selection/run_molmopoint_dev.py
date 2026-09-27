"""MolmoPoint on the five diagnostic frames. Three frozen prompts. No floor count."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("USE_TORCH", "1")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import sys

# Torch is in myenv. Drop the broken system scipy and keep the smoke venv's
# transformers 4.57.1 ahead of myenv.
sys.path = [item for item in sys.path if "dist-packages" not in item]
sys.path.append("/home/dimk/my_project/myenv/lib/python3.10/site-packages")

import numpy as np
import torch
from PIL import Image, ImageDraw
from transformers import AutoModelForImageTextToText, AutoProcessor

ROOT = Path("/home/dimk/my_project/LCT2026")
CKPT = Path(
    "/home/dimk/.cache/huggingface/hub/models--allenai--MolmoPoint-8B/"
    "snapshots/188130f961c8e0888a34e11121a1423c461a01ba"
)
MANIFEST = ROOT / "validation/model_selection/manifest.json"
TASKS = json.loads((ROOT / "validation/model_selection/localization_tasks_frozen.json").read_text())
OUT = ROOT / "artifacts/model_selection/runs/molmopoint_windows_dev"
MAX_NEW_TOKENS = 512
POINT_TRIPLE = re.compile(r"<POINT_(\d+)> ?<POINT_(\d+)> ?<POINT_(\d+)> ?([0-9]+)")


def _points(raw) -> list[list[float]]:
    if raw is None or len(raw) == 0:
        return []
    return [[float(x) for x in row] for row in np.array(raw).tolist()]


def _flags(points: list[list[float]], width: int, height: int) -> dict:
    edge, roof, bottom, pairs = [], [], [], []
    coords = [(row[0], row[2], row[3]) for row in points]
    for pid, x, y in coords:
        if x <= 0.02 * width or x >= 0.98 * width or y <= 0.02 * height or y >= 0.98 * height:
            edge.append(pid)
        if y < 0.15 * height:
            roof.append(pid)
        if y > 0.85 * height:
            bottom.append(pid)
    for i, (a, ax, ay) in enumerate(coords):
        for b, bx, by in coords[i + 1 :]:
            dist = ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5
            if dist < 16:
                pairs.append({"ids": [a, b], "distance_px": round(dist, 1)})
    return {
        "on_image_edge_2pct": edge,
        "in_top_15pct": roof,
        "in_bottom_15pct": bottom,
        "near_duplicate_pairs_under_16px": pairs,
    }


def _generation_record(generated, text: str, points: list, max_new_tokens: int, processor) -> dict:
    n_gen = int(generated.shape[-1])
    tokenizer = processor.tokenizer
    im_end_id = tokenizer.convert_tokens_to_ids("<|im_end|>")
    last_id = int(generated[0, -1].item())
    ended = "<|im_end|>" in text or last_id in {tokenizer.eos_token_id, im_end_id}
    truncated = n_gen >= max_new_tokens and not ended
    if truncated:
        stop_reason = "max_new_tokens"
    elif ended:
        stop_reason = "eos"
    else:
        stop_reason = "other"
    triples = len(POINT_TRIPLE.findall(text))
    return {
        "max_new_tokens": max_new_tokens,
        "n_generated_tokens": n_gen,
        "stop_reason": stop_reason,
        "config_truncated": truncated,
        "point_token_triples": triples,
        "decoded_points": len(points),
        "decode_dropped_triples": triples - len(points),
        "separate_point_count_limit": None,
        "tokens_per_point_in_native_format": "3 POINT tokens plus the object id",
    }


def _overlay_gt(image: Image.Image, points: list[list[float]], boxes, width: int, height: int, dest: Path) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for box in boxes:
        x0, y0, x1, y1 = box
        draw.rectangle((x0 * width, y0 * height, x1 * width, y1 * height), outline=(40, 180, 255), width=2)
    for row in points:
        x, y = float(row[2]), float(row[3])
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), outline=(255, 40, 40), width=2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, quality=85)


def _overlay(image: Image.Image, points: list[list[float]], dest: Path) -> None:
    canvas = image.copy()
    draw = ImageDraw.Draw(canvas)
    for row in points:
        x, y = float(row[2]), float(row[3])
        draw.ellipse((x - 8, y - 8, x + 8, y + 8), outline=(255, 40, 40), width=3)
        draw.line((x - 12, y, x + 12, y), fill=(255, 40, 40), width=2)
        draw.line((x, y - 12, x, y + 12), fill=(255, 40, 40), width=2)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, quality=90)


def _swap_to_gpu(module, _args):
    torch.cuda.empty_cache()
    module.to("cuda:0")
    return None


def _swap_to_cpu(module, _args, output):
    module.to("cpu")
    torch.cuda.empty_cache()
    return output


def _free_mib() -> int:
    free, _total = torch.cuda.mem_get_info()
    return int(free // (1024 * 1024))


def _stop_for_headroom(out: Path, need_mib: int, sample_id: str, task_id: str) -> bool:
    """Чужие процессы не останавливать. Нехватка памяти — граница задания, не FN."""
    free_mib = _free_mib()
    if free_mib >= need_mib:
        return False
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "stopped": "task_boundary",
        "reason": "free GPU memory is below the gate",
        "other_processes": "not stopped",
        "sample_id": sample_id,
        "task_id": task_id,
        "free_mib": free_mib,
        "need_mib": need_mib,
    }
    (out / "stopped_headroom.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("STOP_HEADROOM", json.dumps(payload), flush=True)
    return True


def _place_frozen_decoder_cpu(model) -> int:
    """Owner placement bf16-decoder-blocks-cpu-36: все decoder blocks на CPU, swap по forward."""
    inner = model.model if hasattr(model, "model") else model
    for module in (
        inner.vit,
        inner.connector,
        inner.transformer.wte,
        inner.transformer.ln_f,
        inner.point_predictor,
    ):
        module.to("cuda:0")
    if hasattr(model, "lm_head"):
        model.lm_head.to("cuda:0")
    blocks = list(inner.transformer.blocks)
    for block in blocks:
        block.to("cpu")
        block.register_forward_pre_hook(_swap_to_gpu)
        block.register_forward_hook(_swap_to_cpu)
    kept = set(blocks)

    def _under_kept(module) -> bool:
        for block in kept:
            for sub in block.modules():
                if sub is module:
                    return True
        return False

    for module in model.modules():
        if _under_kept(module):
            continue
        for pname, param in list(module._parameters.items()):
            if param is not None and param.device.type == "cpu":
                module._parameters[pname] = torch.nn.Parameter(param.detach().to("cuda:0"), requires_grad=False)
        for bname, buf in list(module._buffers.items()):
            if buf is not None and buf.device.type == "cpu":
                module._buffers[bname] = buf.to("cuda:0")
    if inner.transformer.ln_f.weight.device.type != "cuda":
        raise SystemExit("ln_f is not on CUDA, image tensors would follow a bad device")
    torch.cuda.empty_cache()
    return len(blocks)


def _place(model, reserve_mib: int = 3000) -> int:
    inner = model.model if hasattr(model, "model") else model
    for module in (
        inner.vit,
        inner.connector,
        inner.transformer.wte,
        inner.transformer.ln_f,
        inner.point_predictor,
    ):
        module.to("cuda:0")
    if hasattr(model, "lm_head"):
        model.lm_head.to("cuda:0")
    blocks = list(inner.transformer.blocks)
    cpu_blocks = 0
    for index, block in enumerate(blocks):
        block.to("cuda:0")
        torch.cuda.synchronize()
        free, _total = torch.cuda.mem_get_info()
        if free < reserve_mib * 1024 * 1024:
            block.to("cpu")
            torch.cuda.empty_cache()
            for rest in blocks[index:]:
                rest.register_forward_pre_hook(_swap_to_gpu)
                rest.register_forward_hook(_swap_to_cpu)
                cpu_blocks += 1
            break
    kept = set(blocks[len(blocks) - cpu_blocks :])

    def _under_kept(module) -> bool:
        for block in kept:
            for sub in block.modules():
                if sub is module:
                    return True
        return False

    for module in model.modules():
        if _under_kept(module):
            continue
        for pname, param in list(module._parameters.items()):
            if param is not None and param.device.type == "cpu":
                module._parameters[pname] = torch.nn.Parameter(param.detach().to("cuda:0"), requires_grad=False)
        for bname, buf in list(module._buffers.items()):
            if buf is not None and buf.device.type == "cpu":
                module._buffers[bname] = buf.to("cuda:0")
    if inner.transformer.ln_f.weight.device.type != "cuda":
        raise SystemExit("ln_f is not on CUDA, image tensors would follow a bad device")
    return cpu_blocks


def main() -> int:
    manifest = json.loads(MANIFEST.read_text())
    wanted = set(TASKS["diagnostic_frames"])
    samples = [sample for sample in manifest["samples"] if sample["sample_id"] in wanted]
    if len(samples) != 5:
        raise SystemExit(f"expected 5 dev frames, got {len(samples)}")

    print("loading", flush=True)
    # Direct bf16 on the 4060 stops at about 14.4 GiB and still needs another
    # shard. Accelerate offload then leaves those weights as meta tensors, and
    # generate() cannot read them. Load real bf16 weights on CPU and move whole
    # blocks to the 4060 until the free margin is under 800 MiB.
    model = AutoModelForImageTextToText.from_pretrained(
        str(CKPT),
        trust_remote_code=True,
        dtype=torch.bfloat16,
        device_map={"": "cpu"},
        low_cpu_mem_usage=True,
    )
    if next(model.parameters()).device.type == "meta":
        raise SystemExit("weights stayed on the meta device; refusing to run")
    processor = AutoProcessor.from_pretrained(str(CKPT), trust_remote_code=True, padding_side="left")
    n_cpu = _place(model)
    infer_device = "cuda:0"
    print("infer_device", infer_device, "cpu_blocks", n_cpu, flush=True)
    rows = []
    for sample in samples:
        image_path = ROOT / sample["image"]
        image = Image.open(image_path).convert("RGB")
        clean = OUT / sample["sample_id"] / "clean.jpg"
        clean.parent.mkdir(parents=True, exist_ok=True)
        if not clean.exists():
            image.save(clean, quality=90)
        for task in TASKS["tasks"]:
            prompt = task["molmo_prompt"]
            dest = OUT / sample["sample_id"] / task["task_id"]
            done = dest / "result.json"
            if done.exists():
                payload = json.loads(done.read_text())
                rows.append({
                    "sample_id": sample["sample_id"],
                    "task_id": task["task_id"],
                    "n_points": payload["n_points"],
                    "hit_token_cap": payload["hit_token_cap"],
                    "flags": payload["flags"],
                })
                print("skip", sample["sample_id"], task["task_id"], flush=True)
                continue
            torch.cuda.empty_cache()
            messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
            inputs = processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
                padding=True,
                return_pointing_metadata=True,
            )
            metadata = inputs.pop("metadata")
            inputs = {key: value.to(infer_device) for key, value in inputs.items()}
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                output = model.generate(
                    **inputs,
                    logits_processor=model.build_logit_processor_from_inputs(inputs),
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            generated = output[:, inputs["input_ids"].size(1) :]
            text = processor.post_process_image_text_to_text(
                generated, skip_special_tokens=False, clean_up_tokenization_spaces=False
            )[0]
            points = _points(
                model.extract_image_points(
                    text, metadata["token_pooling"], metadata["subpatch_mapping"], metadata["image_sizes"]
                )
            )
            dest = OUT / sample["sample_id"] / task["task_id"]
            _overlay(image, points, dest / "overlay.jpg")
            payload = {
                "model": "allenai/MolmoPoint-8B",
                "revision": "188130f961c8e0888a34e11121a1423c461a01ba",
                "sample_id": sample["sample_id"],
                "split": sample["split"],
                "image": sample["image"],
                "task_id": task["task_id"],
                "prompt": prompt,
                "max_new_tokens": MAX_NEW_TOKENS,
                "generated_text": text,
                "hit_token_cap": generated.shape[-1] >= MAX_NEW_TOKENS and "<|im_end|>" not in text,
                "points": points,
                "point_schema": ["object_id", "image_num", "x", "y"],
                "n_points": len(points),
                "flags": _flags(points, image.size[0], image.size[1]),
                "not_floor_count": True,
                "not_ground_truth": True,
                "result_kind": "diagnostic_only",
            }
            (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            brief = {
                "sample_id": sample["sample_id"],
                "task_id": task["task_id"],
                "n_points": len(points),
                "hit_token_cap": payload["hit_token_cap"],
                "flags": payload["flags"],
            }
            rows.append(brief)
            print(json.dumps(brief, ensure_ascii=False), flush=True)
    summary = {
        "status": "diagnostic_only",
        "placement": "bf16, most blocks on CUDA_VISIBLE_DEVICES=1, remainder real CPU tensors swapped per forward",
        "peak_mib": round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1),
        "rows": rows,
        "not_floor_count": True,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MOLMO_DEV_OK", flush=True)
    return 0


def run_cmp() -> int:
    subset = json.loads((ROOT / "validation/model_selection/cmp_facade_subset_frozen.json").read_text())
    prompts = {
        "window": "Point to each visible window.",
        "door": "Point to each visible door.",
    }
    out = ROOT / "artifacts/model_selection/runs/molmopoint_cmp_facade"
    img_root = ROOT / "artifacts/model_selection/external/cmp_facade/subset"
    print("loading", flush=True)
    model = AutoModelForImageTextToText.from_pretrained(
        str(CKPT),
        trust_remote_code=True,
        dtype=torch.bfloat16,
        device_map={"": "cpu"},
        low_cpu_mem_usage=True,
    )
    processor = AutoProcessor.from_pretrained(str(CKPT), trust_remote_code=True, padding_side="left")
    # Owner placement: все decoder blocks на CPU (molmopoint_launch_plan.json).
    n_cpu = _place_frozen_decoder_cpu(model)
    print("cpu_blocks", n_cpu, "placement", "bf16-decoder-blocks-cpu-36", "free_mib_after_place", _free_mib(), flush=True)
    rows = []
    for sample in subset["samples"]:
        image = Image.open(img_root / sample["image"]).convert("RGB")
        for task_id, prompt in prompts.items():
            dest = out / sample["sample_id"] / task_id
            done = dest / "result.json"
            if done.exists():
                print("skip", sample["sample_id"], task_id, flush=True)
                continue
            torch.cuda.empty_cache()
            if _stop_for_headroom(out, 3072, sample["sample_id"], task_id):
                (out / "summary.json").write_text(json.dumps({"rows": rows, "stopped": "headroom"}, indent=2), encoding="utf-8")
                return 2
            messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
            inputs = processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
                padding=True,
                return_pointing_metadata=True,
            )
            metadata = inputs.pop("metadata")
            inputs = {key: value.to("cuda:0") for key, value in inputs.items()}
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                output = model.generate(
                    **inputs,
                    logits_processor=model.build_logit_processor_from_inputs(inputs),
                    max_new_tokens=MAX_NEW_TOKENS,
                )
            generated = output[:, inputs["input_ids"].size(1) :]
            text = processor.post_process_image_text_to_text(
                generated, skip_special_tokens=False, clean_up_tokenization_spaces=False
            )[0]
            points = _points(
                model.extract_image_points(
                    text, metadata["token_pooling"], metadata["subpatch_mapping"], metadata["image_sizes"]
                )
            )
            gen = _generation_record(generated, text, points, MAX_NEW_TOKENS, processor)
            _overlay(image, points, dest / "overlay.jpg")
            payload = {
                "model": "allenai/MolmoPoint-8B",
                "revision": "188130f961c8e0888a34e11121a1423c461a01ba",
                "sample_id": sample["sample_id"],
                "task_id": task_id,
                "prompt": prompt,
                "generated_text": text,
                "hit_token_cap": gen["config_truncated"],
                "gen": gen,
                "points": points,
                "n_points": len(points),
                "point_schema": ["object_id", "image_num", "x", "y"],
                "window_opening": "not scored; CMP has no window-opening class",
            }
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            brief = {
                "sample_id": sample["sample_id"],
                "task_id": task_id,
                "n_points": len(points),
                "hit_token_cap": payload["hit_token_cap"],
                "stop_reason": gen["stop_reason"],
                "n_generated_tokens": gen["n_generated_tokens"],
            }
            rows.append(brief)
            print(json.dumps(brief), flush=True)
            del output, generated, inputs
            torch.cuda.empty_cache()
    (out / "summary.json").write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print("MOLMO_CMP_OK", flush=True)
    return 0


def run_cmp_tech(generation_id: str | None = None) -> int:
    """Фиксированный технический пакет. Промпты не подбирать по ответу."""
    package = json.loads((ROOT / "validation/model_selection/cmp_molmopoint_tech_package.json").read_text())
    if generation_id is None:
        max_new_tokens = int(package["max_new_tokens"])
        out = ROOT / package["output_dir"]
        gen_label = package["id"]
        need_mib = 3072
        prompts_expected = package["prompts"]
    else:
        gen_cfg = json.loads((ROOT / "validation/model_selection/molmopoint_generation_v2.json").read_text())
        if gen_cfg["id"] != generation_id:
            raise SystemExit("generation config id mismatch")
        max_new_tokens = int(gen_cfg["max_new_tokens"])
        out = ROOT / gen_cfg["output_dir"]
        gen_label = gen_cfg["id"]
        need_mib = int(gen_cfg["memory_gate_mib"])
        prompts_expected = gen_cfg["prompts_unchanged"]
    sys.path.insert(0, str(ROOT / "validation/model_selection"))
    from cmp_point_eval import decode_audit, score_points

    prompts = package["prompts"]
    if prompts != prompts_expected:
        raise SystemExit("prompt changed")
    ram_kib = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemAvailable:"):
            ram_kib = int(line.split()[1])
    ram_gib = ram_kib / (1024 * 1024)
    gpu_free = _free_mib()
    print(f"precheck ram_gib={ram_gib:.1f} gpu_free_mib={gpu_free} max_new_tokens={max_new_tokens}", flush=True)
    if ram_gib < 24 or gpu_free < 8192:
        raise SystemExit(
            f"precheck failed: ram_gib={ram_gib:.1f} gpu_free_mib={gpu_free}; need 24 GiB RAM and 8 GiB GPU"
        )
    print("loading", flush=True)
    model = AutoModelForImageTextToText.from_pretrained(
        str(CKPT),
        trust_remote_code=True,
        dtype=torch.bfloat16,
        device_map={"": "cpu"},
        low_cpu_mem_usage=True,
    )
    processor = AutoProcessor.from_pretrained(str(CKPT), trust_remote_code=True, padding_side="left")
    n_cpu = _place_frozen_decoder_cpu(model)
    print("cpu_blocks", n_cpu, "placement", "bf16-decoder-blocks-cpu-36", "gpu_free_mib", _free_mib(), flush=True)
    if n_cpu != 36:
        raise SystemExit(f"expected 36 CPU decoder blocks, got {n_cpu}")
    rows = []
    for sample in package["samples"]:
        image = Image.open(ROOT / sample["image"]).convert("RGB")
        width, height = image.size
        for task_id, prompt in prompts.items():
            if prompt != package["prompts"][task_id]:
                raise SystemExit("prompt changed")
            dest = out / sample["sample_id"] / task_id
            done = dest / "result.json"
            if done.exists():
                print("skip", sample["sample_id"], task_id, flush=True)
                continue
            torch.cuda.empty_cache()
            if _stop_for_headroom(out, need_mib, sample["sample_id"], task_id):
                (out / "summary.json").write_text(
                    json.dumps({"rows": rows, "generation": gen_label, "stopped": "headroom"}, indent=2),
                    encoding="utf-8",
                )
                return 2
            messages = [{"role": "user", "content": [{"type": "image", "image": image}, {"type": "text", "text": prompt}]}]
            inputs = processor.apply_chat_template(
                messages,
                tokenize=True,
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
                padding=True,
                return_pointing_metadata=True,
            )
            metadata = inputs.pop("metadata")
            inputs = {key: value.to("cuda:0") for key, value in inputs.items()}
            torch.cuda.reset_peak_memory_stats()
            print("start", sample["sample_id"], task_id, flush=True)
            started = time.perf_counter()
            with torch.inference_mode(), torch.autocast("cuda", dtype=torch.bfloat16):
                output = model.generate(
                    **inputs,
                    logits_processor=model.build_logit_processor_from_inputs(inputs),
                    max_new_tokens=max_new_tokens,
                )
            elapsed_s = round(time.perf_counter() - started, 3)
            generated = output[:, inputs["input_ids"].size(1) :]
            text = processor.post_process_image_text_to_text(
                generated, skip_special_tokens=False, clean_up_tokenization_spaces=False
            )[0]
            points = _points(
                model.extract_image_points(
                    text, metadata["token_pooling"], metadata["subpatch_mapping"], metadata["image_sizes"]
                )
            )
            generation = _generation_record(generated, text, points, max_new_tokens, processor)
            audit = decode_audit(text, points, width, height, generation["config_truncated"])
            boxes = [tuple(box) for box in sample["boxes_xyxy_norm"][task_id]]
            normalized = [(row[2] / width, row[3] / height) for row in points]
            scored = score_points(normalized, boxes)
            n_pred = scored["n_pred"]
            n_gt = scored["n_gt"]
            scored["precision"] = None if n_pred == 0 else scored["tp"] / n_pred
            scored["recall"] = None if n_gt == 0 else scored["tp"] / n_gt
            scored["fn_is_not_only_visual"] = generation["config_truncated"]
            _overlay(image, points, dest / "overlay.jpg")
            _overlay_gt(image, points, boxes, width, height, dest / "overlay_gt.jpg")
            payload = {
                "model": package["model"],
                "revision": package["revision"],
                "generation_config": gen_label,
                "placement": "bf16-decoder-blocks-cpu-36",
                "cpu_blocks": n_cpu,
                "sample_id": sample["sample_id"],
                "task_id": task_id,
                "prompt": prompt,
                "generated_text": text,
                "hit_token_cap": generation["config_truncated"],
                "generation": generation,
                "elapsed_s": elapsed_s,
                "peak_mib": round(torch.cuda.max_memory_allocated() / (1024 * 1024), 1),
                "points": points,
                "n_points": len(points),
                "point_schema": ["object_id", "image_num", "x", "y"],
                "decode_audit": audit,
                "score": scored,
                "not_a_quality_report": True,
            }
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "result.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            brief = {
                "sample_id": sample["sample_id"],
                "task_id": task_id,
                "n_gt": scored["n_gt"],
                "n_points": len(points),
                "tp": scored["tp"],
                "fp": scored["fp"],
                "fn": scored["fn"],
                "stop_reason": generation["stop_reason"],
                "n_generated_tokens": generation["n_generated_tokens"],
                "config_truncated": generation["config_truncated"],
                "elapsed_s": elapsed_s,
                "peak_mib": payload["peak_mib"],
            }
            rows.append(brief)
            print(json.dumps(brief), flush=True)
            del output, generated, inputs
            torch.cuda.empty_cache()
    (out / "summary.json").write_text(
        json.dumps({"rows": rows, "package": package["id"], "generation": gen_label}, indent=2),
        encoding="utf-8",
    )
    print("MOLMO_CMP_TECH_OK", flush=True)
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cmp":
        sys.exit(run_cmp())
    if len(sys.argv) > 1 and sys.argv[1] == "cmp-tech":
        sys.exit(run_cmp_tech())
    if len(sys.argv) > 1 and sys.argv[1] == "cmp-tech-v2":
        raise SystemExit(
            "cmp-tech-v2: не этот owner-window. Сначала диагностический cmp восьми base "
            "(max_new_tokens 512). См. artifacts/model_selection/runs/molmopoint_cmp_facade/RUN_RECORD.json"
        )
    sys.exit(main())
