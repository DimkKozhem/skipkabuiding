#!/usr/bin/env python3
"""Recompute key timelapse frames with real perception (SAM + Qwen).

Does NOT open holdout. Preserves inspector decisions; clears derived ActualState
only for listed zones before re-observe of the key-frame set.

Usage:
  SITEWATCH_PERCEPTION_MODE=real \\
  .venv/bin/python validation/perception_regression/recompute_timelapse_facts.py
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("SITEWATCH_PERCEPTION_MODE", "real")
# Ensure Qwen is on for floor levels (house6 ingest previously forced false).
os.environ["SITEWATCH_QWEN_VL_ENABLED"] = "true"
os.environ.setdefault("SITEWATCH_SAM3_DEVICE", "cuda:1")

from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.observe import observe_image
from sitewatch.services.catalog import delete_observation
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import (
    ActualStateRecord,
    Alert,
    AlertEvent,
    Camera,
    DeviationRecord,
    Evidence,
    Observation,
    Project,
    Zone,
)

OUT = ROOT / "validation" / "perception_regression" / "timelapse_recompute_report.json"

# Manual verification notes (not GT for training; used in the report).
MANUAL = {
    ("house6", "2026-01-01"): "early: котлован, 0 этажей на участке; соседний дом не считать",
    ("house6", "2026-06-15"): "mid: каркас ~3 видимых уровня + кран",
    ("house6", "2026-11-08"): "late build: много уровней фасада",
    ("house6", "2026-12-24"): "final: готовый фасад, ожидаемо ~6 этажей",
    ("office_01", "2022-06-01"): "early office site",
    ("office_01", "2022-08-31"): "mid: явно 2 этажа блоков, кровля",
    ("office_01", "2023-01-29"): "final: 2 этажа, фасад, окна, снег",
    ("road_alley", "2016-10-25"): "начало работ на разделителе",
    ("road_alley", "2016-10-29"): "середина: отсыпка/техника",
    ("road_alley", "2016-11-03"): "финал клипа: экскаватор, грунт, рабочие; метры не калиброваны",
}


@dataclass
class FrameResult:
    zone: str
    day: str
    path: str
    status: str  # ok | error | skipped
    error: str | None = None
    floors: int | None = None
    floors_derivation: str | None = None
    structural_levels: int | None = None
    equipment: dict = field(default_factory=dict)
    elements_present: list[str] = field(default_factory=list)
    summary: str = ""
    qwen_status: str | None = None
    sam_status: str | None = None
    pipeline_run_id: str | None = None
    manual_note: str = ""


@dataclass
class RunSummary:
    started_at: str
    finished_at: str | None = None
    frames_queued: int = 0
    frames_ok: int = 0
    frames_error: int = 0
    frames_with_floors: int = 0
    frames_with_equipment: int = 0
    results: list[FrameResult] = field(default_factory=list)


def _key_frames() -> list[tuple[str, str, Path, str, date]]:
    """zone, camera, path, day_iso, day."""
    items: list[tuple[str, str, Path, str, date]] = []
    house = ROOT / "data" / "sources" / "house6_2026" / "frames"
    for day in ("2026-01-01", "2026-03-15", "2026-06-15", "2026-09-01", "2026-11-08", "2026-12-24"):
        p = house / f"{day}.jpg"
        if p.exists():
            d = date.fromisoformat(day)
            items.append(("house6", "cam_house6", p, day, d))
    office = ROOT / "data" / "sources" / "office_domodedovo" / "frames"
    for day in ("2022-06-01", "2022-07-01", "2022-08-01", "2022-08-31", "2022-09-15", "2022-11-01", "2023-01-29"):
        p = office / f"{day}.jpg"
        if p.exists():
            d = date.fromisoformat(day)
            items.append(("office_01", "cam_office_01", p, day, d))
    road = ROOT / "data" / "sources" / "road_divider" / "frames"
    for p in sorted(road.glob("2016-*.jpg")):
        day = p.stem
        d = date.fromisoformat(day)
        items.append(("road_alley", "cam_road_alley", p, day, d))
    return items


def _clear_zone_derived(zone_code: str) -> dict:
    """Remove observations/actuals/open alerts for zone. Keep schedule and cameras."""
    init_db()
    stats = {"observations": 0, "alerts": 0}
    with get_session() as session:
        project = session.query(Project).filter_by(code="site_001").one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
        obs_ids = [r.id for r in session.query(Observation).filter_by(zone_id=zone.id).all()]
        alerts = session.query(Alert).filter_by(zone_id=zone.id).all()
        alert_ids = [a.id for a in alerts]
        if alert_ids:
            session.query(Evidence).filter(Evidence.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            session.query(AlertEvent).filter(AlertEvent.alert_id.in_(alert_ids)).delete(synchronize_session=False)
            session.query(Alert).filter(Alert.id.in_(alert_ids)).delete(synchronize_session=False)
        session.query(DeviationRecord).filter_by(zone_id=zone.id).delete(synchronize_session=False)
        if obs_ids:
            session.query(ActualStateRecord).filter(ActualStateRecord.observation_id.in_(obs_ids)).delete(
                synchronize_session=False
            )
        stats["alerts"] = len(alert_ids)
        session.commit()
    for oid in obs_ids:
        delete_observation(oid)
    stats["observations"] = len(obs_ids)
    return stats


def _extract_fact(actual) -> dict:
    sc = actual.scene_attributes or {}
    el = actual.elements or {}
    floors = el.get("floors")
    floors_n = int(floors.count) if floors is not None and getattr(floors, "count", 0) else None
    if floors_n == 0:
        floors_n = None
    levels = sc.get("structural_levels")
    visible = sc.get("visible_floor_levels")
    if floors_n is None and levels is not None:
        try:
            floors_n = int(levels)
        except (TypeError, ValueError):
            floors_n = None
    if floors_n is None and visible is not None:
        try:
            floors_n = int(visible)
        except (TypeError, ValueError):
            floors_n = None
    present = []
    for k, v in el.items():
        if hasattr(v, "detected") and v.detected:
            present.append(k)
        elif hasattr(v, "count") and int(v.count or 0) > 0 and float(getattr(v, "max_confidence", 0) or 0) > 0:
            present.append(k)
    eq = {}
    for k, v in (actual.equipment or {}).items():
        c = int(getattr(v, "count", 0) or 0)
        if c > 0 and float(getattr(v, "max_confidence", 0) or 0) > 0:
            eq[k] = c
    return {
        "floors": floors_n,
        "floors_derivation": sc.get("floors_derivation"),
        "structural_levels": levels,
        "floors_status": sc.get("floors_status") or sc.get("floors_status_latest"),
        "equipment": eq,
        "elements_present": present,
        "summary": str(sc.get("observation_summary") or "")[:240],
        "pipeline_run_id": actual.pipeline_run_id,
    }


def _stage_statuses(actual) -> tuple[str | None, str | None]:
    # pipeline stages live on ObservedState; peek artifact if needed
    run_id = actual.pipeline_run_id
    if not run_id:
        return None, None
    path = ROOT / "data" / "observations" / "artifacts" / run_id / "pipeline_run.json"
    if not path.exists():
        return None, None
    run = json.loads(path.read_text())
    sam = qwen = None
    for st in run.get("stages") or []:
        if st.get("name") == "sam3":
            sam = st.get("status")
        if st.get("name") == "qwen_vl":
            qwen = st.get("status")
    return sam, qwen


def main() -> int:
    init_db()
    summary = RunSummary(started_at=datetime.now().isoformat(timespec="seconds"))
    frames = _key_frames()
    summary.frames_queued = len(frames)
    zones = sorted({z for z, *_ in frames})
    clear_stats = {z: _clear_zone_derived(z) for z in zones}
    print("cleared", clear_stats, flush=True)

    for zone, camera, path, day, d in frames:
        print(f"observe {zone} {day} …", flush=True)
        fr = FrameResult(
            zone=zone,
            day=day,
            path=str(path),
            status="ok",
            manual_note=MANUAL.get((zone, day), ""),
        )
        try:
            actual = observe_image(
                image_path=path,
                project_code="site_001",
                zone_code=zone,
                camera_code=camera,
                timestamp=datetime(d.year, d.month, d.day, 12, 0, 0),
                perception_mode="real",
                capture_origin="scheduled_capture",
            )
            fact = _extract_fact(actual)
            fr.floors = fact["floors"]
            fr.floors_derivation = fact["floors_derivation"]
            fr.structural_levels = fact["structural_levels"]
            fr.equipment = fact["equipment"]
            fr.elements_present = fact["elements_present"]
            fr.summary = fact["summary"]
            fr.pipeline_run_id = fact["pipeline_run_id"]
            fr.sam_status, fr.qwen_status = _stage_statuses(actual)
            summary.frames_ok += 1
            if fr.floors:
                summary.frames_with_floors += 1
            if fr.equipment:
                summary.frames_with_equipment += 1
            print(
                f"  ok floors={fr.floors} der={fr.floors_derivation} "
                f"eq={fr.equipment} qwen={fr.qwen_status} sam={fr.sam_status}",
                flush=True,
            )
        except Exception as exc:
            fr.status = "error"
            fr.error = f"{type(exc).__name__}: {exc}"
            summary.frames_error += 1
            print(f"  ERROR {fr.error}", flush=True)
            traceback.print_exc()
        summary.results.append(fr)

    # Evaluate tip dates per zone
    eval_days = {
        "house6": [date(2026, 6, 15), date(2026, 12, 24)],
        "office_01": [date(2022, 8, 31), date(2023, 1, 29)],
        "road_alley": [date(2016, 10, 29), date(2016, 11, 3)],
    }
    eval_out = {}
    for zone, days in eval_days.items():
        eval_out[zone] = []
        for d in days:
            try:
                ids = evaluate_zone_date(project_code="site_001", zone_code=zone, on_date=d)
                eval_out[zone].append({"date": d.isoformat(), "alert_ids": ids})
                print(f"eval {zone} {d} → {len(ids)} alerts", flush=True)
            except Exception as exc:
                eval_out[zone].append({"date": d.isoformat(), "error": str(exc)})
                print(f"eval ERROR {zone} {d}: {exc}", flush=True)

    summary.finished_at = datetime.now().isoformat(timespec="seconds")
    report = {
        "label": "timelapse key-frame recompute (real + Qwen)",
        "clear_stats": clear_stats,
        "summary": asdict(summary),
        "evaluate": eval_out,
        "notes": [
            "dividing_line_m not measured (no calibration)",
            "floors from VLM visible_floor_levels only, not SAM box count",
            "manual_note is human check aid, not independent formal GT",
        ],
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", OUT, flush=True)
    print(
        f"SUMMARY queued={summary.frames_queued} ok={summary.frames_ok} "
        f"err={summary.frames_error} with_floors={summary.frames_with_floors} "
        f"with_equipment={summary.frames_with_equipment}",
        flush=True,
    )
    return 0 if summary.frames_error == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
