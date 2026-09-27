#!/usr/bin/env python3
"""Расширенная выборка MOCS: эпизоды, не пересекающиеся с diagnostic tune/diag_test.

Не официальный test MOCS. Не трогает diagnostic manifest.
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


def episode_key(sample_id: str) -> int:
    return int(sample_id.rsplit("-", 1)[-1]) // 20


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--diagnostic-manifest",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/manifests/mocs_diagnostic_v1.json",
    )
    ap.add_argument(
        "--images-root",
        type=Path,
        default=ROOT / "data/external/benchmark_sources/mocs_yolo_hf/images",
    )
    ap.add_argument(
        "--labels-root",
        type=Path,
        default=ROOT / "data/external/benchmark_sources/hf_probe/mocs_labels_extracted/labels",
    )
    ap.add_argument(
        "--mapping",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/class_mapping_mocs.json",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/manifests/mocs_extended_v1.json",
    )
    ap.add_argument("--seed", type=int, default=20260927)
    ap.add_argument("--n-tune", type=int, default=40)
    ap.add_argument("--n-eval", type=int, default=200)
    ap.add_argument("--prefer-split", default="val")
    args = ap.parse_args()

    diag = json.loads(args.diagnostic_manifest.read_text())
    used_eps = {s["episode_block"] for s in diag["samples"]}
    used_sha = {s["sha256"] for s in diag["samples"] if s.get("sha256")}
    used_ids = {s["sample_id"] for s in diag["samples"]}

    mapping = load_mapping(args.mapping)
    label_dir = args.labels_root / args.prefer_split
    img_dir = args.images_root / args.prefer_split

    pool = []
    for lp in sorted(label_dir.glob("*.txt")):
        if lp.name in {"classes.txt", "MOCS.txt"}:
            continue
        stem = lp.stem
        ip = img_dir / f"{stem}.jpg"
        if not ip.is_file():
            continue
        boxes = parse_yolo(lp, mapping)
        eq = [b for b in boxes if b["in_equipment_eval"]]
        if len(eq) < 1:
            continue
        sid = f"mocs-{args.prefer_split}-{stem}"
        ek = episode_key(sid)
        if ek in used_eps or sid in used_ids:
            continue
        bins = Counter(b["relative_area_bin"] for b in eq)
        classes = {b["mapped_class"] for b in eq if b["mapped_class"]}
        pool.append(
            {
                "sample_id": sid,
                "image": str(ip.relative_to(ROOT)),
                "label": str(lp.relative_to(ROOT)),
                "source_split": args.prefer_split,
                "n_equipment_boxes": len(eq),
                "n_classes": len(classes),
                "classes": sorted(classes),
                "relative_area_hist": dict(bins),
                "has_small": bins.get("relative_area_small", 0) > 0,
                "boxes": boxes,
                "episode_block": ek,
            }
        )

    # Prefer multi-class + small; keep whole episodes
    multi = [s for s in pool if s["n_classes"] >= 2 and s["has_small"]]
    small = [s for s in pool if s["has_small"]]
    cand = multi or small or pool
    by_ep: dict[int, list] = defaultdict(list)
    for s in cand:
        by_ep[s["episode_block"]].append(s)

    rng = random.Random(args.seed)
    ep_ids = list(by_ep.keys())
    rng.shuffle(ep_ids)
    need = args.n_tune + args.n_eval
    chosen = []
    for eid in ep_ids:
        chosen.extend(by_ep[eid])
        if len(chosen) >= need:
            break
    if len(chosen) < need:
        have = {s["sample_id"] for s in chosen}
        rest = [s for s in pool if s["sample_id"] not in have]
        by_all: dict[int, list] = defaultdict(list)
        for s in rest:
            by_all[s["episode_block"]].append(s)
        rest_eps = list(by_all.keys())
        rng.shuffle(rest_eps)
        for eid in rest_eps:
            for s in by_all[eid]:
                chosen.append(s)
                have.add(s["sample_id"])
                if len(chosen) >= need:
                    break
            if len(chosen) >= need:
                break
    chosen = chosen[:need]

    # Assign whole episodes: first fill tune, rest eval
    ep_order = []
    seen = set()
    for s in chosen:
        if s["episode_block"] not in seen:
            ep_order.append(s["episode_block"])
            seen.add(s["episode_block"])
    tune_eps = set()
    n_t = 0
    for ek in ep_order:
        members = [s for s in chosen if s["episode_block"] == ek]
        if n_t < args.n_tune:
            tune_eps.add(ek)
            n_t += len(members)
        if n_t >= args.n_tune:
            break

    dropped_hash = []
    for s in chosen:
        img_path = ROOT / s["image"]
        s["sha256"] = sha256(img_path)
        s["diag_split"] = "extended_tune" if s["episode_block"] in tune_eps else "extended_eval"
        if s["sha256"] in used_sha:
            s["diag_split"] = "excluded_hash_overlap_diagnostic"
            dropped_hash.append(s["sample_id"])

    # near-dup within extended: exact hash across tune/eval
    by_hash: dict[str, list] = defaultdict(list)
    for s in chosen:
        if s["diag_split"].startswith("excluded"):
            continue
        by_hash[s["sha256"]].append(s)
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        splits = {g["diag_split"] for g in group}
        if "extended_tune" in splits and "extended_eval" in splits:
            for g in group:
                if g["diag_split"] == "extended_eval":
                    g["diag_split"] = "excluded_exact_hash_dup"
                    dropped_hash.append(g["sample_id"])

    # annotation completeness: fraction of label files with ≥1 equipment box among chosen
    n_eq = sum(1 for s in chosen if s["n_equipment_boxes"] >= 1)
    hist = Counter()
    for s in chosen:
        if s["diag_split"] not in {"extended_tune", "extended_eval"}:
            continue
        for b in s["boxes"]:
            if b["in_equipment_eval"]:
                hist[b["relative_area_bin"]] += 1

    man = {
        "protocol": "extended-multiclass-v1",
        "source": "AmiyaChan/mocs_yolo (HF packaging ≠ official MOCS test)",
        "not_official_mocs_test": True,
        "source_split_used": args.prefer_split,
        "train_not_needed": True,
        "note_episodes": (
            f"unused val episodes after diagnostic: {len(by_ep)} in preferred pool; "
            f"diagnostic used {len(used_eps)} episode_blocks; no episode shared across diagnostic↔extended or tune↔eval"
        ),
        "diagnostic_manifest": str(args.diagnostic_manifest.relative_to(ROOT)),
        "mapping_file": str(args.mapping.relative_to(ROOT)),
        "size_bins": SIZE,
        "selection_seed": args.seed,
        "n_pool_available": len(pool),
        "n_chosen": len(chosen),
        "n_extended_tune": sum(1 for s in chosen if s["diag_split"] == "extended_tune"),
        "n_extended_eval": sum(1 for s in chosen if s["diag_split"] == "extended_eval"),
        "excluded": dropped_hash,
        "relative_area_hist_tune_eval": dict(hist),
        "annotation_note": f"all chosen have ≥1 equipment box ({n_eq}/{len(chosen)}); Worker/Other skipped in eval",
        "locked_thresholds_from_diagnostic": {"grounding-dino-base": 0.2, "yoloe-26l-seg": 0.2},
        "models_expected": ["grounding-dino-base", "yoloe-26l-seg"],
        "models_not_run": ["yolo-world-v2.1-l", "sam3.1-multiplex"],
        "samples": chosen,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n")
    print(
        "wrote",
        args.out,
        "tune",
        man["n_extended_tune"],
        "eval",
        man["n_extended_eval"],
        "pool",
        len(pool),
        "eps_pool",
        len(by_ep),
        "excluded",
        len(dropped_hash),
        "bins",
        dict(hist),
    )


if __name__ == "__main__":
    main()
