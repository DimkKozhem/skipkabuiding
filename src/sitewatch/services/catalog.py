from __future__ import annotations

import json
import re
import secrets
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import or_

from sitewatch.ksg.expected import load_equipment_rules, stage_label
from sitewatch.ksg.parser import parse_ksg
from sitewatch.services.queries import _camera_item, _session
from sitewatch.catalog.construction import construction_type_name, known_construction_type_ids
from sitewatch.storage.models import (
    ActualStateRecord,
    Alert,
    AlertEvent,
    Camera,
    DetectionRecord,
    DeviationRecord,
    Evidence,
    EvidenceArtifactRecord,
    ExpectedStateRecord,
    FrameAnalysisJob,
    MediaAsset,
    Observation,
    ObservedStateRecord,
    PipelineRunRecord,
    Project,
    ScheduleStage,
    StateTransitionRecord,
    Zone,
    ZoneNote,
)

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
SOURCE_TYPES = {"photo", "video", "stream", "folder"}


def normalize_code(raw: str, field: str = "code") -> str:
    text = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not CODE_RE.match(text):
        raise ValueError(f"{field} must start with a letter and use latin letters, digits or underscore")
    return text


def _required_name(raw: str, field: str = "name") -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text[:256]


def _as_date(value: date | str | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _check_period(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("Окончание не может быть раньше начала.")


def _project(session, project_code: str) -> Project:
    project = session.query(Project).filter_by(code=project_code).one_or_none()
    if project is None:
        raise KeyError("project not found")
    return project


def _zone(session, project: Project, zone_code: str) -> Zone:
    zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none()
    if zone is None:
        raise KeyError("zone not found")
    return zone


def _stage_payload(row: ScheduleStage, zone_code: str | None) -> dict:
    return {
        "id": row.id,
        "zone": zone_code,
        "stage": row.stage,
        "stage_label": row.stage_label,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "expected": json.loads(row.expected_json or "{}"),
    }


def catalog_stages() -> list[dict]:
    stages = (load_equipment_rules().get("stages") or {})
    result = []
    for code, payload in stages.items():
        item = payload or {}
        result.append(
            {
                "code": code,
                "label": item.get("label") or stage_label(code),
                "required_equipment": item.get("required_equipment") or [],
                "unexpected_equipment": item.get("unexpected_equipment") or [],
            }
        )
    return result


def create_project(*, code: str, name: str, address: str = "") -> dict:
    code = normalize_code(code, "project code")
    name = _required_name(name)
    with _session() as session:
        if session.query(Project).filter_by(code=code).one_or_none():
            raise PermissionError("project already exists")
        project = Project(code=code, name=name, address=(address or "").strip()[:512])
        session.add(project)
        session.flush()
        return {
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "address": project.address,
            "zones": [],
        }


def update_project(project_code: str, *, name: str | None = None, address: str | None = None) -> dict:
    with _session() as session:
        project = _project(session, project_code)
        if name is not None:
            project.name = _required_name(name)
        if address is not None:
            project.address = address.strip()[:512]
        return {
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "address": project.address,
        }


def _zone_fields(zone: Zone) -> dict:
    type_id = (zone.construction_type_id or "").strip() or None
    return {
        "id": zone.id,
        "code": zone.code,
        "name": zone.name,
        "description": zone.description or "",
        "construction_type_id": type_id,
        "construction_type_name": construction_type_name(type_id),
    }


def _normalize_description(raw: str | None) -> str:
    return (raw or "").strip()[:2000]


def _normalize_construction_type_id(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text not in known_construction_type_ids():
        raise ValueError("unknown construction_type_id")
    return text


def create_zone(
    project_code: str,
    *,
    code: str | None = None,
    name: str,
    description: str = "",
    construction_type_id: str | None = None,
) -> dict:
    name = _required_name(name)
    if code is None or not str(code).strip():
        zone_code = f"obj_{secrets.token_hex(4)}"
    else:
        zone_code = normalize_code(code, "zone code")
    description_text = _normalize_description(description)
    type_id = _normalize_construction_type_id(construction_type_id)
    with _session() as session:
        project = _project(session, project_code)
        if session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none():
            raise PermissionError("zone already exists")
        zone = Zone(
            project_id=project.id,
            code=zone_code,
            name=name,
            description=description_text,
            construction_type_id=type_id,
        )
        session.add(zone)
        session.flush()
        payload = _zone_fields(zone)
        payload["cameras"] = []
        return payload


def update_zone(
    project_code: str,
    zone_code: str,
    *,
    name: str | None = None,
    description: str | None = None,
    construction_type_id: str | None = ...,
) -> dict:
    with _session() as session:
        project = _project(session, project_code)
        zone = _zone(session, project, zone_code)
        if name is not None:
            zone.name = _required_name(name)
        if description is not None:
            zone.description = _normalize_description(description)
        if construction_type_id is not ...:
            zone.construction_type_id = _normalize_construction_type_id(construction_type_id)
        return _zone_fields(zone)


def list_zone_notes(project_code: str, zone_code: str) -> list[dict]:
    with _session() as session:
        project = _project(session, project_code)
        zone = _zone(session, project, zone_code)
        rows = (
            session.query(ZoneNote)
            .filter_by(zone_id=zone.id)
            .order_by(ZoneNote.created_at.desc())
            .all()
        )
        return [
            {
                "id": row.id,
                "body": row.body,
                "author": row.author or "",
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]


def create_zone_note(
    project_code: str,
    zone_code: str,
    *,
    body: str,
    author: str = "",
) -> dict:
    text = (body or "").strip()
    if not text:
        raise ValueError("body is required")
    with _session() as session:
        project = _project(session, project_code)
        zone = _zone(session, project, zone_code)
        note = ZoneNote(
            zone_id=zone.id,
            body=text[:4000],
            author=(author or "").strip()[:128],
        )
        session.add(note)
        session.flush()
        return {
            "id": note.id,
            "body": note.body,
            "author": note.author,
            "created_at": note.created_at.isoformat() if note.created_at else None,
        }


def _delete_in(session, model, column, ids: list[str]) -> None:
    if ids:
        session.query(model).filter(column.in_(ids)).delete(synchronize_session=False)


def _purge_zone(session, *, project_id: str, project_code: str, zone_id: str, zone_code: str) -> None:
    """Remove schedule, sources, frames and signals that belong to one object."""
    alert_ids = [row.id for row in session.query(Alert.id).filter_by(project_id=project_id, zone_id=zone_id)]
    observations = session.query(Observation).filter_by(project_id=project_id, zone_id=zone_id).all()
    observation_ids = [row.id for row in observations]
    camera_ids = [row.id for row in session.query(Camera.id).filter_by(zone_id=zone_id)]
    media_ids = {row.media_id for row in observations if row.media_id}
    if camera_ids:
        media_ids.update(
            row.id for row in session.query(MediaAsset.id).filter(MediaAsset.camera_id.in_(camera_ids))
        )
    state_ids = [
        row.id for row in session.query(ActualStateRecord.id).filter_by(project_id=project_id, zone_id=zone_id)
    ]

    _delete_in(session, Evidence, Evidence.alert_id, alert_ids)
    _delete_in(session, Evidence, Evidence.observation_id, observation_ids)
    _delete_in(session, Evidence, Evidence.media_id, list(media_ids))
    _delete_in(session, AlertEvent, AlertEvent.alert_id, alert_ids)
    _delete_in(session, Alert, Alert.id, alert_ids)
    session.query(DeviationRecord).filter_by(project_id=project_id, zone_id=zone_id).delete(synchronize_session=False)

    _delete_in(session, EvidenceArtifactRecord, EvidenceArtifactRecord.observation_id, observation_ids)
    session.query(ObservedStateRecord).filter_by(project_id=project_id, zone_id=zone_id).delete(
        synchronize_session=False
    )
    if state_ids:
        session.query(StateTransitionRecord).filter(
            or_(
                StateTransitionRecord.from_state_id.in_(state_ids),
                StateTransitionRecord.to_state_id.in_(state_ids),
            )
        ).delete(synchronize_session=False)
    session.query(StateTransitionRecord).filter_by(project_id=project_id, zone_id=zone_id).delete(
        synchronize_session=False
    )
    session.query(ActualStateRecord).filter_by(project_id=project_id, zone_id=zone_id).delete(
        synchronize_session=False
    )
    _delete_in(session, DetectionRecord, DetectionRecord.observation_id, observation_ids)
    if observation_ids:
        session.query(PipelineRunRecord).filter(
            or_(
                PipelineRunRecord.zone_id == zone_id,
                PipelineRunRecord.observation_id.in_(observation_ids),
            )
        ).delete(synchronize_session=False)
    else:
        session.query(PipelineRunRecord).filter_by(project_id=project_id, zone_id=zone_id).delete(
            synchronize_session=False
        )
    _delete_in(session, Observation, Observation.id, observation_ids)
    _delete_in(session, MediaAsset, MediaAsset.id, list(media_ids))
    _delete_in(session, Camera, Camera.id, camera_ids)
    session.query(ZoneNote).filter_by(zone_id=zone_id).delete(synchronize_session=False)
    session.query(ScheduleStage).filter_by(project_id=project_id, zone_id=zone_id).delete(synchronize_session=False)
    session.query(ExpectedStateRecord).filter_by(project_id=project_id, zone_id=zone_id).delete(
        synchronize_session=False
    )
    session.query(FrameAnalysisJob).filter_by(project_code=project_code, zone_code=zone_code).delete(
        synchronize_session=False
    )


def delete_zone(project_code: str, zone_code: str) -> dict:
    with _session() as session:
        project = _project(session, project_code)
        zone = _zone(session, project, zone_code)
        _purge_zone(
            session,
            project_id=project.id,
            project_code=project.code,
            zone_id=zone.id,
            zone_code=zone.code,
        )
        session.query(Zone).filter_by(id=zone.id).delete(synchronize_session=False)
        session.expunge_all()
        return {"ok": True, "zone": zone_code}


def delete_observation(observation_id: str) -> dict:
    """Drop one frame and the fact derived from it. Signals stay; this frame leaves their evidence."""
    with _session() as session:
        observation = session.get(Observation, observation_id)
        if observation is None:
            raise KeyError("observation not found")
        media_id = observation.media_id
        state_ids = [
            row.id for row in session.query(ActualStateRecord.id).filter_by(observation_id=observation.id)
        ]
        session.query(Evidence).filter_by(observation_id=observation.id).delete(synchronize_session=False)
        session.query(EvidenceArtifactRecord).filter_by(observation_id=observation.id).delete(
            synchronize_session=False
        )
        session.query(ObservedStateRecord).filter_by(observation_id=observation.id).delete(
            synchronize_session=False
        )
        if state_ids:
            session.query(StateTransitionRecord).filter(
                or_(
                    StateTransitionRecord.from_state_id.in_(state_ids),
                    StateTransitionRecord.to_state_id.in_(state_ids),
                )
            ).delete(synchronize_session=False)
        session.query(ActualStateRecord).filter_by(observation_id=observation.id).delete(
            synchronize_session=False
        )
        session.query(DetectionRecord).filter_by(observation_id=observation.id).delete(synchronize_session=False)
        session.query(PipelineRunRecord).filter_by(observation_id=observation.id).delete(synchronize_session=False)
        session.query(Observation).filter_by(id=observation.id).delete(synchronize_session=False)
        if media_id and session.query(Observation).filter_by(media_id=media_id).count() == 0:
            if session.query(Evidence).filter_by(media_id=media_id).count() == 0:
                session.query(MediaAsset).filter_by(id=media_id).delete(synchronize_session=False)
        session.expunge_all()
        return {"ok": True, "observation": observation_id}


def _camera_fields(
    *,
    name: str | None = None,
    location: str | None = None,
    orientation: str | None = None,
    source_type: str | None = None,
    uri: str | None = None,
    enabled: bool | None = None,
    interval_minutes: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = _required_name(name)
    if location is not None:
        payload["location"] = location.strip()[:256]
    if orientation is not None:
        payload["orientation"] = orientation.strip()[:128]
    if source_type is not None:
        kind = source_type.strip().lower() or "photo"
        if kind not in SOURCE_TYPES:
            raise ValueError("source_type must be photo|video|stream|folder")
        payload["source_type"] = kind
    if uri is not None:
        payload["uri"] = uri.strip()[:1024]
    if enabled is not None:
        payload["enabled"] = bool(enabled)
    if interval_minutes is not None:
        minutes = int(interval_minutes)
        if minutes < 5 or minutes > 24 * 60:
            raise ValueError("interval_minutes must be between 5 and 1440")
        payload["interval_minutes"] = minutes
    return payload


def create_camera(
    project_code: str,
    zone_code: str,
    *,
    code: str,
    name: str,
    location: str = "",
    orientation: str = "",
    source_type: str = "photo",
    uri: str = "",
    enabled: bool = True,
    interval_minutes: int = 30,
) -> dict:
    code = normalize_code(code, "camera code")
    fields = _camera_fields(
        name=name,
        location=location,
        orientation=orientation,
        source_type=source_type or "photo",
        uri=uri,
        enabled=enabled,
        interval_minutes=interval_minutes,
    )
    with _session() as session:
        project = _project(session, project_code)
        zone = _zone(session, project, zone_code)
        if session.query(Camera).filter_by(code=code).one_or_none():
            raise PermissionError("camera already exists")
        camera = Camera(zone_id=zone.id, code=code, **fields)
        session.add(camera)
        session.flush()
        return _camera_item(camera)


def update_camera(camera_code: str, **changes: Any) -> dict:
    fields = _camera_fields(
        name=changes.get("name", None) if "name" in changes else None,
        location=changes.get("location", None) if "location" in changes else None,
        orientation=changes.get("orientation", None) if "orientation" in changes else None,
        source_type=changes.get("source_type", None) if "source_type" in changes else None,
        uri=changes.get("uri", None) if "uri" in changes else None,
        enabled=changes.get("enabled", None) if "enabled" in changes else None,
        interval_minutes=changes.get("interval_minutes", None) if "interval_minutes" in changes else None,
    )
    with _session() as session:
        camera = session.query(Camera).filter_by(code=camera_code).one_or_none()
        if camera is None:
            raise KeyError("camera not found")
        for key, value in fields.items():
            setattr(camera, key, value)
        return _camera_item(camera)


def delete_camera(camera_code: str) -> dict:
    with _session() as session:
        camera = session.query(Camera).filter_by(code=camera_code).one_or_none()
        if camera is None:
            raise KeyError("camera not found")
        if session.query(Observation).filter_by(camera_id=camera.id).count():
            raise PermissionError(
                "Источник уже используется в истории наблюдений. Его можно отключить, но нельзя удалить."
            )
        session.delete(camera)
        return {"ok": True, "camera": camera_code}


def create_stage(
    project_code: str,
    zone_code: str,
    *,
    start_date: date | str,
    end_date: date | str | None = None,
    stage: str,
    stage_label_text: str = "",
    expected: dict | None = None,
) -> dict:
    start = _as_date(start_date)
    if start is None:
        raise ValueError("start_date is required")
    end = _as_date(end_date)
    _check_period(start, end)
    stage_code = (stage or "").strip().lower()
    if not stage_code:
        raise ValueError("stage is required")
    payload = expected or {}
    if not isinstance(payload, dict):
        raise ValueError("expected must be an object")
    with _session() as session:
        project = _project(session, project_code)
        zone = _zone(session, project, zone_code)
        row = ScheduleStage(
            project_id=project.id,
            zone_id=zone.id,
            date=start,
            start_date=start,
            end_date=end,
            stage=stage_code,
            stage_label=(stage_label_text or "").strip() or stage_label(stage_code),
            expected_json=json.dumps(payload, ensure_ascii=False),
        )
        session.add(row)
        session.flush()
        return _stage_payload(row, zone.code)


def update_stage(stage_id: str, **changes: Any) -> dict:
    with _session() as session:
        row = session.get(ScheduleStage, stage_id)
        if row is None:
            raise KeyError("schedule row not found")
        next_start = row.start_date
        next_end = row.end_date
        if "start_date" in changes:
            next_start = _as_date(changes.get("start_date"))
            if next_start is None:
                raise ValueError("start_date is required")
        if "end_date" in changes:
            next_end = _as_date(changes.get("end_date"))
        _check_period(next_start, next_end)
        if "start_date" in changes:
            row.start_date = next_start
            row.date = next_start
        if "end_date" in changes:
            row.end_date = next_end
        if "stage" in changes:
            stage_code = str(changes.get("stage") or "").strip().lower()
            if not stage_code:
                raise ValueError("stage is required")
            row.stage = stage_code
            if not changes.get("stage_label"):
                row.stage_label = stage_label(stage_code)
        if "stage_label" in changes and changes.get("stage_label") is not None:
            text = str(changes.get("stage_label") or "").strip()
            row.stage_label = text or stage_label(row.stage)
        if "expected" in changes:
            payload = changes.get("expected") or {}
            if not isinstance(payload, dict):
                raise ValueError("expected must be an object")
            row.expected_json = json.dumps(payload, ensure_ascii=False)
        zone = session.get(Zone, row.zone_id)
        return _stage_payload(row, zone.code if zone else None)


def delete_stage(stage_id: str) -> dict:
    with _session() as session:
        row = session.get(ScheduleStage, stage_id)
        if row is None:
            raise KeyError("schedule row not found")
        session.query(ExpectedStateRecord).filter_by(
            project_id=row.project_id,
            zone_id=row.zone_id,
            date=row.start_date,
        ).delete()
        session.delete(row)
        return {"ok": True, "id": stage_id}


def import_schedule_file(
    path: Path,
    *,
    project_code: str,
    zone_code: str | None = None,
    replace: bool = True,
) -> dict:
    rows = parse_ksg(path, default_zone=zone_code, default_project=project_code)
    if not rows:
        raise ValueError("KSG file has no rows")
    with _session() as session:
        project = _project(session, project_code)
        zones = {item.code: item for item in session.query(Zone).filter_by(project_id=project.id).all()}
        if zone_code and zone_code not in zones:
            raise KeyError("zone not found")
        touched: set[str] = set()
        saved = 0
        for item in rows:
            code = zone_code or item["zone"]
            zone = zones.get(code)
            if zone is None:
                raise KeyError(f"zone not found: {code}")
            if replace and zone.id not in touched:
                session.query(ScheduleStage).filter_by(project_id=project.id, zone_id=zone.id).delete()
                session.query(ExpectedStateRecord).filter_by(project_id=project.id, zone_id=zone.id).delete()
                touched.add(zone.id)
            start = item["start_date"]
            session.add(
                ScheduleStage(
                    project_id=project.id,
                    zone_id=zone.id,
                    date=start,
                    start_date=start,
                    end_date=item.get("end_date"),
                    stage=item["stage"],
                    stage_label=item.get("stage_label") or stage_label(item["stage"]),
                    expected_json=json.dumps(item["expected"], ensure_ascii=False),
                )
            )
            saved += 1
    return {"ok": True, "imported": saved, "replaced": replace}
