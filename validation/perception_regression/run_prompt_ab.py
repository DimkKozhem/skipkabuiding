#!/usr/bin/env python3
"""Controlled A/B: baseline mvp prompts vs equipment-only narrow prompts.

Hypothesis: one short equipment prompt per class (no structure prompts) reduces
equipment FP without lowering TP on confirmed GT of house6_earthworks.

Does not change production config. Does not open holdout. Does not train.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

import cv2
import yaml

from sitewatch.domain.enums import EntityVisibility, PerceptionMode
from sitewatch.perception import ontology as ont
from sitewatch.perception import pipeline as pipe_mod
from sitewatch.perception.pipeline import PerceptionPipeline
from sitewatch.perception.providers.sam3 import Sam3Provider

from eval_match import evaluate_predictions

ROOT = Path(__file__).resolve().parents[2]
GT = ROOT / "validation/perception_regression/gt/house6_earthworks.json"
NARROW = ROOT / "validation/perception_regression/experiments/narrow_prompts_v1.yaml"
OUT = ROOT / "validation/perception_regression/experiments/prompt_ab_2026-01"


def _draw_errors(image_path: Path, frame_metrics: dict, out_path: Path) -> None:
    img = cv2.imread(str(image_path))
    if img is None:
        return
    for row in frame_metrics.get("tp_rows") or []:
        pass
    for row in frame_metrics.get("fp_rows") or []:
        x1, y1, x2, y2 = map(int, row["xyxy"])
        cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(img, f"FP:{row['class']}", (x1, max(20, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    for row in frame_metrics.get("fn_rows") or []:
        x1, y1, x2, y2 = map(int, row["xyxy"])
        cv2.rectangle(img, (x1, y1), (x2, y2), (255, 128, 0), 2)
        cv2.putText(img, f"FN:{row['class']}", (x1, max(20, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 128, 0), 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)


def _confirmed_equipment(observed) -> dict[str, int]:
    out: dict[str, int] = {}
    for label, obs in observed.equipment.items():
        if obs.status not in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}:
            continue
        if any(n.startswith("agreement:conflict") or n.startswith("agreement:vlm_only") for n in obs.notes):
            continue
        if obs.count_visible is None:
            continue
        out[label] = int(obs.count_visible)
    return out


def _detector_preds(observed) -> list[dict]:
    return [
        {
            "normalized_label": e.normalized_label,
            "score": e.score,
            "bbox": e.bbox.model_dump() if e.bbox else None,
            "source": e.source.value,
        }
        for e in observed.evidence
        if e.bbox is not None and e.source.value in {"sam3", "annotation"}
    ]


def _conflicts(observed) -> list[dict]:
    rows = []
    for label, obs in {**observed.structures, **observed.equipment}.items():
        if any("conflict" in n for n in obs.notes):
            rows.append({"label": label, "count_visible": obs.count_visible, "notes": obs.notes})
    return rows


def run_variant(name: str, prompt_fn) -> dict:
    original_ont = ont.mvp_prompts
    original_pipe = pipe_mod.mvp_prompts
    ont.mvp_prompts = prompt_fn  # type: ignore[assignment]
    pipe_mod.mvp_prompts = prompt_fn  # type: ignore[assignment]
    try:
        pipe = PerceptionPipeline(mode=PerceptionMode.REAL)
        gt = json.loads(GT.read_text(encoding="utf-8"))
        preds_by_day: dict[str, list] = {}
        fusion_counts: dict[str, dict[str, int]] = {}
        conflicts: dict[str, list] = {}
        latencies: dict[str, float] = {}
        for frame in gt["frames"]:
            day = frame["day"]
            image = ROOT / frame["image"]
            artifact = OUT / name / day
            if artifact.exists():
                shutil.rmtree(artifact)
            observed = pipe.run(
                image,
                object_id="site_001",
                zone_id="house6",
                camera_id="house6",
                captured_at=datetime.fromisoformat(f"{day}T12:00:00"),
                artifact_dir=artifact,
            )
            preds_by_day[day] = _detector_preds(observed)
            fusion_counts[day] = _confirmed_equipment(observed)
            conflicts[day] = _conflicts(observed)
            latencies[day] = float(observed.pipeline_run.total_latency_ms or 0) if observed.pipeline_run else 0.0
            (artifact / "fusion_counts.json").write_text(
                json.dumps(fusion_counts[day], ensure_ascii=False, indent=2), encoding="utf-8"
            )
        det_report = evaluate_predictions(GT, preds_by_day, fusion_counts=fusion_counts)
        for frame_m, frame in zip(det_report["frames"], gt["frames"]):
            _draw_errors(
                ROOT / frame["image"],
                frame_m,
                OUT / name / f"{frame['day']}_errors.jpg",
            )
        return {
            "name": name,
            "prompts": list(prompt_fn()),
            "detector": det_report,
            "fusion_counts": fusion_counts,
            "conflicts": conflicts,
            "latencies_ms": latencies,
            "sam_device": Sam3Provider().device,
        }
    finally:
        ont.mvp_prompts = original_ont  # type: ignore[assignment]
        pipe_mod.mvp_prompts = original_pipe  # type: ignore[assignment]


def baseline_prompts() -> list[str]:
    return ont.mvp_prompts.__wrapped__() if hasattr(ont.mvp_prompts, "__wrapped__") else list(
        __import__("sitewatch.perception.ontology", fromlist=["mvp_prompts"]).mvp_prompts()
    )


def narrow_equipment_prompts() -> list[str]:
    data = yaml.safe_load(NARROW.read_text(encoding="utf-8"))
    classes = data.get("classes") or {}
    # one prompt per equipment class under test; no structure prompts
    return [str(classes[k]) for k in classes]


def decide(baseline: dict, candidate: dict) -> dict:
    b = baseline["detector"]["totals"]
    c = candidate["detector"]["totals"]
    b_per = baseline["detector"]["per_class"]
    c_per = candidate["detector"]["per_class"]
    class_regressions = []
    classes = sorted(set(b_per) | set(c_per))
    for cls in classes:
        bt = b_per.get(cls, {}).get("tp", 0)
        ct = c_per.get(cls, {}).get("tp", 0)
        bf = b_per.get(cls, {}).get("fp", 0)
        cf = c_per.get(cls, {}).get("fp", 0)
        if ct < bt or cf > bf and ct <= bt:
            # flag TP drop; FP rise without TP gain is also noted
            if ct < bt:
                class_regressions.append({"class": cls, "reason": "tp_drop", "baseline_tp": bt, "candidate_tp": ct})
            elif cf > bf and ct == bt:
                class_regressions.append({"class": cls, "reason": "fp_up_same_tp", "baseline_fp": bf, "candidate_fp": cf})
    accept = (
        c["fp"] < b["fp"]
        and c["tp"] >= b["tp"]
        and not any(r["reason"] == "tp_drop" for r in class_regressions)
    )
    if c["fp"] == b["fp"] and c["tp"] == b["tp"]:
        accept = False
        verdict = "keep_baseline_equal"
    elif accept:
        verdict = "accept_candidate_for_further_check"
    else:
        verdict = "keep_baseline"
    return {
        "verdict": verdict,
        "accept_for_further_check": accept,
        "criterion": "FP down without TP loss; no per-class TP regression; equal → keep baseline",
        "baseline_totals": b,
        "candidate_totals": c,
        "class_regressions": class_regressions,
        "conflict_metric_secondary": {
            "baseline": {d: len(v) for d, v in baseline["conflicts"].items()},
            "candidate": {d: len(v) for d, v in candidate["conflicts"].items()},
            "note": "Согласованная ошибка обеих моделей не видна в числе конфликтов.",
        },
    }


def freeze_baseline_card() -> dict:
    cfg = ont.perception_config()
    sam = cfg.get("sam3") or {}
    return {
        "pipeline_version": cfg.get("pipeline_version"),
        "prompt_version": cfg.get("prompt_version"),
        "ontology_version": ont.ontology_version(),
        "primary_prompt_only": sam.get("primary_prompt_only"),
        "imgsz": sam.get("imgsz"),
        "threshold": sam.get("threshold"),
        "prompt_batch_size": sam.get("prompt_batch_size"),
        "device": sam.get("device"),
        "mvp_prompts": ont.mvp_prompts(),
        "iou_match": 0.3,
        "qwen_unchanged": True,
        "fusion_unchanged": True,
        "temporal_unchanged": True,
        "hypothesis": (
            "Candidate uses only the equipment prompts from narrow_prompts_v1.yaml "
            "(one short prompt per class, no structure prompts). "
            "Baseline uses current mvp_prompts() including structure classes."
        ),
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    card = freeze_baseline_card()
    (OUT / "baseline_freeze.json").write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")

    from sitewatch.perception.ontology import mvp_prompts as real_mvp

    def baseline_fn() -> list[str]:
        return list(real_mvp())

    print("BASELINE prompts", baseline_fn())
    baseline = run_variant("baseline", baseline_fn)
    print("CANDIDATE prompts", narrow_equipment_prompts())
    candidate = run_variant("narrow_equipment", narrow_equipment_prompts)
    decision = decide(baseline, candidate)
    report = {
        "created_at": datetime.utcnow().isoformat(),
        "episode": "house6_earthworks",
        "days": ["2026-01-02", "2026-01-06"],
        "baseline_freeze": card,
        "baseline": baseline,
        "candidate": candidate,
        "decision": decision,
        "limitations": [
            "GT not confirmed by human inspector",
            "Two frames of one camera only",
            "Holdout not used",
            "Conflicts are a secondary metric only",
        ],
    }
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(decision, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
