#!/usr/bin/env python3
"""Class-aware audit + metrics v2.1 from raw (no new inference).

v2.1 = v2 + normalize_pred_class (DINO tokenizer debris / aliases).
Does not overwrite metrics_mocs_*_v2.json.
"""
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


def load_filt(path: Path, raw_key: str, filt_key: str, thr: float):
    d = json.loads(path.read_text())
    src = d.get(raw_key) or d.get(filt_key) or {}
    return {sid: [p for p in dets if p["score"] >= thr] for sid, dets in src.items()}, d.get("runtime")


def main():
    ext_samples = ev.load_samples_from_manifest(
        ROOT / "validation/model_selection/external_equipment/manifests/mocs_extended_v1.json",
        {"extended_eval"},
    )
    diag_samples = ev.load_samples_from_manifest(
        ROOT / "validation/model_selection/external_equipment/manifests/mocs_diagnostic_v1.json",
        {"diag_test"},
    )

    # --- raw label inventory (proof) ---
    from collections import Counter

    inv = {}
    for mid, rel, rk, fk in [
        ("grounding-dino-base", "mocs_extended/dino_raw_predictions.json", "eval_raw", "eval_filtered"),
        ("yoloe-26l-seg", "mocs_extended/yoloe26_raw_predictions.json", "eval_raw", "eval_filtered"),
    ]:
        d = json.loads((ROOT / "artifacts/model_selection/runs/external_equipment" / rel).read_text())
        ctr = Counter()
        for dets in d[fk].values():
            for p in dets:
                ctr[p.get("class")] += 1
        inv[mid] = {
            "raw_class_counts_at_lock_thr": dict(ctr.most_common()),
            "noncanonical_raw": {
                k: v for k, v in ctr.items() if ev.normalize_pred_class(k) != k and k not in ev.EQUIPMENT_CLASSES
            },
            "prompt_list_lock": list(ev.EQUIPMENT_CLASSES),
            "note_yoloe": "class name = prompts[cls_i] after set_classes(sorted EQUIPMENT_CLASSES); not source_id from MOCS labels",
            "note_dino": "labels from processor; fragments ##* normalized in v2.1",
        }

    # --- extended models ---
    preds = {}
    models = {}
    confusions = {}
    for mid, rel in [
        ("grounding-dino-base", "mocs_extended/dino_raw_predictions.json"),
        ("yoloe-26l-seg", "mocs_extended/yoloe26_raw_predictions.json"),
    ]:
        path = ROOT / "artifacts/model_selection/runs/external_equipment" / rel
        filt, runtime = load_filt(path, "eval_raw", "eval_filtered", LOCK_THR[mid])
        preds[mid] = filt
        models[mid] = ev.evaluate_model(
            ext_samples,
            filt,
            {"model": mid, "locked_thr": LOCK_THR[mid], "runtime": runtime, "metrics_version": "v2.1"},
        )
        confusions[mid] = ev.geometric_type_confusion(ext_samples, filt)
        print(
            mid,
            "agn",
            round(models[mid]["class_agnostic"]["AP50"], 3),
            "macro",
            round(models[mid]["by_class"]["macro_AP50"], 3),
            "n_macro",
            models[mid]["by_class"]["n_classes_in_macro"],
            "type_ok",
            round(confusions[mid]["fraction_correct_among_matches"], 3),
        )

    paired = ev.paired_bootstrap_delta_ap(
        ext_samples, preds["grounding-dino-base"], preds["yoloe-26l-seg"], mode="class_agnostic"
    )
    paired_macro = ev.paired_bootstrap_delta_ap(
        ext_samples, preds["grounding-dino-base"], preds["yoloe-26l-seg"], mode="macro"
    )
    print("paired agn", paired)
    print("paired macro", paired_macro)

    # brief YW / SAM on diagnostic
    brief = {}
    for mid, rel, rk, fk in [
        ("yolo-world-v2.1-l", "mocs_diagnostic/yoloworld_raw_predictions.json", "test_raw", "test_filtered"),
        ("sam3.1-multiplex", "mocs_diagnostic_sam/sam_raw_predictions.json", "test_raw", "test_filtered"),
    ]:
        path = ROOT / "artifacts/model_selection/runs/external_equipment" / rel
        if not path.is_file():
            brief[mid] = {"error": "missing raw"}
            continue
        filt, runtime = load_filt(path, rk, fk, LOCK_THR[mid])
        conf = ev.geometric_type_confusion(diag_samples, filt)
        m = ev.evaluate_by_class(diag_samples, filt)
        brief[mid] = {
            "split": "diag_test_120",
            "macro_AP50": m["macro_AP50"],
            "n_classes_in_macro": m["n_classes_in_macro"],
            "fraction_correct_among_geom_matches": conf["fraction_correct_among_matches"],
            "top_confusions": conf["top_confusions_gt_to_pred"][:5],
            "runtime": runtime,
        }

    # compare macro v2 (no norm) vs v2.1: load v2 if present
    v2_macro = {}
    v2p = REP / "metrics_mocs_extended_v2.json"
    if v2p.is_file():
        old = json.loads(v2p.read_text())
        for mid, md in old.get("models", {}).items():
            v2_macro[mid] = md.get("by_class", {}).get("macro_AP50")

    out = {
        "metrics_version": "mocs_extended_v2.1",
        "changes_from_v2": "normalize_pred_class for DINO wordpiece debris and space aliases; skip Worker/Other/Hanging; no crane↔static_crane auto-merge",
        "legacy_v2_preserved": "metrics_mocs_extended_v2.json",
        "raw_label_inventory": inv,
        "macro_AP50_v2_before_norm": v2_macro,
        "n_extended_eval": len(ext_samples),
        "models": models,
        "geometric_type_confusion": confusions,
        "paired_bootstrap_dino_minus_yoloe": {
            "class_agnostic_AP50": paired,
            "macro_AP50": paired_macro,
        },
        "diagnostic_brief_yw_sam": brief,
    }
    (REP / "metrics_mocs_extended_v2.1.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")

    # also diagnostic v2.1 for DINO/YOLOE completeness
    diag_models = {}
    for mid, rel in [
        ("grounding-dino-base", "mocs_diagnostic/dino_raw_predictions.json"),
        ("yoloe-26l-seg", "mocs_diagnostic/yoloe26_raw_predictions.json"),
    ]:
        filt, runtime = load_filt(
            ROOT / "artifacts/model_selection/runs/external_equipment" / rel,
            "test_raw",
            "test_filtered",
            LOCK_THR[mid],
        )
        diag_models[mid] = ev.evaluate_model(
            diag_samples, filt, {"model": mid, "locked_thr": LOCK_THR[mid], "runtime": runtime}
        )
    (REP / "metrics_mocs_diagnostic_v2.1.json").write_text(
        json.dumps(
            {
                "metrics_version": "mocs_diagnostic_v2.1",
                "legacy_v2_preserved": "metrics_mocs_diagnostic_v2.json",
                "n_diag_test": len(diag_samples),
                "models": diag_models,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print("WROTE v2.1")


if __name__ == "__main__":
    main()
