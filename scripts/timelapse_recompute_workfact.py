#!/usr/bin/env python3
"""Full timelapse recompute with WorkFact pipeline (journal + resume).

pipeline_version=workfact-1.
Raw stage key: source + floor prompt hash + model id.
Derivation key: facts-2. A derivation-only change does not redo GPU.
Journal rows with method_version 1 or 4 are not this raw stage.

Journal: docs/engineering/timelapse_recompute_workfact_journal.jsonl
Summary: docs/engineering/timelapse_recompute_workfact_summary.md

Usage:
  SITEWATCH_PERCEPTION_MODE=real SITEWATCH_SAM3_DEVICE=cuda:1 \\
    PYTHONPATH=src .venv/bin/python scripts/timelapse_recompute_workfact.py

  # Resume after interrupt (same command).
  # Limit for smoke: --limit 5 --series house6
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SITEWATCH_PERCEPTION_MODE", "real")
os.environ.setdefault("SITEWATCH_SAM3_DEVICE", "cuda:1")

from sitewatch.pipeline.evaluate import evaluate_zone_date  # noqa: E402
from sitewatch.pipeline.observe import observe_image  # noqa: E402

PIPELINE_VERSION = "workfact-1"
METHOD = "floors_localize"
DERIVATION_VERSION = "facts-2"
RAW_PROMPT = ROOT / "config" / "prompts" / "qwen_floor_levels_v2.txt"
RAW_MODEL = "Qwen/Qwen3-VL-8B-Instruct"


def _raw_stage_version() -> str:
    """Identity of the GPU stage. Independent of the shared derivation version."""
    digest = hashlib.sha256(RAW_PROMPT.read_bytes()).hexdigest()[:12]
    return f"{RAW_MODEL}|{RAW_PROMPT.name}|{digest}"


METHOD_VERSION = _raw_stage_version()
JOURNAL = ROOT / "docs" / "engineering" / "timelapse_recompute_workfact_journal.jsonl"
SUMMARY = ROOT / "docs" / "engineering" / "timelapse_recompute_workfact_summary.md"
CACHE_DIR = ROOT / "artifacts" / "workfact_recompute_cache"

SERIES = {
    "house6": {
        "frames": ROOT / "data/sources/house6_2026/frames",
        "zone": "house6",
        "camera": "cam_house6",
        "project": "site_001",
    },
    "office": {
        "frames": ROOT / "data/sources/office_domodedovo/frames",
        "zone": "office_01",
        "camera": "cam_office_01",
        "project": "site_001",
    },
    "road": {
        "frames": ROOT / "data/sources/road_divider/frames",
        "zone": "road_alley",
        "camera": "cam_road_alley",
        "project": "site_001",
    },
}


def _cache_key(source: Path) -> str:
    raw = f"{source.resolve()}|{METHOD}|{METHOD_VERSION}|{PIPELINE_VERSION}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _stamp_from_name(path: Path) -> datetime:
    # YYYY-MM-DD.jpg
    stem = path.stem
    try:
        d = date.fromisoformat(stem[:10])
        return datetime(d.year, d.month, d.day, 12, 0, 0)
    except ValueError:
        return datetime.utcnow()


def _load_done() -> set[str]:
    done: set[str] = set()
    if not JOURNAL.is_file():
        return done
    for line in JOURNAL.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") in {"ok", "skipped_cached"} and row.get("cache_key"):
            done.add(row["cache_key"])
    return done


def _append(row: dict) -> None:
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _list_frames(series: str) -> list[Path]:
    folder = SERIES[series]["frames"]
    return sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.jpeg")) + sorted(folder.glob("*.png"))


def process_one(series: str, path: Path, done: set[str]) -> dict:
    meta = SERIES[series]
    key = _cache_key(path)
    row = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "series": series,
        "path": str(path),
        "cache_key": key,
        "pipeline_version": PIPELINE_VERSION,
        "method": METHOD,
        "method_version": METHOD_VERSION,
        "raw_stage_version": METHOD_VERSION,
        "derivation_version": DERIVATION_VERSION,
    }
    if key in done:
        row["status"] = "skipped_cached"
        row["reason"] = "resume_hit"
        return row
    marker = CACHE_DIR / key / "done.json"
    if marker.is_file():
        # Stale cache without journal line — accept and journal
        row["status"] = "skipped_cached"
        row["reason"] = "disk_cache"
        done.add(key)
        return row

    captured = _stamp_from_name(path)
    try:
        actual = observe_image(
            image_path=path,
            project_code=meta["project"],
            zone_code=meta["zone"],
            camera_code=meta["camera"],
            timestamp=captured,
            perception_mode=os.environ.get("SITEWATCH_PERCEPTION_MODE", "real"),
            capture_origin="timelapse_recompute",
        )
        scene = actual.scene_attributes or {}
        wf = (actual.work_facts or {}).get("visible_floor_levels")
        # evaluate same day
        try:
            evaluate_zone_date(
                project_code=meta["project"],
                zone_code=meta["zone"],
                on_date=captured.date(),
            )
            eval_ok = True
        except Exception as exc:  # noqa: BLE001
            eval_ok = False
            row["evaluate_error"] = f"{type(exc).__name__}: {exc}"

        certainty = wf.certainty.value if wf else None
        row.update(
            {
                "status": "ok",
                "evaluate_ok": eval_ok,
                "floors": scene.get("visible_floor_levels"),
                "floors_status": scene.get("floors_status"),
                "floors_derivation": scene.get("floors_derivation"),
                "wf_certainty": certainty,
                "wf_value": wf.value if wf else None,
                "work_facts_n": len(actual.work_facts or {}),
            }
        )
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / key).mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(row, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        done.add(key)
    except Exception as exc:  # noqa: BLE001
        row["status"] = "error"
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["traceback"] = traceback.format_exc()[-1500:]
    return row


def write_summary() -> None:
    counts = {
        "ok": 0,
        "skipped_cached": 0,
        "error": 0,
        "other": 0,
        "confirmed": 0,
        "unknown": 0,
        "by_series": {},
    }
    if JOURNAL.is_file():
        for line in JOURNAL.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            st = row.get("status") or "other"
            counts[st] = counts.get(st, 0) + 1
            ser = row.get("series") or "?"
            bucket = counts["by_series"].setdefault(ser, {"ok": 0, "error": 0, "skipped_cached": 0, "total": 0})
            bucket["total"] += 1
            if st in bucket:
                bucket[st] += 1
            if row.get("wf_certainty") == "confirmed":
                counts["confirmed"] += 1
            if row.get("wf_certainty") == "unknown":
                counts["unknown"] += 1

    expected = {s: len(_list_frames(s)) for s in SERIES}
    lines = [
        "# Timelapse recompute WorkFact — summary",
        "",
        f"Updated: `{datetime.utcnow().isoformat()}Z`",
        f"pipeline_version=`{PIPELINE_VERSION}` method=`{METHOD}` v`{METHOD_VERSION}`",
        "",
        f"| Series | frames on disk | journal total | ok | skipped | error |",
        f"|---|---:|---:|---:|---:|---:|",
    ]
    for ser, n in expected.items():
        b = counts["by_series"].get(ser, {})
        lines.append(
            f"| {ser} | {n} | {b.get('total', 0)} | {b.get('ok', 0)} | "
            f"{b.get('skipped_cached', 0)} | {b.get('error', 0)} |"
        )
    lines.extend(
        [
            "",
            f"Totals: ok={counts.get('ok', 0)} skipped={counts.get('skipped_cached', 0)} "
            f"error={counts.get('error', 0)} wf_confirmed={counts['confirmed']} wf_unknown={counts['unknown']}",
            "",
            "23 key-frames from prior report are a control sample only — not full recompute.",
            "Open: house6 floors proven without open-frame IoU; office oversegment vs visual 2.",
            "",
        ]
    )
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", choices=list(SERIES) + ["all"], default="all")
    ap.add_argument("--limit", type=int, default=0, help="Max frames per series (0=all)")
    ap.add_argument("--summary-only", action="store_true")
    args = ap.parse_args()
    if args.summary_only:
        write_summary()
        print("summary", SUMMARY)
        return 0

    series_list = list(SERIES) if args.series == "all" else [args.series]
    done = _load_done()
    print(f"resume done_keys={len(done)} mode={os.environ.get('SITEWATCH_PERCEPTION_MODE')}", flush=True)

    for ser in series_list:
        frames = _list_frames(ser)
        if args.limit > 0:
            frames = frames[: args.limit]
        print(f"== {ser} n={len(frames)}", flush=True)
        for i, path in enumerate(frames, 1):
            row = process_one(ser, path, done)
            _append(row)
            print(
                f"[{ser} {i}/{len(frames)}] {path.name} {row.get('status')} "
                f"floors={row.get('floors')} cert={row.get('wf_certainty')} err={row.get('error')}",
                flush=True,
            )
            if i % 10 == 0:
                write_summary()

    write_summary()
    print("DONE", SUMMARY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
