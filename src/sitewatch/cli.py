from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.observe import observe_image, observe_video
from sitewatch.pipeline.seed import import_ksg, seed_demo
from sitewatch.services.queries import list_alerts, set_alert_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sitewatch")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed-demo", help="Generate demo data and run the full pipeline")
    p_ksg = sub.add_parser("import-ksg", help="Import KSG CSV/Excel")
    p_ksg.add_argument("path")
    p_ksg.add_argument("--project")
    p_ksg.add_argument("--zone")
    p_ksg.add_argument("--replace", action="store_true")

    p_obs = sub.add_parser("observe", help="Run CV → ActualState for one image")
    p_obs.add_argument("image")
    p_obs.add_argument("--project", default="site_001")
    p_obs.add_argument("--zone", required=True)
    p_obs.add_argument("--camera", required=True)
    p_obs.add_argument("--timestamp", required=True)

    p_vid = sub.add_parser("observe-video", help="Sample video → Observation Window → ActualState")
    p_vid.add_argument("video")
    p_vid.add_argument("--project", default="site_001")
    p_vid.add_argument("--zone", required=True)
    p_vid.add_argument("--camera", required=True)
    p_vid.add_argument("--timestamp", required=True)

    p_eval = sub.add_parser("evaluate", help="Plan/fact + temporal + alerts for a zone/date")
    p_eval.add_argument("--project", default="site_001")
    p_eval.add_argument("--zone", required=True)
    p_eval.add_argument("--date", required=True)

    sub.add_parser("alerts", help="List alerts")
    p_dec = sub.add_parser("decide", help="Record inspector decision for an alert")
    p_dec.add_argument("alert_id")
    p_dec.add_argument("--status", required=True, choices=["open", "confirmed", "rejected", "needs_more_data"])
    p_dec.add_argument("--reason", default="")
    p_dec.add_argument("--note", default="")
    p_dec.add_argument("--actor", default="inspector")
    sub.add_parser("api", help="Run FastAPI + React UI on :8000")
    sub.add_parser("ui", help="Run FastAPI + React UI on :8000")
    p_cap = sub.add_parser("capture", help="Grab due camera frames and refresh plan/fact")
    p_cap.add_argument("--camera")
    p_cap.add_argument("--project")
    p_cap.add_argument("--zone")
    p_cap.add_argument("--force", action="store_true")

    p_an = sub.add_parser("analyze", help="Perception smoke: frame → ObservedState → ActualState")
    p_an.add_argument("image")
    p_an.add_argument("--project", default="site_001")
    p_an.add_argument("--zone", required=True)
    p_an.add_argument("--camera", required=True)
    p_an.add_argument("--timestamp", default=None)
    p_an.add_argument("--mode", default=None, help="annotation|real|full")
    p_an.add_argument("--evaluate", action="store_true")

    p_bench = sub.add_parser("perception-benchmark", help="Run real-image perception benchmark")
    p_bench.add_argument("root", nargs="?", default="validation/perception")
    p_bench.add_argument("--out", default=None)
    p_bench.add_argument("--mode", default="real", help="annotation|real|full")

    p_vc = sub.add_parser("vlm-compare", help="Эксперимент сравнения VLM. Не пишет в рабочую БД.")
    p_vc.add_argument("rest", nargs=argparse.REMAINDER)

    args = parser.parse_args(argv)
    if args.cmd == "seed-demo":
        result = seed_demo()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "import-ksg":
        from sitewatch.services.catalog import import_schedule_file

        if args.project and args.zone:
            result = import_schedule_file(
                Path(args.path),
                project_code=args.project,
                zone_code=args.zone,
                replace=args.replace,
            )
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps({"imported": import_ksg(Path(args.path), project_code=args.project, replace=args.replace)}))
        return 0
    if args.cmd == "observe":
        state = observe_image(
            image_path=Path(args.image),
            project_code=args.project,
            zone_code=args.zone,
            camera_code=args.camera,
            timestamp=datetime.fromisoformat(args.timestamp),
        )
        print(state.model_dump_json(indent=2))
        return 0
    if args.cmd == "observe-video":
        state = observe_video(
            video_path=Path(args.video),
            project_code=args.project,
            zone_code=args.zone,
            camera_code=args.camera,
            timestamp=datetime.fromisoformat(args.timestamp),
        )
        print(state.model_dump_json(indent=2))
        return 0
    if args.cmd == "evaluate":
        ids = evaluate_zone_date(
            project_code=args.project,
            zone_code=args.zone,
            on_date=datetime.fromisoformat(args.date).date(),
        )
        print(json.dumps({"alert_ids": ids}))
        return 0
    if args.cmd == "alerts":
        print(json.dumps(list_alerts(), ensure_ascii=False, indent=2))
        return 0
    if args.cmd == "decide":
        result = set_alert_status(
            args.alert_id,
            args.status,
            reason=args.reason,
            note=args.note,
            actor=args.actor,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.cmd == "capture":
        from sitewatch.pipeline.capture import capture_due_cameras

        result = capture_due_cameras(
            force=args.force,
            camera_code=args.camera,
            project_code=args.project,
            zone_code=args.zone,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.cmd == "analyze":
        from sitewatch.pipeline.observe import observe_image
        from sitewatch.storage.db import get_session
        from sitewatch.storage.models import ObservedStateRecord, Project, Zone

        stamp = datetime.fromisoformat(args.timestamp) if args.timestamp else datetime.utcnow()
        state = observe_image(
            image_path=Path(args.image),
            project_code=args.project,
            zone_code=args.zone,
            camera_code=args.camera,
            timestamp=stamp,
            perception_mode=args.mode,
        )
        observed_payload = None
        with get_session() as session:
            project = session.query(Project).filter_by(code=args.project).one_or_none()
            zone = (
                session.query(Zone).filter_by(project_id=project.id, code=args.zone).one_or_none()
                if project
                else None
            )
            if project and zone:
                row = (
                    session.query(ObservedStateRecord)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .order_by(ObservedStateRecord.timestamp.desc())
                    .first()
                )
                if row:
                    observed_payload = json.loads(row.payload_json)
        out = {
            "actual_state": json.loads(state.model_dump_json()),
            "observed_state": observed_payload,
            "pipeline_run_id": state.pipeline_run_id,
        }
        if args.evaluate:
            out["alert_ids"] = evaluate_zone_date(
                project_code=args.project,
                zone_code=args.zone,
                on_date=stamp.date(),
            )
        # Human-readable summary
        obs = observed_payload or {}
        quality = obs.get("quality") or {}
        structures = obs.get("structures") or {}
        equipment = obs.get("equipment") or {}
        narrative = obs.get("observation") or {}
        run = obs.get("pipeline_run") or {}
        summary = {
            "frame": args.image,
            "quality": {
                "usable": quality.get("usable"),
                "blur": quality.get("blur"),
                "issues": quality.get("issues"),
            },
            "structures": {
                k: {"status": v.get("status"), "count": v.get("count_visible"), "confidence": v.get("confidence")}
                for k, v in structures.items()
                if isinstance(v, dict) and v.get("status") not in {None, "not_visible"}
            },
            "equipment": {
                k: {"status": v.get("status"), "count": v.get("count_visible"), "confidence": v.get("confidence")}
                for k, v in equipment.items()
                if isinstance(v, dict) and v.get("status") not in {None, "not_visible"}
            },
            "professional_observation": narrative.get("summary"),
            "limitations": narrative.get("limitations"),
            "latency_ms": run.get("total_latency_ms"),
            "pipeline_status": [
                {"name": s.get("name"), "status": s.get("status"), "latency_ms": s.get("latency_ms"), "error": s.get("error")}
                for s in (run.get("stages") or [])
            ],
            "artifacts": (obs.get("scene_attributes") or {}).get("artifact_paths"),
        }
        out["summary"] = summary
        print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.cmd == "perception-benchmark":
        from sitewatch.pipeline.benchmark import run_benchmark

        from sitewatch.perception.pipeline import resolve_perception_mode

        result = run_benchmark(
            Path(args.root),
            out_dir=Path(args.out) if args.out else None,
            mode=resolve_perception_mode(args.mode),
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.cmd == "vlm-compare":
        from sitewatch.experiments.vlm_compare.cli import main as vlm_compare_main

        rest = list(args.rest)
        if rest and rest[0] == "--":
            rest = rest[1:]
        return vlm_compare_main(rest)
    if args.cmd in {"api", "ui"}:
        return _serve()
    return 1


def _serve() -> int:
    import os
    import sys

    import uvicorn

    from sitewatch.settings import get_settings, project_root

    os.environ.setdefault("SITEWATCH_CAPTURE_LOOP", "1")
    get_settings.cache_clear()

    index = project_root() / "frontend" / "dist" / "index.html"
    if not index.is_file():
        print("SPA не собран: cd frontend && npm install && npm run build", file=sys.stderr)
    print("Скрипка — контроль строительства  http://127.0.0.1:8000")
    uvicorn.run("sitewatch.api.main:app", host="0.0.0.0", port=8000, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
