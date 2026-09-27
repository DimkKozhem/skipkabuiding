#!/usr/bin/env python3
"""Real CV sample: Qwen:8001 + SAM cuda:1 → WorkFact → CheckOutcome.

Writes docs/engineering/workfact_sample_real_report.md + .json
and copies floor overlays under artifacts/workfact_sample/.
Does not kill foreign GPU processes. If Qwen is down, records GPU item open.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SITEWATCH_PERCEPTION_MODE", "real")
os.environ.setdefault("SITEWATCH_SAM3_DEVICE", "cuda:1")
os.environ.setdefault(
    "SITEWATCH_DB_PATH",
    str(ROOT / "artifacts" / "workfact_sample" / "sample.db"),
)

from sitewatch.ksg.expected import build_expected_state  # noqa: E402
from sitewatch.perception.pipeline import PerceptionPipeline  # noqa: E402
from sitewatch.perception.project import observed_to_frame_actual  # noqa: E402
from sitewatch.works.compare import check_indicators  # noqa: E402

SAMPLES = [
    {
        "id": "house6_early",
        "path": ROOT / "data/sources/house6_2026/frames/2026-01-02.jpg",
        "zone": "house6",
        "camera": "cam_house6",
        "captured_at": datetime(2026, 1, 2, 12, 0, 0),
        "stage": "excavation",
        "expected": {"excavation": True},
        "work_code": "excavation",
    },
    {
        "id": "house6_mid",
        "path": ROOT / "data/sources/house6_2026/frames/2026-05-01.jpg",
        "zone": "house6",
        "camera": "cam_house6",
        "captured_at": datetime(2026, 5, 1, 12, 0, 0),
        "stage": "superstructure",
        "expected": {"floors": 4},
        "work_code": "superstructure",
    },
    {
        "id": "house6_final",
        "path": ROOT / "data/sources/house6_2026/frames/2026-12-24.jpg",
        "zone": "house6",
        "camera": "cam_house6",
        "captured_at": datetime(2026, 12, 24, 12, 0, 0),
        "stage": "facade",
        "expected": {"floors": 6, "facade": True, "roof": True, "windows": 1},
        "work_code": "facade",
    },
    {
        "id": "office_early",
        "path": ROOT / "data/sources/office_domodedovo/frames/2022-06-01.jpg",
        "zone": "office_01",
        "camera": "cam_office",
        "captured_at": datetime(2022, 6, 1, 12, 0, 0),
        "stage": "foundation",
        "expected": {"foundation": True},
        "work_code": "foundation",
    },
    {
        "id": "office_mid",
        "path": ROOT / "data/sources/office_domodedovo/frames/2022-09-28.jpg",
        "zone": "office_01",
        "camera": "cam_office",
        "captured_at": datetime(2022, 9, 28, 12, 0, 0),
        "stage": "superstructure",
        "expected": {"floors": 2, "roof": True},
        "work_code": "superstructure",
    },
    {
        "id": "office_final",
        "path": ROOT / "data/sources/office_domodedovo/frames/2023-01-29.jpg",
        "zone": "office_01",
        "camera": "cam_office",
        "captured_at": datetime(2023, 1, 29, 17, 40, 0),
        "stage": "facade",
        "expected": {"floors": 2, "facade": True, "roof": True, "windows": 1},
        "work_code": "facade",
    },
    {
        "id": "road_early",
        "path": ROOT / "data/sources/road_divider/frames/2016-10-25.jpg",
        "zone": "road_alley",
        "camera": "cam_road",
        "captured_at": datetime(2016, 10, 25, 12, 0, 0),
        "stage": "divider",
        "expected": {"dividing_line_m": 18},
        "work_code": "divider",
    },
    {
        "id": "road_final",
        "path": ROOT / "data/sources/road_divider/frames/2016-11-03.jpg",
        "zone": "road_alley",
        "camera": "cam_road",
        "captured_at": datetime(2016, 11, 3, 12, 0, 0),
        "stage": "divider",
        "expected": {"dividing_line_m": 18},
        "work_code": "divider",
    },
]


def qwen_ok() -> tuple[bool, str]:
    try:
        r = httpx.get("http://127.0.0.1:8001/v1/models", timeout=5.0)
        if r.status_code == 200:
            return True, r.text[:200]
        return False, f"status={r.status_code}"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def _fact_row(facts: dict) -> list[dict]:
    rows = []
    for key, wf in sorted(facts.items()):
        rows.append(
            {
                "indicator_id": key,
                "certainty": wf.certainty.value if wf.certainty else None,
                "value": wf.value,
                "unit": wf.unit,
                "method": wf.method,
                "limitations": list(wf.limitations or [])[:4],
            }
        )
    return rows


def run_one(pipe: PerceptionPipeline, sample: dict, out_dir: Path) -> dict:
    path: Path = sample["path"]
    row: dict = {
        "id": sample["id"],
        "path": str(path),
        "exists": path.is_file(),
        "job_ok": False,
        "fact_ok_notes": [],
        "error": None,
    }
    if not path.is_file():
        row["error"] = "missing_frame"
        return row

    art = out_dir / sample["id"]
    art.mkdir(parents=True, exist_ok=True)
    cached = art / "observed_state.json"
    try:
        if cached.is_file() and (art / ".sample_done").is_file():
            # Resume: rebuild ActualState from cached ObservedState
            from sitewatch.domain.contracts import ObservedState as OS

            observed = OS.model_validate_json(cached.read_text(encoding="utf-8"))
            row["resumed"] = True
        else:
            observed = pipe.run(
                image_path=path,
                object_id="site_001",
                zone_id=sample["zone"],
                camera_id=sample["camera"],
                captured_at=sample["captured_at"],
                artifact_dir=art,
            )
            (art / ".sample_done").write_text("ok", encoding="utf-8")
        # Tag work code for derive
        observed.scene_attributes["work_code"] = sample["work_code"]
        actual = observed_to_frame_actual(observed)
        expected = build_expected_state(
            object_id="site_001",
            zone_id=sample["zone"],
            on_date=sample["captured_at"].date(),
            stage=sample["stage"],
            expected=sample["expected"],
            schedule_row_id=f"ksg-{sample['id']}",
        )
        checks = check_indicators(
            expected.planned_indicators,
            actual,
            evaluation_as_of=sample["captured_at"].date(),
            last_observation_date=sample["captured_at"].date(),
        )
        scene = actual.scene_attributes or {}
        floors_wf = (actual.work_facts or {}).get("visible_floor_levels")
        check_rows = []
        for c in checks:
            ind = c.planned.indicator_id if c.planned else None
            check_rows.append(
                {
                    "indicator_id": ind,
                    "outcome": c.outcome.value if c.outcome else None,
                    "title": c.title,
                    "rationale": (c.rationale or "")[:200],
                    "rule_id": c.rule_id,
                }
            )
        row.update(
            {
                "job_ok": True,
                "stages": [
                    {
                        "name": s.name,
                        "status": s.status.value if s.status else None,
                        "error": s.error,
                        "latency_ms": s.latency_ms,
                    }
                    for s in (observed.pipeline_run.stages if observed.pipeline_run else [])
                ],
                "scene": {
                    "visible_floor_levels": scene.get("visible_floor_levels"),
                    "floors_status": scene.get("floors_status"),
                    "floors_derivation": scene.get("floors_derivation"),
                    "structural_levels": scene.get("structural_levels"),
                    "floor_bands_count": len(scene.get("floor_bands") or []),
                    "floor_bands_overlay": scene.get("floor_bands_overlay"),
                    "floors_prove_reasons": scene.get("floors_prove_reasons"),
                    "observation_summary": (scene.get("observation_summary") or "")[:240],
                },
                "work_facts": _fact_row(actual.work_facts or {}),
                "checks": check_rows,
                "floors_workfact": {
                    "certainty": floors_wf.certainty.value if floors_wf else None,
                    "value": floors_wf.value if floors_wf else None,
                    "method": floors_wf.method if floors_wf else None,
                    "limitations": list(floors_wf.limitations or [])[:6] if floors_wf else [],
                },
            }
        )
        # Copy overlay next to report artifacts
        ov = scene.get("floor_bands_overlay")
        if ov and Path(ov).is_file():
            dest = out_dir / f"{sample['id']}_floors_overlay.jpg"
            shutil.copy2(ov, dest)
            row["overlay_copied"] = str(dest)
        # Heuristic fact notes (job ok ≠ fact correct)
        notes = []
        if sample["id"].startswith("house6") and sample["id"] != "house6_early":
            fv = floors_wf.value if floors_wf else scene.get("visible_floor_levels")
            if floors_wf and floors_wf.certainty.value == "confirmed" and fv == 6 and sample["id"] == "house6_final":
                notes.append("WARN: confirmed 6 without strong bands — review overlay")
            if scene.get("floors_status") == "proven" and fv and int(fv) >= 6:
                notes.append("open: house6 floors proven>=6 needs human band check")
            if scene.get("floors_status") != "proven":
                notes.append("floors not proven (expected until bands justify)")
        if sample["id"].startswith("office") and sample["id"] != "office_early":
            fv = floors_wf.value if floors_wf else scene.get("visible_floor_levels")
            if fv is not None and int(fv) not in (2,):
                notes.append(f"office floors count={fv} expected~2 — band merge issue?")
            if fv == 2:
                notes.append("office floors count matches visual 2")
        if sample["zone"] == "road_alley":
            for c in check_rows:
                if c.get("indicator_id") == "dividing_line_m":
                    if c.get("outcome") == "measurement_unimplemented":
                        notes.append("dividing_line_m correctly unimplemented")
                    else:
                        notes.append(f"dividing_line_m outcome={c.get('outcome')}")
        row["fact_ok_notes"] = notes
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc()[-2000:]
    return row


def main() -> int:
    out_dir = ROOT / "artifacts" / "workfact_sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok, detail = qwen_ok()
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "qwen_8001": {"ok": ok, "detail": detail},
        "sam_device": os.environ.get("SITEWATCH_SAM3_DEVICE"),
        "perception_mode": os.environ.get("SITEWATCH_PERCEPTION_MODE"),
        "pipeline_version": "workfact-1",
        "samples": [],
    }
    if not ok:
        report["open"] = ["Qwen :8001 unavailable — GPU sample deferred; CPU/integration can continue"]
        (out_dir / "workfact_sample_real.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print("QWEN_DOWN", detail)
        return 2

    pipe = PerceptionPipeline(mode=None)  # resolves SITEWATCH_PERCEPTION_MODE=real
    for sample in SAMPLES:
        print(f"== {sample['id']} {sample['path'].name}", flush=True)
        row = run_one(pipe, sample, out_dir)
        report["samples"].append(row)
        print(
            f"   job_ok={row.get('job_ok')} floors={row.get('scene', {}).get('visible_floor_levels')} "
            f"status={row.get('scene', {}).get('floors_status')} err={row.get('error')}",
            flush=True,
        )
        # Persist incrementally for resume visibility
        (out_dir / "workfact_sample_real.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )

    # Markdown summary
    lines = [
        "# WorkFact real sample report",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Qwen:8001 ok={ok}; SAM `{report['sam_device']}`; mode=`{report['perception_mode']}`",
        "",
        "| Sample | job_ok | floors | floors_status | WF certainty | notes |",
        "|---|---|---:|---|---|---|",
    ]
    for s in report["samples"]:
        sc = s.get("scene") or {}
        fw = s.get("floors_workfact") or {}
        lines.append(
            f"| {s['id']} | {s.get('job_ok')} | {sc.get('visible_floor_levels')} | "
            f"{sc.get('floors_status')} | {fw.get('certainty')}/{fw.get('value')} | "
            f"{'; '.join(s.get('fact_ok_notes') or []) or s.get('error') or ''} |"
        )
    lines.extend(["", "## Chain detail", ""])
    for s in report["samples"]:
        lines.append(f"### {s['id']}")
        lines.append("```json")
        lines.append(
            json.dumps(
                {
                    "scene": s.get("scene"),
                    "work_facts": s.get("work_facts"),
                    "checks": s.get("checks"),
                    "stages": s.get("stages"),
                    "notes": s.get("fact_ok_notes"),
                    "error": s.get("error"),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        lines.append("```")
        lines.append("")
    md_path = ROOT / "docs" / "engineering" / "workfact_sample_real_report.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = ROOT / "docs" / "engineering" / "workfact_sample_real.json"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print("WROTE", md_path, json_path)
    return 0 if all(s.get("job_ok") for s in report["samples"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
