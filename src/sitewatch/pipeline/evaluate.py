from __future__ import annotations

import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import text

from sitewatch.cv.aggregator import merge_actual_states
from sitewatch.cv.embeddings import visual_change
from sitewatch.deviation.plan_fact import PlanFactEngine
from sitewatch.domain.contracts import ActualState, ExpectedState
from sitewatch.evidence.builder import evidence_from_observations
from sitewatch.inspector.workflow import persist_candidate
from sitewatch.ksg.expected import build_expected_state
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import (
    ActualStateRecord,
    Camera,
    ExpectedStateRecord,
    MediaAsset,
    Observation,
    Project,
    ScheduleStage,
    StateTransitionRecord,
    Zone,
)
from sitewatch.temporal.engine import TemporalEngine


def _load_json(text: str) -> dict:
    return json.loads(text)


def _actual_from_row(row: ActualStateRecord) -> ActualState:
    from sitewatch.services.queries import _demote_legacy_floors

    payload = json.loads(row.payload_json)
    if isinstance(payload, dict):
        from sitewatch.works.reinterpret import detach_unconfirmed_floor_value, reinterpret_work_facts

        reinterpret_work_facts(payload)
        _demote_legacy_floors(payload)
        detach_unconfirmed_floor_value(payload)
        payload.pop("work_facts_archive", None)
        return ActualState.model_validate(payload)
    return ActualState.model_validate_json(row.payload_json)


def _camera_of(row: ActualStateRecord) -> str:
    payload = _load_json(row.payload_json)
    return str(payload.get("camera_code") or "")


def _safe_visual_change(path_a: str | None, path_b: str | None) -> float | None:
    if not path_a or not path_b:
        return None
    a, b = Path(path_a), Path(path_b)
    if not a.exists() or not b.exists():
        return None
    if a.suffix.lower() not in {".jpg", ".jpeg", ".png"} or b.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        return None
    try:
        return visual_change(a, b)
    except Exception:
        return None


def evaluate_zone_date(
    *,
    project_code: str,
    zone_code: str,
    on_date: date,
) -> list[str]:
    """Plan/fact + temporal evaluation for one zone/date.

    Temporal comparison is per camera / comparable viewpoint. Different cameras
    are never treated as a single state change.
    """
    init_db()
    engine = PlanFactEngine()
    temporal = TemporalEngine()
    alert_ids: list[str] = []

    with get_session() as session:
        project = session.query(Project).filter_by(code=project_code).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
        stage_row = (
            session.query(ScheduleStage)
            .filter(
                ScheduleStage.project_id == project.id,
                ScheduleStage.zone_id == zone.id,
                ScheduleStage.start_date <= on_date,
            )
            .order_by(ScheduleStage.start_date.desc())
            .first()
        )
        if stage_row is None:
            raise ValueError(f"No KSG row for {project_code}/{zone_code} on {on_date}")
        expected = build_expected_state(
            object_id=project.code,
            zone_id=zone.code,
            on_date=on_date,
            stage=stage_row.stage,
            expected=_load_json(stage_row.expected_json),
            start_date=stage_row.start_date,
            end_date=stage_row.end_date,
            stage_label_override=stage_row.stage_label or None,
            schedule_row_id=str(stage_row.id),
        )
        existing_expected = (
            session.query(ExpectedStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id, date=on_date)
            .first()
        )
        if existing_expected is None:
            session.add(
                ExpectedStateRecord(
                    project_id=project.id,
                    zone_id=zone.id,
                    date=on_date,
                    stage=expected.stage,
                    payload_json=expected.model_dump_json(),
                )
            )

        state_rows = (
            session.query(ActualStateRecord)
            .filter(
                ActualStateRecord.project_id == project.id,
                ActualStateRecord.zone_id == zone.id,
            )
            .order_by(ActualStateRecord.timestamp.asc(), text("rowid ASC"))
            .all()
        )
        if not state_rows:
            return []

        expected_series = [
            build_expected_state(
                object_id=project.code,
                zone_id=zone.code,
                on_date=row.start_date,
                stage=row.stage,
                expected=_load_json(row.expected_json),
                start_date=row.start_date,
                end_date=row.end_date,
                stage_label_override=row.stage_label or None,
                schedule_row_id=str(row.id),
            )
            for row in session.query(ScheduleStage)
            .filter(ScheduleStage.project_id == project.id, ScheduleStage.zone_id == zone.id)
            .order_by(ScheduleStage.start_date.asc())
            .all()
        ]

        by_camera: dict[str, list[ActualStateRecord]] = defaultdict(list)
        for row in state_rows:
            by_camera[_camera_of(row)].append(row)

        cameras = {item.id: item for item in session.query(Camera).all()}

        for _camera_code, cam_rows in by_camera.items():
            day_rows = [row for row in cam_rows if row.timestamp.date() == on_date]
            if not day_rows:
                continue
            history_rows = [row for row in cam_rows if row.timestamp.date() < on_date]
            history_by_day: dict[date, list[ActualStateRecord]] = defaultdict(list)
            for row in history_rows:
                history_by_day[row.timestamp.date()].append(row)
            history = [
                merge_actual_states([_actual_from_row(item) for item in items])
                for _, items in sorted(history_by_day.items())
            ]
            actual = merge_actual_states([_actual_from_row(row) for row in day_rows])

            series_rows = history_rows + day_rows
            obs_ids = [row.observation_id for row in series_rows]
            observations = session.query(Observation).filter(Observation.id.in_(obs_ids)).all()
            obs_by_id = {item.id: item for item in observations}
            media_by_id = {
                item.id: item
                for item in session.query(MediaAsset).filter(MediaAsset.id.in_([obs.media_id for obs in observations]))
            }
            evidence_rows = []
            for obs in sorted(observations, key=lambda item: item.timestamp):
                media = media_by_id.get(obs.media_id)
                camera = cameras.get(obs.camera_id)
                evidence_rows.append(
                    {
                        "media_path": media.path if media else "",
                        "timestamp": obs.timestamp,
                        "observation_id": obs.id,
                        "media_id": media.id if media else None,
                        "viz_path": obs.viz_path,
                        "camera_code": camera.code if camera else None,
                    }
                )
            evidence = evidence_from_observations(evidence_rows)

            timeline_states = history + [actual]
            visual_changes: list[float | None] = []
            if len(timeline_states) >= 2:
                ordered_rows = []
                for _, items in sorted(history_by_day.items()):
                    ordered_rows.append(items[-1])
                ordered_rows.append(day_rows[-1])
                for idx in range(1, len(ordered_rows)):
                    prev_obs = obs_by_id.get(ordered_rows[idx - 1].observation_id)
                    curr_obs = obs_by_id.get(ordered_rows[idx].observation_id)
                    prev_media = media_by_id.get(prev_obs.media_id) if prev_obs else None
                    curr_media = media_by_id.get(curr_obs.media_id) if curr_obs else None
                    visual_changes.append(
                        _safe_visual_change(
                            prev_media.path if prev_media else None,
                            curr_media.path if curr_media else None,
                        )
                    )
                    already = (
                        session.query(StateTransitionRecord)
                        .filter_by(
                            from_state_id=ordered_rows[idx - 1].id,
                            to_state_id=ordered_rows[idx].id,
                        )
                        .first()
                    )
                    if already is None:
                        transition = temporal.transition(
                            timeline_states[idx - 1],
                            timeline_states[idx],
                            visual_change=visual_changes[-1],
                        )
                        session.add(
                            StateTransitionRecord(
                                project_id=project.id,
                                zone_id=zone.id,
                                from_state_id=ordered_rows[idx - 1].id,
                                to_state_id=ordered_rows[idx].id,
                                payload_json=transition.model_dump_json(),
                            )
                        )

            candidates = engine.evaluate(
                expected,
                actual,
                history=history,
                expected_series=expected_series,
                evidence=evidence,
                visual_changes=visual_changes or None,
            )
            for candidate in candidates:
                alert_id, _created = persist_candidate(
                    session,
                    project_id=project.id,
                    zone_id=zone.id,
                    candidate=candidate,
                )
                alert_ids.append(alert_id)
    return alert_ids
