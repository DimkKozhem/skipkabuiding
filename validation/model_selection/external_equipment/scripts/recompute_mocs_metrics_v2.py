#!/usr/bin/env python3
"""Пересчёт MOCS metrics v2 из raw (без нового inference)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
sys.path.insert(0, str(ROOT / "validation/model_selection/external_equipment/scripts"))
import mocs_eval_v2 as ev  # noqa: E402

REP = ROOT / "validation/model_selection/external_equipment/reports"
LOCK_THR = {
    "grounding-dino-base": 0.2,
    "yoloe-26l-seg": 0.2,
    "yolo-world-v2.1-l": 0.4,
    "sam3.1-multiplex": 0.5,
}


def load_preds(raw_path: Path, filt_key: str, raw_key: str | None, thr: float):
    d = json.loads(raw_path.read_text())
    if filt_key in d and d[filt_key]:
        return d[filt_key], d.get("runtime"), d.get("locked_thr", thr)
    # resolution tune: filtered or raw+thr
    if "filtered" in d:
        return d["filtered"], d.get("runtime"), thr
    src = d.get(raw_key) or d.get("raw") or {}
    filt = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in src.items()}
    return filt, d.get("runtime"), thr


def pack(samples, preds, mid, runtime, thr):
    meta = {
        "model": mid,
        "locked_thr": thr,
        "thr_source": "MOCS_CANDIDATE_LOCK (not retuned)",
        "runtime": runtime,
        "evaluator": "mocs_eval_v2 ignore_out_of_bin",
        "legacy_note": "legacy_size_fp_inflation reports are separate; do not compare size AP to v1 directly without reading policy",
    }
    out = ev.evaluate_model(samples, preds, meta)
    return out


def main():
    diag_man = ROOT / "validation/model_selection/external_equipment/manifests/mocs_diagnostic_v1.json"
    ext_man = ROOT / "validation/model_selection/external_equipment/manifests/mocs_extended_v1.json"
    diag_samples = ev.load_samples_from_manifest(diag_man, {"diag_test"})
    ext_samples = ev.load_samples_from_manifest(ext_man, {"extended_eval"})
    tune_samples = ev.load_samples_from_manifest(ext_man, {"extended_tune"})

    # --- diagnostic ---
    diag_models = {}
    diag_specs = [
        ("grounding-dino-base", "mocs_diagnostic/dino_raw_predictions.json", "test_filtered", "test_raw"),
        ("yoloe-26l-seg", "mocs_diagnostic/yoloe26_raw_predictions.json", "test_filtered", "test_raw"),
        ("yolo-world-v2.1-l", "mocs_diagnostic/yoloworld_raw_predictions.json", "test_filtered", "test_raw"),
        ("sam3.1-multiplex", "mocs_diagnostic_sam/sam_raw_predictions.json", "test_filtered", "test_raw"),
    ]
    for mid, rel, fk, rk in diag_specs:
        path = ROOT / "artifacts/model_selection/runs/external_equipment" / rel
        if not path.is_file():
            diag_models[mid] = {"error": f"missing raw {path}"}
            continue
        preds, runtime, thr = load_preds(path, fk, rk, LOCK_THR[mid])
        assert abs(thr - LOCK_THR[mid]) < 1e-9 or thr == LOCK_THR[mid], (mid, thr, LOCK_THR[mid])
        thr = LOCK_THR[mid]
        # re-filter from raw if needed to enforce lock thr
        raw_full = json.loads(path.read_text())
        src = raw_full.get("test_raw") or raw_full.get("test_filtered")
        preds = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in src.items()}
        diag_models[mid] = pack(diag_samples, preds, mid, runtime or raw_full.get("runtime"), thr)
        print(
            "diag",
            mid,
            "agnAP50",
            round(diag_models[mid]["class_agnostic"]["AP50"], 3),
            "small",
            round(diag_models[mid]["by_relative_area_ignore"]["relative_area_small"]["AP50"], 3),
            "n_small",
            diag_models[mid]["by_relative_area_ignore"]["relative_area_small"]["n_gt"],
        )

    diag_out = {
        "metrics_version": "mocs_diagnostic_v2",
        "policy": "relative_area ignore_out_of_bin; class_agnostic = equipment detection",
        "legacy": "metrics_mocs_diagnostic_v1*.json = legacy_size_fp_inflation",
        "n_diag_test": len(diag_samples),
        "bins_all_160_caption_only": {"relative_area_small": 503, "relative_area_medium": 112, "relative_area_large": 60},
        "bins_diag_test_scored": {
            b: diag_models["grounding-dino-base"]["by_relative_area_ignore"][b]["n_gt"]
            for b in ("relative_area_small", "relative_area_medium", "relative_area_large")
        },
        "models": diag_models,
    }
    (REP / "metrics_mocs_diagnostic_v2.json").write_text(json.dumps(diag_out, ensure_ascii=False, indent=2) + "\n")

    # SAM separate convenience copy
    if "sam3.1-multiplex" in diag_models and "error" not in diag_models["sam3.1-multiplex"]:
        (REP / "metrics_mocs_diagnostic_sam_v2.json").write_text(
            json.dumps(
                {
                    "metrics_version": "mocs_diagnostic_sam_v2",
                    "model": diag_models["sam3.1-multiplex"],
                    "legacy": "metrics_mocs_diagnostic_sam_v1.json = legacy_size_fp_inflation",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n"
        )

    # --- extended ---
    ext_models = {}
    boot = {}
    for mid, rel in [
        ("grounding-dino-base", "mocs_extended/dino_raw_predictions.json"),
        ("yoloe-26l-seg", "mocs_extended/yoloe26_raw_predictions.json"),
    ]:
        path = ROOT / "artifacts/model_selection/runs/external_equipment" / rel
        raw_full = json.loads(path.read_text())
        thr = LOCK_THR[mid]
        src = raw_full.get("eval_raw") or raw_full.get("eval_filtered")
        preds = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in src.items()}
        ext_models[mid] = pack(ext_samples, preds, mid, raw_full.get("runtime"), thr)
        boot[mid] = ev.bootstrap_ap_by_episode(ext_samples, preds)
        print(
            "ext",
            mid,
            "agnAP50",
            round(ext_models[mid]["class_agnostic"]["AP50"], 3),
            "macro",
            round(ext_models[mid]["by_class"]["macro_AP50"], 3),
            "small",
            round(ext_models[mid]["by_relative_area_ignore"]["relative_area_small"]["AP50"], 3),
            "boot",
            boot[mid],
        )

    ext_out = {
        "metrics_version": "mocs_extended_v2",
        "policy": "relative_area ignore_out_of_bin; class_agnostic = equipment detection",
        "legacy": "metrics_mocs_extended_v1.json = legacy_size_fp_inflation",
        "n_extended_eval": len(ext_samples),
        "models": ext_models,
        "episode_bootstrap_class_agnostic_AP50": boot,
        "delta_dino_minus_yoloe_agnostic_AP50": ext_models["grounding-dino-base"]["class_agnostic"]["AP50"]
        - ext_models["yoloe-26l-seg"]["class_agnostic"]["AP50"],
    }
    (REP / "metrics_mocs_extended_v2.json").write_text(json.dumps(ext_out, ensure_ascii=False, indent=2) + "\n")

    # --- resolution tune ---
    res_rows = []
    res_dir = ROOT / "artifacts/model_selection/runs/external_equipment/mocs_resolution_tune"
    res_specs = [
        ("yoloe-26l-seg", "lock_640", "yoloe-26l-seg_lock_640_raw.json", 0.2),
        ("yoloe-26l-seg", "hi_1280", "yoloe-26l-seg_hi_1280_raw.json", 0.2),
        ("grounding-dino-base", "lock_longedge_800", "grounding-dino-base_lock_longedge_800_raw.json", 0.2),
        ("grounding-dino-base", "hi_longedge_1280", "grounding-dino-base_hi_longedge_1280_raw.json", 0.2),
    ]
    for mid, tag, fname, thr in res_specs:
        path = res_dir / fname
        if not path.is_file():
            res_rows.append({"model": mid, "config": tag, "error": f"missing {path}"})
            continue
        d = json.loads(path.read_text())
        src = d.get("raw") or {}
        preds = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in src.items()}
        # also use precomputed filtered if present and thr matches
        if d.get("filtered"):
            preds = d["filtered"]
        m = pack(tune_samples, preds, mid, d.get("runtime"), thr)
        small = m["by_relative_area_ignore"]["relative_area_small"]
        res_rows.append(
            {
                "model": mid,
                "config": tag,
                "class_agnostic_AP50": m["class_agnostic"]["AP50"],
                "AP50_small_ignore": small["AP50"],
                "n_gt_small": small["n_gt"],
                "working_point_small": small["working_point_iou0.5"],
                "working_point_agnostic": m["class_agnostic"]["working_point_iou0.5"],
                "runtime": d.get("runtime"),
                "status": "ok",
            }
        )
        print("res", mid, tag, "small", round(small["AP50"], 3), "agn", round(m["class_agnostic"]["AP50"], 3))

    res_out = {
        "metrics_version": "mocs_resolution_tune_v2",
        "split": "extended_tune only",
        "policy": "relative_area ignore_out_of_bin",
        "legacy": "metrics_mocs_resolution_tune_v1.json = legacy_size_fp_inflation",
        "winner_not_declared": True,
        "rows": res_rows,
    }
    (REP / "metrics_mocs_resolution_tune_v2.json").write_text(json.dumps(res_out, ensure_ascii=False, indent=2) + "\n")
    print("WROTE all v2 metrics")


if __name__ == "__main__":
    main()
