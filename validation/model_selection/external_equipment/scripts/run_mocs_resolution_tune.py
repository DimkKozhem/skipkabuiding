#!/usr/bin/env python3
"""Один эксперимент разрешения на extended_tune (не diag_test, не extended_eval).

Сравнивает locked resize vs один повышенный вариант для DINO и YOLOE по отдельности.
Tiling не смешивается. Победителя по tune не объявлять.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
sys.path.insert(0, str(ROOT / "validation/model_selection/external_equipment/scripts"))
import run_mocs_diagnostic as diag  # noqa: E402
import run_mocs_extended as ext  # noqa: E402

OUT = ROOT / "artifacts/model_selection/runs/external_equipment/mocs_resolution_tune"
REPORT = ROOT / "validation/model_selection/external_equipment/reports"
PROMPTS = ext.PROMPTS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "validation/model_selection/external_equipment/manifests/mocs_extended_v1.json",
    )
    ap.add_argument("--device", default="cuda:1")
    ap.add_argument("--yoloe-hi", type=int, default=1280)
    ap.add_argument("--dino-hi", type=int, default=1280)
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    man, samples = ext.load_extended(args.manifest)
    tune = [s for s in samples if s["diag_split"] == "extended_tune"]
    print("extended_tune n", len(tune), flush=True)
    if not tune:
        raise SystemExit("no extended_tune samples")

    configs = [
        ("yoloe-26l-seg", "lock_640", lambda: ext.run_yoloe26(tune, PROMPTS, args.device, 640)),
        ("yoloe-26l-seg", f"hi_{args.yoloe_hi}", lambda: ext.run_yoloe26(tune, PROMPTS, args.device, args.yoloe_hi)),
        ("grounding-dino-base", "lock_longedge_800", lambda: ext.run_dino_longedge(tune, PROMPTS, args.device, 800)),
        (
            "grounding-dino-base",
            f"hi_longedge_{args.dino_hi}",
            lambda: ext.run_dino_longedge(tune, PROMPTS, args.device, args.dino_hi),
        ),
    ]
    # locked thr for working-point; AP still over all scores ≥0.01 from runner
    thr_map = {"yoloe-26l-seg": 0.2, "grounding-dino-base": 0.2}
    rows = []
    for mid, tag, fn in configs:
        print("===", mid, tag, flush=True)
        try:
            raw, runtime = fn()
            thr = thr_map[mid]
            filt = {sid: [p for p in dets if p["score"] >= thr] for sid, dets in raw.items()}
            # AP overall + small on tune
            ev = diag.evaluate_multiclass(tune, filt, {"runtime": runtime, "locked_thr": thr, "config": tag})
            small = ev["by_relative_area"].get("relative_area_small", {})
            row = {
                "model": mid,
                "config": tag,
                "AP50": ev["AP50"],
                "AP50_small": small.get("AP50"),
                "n_gt_small": small.get("n_gt"),
                "working_point": ev["working_point_iou0.5"],
                "runtime": runtime,
                "status": "ok",
            }
            (OUT / f"{mid}_{tag}_raw.json").write_text(
                json.dumps({"raw": raw, "filtered": filt, "runtime": runtime}, ensure_ascii=False, indent=2) + "\n"
            )
        except Exception as e:
            import traceback

            row = {
                "model": mid,
                "config": tag,
                "status": "blocked",
                "error": f"{type(e).__name__}: {e}",
                "traceback": traceback.format_exc()[-2000:],
            }
            print("BLOCKED", e, flush=True)
        rows.append(row)
        print(row, flush=True)

    out = {
        "protocol": "resolution-tune-one-change-v1",
        "split": "extended_tune only",
        "not_diag_test": True,
        "not_extended_eval": True,
        "tiling": False,
        "winner_not_declared": True,
        "rows": rows,
    }
    (REPORT / "metrics_mocs_resolution_tune_v1.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print("WROTE resolution tune metrics")


if __name__ == "__main__":
    main()
