#!/usr/bin/env python3
"""E2E integration: TEST KSG → observe → evaluate → decision → re-evaluate evidence.

Uses SITEWATCH_DB_PATH (default /tmp/sw_integ_ksg.db). Not a real object schedule.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

DB_PATH = Path(os.environ.get("SITEWATCH_DB_PATH", "/tmp/sw_integ_ksg.db")).resolve()
os.environ["SITEWATCH_DB_PATH"] = str(DB_PATH)

from sitewatch.settings import get_settings

get_settings.cache_clear()
settings = get_settings()
if Path(settings.sqlite_path).resolve() != DB_PATH:
    raise SystemExit(
        f"DB path mismatch: settings={settings.sqlite_path!s} expected={DB_PATH!s}"
    )

from sitewatch.storage import db as dbmod

dbmod._engine = None
dbmod.SessionLocal = None

from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.observe import observe_image
from sitewatch.pipeline.seed import import_ksg, seed_catalog
from sitewatch.services.queries import get_alert, set_alert_status
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import Alert, Evidence, ScheduleStage, Zone

REPORT_PATH = ROOT / "validation" / "perception_regression" / "integration_ksg_report.json"
KSG_PATH = ROOT / "validation" / "perception_regression" / "test_ksg_building_01_jan2026.csv"
IMG_02 = ROOT / "data" / "source" / "site_001" / "2026-01-02.jpg"
IMG_06 = ROOT / "data" / "source" / "site_001" / "2026-01-06.jpg"


def _reset_db() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    for suffix in ("-wal", "-shm"):
        side = Path(str(DB_PATH) + suffix)
        if side.exists():
            side.unlink()
    dbmod._engine = None
    dbmod.SessionLocal = None
    get_settings.cache_clear()
    settings2 = get_settings()
    if Path(settings2.sqlite_path).resolve() != DB_PATH:
        raise RuntimeError(f"after reset path mismatch: {settings2.sqlite_path}")
    init_db()
    print(f"[integ] sqlite={settings2.sqlite_path}", flush=True)


def _sqlite_alert(alert_id: str) -> dict | None:
    con = sqlite3.connect(str(DB_PATH))
    try:
        row = con.execute(
            "SELECT id, alert_type, status, decision_reason, fingerprint FROM alerts WHERE id=?",
            (alert_id,),
        ).fetchone()
        if not row:
            return None
        ev = con.execute(
            "SELECT count(*) FROM evidence WHERE alert_id=?", (alert_id,)
        ).fetchone()[0]
        events = [
            r[0]
            for r in con.execute(
                "SELECT action FROM alert_events WHERE alert_id=? ORDER BY rowid",
                (alert_id,),
            )
        ]
        return {
            "id": row[0],
            "type": row[1],
            "status": row[2],
            "decision_reason": row[3] or "",
            "fingerprint": row[4] or "",
            "evidence_count": int(ev),
            "events": events,
        }
    finally:
        con.close()


def main() -> int:
    report: dict = {
        "label": "TEST KSG only — интеграция (не график объекта)",
        "db_path": str(DB_PATH),
        "ksg_csv": str(KSG_PATH.relative_to(ROOT)),
        "perception_mode_requested": "real",
        "commands": [
            f"SITEWATCH_DB_PATH={DB_PATH} {ROOT}/.venv/bin/python "
            "validation/perception_regression/run_integration_ksg.py"
        ],
        "steps": {},
        "blockers": [],
        "ok": False,
    }
    perception_mode = "real"

    try:
        _reset_db()
        seed_catalog()
        n_ksg = import_ksg(KSG_PATH, replace=True)
        with get_session() as session:
            stages = session.query(ScheduleStage).all()
            report["steps"]["ksg"] = {
                "imported_rows": n_ksg,
                "note": "TEST KSG only — not a real object schedule",
                "rows": [
                    {
                        "zone": session.get(Zone, s.zone_id).code
                        if session.get(Zone, s.zone_id)
                        else "?",
                        "start": s.start_date.isoformat(),
                        "end": s.end_date.isoformat() if s.end_date else None,
                        "stage": s.stage,
                        "stage_label": s.stage_label,
                        "expected": json.loads(s.expected_json),
                    }
                    for s in stages
                ],
            }

        print(f"[integ] observe {IMG_02.name} mode={perception_mode}", flush=True)
        state1 = observe_image(
            image_path=IMG_02,
            project_code="site_001",
            zone_code="building_01",
            camera_code="cam_building",
            timestamp=datetime(2026, 1, 2, 12, 0, 0),
            perception_mode=perception_mode,
        )
        # Re-assert engine still points at temp DB after heavy observe
        if Path(get_settings().sqlite_path).resolve() != DB_PATH:
            raise RuntimeError("sqlite path drifted after observe_01")

        report["perception_mode_used"] = perception_mode
        payload1 = json.loads(state1.model_dump_json())
        report["steps"]["observe_01"] = {
            "image": str(IMG_02.relative_to(ROOT)),
            "timestamp": "2026-01-02T12:00:00",
            "camera": "cam_building",
            "equipment": payload1.get("equipment") or {},
            "elements": payload1.get("elements") or {},
            "pipeline_run_id": state1.pipeline_run_id,
            "floors_scene": (state1.scene_attributes or {}).get("visible_floor_levels"),
        }

        alert_ids_1 = evaluate_zone_date(
            project_code="site_001",
            zone_code="building_01",
            on_date=date(2026, 1, 2),
        )
        report["steps"]["evaluate_01"] = {"alert_ids": alert_ids_1, "date": "2026-01-02"}
        if not alert_ids_1:
            report["blockers"].append("evaluate_zone_date(2026-01-02) produced no alerts")
            REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            return 1

        prefer = ("schedule_delay", "missing_equipment", "no_dynamics", "insufficient_evidence")
        primary_id = alert_ids_1[0]
        with get_session() as session:
            alerts = session.query(Alert).filter(Alert.id.in_(alert_ids_1)).all()
            by_type = {a.alert_type: a.id for a in alerts}
            report["steps"]["evaluate_01"]["types"] = {
                a.id: a.alert_type for a in alerts
            }
            for t in prefer:
                if t in by_type:
                    primary_id = by_type[t]
                    break

        before = _sqlite_alert(primary_id)
        if before is None:
            raise RuntimeError(f"primary alert {primary_id} missing in {DB_PATH}")
        evidence_before = before["evidence_count"]
        report["steps"]["alert_before_decision"] = before

        decided = set_alert_status(
            primary_id,
            "rejected",
            reason="false_detection",
            note="integration_ksg: TEST decision — false_detection",
            actor="inspector",
        )
        mid = _sqlite_alert(primary_id)
        report["steps"]["decision"] = {
            "alert_id": primary_id,
            "status": decided["status"],
            "decision_reason": decided.get("decision_reason"),
            "decided_by": decided.get("decided_by"),
            "sqlite_verify": mid,
        }
        if not mid or mid["status"] != "rejected":
            raise RuntimeError(f"decision not visible in sqlite: {mid}")

        print(f"[integ] observe second frame same date", flush=True)
        state2 = observe_image(
            image_path=IMG_06,
            project_code="site_001",
            zone_code="building_01",
            camera_code="cam_building",
            timestamp=datetime(2026, 1, 2, 18, 0, 0),
            perception_mode=perception_mode,
        )
        report["steps"]["observe_02"] = {
            "image": str(IMG_06.relative_to(ROOT)),
            "timestamp": "2026-01-02T18:00:00",
            "note": "second frame same evaluate date → new evidence, same episode fingerprint",
            "pipeline_run_id": state2.pipeline_run_id,
        }

        alert_ids_2 = evaluate_zone_date(
            project_code="site_001",
            zone_code="building_01",
            on_date=date(2026, 1, 2),
        )
        after = _sqlite_alert(primary_id)
        if after is None:
            raise RuntimeError(f"primary alert {primary_id} vanished after re-evaluate")
        evidence_after = after["evidence_count"]
        report["steps"]["evaluate_02"] = {
            "alert_ids": alert_ids_2,
            "date": "2026-01-02",
            "primary_still_present": primary_id in alert_ids_2 or after["status"] == "rejected",
        }
        report["steps"]["alert_after_reevaluate"] = after

        # Advancing TEST KSG on 2026-01-06
        print(f"[integ] observe+evaluate 2026-01-06", flush=True)
        state3 = observe_image(
            image_path=IMG_06,
            project_code="site_001",
            zone_code="building_01",
            camera_code="cam_building",
            timestamp=datetime(2026, 1, 6, 12, 0, 0),
            perception_mode=perception_mode,
        )
        alert_ids_06 = evaluate_zone_date(
            project_code="site_001",
            zone_code="building_01",
            on_date=date(2026, 1, 6),
        )
        # Decision must still be intact after later-date evaluate
        final = _sqlite_alert(primary_id)
        report["steps"]["observe_evaluate_06"] = {
            "pipeline_run_id": state3.pipeline_run_id,
            "alert_ids": alert_ids_06,
            "note": "advancing TEST KSG floors 4→5 on 2026-01-06",
            "primary_after": final,
        }

        decision_preserved = (
            final is not None
            and final["status"] == "rejected"
            and final.get("decision_reason") == "false_detection"
        )
        evidence_grew = evidence_after > evidence_before
        with get_session() as session:
            same_fp = (
                session.query(Alert)
                .filter_by(fingerprint=before["fingerprint"])
                .count()
            )
        report["assertions"] = {
            "decision_preserved": decision_preserved,
            "evidence_before": evidence_before,
            "evidence_after": evidence_after,
            "evidence_grew": evidence_grew,
            "fingerprint_alert_count": same_fp,
            "no_duplicate_primary": same_fp == 1,
            "sqlite_path": str(DB_PATH),
            "settings_sqlite_path": str(Path(get_settings().sqlite_path).resolve()),
        }
        report["ok"] = bool(
            decision_preserved and evidence_grew and same_fp == 1
        )
        if not decision_preserved:
            report["blockers"].append("inspector decision not preserved after re-evaluate")
        if not evidence_grew:
            report["blockers"].append(
                f"evidence did not grow ({evidence_before} → {evidence_after})"
            )

    except Exception as exc:
        report["blockers"].append(repr(exc))
        report["traceback"] = traceback.format_exc()
        report["ok"] = False

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "ok": report["ok"],
                "report": str(REPORT_PATH),
                "db_path": str(DB_PATH),
                "blockers": report["blockers"],
                "assertions": report.get("assertions"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
