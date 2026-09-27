#!/usr/bin/env python3
"""Сборка diagnostic-manifest для MOCS YOLO (после появления images).

Не смешивает со Скрипкой / miniexcav. Не пишет production config.
Пороги miniexcav не использует.

Пример:
  LCT2026/.venv/bin/python validation/model_selection/external_equipment/scripts/build_mocs_diagnostic_manifest.py \\
    --images-root data/external/benchmark_sources/mocs_yolo_hf/images \\
    --labels-root data/external/benchmark_sources/hf_probe/mocs_labels_extracted/labels \\
    --out validation/model_selection/external_equipment/manifests/mocs_diagnostic_v1.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SIZE = {"relative_area_small": 0.04, "relative_area_medium": 0.16}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_mapping(path: Path) -> dict:
    return json.loads(path.read_text())


def parse_yolo(label_path: Path, mapping: dict) -> list[dict]:
    by_id = {c["source_id"]: c for c in mapping["classes"]}
    boxes = []
    for ln in label_path.read_text().splitlines():
        parts = ln.split()
        if len(parts) < 5:
            continue
        cid = int(float(parts[0]))
        xc, yc, w, h = map(float, parts[1:5])
        area = w * h
        if area < SIZE["relative_area_small"]:
            bin_name = "relative_area_small"
        elif area < SIZE["relative_area_medium"]:
            bin_name = "relative_area_medium"
        else:
            bin_name = "relative_area_large"
        meta = by_id[cid]
        boxes.append(
            {
                "source_class_id": cid,
                "source_class_name": meta["source_name"],
                "mapped_class": meta["mapped"],
                "policy": meta["policy"],
                "bbox_yolo_norm": [xc, yc, w, h],
                "area_ratio": area,
                "relative_area_bin": bin_name,
                "in_equipment_eval": cid in mapping["equipment_eval_ids"],
            }
        )
    return boxes


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--images-root", type=Path, required=True)
    ap.add_argument("--labels-root", type=Path, required=True)
    ap.add_argument(
        "--mapping",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/class_mapping_mocs.json",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "validation/model_selection/external_equipment/manifests/mocs_diagnostic_v1.json",
    )
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--n-tune", type=int, default=40)
    ap.add_argument("--n-diag-test", type=int, default=120)
    ap.add_argument("--prefer-split", default="val", choices=["train", "val", "test"])
    args = ap.parse_args()

    mapping = load_mapping(args.mapping)
    label_dir = args.labels_root / args.prefer_split
    img_dir = args.images_root / args.prefer_split
    if not img_dir.is_dir():
        # flat or images/val
        candidates = [args.images_root / args.prefer_split, args.images_root / "images" / args.prefer_split, args.images_root]
        img_dir = next((p for p in candidates if p.is_dir() and any(p.glob("*.jpg"))), None)
        if img_dir is None:
            raise SystemExit(
                f"Images not found under {args.images_root}. "
                "Extract images.rar first (expected ~9.0 GiB from AmiyaChan/mocs_yolo)."
            )

    samples = []
    for lp in sorted(label_dir.glob("*.txt")):
        if lp.name in {"classes.txt", "MOCS.txt"}:
            continue
        stem = lp.stem
        ip = None
        for ext in (".jpg", ".jpeg", ".png"):
            cand = img_dir / f"{stem}{ext}"
            if cand.is_file():
                ip = cand
                break
        if ip is None:
            continue
        boxes = parse_yolo(lp, mapping)
        eq = [b for b in boxes if b["in_equipment_eval"]]
        if len(eq) < 1:
            continue
        bins = Counter(b["relative_area_bin"] for b in eq)
        classes = {b["mapped_class"] for b in eq if b["mapped_class"]}
        samples.append(
            {
                "sample_id": f"mocs-{args.prefer_split}-{stem}",
                "image": str(ip.relative_to(ROOT)) if ip.is_relative_to(ROOT) else str(ip),
                "label": str(lp.relative_to(ROOT)) if lp.is_relative_to(ROOT) else str(lp),
                "source_split": args.prefer_split,
                "n_equipment_boxes": len(eq),
                "n_classes": len(classes),
                "classes": sorted(classes),
                "relative_area_hist": dict(bins),
                "has_small": bins.get("relative_area_small", 0) > 0,
                "boxes": boxes,
            }
        )

    if not samples:
        raise SystemExit("No paired image+label samples. Check images extract.")

    # Prefer multi-class + small; keep episode independence:
    # numeric stem // 20 = episode block — never split one block across tune/diag_test.
    def stem_num(sample_id: str) -> int:
        # mocs-val-0021407 -> 21407
        return int(sample_id.rsplit("-", 1)[-1])

    def episode_key(sample_id: str) -> int:
        return stem_num(sample_id) // 20

    multi = [s for s in samples if s["n_classes"] >= 2 and s["has_small"]]
    small = [s for s in samples if s["has_small"]]
    pool = multi or small or samples
    rng = random.Random(args.seed)
    # group pool by episode
    by_ep = defaultdict(list)
    for s in pool:
        by_ep[episode_key(s["sample_id"])].append(s)
    ep_ids = list(by_ep.keys())
    rng.shuffle(ep_ids)
    need = args.n_tune + args.n_diag_test
    chosen = []
    for eid in ep_ids:
        chosen.extend(by_ep[eid])
        if len(chosen) >= need:
            break
    chosen = chosen[:need]
    # fill from remaining samples if short (still by episode)
    if len(chosen) < need:
        have = {s["sample_id"] for s in chosen}
        rest_eps = sorted({episode_key(s["sample_id"]) for s in samples if s["sample_id"] not in have})
        rng.shuffle(rest_eps)
        by_all = defaultdict(list)
        for s in samples:
            by_all[episode_key(s["sample_id"])].append(s)
        for eid in rest_eps:
            for s in by_all[eid]:
                if s["sample_id"] not in have:
                    chosen.append(s)
                    have.add(s["sample_id"])
                if len(chosen) >= need:
                    break
            if len(chosen) >= need:
                break
        chosen = chosen[:need]

    # Assign whole episodes to tune until n_tune, rest diag_test
    ep_order = []
    seen = set()
    for s in chosen:
        ek = episode_key(s["sample_id"])
        if ek not in seen:
            ep_order.append(ek)
            seen.add(ek)
    tune_eps = set()
    n_t = 0
    for ek in ep_order:
        members = [s for s in chosen if episode_key(s["sample_id"]) == ek]
        if n_t < args.n_tune:
            tune_eps.add(ek)
            n_t += len(members)
        if n_t >= args.n_tune:
            break
    for s in chosen:
        s["episode_block"] = episode_key(s["sample_id"])
        s["diag_split"] = "tune" if episode_key(s["sample_id"]) in tune_eps else "diag_test"
        # sha only for chosen (cost)
        img_path = ROOT / s["image"] if not Path(s["image"]).is_absolute() else Path(s["image"])
        s["sha256"] = sha256(img_path)

    # exact hash collision drop from diag_test if in tune
    by_hash: dict[str, list] = defaultdict(list)
    for s in chosen:
        by_hash[s["sha256"]].append(s)
    dropped = []
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        splits = {g["diag_split"] for g in group}
        if splits == {"tune", "diag_test"}:
            for g in group:
                if g["diag_split"] == "diag_test":
                    g["diag_split"] = "excluded_exact_hash_dup"
                    dropped.append(g["sample_id"])

    man = {
        "protocol": "diagnostic-multiclass-v1",
        "source": "AmiyaChan/mocs_yolo",
        "mapping_file": str(args.mapping.relative_to(ROOT)),
        "size_bins": SIZE,
        "size_bins_note": "relative_area (YOLO w*h); NOT COCO",
        "n_pool_scanned": len(samples),
        "n_chosen": len(chosen),
        "n_tune": sum(1 for s in chosen if s["diag_split"] == "tune"),
        "n_diag_test": sum(1 for s in chosen if s["diag_split"] == "diag_test"),
        "exact_hash_dropped_from_diag_test": dropped,
        "selection_seed": args.seed,
        "models_expected": [
            "grounding-dino-base",
            "yoloe-26l-seg",
            "sam3.1-multiplex",
            "yolo-world-v2.1-l",
        ],
        "models_excluded": ["yoloe-11l-seg"],
        "miniexcav_thresholds_not_reused": True,
        "samples": chosen,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")
    print("wrote", args.out, "tune", man["n_tune"], "diag_test", man["n_diag_test"], "dropped", dropped)


if __name__ == "__main__":
    main()
