#!/usr/bin/env python3
"""Compare scalar VLM floor count vs localize→bands→count against manual GT.

Success criterion is NOT «answer equals 6». It is whether localized bands
cover real levels (esp. commercial base) while office stays ~2.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from sitewatch.perception.floors_localize import (  # noqa: E402
    FloorBand,
    band_match_score,
    draw_level_overlay,
    localize_floor_levels,
)
from sitewatch.perception.providers.qwen_vl import QwenVlProvider  # noqa: E402
from sitewatch.settings import project_root  # noqa: E402


def _numeric_floor_count(image_path: Path) -> dict:
    """Baseline: full-frame construction observer → visible_floor_levels only."""
    provider = QwenVlProvider()
    result = provider.interpret(
        image_path,
        evidence=[],
        quality={"usable": True, "visibility": 0.9},
        ontology_hints={"task": "count_visible_floor_levels"},
    )
    structured = (result.extras or {}).get("vlm_structured") or {}
    floors = structured.get("visible_floor_levels")
    try:
        floors_n = int(floors) if floors is not None else None
    except (TypeError, ValueError):
        floors_n = None
    return {
        "visible_floor_levels": floors_n,
        "status": result.status.value if hasattr(result.status, "value") else str(result.status),
        "error": result.error,
        "latency_ms": result.latency_ms,
        "limitations": structured.get("limitations") or [],
        "uncertainties": structured.get("uncertainties") or [],
    }


def _load_gt(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gt",
        type=Path,
        default=ROOT / "validation/perception_regression/gt/floors_localize_manual.json",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / "validation/perception_regression/experiments/floors_localize_run",
    )
    parser.add_argument("--skip-numeric", action="store_true")
    args = parser.parse_args()

    gt_doc = _load_gt(args.gt)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    overlays = out_dir / "overlays"
    overlays.mkdir(exist_ok=True)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gt_path": str(args.gt),
        "goal": "localize real levels; do not force answer 6",
        "cases": [],
    }

    for case in gt_doc["cases"]:
        case_id = case["id"]
        image_path = project_root() / case["image"]
        crop_box = tuple(int(x) for x in case["crop_box_xyxy"])
        gt_bands = case["bands"]
        gt_count = int(case["gt_level_count"])

        print(f"\n=== {case_id} ===", flush=True)
        print(f"image={image_path}", flush=True)

        numeric = None
        if not args.skip_numeric:
            print("numeric Qwen (full frame)…", flush=True)
            numeric = _numeric_floor_count(image_path)
            print(f"  numeric visible_floor_levels={numeric.get('visible_floor_levels')}", flush=True)

        print("localize bands…", flush=True)
        loc = localize_floor_levels(
            image_path,
            crop_box=crop_box,
            out_dir=overlays,
        )
        print(
            f"  bands={loc.level_count_from_bands} proposed={loc.level_count_proposed} "
            f"unambiguous={loc.unambiguous_count} err={loc.error}",
            flush=True,
        )

        match = band_match_score(loc.levels, gt_bands, iou_thr=0.3)

        # GT overlay for side-by-side
        img = cv2.imread(str(image_path))
        x1, y1, x2, y2 = crop_box
        crop = img[y1:y2, x1:x2]
        gt_overlay = draw_level_overlay(
            crop,
            [
                FloorBand(
                    index=int(b["index"]),
                    y0=float(b["y0"]),
                    y1=float(b["y1"]),
                    cues=list(b.get("cues") or []),
                    ambiguous=False,
                    confidence=1.0,
                )
                for b in gt_bands
            ],
            title=f"GT {case_id} n={gt_count}",
        )
        gt_path = overlays / f"{case_id}_gt.jpg"
        cv2.imwrite(str(gt_path), gt_overlay)

        entry = {
            "id": case_id,
            "image": str(image_path),
            "crop_box_xyxy": list(crop_box),
            "gt_level_count": gt_count,
            "numeric": numeric,
            "localize": {
                "level_count_from_bands": loc.level_count_from_bands,
                "level_count_proposed": loc.level_count_proposed,
                "unambiguous_count": loc.unambiguous_count,
                "building_focus": loc.building_focus,
                "limitations": loc.limitations,
                "uncertainties": loc.uncertainties,
                "error": loc.error,
                "latency_ms": loc.latency_ms,
                "crop_path": loc.crop_path,
                "overlay_path": loc.overlay_path,
                "levels": [
                    {
                        "index": b.index,
                        "y0": b.y0,
                        "y1": b.y1,
                        "cues": b.cues,
                        "ambiguous": b.ambiguous,
                        "confidence": b.confidence,
                    }
                    for b in loc.levels
                ],
            },
            "band_match": match,
            "gt_overlay": str(gt_path),
            "delta_numeric_vs_gt": (
                None
                if not numeric or numeric.get("visible_floor_levels") is None
                else int(numeric["visible_floor_levels"]) - gt_count
            ),
            "delta_bands_vs_gt": loc.level_count_from_bands - gt_count,
            "notes": case.get("notes"),
        }
        report["cases"].append(entry)

    # Compact verdict table
    lines = [
        "# Floors localize experiment",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "Goal: check whether localize→bands recovers real levels (not force answer 6).",
        "",
        "| Case | GT | Numeric | Bands | Band recall | Notes |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for c in report["cases"]:
        num = (c.get("numeric") or {}).get("visible_floor_levels")
        recall = c["band_match"]["recall"]
        note = []
        if c["id"] == "house6_final" and c["localize"]["level_count_from_bands"] >= 5:
            note.append("lower levels likely recovered")
        if c["id"] == "office_final" and c["localize"]["level_count_from_bands"] == 2:
            note.append("office control OK")
        if c["id"] == "office_final" and c["localize"]["level_count_from_bands"] != 2:
            note.append("office control FAILED")
        lines.append(
            f"| {c['id']} | {c['gt_level_count']} | {num} | "
            f"{c['localize']['level_count_from_bands']} | {recall} | {'; '.join(note) or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- `Numeric` = scalar `visible_floor_levels` from full-frame observer.",
            "- `Bands` = count after localize→merge (authoritative for this method).",
            "- Overlay paths are under `overlays/` for human check; VLM coordinates may still drift.",
            "- Confirmed floors for plan/fact must use proven levels, not historical max of proposed numbers.",
            "",
        ]
    )
    md_path = out_dir / "REPORT.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path = out_dir / "report.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {json_path}\nWrote {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
