from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone

from sqlalchemy import func, text

from sitewatch.catalog.construction import construction_type_name
from sitewatch.inspector.workflow import apply_decision, load_inspector_cfg, on_site_checks, status_label
from sitewatch.pipeline.observe import capture_origin_label, parse_capture_origin
from sitewatch.services.media import public_media_url
from sitewatch.settings import load_yaml
from sitewatch.temporal.daybook import DayFrame, DayRoll, roll_day
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import (
    Alert,
    AlertEvent,
    ActualStateRecord,
    Camera,
    DetectionRecord,
    Evidence,
    EvidenceArtifactRecord,
    ExpectedStateRecord,
    MediaAsset,
    Observation,
    ObservedStateRecord,
    Project,
    ScheduleStage,
    ShadowCandidateReview,
    StateTransitionRecord,
    Zone,
)


def _session():
    init_db()
    return get_session()


def _ui_actual(raw: str | dict | None) -> dict | None:
    """ActualState for the inspector UI.

    `entities` is the perception history (~100KB per day). Screens only read
    elements, equipment, scene counts and work_facts summary.
    """
    if raw is None:
        return None
    payload = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(payload, dict):
        return None
    slim = {key: value for key, value in payload.items() if key != "entities"}
    scene = slim.get("scene_attributes")
    if isinstance(scene, dict) and "artifact_paths" in scene:
        slim["scene_attributes"] = {key: value for key, value in scene.items() if key != "artifact_paths"}
    from sitewatch.works.reinterpret import detach_unconfirmed_floor_value, reinterpret_work_facts

    reinterpret_work_facts(slim)
    _demote_legacy_floors(slim)
    detach_unconfirmed_floor_value(slim)
    facts = slim.get("work_facts")
    if isinstance(facts, dict):
        slim["work_facts_summary"] = [
            {
                "indicator_id": key,
                "certainty": (val or {}).get("certainty"),
                "value": (val or {}).get("value"),
                "unit": (val or {}).get("unit"),
                "method": (val or {}).get("method"),
                "confirms": (val or {}).get("confirms"),
                "limitations": (val or {}).get("limitations") or [],
            }
            for key, val in facts.items()
            if isinstance(val, dict)
        ]
    slim.pop("work_facts_archive", None)
    return slim


_TRUSTED_FLOOR_DERIVATIONS = frozenset(
    {"annotation", "scene_label", "floor_bands_proven", "manual_gt"}
)


def _demote_legacy_floors(slim: dict) -> None:
    """Old maxima and placeholder zeros are not a confirmed WorkFact."""
    scene = slim.get("scene_attributes")
    if not isinstance(scene, dict):
        scene = {}
        slim["scene_attributes"] = scene
    facts = slim.get("work_facts") if isinstance(slim.get("work_facts"), dict) else {}
    fact = facts.get("visible_floor_levels") if isinstance(facts.get("visible_floor_levels"), dict) else None
    derivation = str(scene.get("floors_derivation") or "")
    status = scene.get("floors_status")
    trusted_deriv = derivation in _TRUSTED_FLOOR_DERIVATIONS
    trusted_fact = bool(
        fact
        and fact.get("certainty") == "confirmed"
        and status == "proven"
        and trusted_deriv
        and fact.get("coverage") not in {"partial", "target_not_in_frame"}
    )
    trusted_label = status == "proven" and trusted_deriv and fact is None
    if trusted_fact or trusted_label:
        return
    elements = slim.get("elements") if isinstance(slim.get("elements"), dict) else None
    legacy = scene.get("structural_levels")
    if legacy in (None, 0) and elements and isinstance(elements.get("floors"), dict):
        count = elements["floors"].get("count")
        if isinstance(count, int) and count > 0:
            legacy = count
    if legacy not in (None, 0):
        scene["floors_disputed"] = legacy
        scene["floors_dispute_reason"] = (
            "прежнее число этажей не подтверждено разметкой или методом полос"
        )
    scene.pop("structural_levels", None)
    if scene.get("floors_status") != "disputed":
        scene["floors_status"] = "proposed"
    if elements and "floors" in elements:
        elements.pop("floors", None)


def _retired_open_delay(alert: Alert, *, floors_proven: bool) -> bool:
    """Open delays whose basis is an unproven floor count or a proxy 'not seen'.

    The row stays in the database. It must not lead the card.
    Inspector decisions (decided_at) are left as recorded.
    """
    if alert.status != "open" or alert.alert_type != "schedule_delay" or alert.decided_at is not None:
        return False
    payload: dict = {}
    deviation = getattr(alert, "deviation", None)
    raw = getattr(deviation, "payload_json", None) if deviation is not None else None
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            payload = parsed
    observed = payload.get("observed")
    if isinstance(observed, dict):
        if {"floors", "visible_floor_levels", "structural_levels"} & set(observed) and not floors_proven:
            return True
        indicator = str(observed.get("indicator_id") or "")
        if indicator in {"divider_stage_sign", "foundation_visible"}:
            return True
        if observed.get("coverage") == "unknown" and observed.get("value") is False:
            return True
        if "divider_stage_sign" in observed:
            return True
        return False
    text = alert.message or ""
    if "Этажи:" in text and not floors_proven:
        return True
    if "divider_stage_sign" in text:
        return True
    return False


def _latest_evidence_preview(items: list[Evidence]) -> dict | None:
    if not items:
        return None
    item = max(items, key=lambda row: row.timestamp)
    return {
        "id": item.id,
        "media_url": public_media_url(item.media_path),
        "viz_url": public_media_url(item.viz_path),
        "timestamp": item.timestamp.isoformat(),
    }


def _alert_list_item(
    row: Alert,
    *,
    project_code: str | None,
    zone_code: str | None,
    deviation_payload: dict | None,
    evidence_rows: list[Evidence],
    project_name: str | None = None,
    zone_name: str | None = None,
    status_override: str | None = None,
) -> dict:
    payload = deviation_payload or {}
    times = [item.timestamp for item in evidence_rows]
    status = status_override or row.status
    return {
        "id": row.id,
        "type": row.alert_type,
        "severity": row.severity,
        "status": status,
        "status_label": status_label(status),
        "fingerprint": row.fingerprint,
        "decision_reason": row.decision_reason,
        "decision_note": row.decision_note,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "decided_by": row.decided_by,
        "message": row.message,
        "created_at": row.created_at.isoformat(),
        "project": project_code,
        "project_name": project_name,
        "zone": zone_code,
        "zone_name": zone_name,
        "title": payload.get("title") or "",
        "expected": payload.get("expected"),
        "observed": payload.get("observed"),
        "rationale": payload.get("rationale"),
        "related_dates": payload.get("related_dates") or [],
        "latest_evidence": _latest_evidence_preview(evidence_rows),
        "first_observed_at": min(times).isoformat() if times else None,
        "last_observed_at": max(times).isoformat() if times else None,
    }


def _camera_item(item: Camera) -> dict:
    last = getattr(item, "last_captured_at", None)
    return {
        "code": item.code,
        "name": item.name,
        "source_type": item.source_type,
        "location": item.location or "",
        "orientation": item.orientation or "",
        "uri": getattr(item, "uri", "") or "",
        "enabled": bool(getattr(item, "enabled", True)),
        "interval_minutes": int(getattr(item, "interval_minutes", 30) or 30),
        "last_captured_at": last.isoformat() if last else None,
        "last_error": getattr(item, "last_error", "") or "",
    }


def _camera_items(session, zone_id: str) -> list[dict]:
    return [
        _camera_item(item)
        for item in session.query(Camera).filter_by(zone_id=zone_id).order_by(Camera.code.asc()).all()
    ]


def cover_fields(media: MediaAsset | None, camera: Camera | None) -> dict:
    """Подпись обложки витрины: канал кадра + имя точки съёмки (не id детектора)."""
    origin = parse_capture_origin(media.meta_json if media else None)
    return {
        "cover_origin": origin,
        "cover_origin_label": capture_origin_label(origin),
        "cover_camera_name": camera.name if camera else None,
    }


def assert_capture_point(project_code: str, zone_code: str, camera_code: str) -> None:
    with _session() as session:
        project = session.query(Project).filter_by(code=project_code).one_or_none()
        if project is None:
            raise KeyError("project not found")
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none()
        if zone is None:
            raise KeyError("zone not found")
        camera = session.query(Camera).filter_by(code=camera_code).one_or_none()
        if camera is None or camera.zone_id != zone.id:
            raise ValueError("camera does not belong to this zone")


def _project_by_id_or_code(session, project_id: str) -> Project:
    project = session.get(Project, project_id)
    if project is not None:
        return project
    project = session.query(Project).filter_by(code=project_id).one_or_none()
    if project is None:
        raise KeyError(project_id)
    return project


# Мягкие короткие лейблы витрины (не юридические вердикты).
_ZONE_BADGE_LABELS = {
    "schedule_delay": "Возможное отставание этапа",
    "equipment": "Признаки отсутствия техники",
    "equipment_unexpected": "Нетипичная техника для этапа",
    "no_dynamics": "Нет наблюдаемой динамики",
}

# Порядок приоритета витрины: schedule_delay > equipment > no_dynamics.
_ZONE_BADGE_ORDER = ("schedule_delay", "equipment", "no_dynamics")

# Признаки «этап по сроку» в тексте сигнала (basis/message/rationale) — не выдумывать overdue.
_OVERDUE_TEXT_MARKERS = (
    "должен был завершиться",
    "завершиться к",
    "этап по сроку",
)

# card_state: possible_issue = open delay/equipment/no_dynamics без решения инспектора.
# needs_check не дублируем как синоним — для open сигналов используем possible_issue.


def _equipment_badge_label(counts: dict[str, int]) -> str:
    if int(counts.get("missing_equipment") or 0) > 0:
        return _ZONE_BADGE_LABELS["equipment"]
    if int(counts.get("unexpected_equipment") or 0) > 0:
        return _ZONE_BADGE_LABELS["equipment_unexpected"]
    return _ZONE_BADGE_LABELS["equipment"]


def zone_badge_fields(type_counts: dict[str, int] | None) -> dict:
    """primary_badge / badge_label / badges / schedule_delay / attention по open alert_counts.

    ``badges`` — список ``{code, label}`` в порядке приоритета (primary первым),
    максимум из тройки schedule/equipment/no_dynamics, без дублей.
    """
    counts = type_counts or {}
    schedule_delay = int(counts.get("schedule_delay") or 0) > 0
    equipment = (
        int(counts.get("missing_equipment") or 0) > 0
        or int(counts.get("unexpected_equipment") or 0) > 0
    )
    no_dynamics = int(counts.get("no_dynamics") or 0) > 0
    attention = any(
        int(v or 0) > 0 for key, v in counts.items() if key not in _REVIEW_ONLY_ALERTS
    )
    present = {
        "schedule_delay": schedule_delay,
        "equipment": equipment,
        "no_dynamics": no_dynamics,
    }
    badges: list[dict[str, str]] = []
    for code in _ZONE_BADGE_ORDER:
        if not present[code]:
            continue
        label = _equipment_badge_label(counts) if code == "equipment" else _ZONE_BADGE_LABELS[code]
        badges.append({"code": code, "label": label})
    primary = badges[0]["code"] if badges else None
    return {
        "primary_badge": primary,
        "badge_label": badges[0]["label"] if badges else None,
        "badges": badges,
        "schedule_delay": schedule_delay,
        "attention": attention,
    }


def freshness_stale_after_hours() -> float:
    """Порог stale из config/thresholds.yaml → freshness.stale_after_hours."""
    cfg = load_yaml("thresholds.yaml").get("freshness") or {}
    return float(cfg.get("stale_after_hours", 48))


def _parse_observed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _age_hours(last_observed_at: str | None, *, now: datetime | None = None) -> float | None:
    stamp = _parse_observed_at(last_observed_at)
    if stamp is None:
        return None
    ref = now or _utcnow()
    return max((ref - stamp).total_seconds() / 3600.0, 0.0)


def _has_overdue_stage_hint(*texts: str | None) -> bool:
    blob = " ".join(str(item or "") for item in texts).casefold()
    return any(marker in blob for marker in _OVERDUE_TEXT_MARKERS)


def _freshness_label(last_observed_at: str | None, *, now: datetime | None = None) -> str:
    age = _age_hours(last_observed_at, now=now)
    if age is None:
        return "Нет кадра"
    stamp = _parse_observed_at(last_observed_at)
    if age < 1:
        hhmm = stamp.strftime("%H:%M") if stamp else ""
        return f"Обновлено {hhmm}".strip() if hhmm else "Обновлено недавно"
    if age < 24:
        hours = max(int(age), 1)
        return f"Последнее наблюдение {hours} ч назад"
    if age < 48:
        hours = int(age)
        return f"Последнее наблюдение {hours} ч назад"
    days = max(int(age // 24), 1)
    if days == 1:
        return "Последнее наблюдение 1 дн назад"
    return f"Последнее наблюдение {days} дн назад"


def enrich_zone_vitrine_fields(zone: dict, *, now: datetime | None = None) -> dict:
    """Добавляет rank_reason / stale / card_state / freshness_label (мутирует zone)."""
    ref = now or _utcnow()
    threshold = freshness_stale_after_hours()
    counts = zone.get("alert_counts") or {}
    open_delay = bool(zone.get("schedule_delay")) or int(counts.get("schedule_delay") or 0) > 0
    confirmed_delay = bool(zone.get("confirmed_schedule_delay"))
    open_no_dynamics = int(counts.get("no_dynamics") or 0) > 0
    open_missing = int(counts.get("missing_equipment") or 0) > 0
    open_unexpected = int(counts.get("unexpected_equipment") or 0) > 0
    open_equipment = open_missing or open_unexpected
    last_at = zone.get("last_observed_at")
    has_frame = bool(last_at) and bool(zone.get("preview_url"))
    # Исторический таймлапс: камеры выключены → tip серии не «протухает» от wall-clock.
    cameras = zone.get("cameras") or []
    live_monitoring = any(bool(cam.get("enabled")) for cam in cameras) if cameras else True
    age = _age_hours(last_at, now=ref)
    frame_stale = bool(live_monitoring and age is not None and age > threshold)
    no_frame = not has_frame
    # Для подписи свежести в playback: as_of = дата последнего кадра серии.
    freshness_now = ref if live_monitoring else (_parse_observed_at(last_at) or ref)
    signal_tier = None
    if open_delay or confirmed_delay:
        signal_tier = 0
    elif open_no_dynamics:
        signal_tier = 1
    elif open_equipment:
        signal_tier = 2
    elif int(zone.get("open_alerts") or 0) > 0:
        signal_tier = 3

    stale = bool(signal_tier is None and (frame_stale or no_frame))

    overdue_hint = _has_overdue_stage_hint(
        zone.get("delay_signal_text"),
        zone.get("delay_rationale"),
        zone.get("last_alert"),
    )

    if open_delay:
        if overdue_hint:
            rank_reason = "Возможное отставание: этап по сроку"
        else:
            rank_reason = "Возможное отставание этапа"
    elif confirmed_delay:
        rank_reason = "Подтверждено инспектором: отставание этапа"
    elif open_no_dynamics:
        rank_reason = "Нет наблюдаемой динамики"
    elif open_missing:
        rank_reason = "Признаки отсутствия техники"
    elif open_unexpected:
        rank_reason = "Нетипичная техника для этапа"
    elif no_frame:
        rank_reason = "Нет свежего кадра"
    elif frame_stale:
        hours = int(threshold) if threshold == int(threshold) else threshold
        rank_reason = f"Кадр старше {hours:g} ч"
    elif int(counts.get("insufficient_evidence") or 0) > 0 or int(zone.get("open_alerts") or 0) > 0:
        # Неподтверждённый факт не является «по плану».
        rank_reason = "Недостаточно данных для сопоставления"
    else:
        rank_reason = "По плану"

    if no_frame:
        card_state = "no_frame"
    elif open_delay or open_no_dynamics or open_equipment:
        card_state = "possible_issue"
    elif confirmed_delay:
        card_state = "confirmed"
    elif frame_stale:
        card_state = "stale"
    elif int(counts.get("insufficient_evidence") or 0) > 0 or int(zone.get("open_alerts") or 0) > 0:
        # Неподтверждённый факт — наблюдение, не «по плану».
        card_state = "observation"
    else:
        card_state = "on_plan"

    zone["rank_reason"] = rank_reason
    # stale: нет сигнала выше tier И (кадр старше порога ИЛИ кадра нет). no_frame ≠ «старый кадр» в card_state.
    zone["stale"] = stale
    zone["card_state"] = card_state
    zone["freshness_label"] = _freshness_label(last_at if has_frame else None, now=freshness_now)
    zone["playback_mode"] = "live" if live_monitoring else "historical"
    zone["_vitrine_tier"] = signal_tier if signal_tier is not None else (4 if stale else 5)
    return zone


_UNUSABLE_VISIBILITY = {"poor", "not_visible", "occluded", "outside_view"}


def frame_viewpoint(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""
    scene = payload.get("scene_attributes") if isinstance(payload.get("scene_attributes"), dict) else {}
    return str(scene.get("orientation") or scene.get("viewpoint") or "")


def frame_usable(payload: dict | None) -> bool:
    """Кадр годится как точка «было»: виден и сопоставим. Плохой или закрытый — нет."""
    if not isinstance(payload, dict):
        return True
    quality = payload.get("quality") if isinstance(payload.get("quality"), dict) else {}
    scene = payload.get("scene_attributes") if isinstance(payload.get("scene_attributes"), dict) else {}
    visibility = str(quality.get("visibility") or scene.get("visibility") or "good")
    coverage = str(quality.get("coverage") or scene.get("coverage") or "full")
    if visibility in _UNUSABLE_VISIBILITY:
        return False
    if coverage == "unknown":
        return False
    notes = quality.get("notes") or []
    if isinstance(notes, list):
        blob = " ".join(str(item).lower() for item in notes)
        if "occlud" in blob or "препят" in blob:
            return False
    return True


def pick_baseline(history: list, current, usable) -> object | None:
    """Самый ранний годный кадр той же камеры. Не вчера и не соседний снимок."""
    if current is None:
        return None
    camera = current.camera_id or ""
    for obs in history:
        if obs.id == current.id:
            continue
        if (obs.camera_id or "") != camera:
            continue
        if not obs.media_id or obs.media_id == current.media_id:
            continue
        if not usable(obs):
            continue
        return obs
    return None


# Open cards that are not plan/fact deviations. They stay in the inspector queue.
_REVIEW_ONLY_ALERTS = frozenset({"insufficient_evidence", "model_candidate"})


_CHECK_RANK = (
    "no_dynamics",
    "schedule_delay",
    "missing_equipment",
    "unexpected_equipment",
    "missing_element",
    "insufficient_evidence",
)


def primary_check(rows: list) -> dict | None:
    """Открытая проверка объекта: код типа, без текста вердикта."""
    live = [
        row
        for row in rows
        if row.status in {"open", "needs_more_data"} and row.alert_type != "model_candidate"
    ]
    pool = [row for row in live if row.status == "open"] or live
    if not pool:
        return None

    def rank(item) -> int:
        try:
            return _CHECK_RANK.index(item.alert_type)
        except ValueError:
            return len(_CHECK_RANK)

    chosen = min(pool, key=rank)
    return {"id": chosen.id, "type": chosen.alert_type, "status": chosen.status}


def schedule_ticks(stages: list, current_stage: str | None, delayed: bool, today: date | None = None) -> list[dict]:
    """Чертёжные засечки графика: пройденное, текущая точка, отставание."""
    if len(stages) < 2:
        return []
    today = today or date.today()
    current_index = next((i for i, row in enumerate(stages) if row.stage == current_stage), None)
    if current_index is None:
        current_index = 0
        for i, row in enumerate(stages):
            if row.start_date <= today:
                current_index = i
    chosen = list(stages)
    if len(stages) > 6:
        indexes = {0, len(stages) - 1, current_index}
        step = max(1, (len(stages) - 1) // 4)
        indexes.update(range(0, len(stages), step))
        chosen = [stages[i] for i in sorted(indexes)]
    current = stages[current_index]
    ticks: list[dict] = []
    for row in chosen:
        if row.id == current.id:
            state = "lag" if delayed else "now"
        elif row.start_date < current.start_date:
            state = "done"
        else:
            state = "ahead"
        ticks.append({"label": row.stage_label or row.stage or "", "state": state})
    return ticks


def sort_zones_for_vitrine(zones: list[dict], *, now: datetime | None = None) -> list[dict]:
    """Витрина: tier ↑ → last_observed_at ↓ → имя.

    Tier (меньше = выше):
    0 отставание (open или confirmed schedule_delay);
    1 нет динамики (open);
    2 нет/нетипичная техника (open);
    3 прочие open-сигналы;
    4 stale / нет кадра (если нет сигнала выше);
    5 остальные по свежести.
    """
    ref = now or _utcnow()
    rows = [enrich_zone_vitrine_fields(dict(zone), now=ref) for zone in zones]

    def _name(zone: dict) -> str:
        return str(zone.get("name") or zone.get("code") or "").casefold()

    def _tier(zone: dict) -> int:
        return int(zone.get("_vitrine_tier", 5))

    rows.sort(key=_name)
    rows.sort(key=lambda z: z.get("last_observed_at") or "", reverse=True)
    rows.sort(key=_tier)
    for row in rows:
        row.pop("_vitrine_tier", None)
    return rows


def dashboard() -> list[dict]:
    with _session() as session:
        projects = session.query(Project).all()
        result = []
        for project in projects:
            zones = session.query(Zone).filter_by(project_id=project.id).all()
            zone_rows = []
            for zone in zones:
                last_actual = (
                    session.query(ActualStateRecord)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .order_by(ActualStateRecord.timestamp.desc(), text("rowid DESC"))
                    .first()
                )
                last_expected = (
                    session.query(ExpectedStateRecord)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .order_by(ExpectedStateRecord.date.desc())
                    .first()
                )
                open_rows = (
                    session.query(Alert)
                    .filter_by(project_id=project.id, zone_id=zone.id, status="open")
                    .all()
                )
                live_rows = (
                    session.query(Alert)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .filter(Alert.status.in_(("open", "needs_more_data")))
                    .all()
                )
                ui_actual = _ui_actual(last_actual.payload_json) if last_actual else None
                floors_proven = ((ui_actual or {}).get("scene_attributes") or {}).get("floors_status") == "proven"
                retired_ids = {
                    item.id for item in open_rows if _retired_open_delay(item, floors_proven=floors_proven)
                }
                type_counts: dict[str, int] = {}
                for item in open_rows:
                    if item.id in retired_ids:
                        continue
                    type_counts[item.alert_type] = type_counts.get(item.alert_type, 0) + 1
                open_alerts = sum(
                    count for kind, count in type_counts.items() if kind not in _REVIEW_ONLY_ALERTS
                )
                live_rows = [item for item in live_rows if item.id not in retired_ids]
                zone_status: dict[str, int] = {}
                confirmed_delay = False
                delay_signal_text = ""
                delay_rationale = ""
                for item in session.query(Alert).filter_by(project_id=project.id, zone_id=zone.id).all():
                    zone_status[item.status] = zone_status.get(item.status, 0) + 1
                    if item.alert_type == "schedule_delay" and item.status == "confirmed":
                        confirmed_delay = True
                    if (
                        item.alert_type == "schedule_delay"
                        and item.status in {"open", "confirmed"}
                        and item.id not in retired_ids
                    ):
                        if not delay_signal_text:
                            delay_signal_text = item.message or ""
                            payload = {}
                            if item.deviation and item.deviation.payload_json:
                                try:
                                    payload = json.loads(item.deviation.payload_json)
                                except json.JSONDecodeError:
                                    payload = {}
                            delay_rationale = str(payload.get("rationale") or "")
                            # basis часто лежит в message; rationale — запасной канал.
                worst = (
                    session.query(Alert)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .order_by(Alert.created_at.desc())
                    .first()
                )
                history = (
                    session.query(Observation)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .order_by(Observation.timestamp.asc())
                    .all()
                )
                last_obs = history[-1] if history else None
                actual_by_obs = {
                    row.observation_id: json.loads(row.payload_json or "{}")
                    for row in session.query(ActualStateRecord).filter_by(project_id=project.id, zone_id=zone.id).all()
                    if row.observation_id
                }
                current_view = frame_viewpoint(actual_by_obs.get(last_obs.id) if last_obs else None)

                def _baseline_ok(obs: Observation) -> bool:
                    payload = actual_by_obs.get(obs.id)
                    if not frame_usable(payload):
                        return False
                    view = frame_viewpoint(payload)
                    return not (current_view and view and view != current_view)

                baseline = pick_baseline(history, last_obs, _baseline_ok)
                preview_asset = session.get(MediaAsset, last_obs.media_id) if last_obs and last_obs.media_id else None
                prior_asset = session.get(MediaAsset, baseline.media_id) if baseline else None
                prior_url = ""
                if prior_asset and preview_asset and prior_asset.path and prior_asset.path != preview_asset.path:
                    prior_url = public_media_url(prior_asset.path)
                stage_rows = (
                    session.query(ScheduleStage)
                    .filter_by(project_id=project.id, zone_id=zone.id)
                    .order_by(ScheduleStage.start_date.asc())
                    .all()
                )
                cover_camera = (
                    session.get(Camera, last_obs.camera_id) if last_obs and last_obs.camera_id else None
                )
                expected_payload = json.loads(last_expected.payload_json) if last_expected else None
                badge = zone_badge_fields(type_counts)
                zone_rows.append(
                    {
                        "zone_id": zone.id,
                        "code": zone.code,
                        "name": zone.name,
                        "description": getattr(zone, "description", None) or "",
                        "construction_type_id": (getattr(zone, "construction_type_id", None) or None),
                        "construction_type_name": construction_type_name(
                            getattr(zone, "construction_type_id", None)
                        ),
                        "stage": last_expected.stage if last_expected else None,
                        "stage_label": (expected_payload or {}).get("stage_label")
                        or (last_expected.stage if last_expected else None),
                        "last_actual": _ui_actual(last_actual.payload_json) if last_actual else None,
                        "last_expected": expected_payload,
                        "last_observed_at": (
                            last_obs.timestamp.isoformat()
                            if last_obs
                            else (last_actual.timestamp.isoformat() if last_actual else None)
                        ),
                        "preview_url": public_media_url(preview_asset.path if preview_asset else ""),
                        "prior_preview_url": prior_url,
                        "schedule_ticks": schedule_ticks(
                            stage_rows,
                            last_expected.stage if last_expected else None,
                            bool(type_counts.get("schedule_delay") or confirmed_delay),
                        ),
                        "last_source": last_obs.source if last_obs else None,
                        **cover_fields(preview_asset, cover_camera),
                        "cameras": _camera_items(session, zone.id),
                        "open_alerts": open_alerts,
                        "check": primary_check(live_rows),
                        "alert_counts": type_counts,
                        "status_counts": zone_status,
                        "schedule_deviations": type_counts.get("schedule_delay", 0),
                        "no_dynamics": type_counts.get("no_dynamics", 0),
                        "last_alert": worst.message if worst else None,
                        "last_severity": worst.severity if worst else None,
                        "confirmed_schedule_delay": confirmed_delay,
                        "delay_signal_text": delay_signal_text,
                        "delay_rationale": delay_rationale,
                        **badge,
                    }
                )
            zone_rows = sort_zones_for_vitrine(zone_rows)
            # Служебные поля overdue-текста наружу не отдаём — только производные.
            for row in zone_rows:
                row.pop("delay_signal_text", None)
                row.pop("delay_rationale", None)
            result.append(
                {
                    "id": project.id,
                    "code": project.code,
                    "name": project.name,
                    "address": project.address,
                    "zones": zone_rows,
                    "alert_counts": {
                        "open": sum(z["open_alerts"] for z in zone_rows),
                        "confirmed": sum(z.get("status_counts", {}).get("confirmed", 0) for z in zone_rows),
                        "rejected": sum(z.get("status_counts", {}).get("rejected", 0) for z in zone_rows),
                        "needs_more_data": sum(
                            z.get("status_counts", {}).get("needs_more_data", 0) for z in zone_rows
                        ),
                        "schedule_delay": sum(z.get("schedule_deviations", 0) for z in zone_rows),
                        "no_dynamics": sum(z.get("no_dynamics", 0) for z in zone_rows),
                        "missing_equipment": sum(z.get("alert_counts", {}).get("missing_equipment", 0) for z in zone_rows),
                    },
                }
            )
        return result


def get_project(project_id: str) -> dict:
    with _session() as session:
        project = _project_by_id_or_code(session, project_id)
        zones = session.query(Zone).filter_by(project_id=project.id).all()
        return {
            "id": project.id,
            "code": project.code,
            "name": project.name,
            "address": project.address,
            "zones": [{"id": z.id, "code": z.code, "name": z.name} for z in zones],
        }


def list_stages(project_id: str) -> list[dict]:
    with _session() as session:
        project = _project_by_id_or_code(session, project_id)
        zones = {z.id: z for z in session.query(Zone).filter_by(project_id=project.id).all()}
        rows = (
            session.query(ScheduleStage)
            .filter_by(project_id=project.id)
            .order_by(ScheduleStage.start_date.asc())
            .all()
        )
        return [
            {
                "id": row.id,
                "zone": zones[row.zone_id].code if row.zone_id in zones else None,
                "stage": row.stage,
                "stage_label": row.stage_label,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "expected": json.loads(row.expected_json),
            }
            for row in rows
        ]


def list_observations(project_id: str, zone_code: str | None = None) -> list[dict]:
    with _session() as session:
        project = _project_by_id_or_code(session, project_id)
        query = session.query(Observation).filter_by(project_id=project.id)
        if zone_code:
            zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
            query = query.filter_by(zone_id=zone.id)
        rows = query.order_by(Observation.timestamp.desc()).all()
        zones = {z.id: z for z in session.query(Zone).filter_by(project_id=project.id).all()}
        media = {m.id: m for m in session.query(MediaAsset).all()}
        obs_ids = [row.id for row in rows]
        dets_by_obs: dict[str, list[DetectionRecord]] = defaultdict(list)
        if obs_ids:
            for det in session.query(DetectionRecord).filter(DetectionRecord.observation_id.in_(obs_ids)).all():
                dets_by_obs[det.observation_id].append(det)
        result = []
        for row in rows:
            asset = media.get(row.media_id)
            origin = parse_capture_origin(asset.meta_json if asset else None)
            dets = dets_by_obs.get(row.id, [])
            result.append(
                {
                    "id": row.id,
                    "timestamp": row.timestamp.isoformat(),
                    "source": row.source,
                    "zone": zones[row.zone_id].code if row.zone_id in zones else None,
                    "camera_id": row.camera_id,
                    "image_path": asset.path if asset else "",
                    "image_url": public_media_url(asset.path if asset else ""),
                    "viz_path": row.viz_path,
                    "viz_url": public_media_url(row.viz_path),
                    "prediction_path": row.prediction_path,
                    "capture_origin": origin,
                    "capture_origin_label": capture_origin_label(origin),
                    "detections": [
                        {
                            "id": d.id,
                            "class_name": d.class_name,
                            "confidence": d.confidence,
                            "bbox": [d.x1, d.y1, d.x2, d.y2],
                        }
                        for d in dets
                    ],
                }
            )
        return result


def object_page(project_code: str, zone_code: str) -> dict:
    with _session() as session:
        project = session.query(Project).filter_by(code=project_code).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
        expected = (
            session.query(ExpectedStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ExpectedStateRecord.date.desc())
            .first()
        )
        actuals = (
            session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ActualStateRecord.timestamp.desc(), text("rowid DESC"))
            .all()
        )
        observations = (
            session.query(Observation)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(Observation.timestamp.desc())
            .all()
        )
        media = {m.id: m for m in session.query(MediaAsset).all()}
        cameras = {item.id: item for item in session.query(Camera).all()}
        alerts = (
            session.query(Alert)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(Alert.created_at.desc())
            .all()
        )
        stages = (
            session.query(ScheduleStage)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ScheduleStage.start_date.asc())
            .all()
        )
        obs_ids = [row.id for row in observations]
        dets_by_obs: dict[str, list[DetectionRecord]] = defaultdict(list)
        if obs_ids:
            for det in session.query(DetectionRecord).filter(DetectionRecord.observation_id.in_(obs_ids)).all():
                dets_by_obs[det.observation_id].append(det)
        obs_payload = []
        for row in observations:
            asset = media.get(row.media_id)
            camera = cameras.get(row.camera_id)
            origin = parse_capture_origin(asset.meta_json if asset else None)
            dets = dets_by_obs.get(row.id, [])
            obs_payload.append(
                {
                    "id": row.id,
                    "timestamp": row.timestamp.isoformat(),
                    "source": row.source,
                    "camera_id": row.camera_id,
                    "camera_code": camera.code if camera else None,
                    "camera_name": camera.name if camera else None,
                    "capture_origin": origin,
                    "capture_origin_label": capture_origin_label(origin),
                    "image_path": asset.path if asset else "",
                    "image_url": public_media_url(asset.path if asset else ""),
                    "viz_path": row.viz_path,
                    "viz_url": public_media_url(row.viz_path),
                    "prediction_path": row.prediction_path,
                    "detections": [
                        {
                            "class_name": d.class_name,
                            "confidence": d.confidence,
                            "bbox": [d.x1, d.y1, d.x2, d.y2],
                        }
                        for d in dets
                    ],
                }
            )
        alert_ids = [row.id for row in alerts]
        evidence_by_alert: dict[str, list[Evidence]] = defaultdict(list)
        if alert_ids:
            for item in session.query(Evidence).filter(Evidence.alert_id.in_(alert_ids)).all():
                evidence_by_alert[item.alert_id].append(item)
        ui_actual = _ui_actual(actuals[0].payload_json) if actuals else None
        floors_proven = ((ui_actual or {}).get("scene_attributes") or {}).get("floors_status") == "proven"
        retired_ids = {row.id for row in alerts if _retired_open_delay(row, floors_proven=floors_proven)}
        last_obs = observations[0] if observations else None
        last_asset = media.get(last_obs.media_id) if last_obs else None
        last_camera = cameras.get(last_obs.camera_id) if last_obs else None
        rolls = day_rolls(observations, {row.observation_id: row for row in actuals}, media)
        kept_ids = {item for roll in rolls.values() for item in roll.kept_ids}
        for item in obs_payload:
            item["kept"] = item["id"] in kept_ids
        current_stage_id: str | None = None
        if expected is not None:
            expected_date = expected.date
            expected_stage = expected.stage
            candidates = [
                row
                for row in stages
                if row.stage == expected_stage
                and row.start_date <= expected_date
                and (row.end_date is None or row.end_date >= expected_date)
            ]
            if candidates:
                current_stage_id = max(candidates, key=lambda row: row.start_date).id
        return {
            "project": {"id": project.id, "code": project.code, "name": project.name, "address": project.address},
            "zone": {
                "id": zone.id,
                "code": zone.code,
                "name": zone.name,
                "description": getattr(zone, "description", None) or "",
                "construction_type_id": (getattr(zone, "construction_type_id", None) or None),
                "construction_type_name": construction_type_name(
                    getattr(zone, "construction_type_id", None)
                ),
            },
            "cameras": _camera_items(session, zone.id),
            "expected": json.loads(expected.payload_json) if expected else None,
            "actual": ui_actual,
            "last_observed_at": last_obs.timestamp.isoformat() if last_obs else None,
            **cover_fields(last_asset, last_camera),
            "ksg": [
                {
                    "id": row.id,
                    "date": row.start_date.isoformat(),
                    "start_date": row.start_date.isoformat(),
                    "end_date": row.end_date.isoformat() if row.end_date else None,
                    "stage": row.stage,
                    "stage_label": row.stage_label,
                    "expected": json.loads(row.expected_json),
                    "current": bool(current_stage_id and row.id == current_stage_id),
                    **_stage_day_done(row, rolls),
                }
                for row in stages
            ],
            "observations": obs_payload,
            "alerts": [
                _alert_list_item(
                    row,
                    project_code=project.code,
                    zone_code=zone.code,
                    project_name=project.name,
                    zone_name=zone.name,
                    deviation_payload=json.loads(row.deviation.payload_json) if row.deviation else {},
                    evidence_rows=evidence_by_alert.get(row.id, []),
                    status_override="needs_more_data" if row.id in retired_ids else None,
                )
                for row in alerts
            ],
            "status": "ok"
            if not [item for item in alerts if item.status == "open" and item.id not in retired_ids]
            else "deviation",
        }


def alert_control_date(payload: dict | None, fallback: str) -> str:
    """Дата, на которую правило сработало: конец окна, не каждый день evidence."""
    related = [str(day) for day in ((payload or {}).get("related_dates") or []) if day]
    return max(related) if related else fallback


def _nonzero_deltas(raw: dict | None) -> dict[str, int]:
    out: dict[str, int] = {}
    for key, value in (raw or {}).items():
        try:
            delta = int(value)
        except (TypeError, ValueError):
            continue
        if delta:
            out[str(key)] = delta
    return out


def site_change_view(payload: dict | None) -> dict | None:
    """Inspector-facing diff of two comparable observations. Not a verdict."""
    if not payload:
        return None
    return {
        "kind": payload.get("change_kind") or "unknown",
        "comparable": bool(payload.get("comparable")),
        "same_camera": bool(payload.get("same_camera")),
        "equipment_deltas": _nonzero_deltas(payload.get("equipment_deltas")),
        "element_deltas": _nonzero_deltas(payload.get("element_deltas")),
        "visual_change": payload.get("visual_change"),
        "notes": list(payload.get("notes") or []),
    }


def _frame_from_observation(obs: Observation, actual: ActualStateRecord | None, media: dict) -> DayFrame:
    payload: dict = {}
    if actual is not None and actual.payload_json:
        parsed = json.loads(actual.payload_json)
        if isinstance(parsed, dict):
            payload = parsed
    scene = payload.get("scene_attributes") or {}
    asset = media.get(obs.media_id)
    return DayFrame(
        observation_id=obs.id,
        camera_id=obs.camera_id or "",
        timestamp=obs.timestamp,
        image_path=asset.path if asset else "",
        summary=str(scene.get("observation_summary") or ""),
        elements=payload.get("elements") or {},
        equipment=payload.get("equipment") or {},
    )


def day_rolls(
    observations: list[Observation],
    actual_by_obs: dict[str, ActualStateRecord],
    media: dict,
) -> dict[str, DayRoll]:
    grouped: dict[str, list[DayFrame]] = defaultdict(list)
    for obs in observations:
        grouped[obs.timestamp.date().isoformat()].append(
            _frame_from_observation(obs, actual_by_obs.get(obs.id), media)
        )
    return {day: roll_day(frames) for day, frames in grouped.items()}


def _stage_day_done(row: ScheduleStage, rolls: dict[str, DayRoll]) -> dict:
    start = row.start_date.isoformat()
    end = (row.end_date or row.start_date).isoformat()
    days = [day for day, roll in rolls.items() if start <= day <= end and roll.kept_ids]
    if not days:
        return {}
    day = max(days)
    return {"day_done": rolls[day].done, "day_done_on": day}


def timeline(project_code: str, zone_code: str) -> list[dict]:
    with _session() as session:
        project = session.query(Project).filter_by(code=project_code).one()
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one()
        actuals = (
            session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ActualStateRecord.timestamp.asc(), text("rowid ASC"))
            .all()
        )
        alerts = session.query(Alert).filter_by(project_id=project.id, zone_id=zone.id).all()
        alerts_by_day: dict[str, list[dict]] = defaultdict(list)
        for alert in alerts:
            payload = json.loads(alert.deviation.payload_json) if alert.deviation else {}
            day = alert_control_date(payload, alert.created_at.date().isoformat())
            alerts_by_day[day].append(
                {
                    "id": alert.id,
                    "type": alert.alert_type,
                    "severity": alert.severity,
                    "status": alert.status,
                    "title": payload.get("title") or "",
                    "message": alert.message,
                }
            )
        change_by_state = {
            row.to_state_id: site_change_view(json.loads(row.payload_json))
            for row in session.query(StateTransitionRecord).filter_by(project_id=project.id, zone_id=zone.id).all()
        }
        by_day: dict[str, dict] = {}
        for row in actuals:
            day = row.timestamp.date().isoformat()
            payload = _ui_actual(row.payload_json) or {}
            by_day[day] = {
                "date": day,
                "actual": payload,
                "alerts": alerts_by_day.get(day, []),
                "change": change_by_state.get(row.id),
            }
        expected_rows = (
            session.query(ScheduleStage)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ScheduleStage.start_date.asc())
            .all()
        )
        for row in expected_rows:
            day = row.start_date.isoformat()
            by_day.setdefault(day, {"date": day, "actual": None, "alerts": alerts_by_day.get(day, []), "change": None})
            by_day[day]["expected"] = json.loads(row.expected_json)
            by_day[day]["stage"] = row.stage
            by_day[day]["stage_label"] = row.stage_label
        observations = (
            session.query(Observation)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(Observation.timestamp.asc())
            .all()
        )
        media = {item.id: item for item in session.query(MediaAsset).all()}
        rolls = day_rolls(observations, {row.observation_id: row for row in actuals}, media)
        for day, roll in rolls.items():
            slot = by_day.setdefault(day, {"date": day, "actual": None, "alerts": alerts_by_day.get(day, []), "change": None})
            slot["summary"] = roll.summary
            slot["done"] = roll.done
            slot["kept_ids"] = roll.kept_ids
        result = [by_day[key] for key in sorted(by_day)]
        # #region agent log
        try:
            import time as _t
            _log = {
                "sessionId": "87693a",
                "runId": "pre-fix",
                "hypothesisId": "H1-H5",
                "location": "queries.py:timeline",
                "message": "timeline payload snapshot",
                "data": {
                    "zone": zone_code,
                    "days": len(result),
                    "with_actual": sum(1 for r in result if r.get("actual")),
                    "empty_summary": sum(1 for r in result if not (r.get("summary") or "")),
                    "sample": [
                        {
                            "date": r.get("date"),
                            "floors": ((r.get("actual") or {}).get("elements") or {}).get("floors"),
                            "vis": ((r.get("actual") or {}).get("scene_attributes") or {}).get("visible_floor_levels"),
                            "status": ((r.get("actual") or {}).get("scene_attributes") or {}).get("floors_status"),
                            "eq_deltas": ((r.get("change") or {}).get("equipment_deltas")),
                            "summary": str(r.get("summary") or "")[:100],
                        }
                        for r in result
                        if r.get("actual")
                    ][-5:],
                },
                "timestamp": int(_t.time() * 1000),
            }
            with open("/home/dimk/my_project/LCT2026/.cursor/debug-87693a.log", "a", encoding="utf-8") as _f:
                _f.write(__import__("json").dumps(_log, ensure_ascii=False) + "\n")
        except Exception:
            pass
        # #endregion
        return result


def alert_summary(
    status: str | None = None,
    zone_code: str | None = None,
    project_code: str | None = None,
) -> dict:
    """Counts only. Does not load alert payloads or evidence."""
    with _session() as session:
        query = session.query(Alert.alert_type, func.count(Alert.id)).group_by(Alert.alert_type)
        if status:
            query = query.filter(Alert.status == status)
        if project_code:
            query = query.join(Project, Alert.project_id == Project.id).filter(Project.code == project_code)
        if zone_code:
            query = query.join(Zone, Alert.zone_id == Zone.id).filter(Zone.code == zone_code)
        by_type = {str(kind): int(count) for kind, count in query.all()}
        return {"total": sum(by_type.values()), "by_type": by_type}


def list_alerts(
    status: str | None = None,
    zone_code: str | None = None,
    project_code: str | None = None,
    alert_type: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    with _session() as session:
        query = session.query(Alert).order_by(Alert.created_at.desc())
        if status:
            query = query.filter(Alert.status == status)
        if alert_type:
            query = query.filter(Alert.alert_type == alert_type)
        paging = limit is not None or offset
        if paging and project_code:
            query = query.join(Project, Alert.project_id == Project.id).filter(Project.code == project_code)
        if paging and zone_code:
            query = query.join(Zone, Alert.zone_id == Zone.id).filter(Zone.code == zone_code)
        if offset:
            query = query.offset(max(int(offset), 0))
        if limit is not None:
            query = query.limit(max(int(limit), 0))
        rows = query.all()
        projects = {item.id: item for item in session.query(Project).all()}
        zones = {item.id: item for item in session.query(Zone).all()}
        evidence_by_alert: dict[str, list[Evidence]] = defaultdict(list)
        if rows:
            for item in session.query(Evidence).filter(Evidence.alert_id.in_([row.id for row in rows])).all():
                evidence_by_alert[item.alert_id].append(item)
        result = []
        for row in rows:
            zone = zones.get(row.zone_id)
            if zone_code and (zone is None or zone.code != zone_code):
                continue
            project = projects.get(row.project_id)
            if project_code and (project is None or project.code != project_code):
                continue
            payload = json.loads(row.deviation.payload_json) if row.deviation else {}
            result.append(
                _alert_list_item(
                    row,
                    project_code=project.code if project else None,
                    project_name=project.name if project else None,
                    zone_code=zone.code if zone else None,
                    zone_name=zone.name if zone else None,
                    deviation_payload=payload,
                    evidence_rows=evidence_by_alert.get(row.id, []),
                )
            )
        return result


_LAYER_LABELS = {
    "yoloe_26l": "YOLOE-26L",
    "grounding_dino": "Grounding DINO",
}


def _shadow_layers(session, observation_ids: list[str], deviation: dict) -> list[dict]:
    """Boxes stay grouped by model. Fact detections are not reused here."""
    by_source: dict[str, dict] = {}
    observed = deviation.get("observed") or {}
    for item in observed.get("sources") or []:
        source = str(item.get("source") or "")
        if not source:
            continue
        by_source[source] = {
            "source": source,
            "label": _LAYER_LABELS.get(source, source),
            "status": item.get("status") or "",
            "model": item.get("model") or "",
            "model_version": item.get("model_version") or "",
            "error": item.get("error"),
            "boxes": [],
        }
    if observation_ids:
        rows = (
            session.query(EvidenceArtifactRecord)
            .filter(EvidenceArtifactRecord.observation_id.in_(observation_ids))
            .all()
        )
        for row in rows:
            try:
                payload = json.loads(row.payload_json or "{}")
            except json.JSONDecodeError:
                continue
            meta = payload.get("metadata") or {}
            if meta.get("role") != "shadow_candidate":
                continue
            source = str(meta.get("source_id") or row.source or "")
            layer = by_source.setdefault(
                source,
                {
                    "source": source,
                    "label": _LAYER_LABELS.get(source, source),
                    "status": "success",
                    "model": payload.get("model") or "",
                    "model_version": payload.get("model_version") or "",
                    "error": None,
                    "boxes": [],
                },
            )
            bbox = payload.get("bbox") or {}
            if isinstance(bbox, dict) and {"x1", "y1", "x2", "y2"} <= set(bbox):
                box = [bbox["x1"], bbox["y1"], bbox["x2"], bbox["y2"]]
            elif isinstance(bbox, list) and len(bbox) == 4:
                box = bbox
            else:
                continue
            layer["boxes"].append(
                {
                    "evidence_id": payload.get("evidence_id") or row.evidence_id,
                    "class_name": payload.get("normalized_label") or row.class_name,
                    "confidence": payload.get("score") or 0,
                    "bbox": box,
                }
            )
    order = [item.get("source") for item in (observed.get("sources") or [])]
    layers = list(by_source.values())
    if order:
        rank = {name: index for index, name in enumerate(order)}
        layers.sort(key=lambda item: rank.get(item["source"], 99))
    return layers


def _shadow_reviews(session, alert_id: str) -> list[dict]:
    rows = (
        session.query(ShadowCandidateReview)
        .filter_by(alert_id=alert_id)
        .order_by(ShadowCandidateReview.created_at.asc())
        .all()
    )
    return [
        {
            "id": row.id,
            "source": row.source,
            "verdict": row.verdict,
            "wrong_type": row.wrong_type,
            "missed_object": row.missed_object,
            "completeness": row.completeness,
            "actor": row.actor,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


def _shadow_diagnostics(alert_id: str, observation_ids: list[str], layers: list[dict]) -> dict:
    return {
        "alert_id": alert_id,
        "observation_ids": observation_ids,
        "layers": [
            {
                "source": item.get("source"),
                "model": item.get("model"),
                "model_version": item.get("model_version"),
                "n_boxes": len(item.get("boxes") or []),
                "evidence_ids": [box.get("evidence_id") for box in item.get("boxes") or []],
            }
            for item in layers
        ],
    }


def add_candidate_review(
    alert_id: str,
    *,
    source: str,
    verdict: str,
    wrong_type: str = "",
    missed_object: str = "",
    actor: str | None = None,
) -> dict:
    """Store a spot check. Does not write ActualState and does not open a deviation."""
    allowed = {"correct", "incorrect", "indeterminate"}
    if verdict not in allowed:
        raise ValueError("verdict must be correct|incorrect|indeterminate")
    if source not in {"yoloe_26l", "grounding_dino"}:
        raise ValueError("unknown model source")
    with _session() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise KeyError(alert_id)
        if alert.alert_type != "model_candidate":
            raise ValueError("review is only for a model candidate")
        evidence = session.query(Evidence).filter_by(alert_id=alert.id).all()
        observation_id = next((row.observation_id for row in evidence if row.observation_id), "")
        before_states = session.query(ActualStateRecord).count()
        before_deviations = session.query(Alert).filter(Alert.alert_type != "model_candidate").count()
        row = ShadowCandidateReview(
            alert_id=alert.id,
            observation_id=observation_id or "",
            source=source,
            verdict=verdict,
            wrong_type=(wrong_type or "").strip()[:128],
            missed_object=(missed_object or "").strip()[:256],
            completeness="spot_check",
            actor=(actor or "").strip()[:128],
        )
        session.add(row)
        session.add(
            AlertEvent(
                alert_id=alert.id,
                action="candidate_review",
                from_status=alert.status,
                to_status=alert.status,
                reason=verdict,
                note="Точечная проверка предложения модели, не полная разметка кадра.",
                actor=row.actor or "inspector",
            )
        )
        session.flush()
        if session.query(ActualStateRecord).count() != before_states:
            raise RuntimeError("candidate review must not change facts")
        if session.query(Alert).filter(Alert.alert_type != "model_candidate").count() != before_deviations:
            raise RuntimeError("candidate review must not open a deviation")
    return get_alert(alert_id)


def get_alert(alert_id: str) -> dict:
    with _session() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise KeyError(alert_id)
        evidence = session.query(Evidence).filter_by(alert_id=alert.id).order_by(Evidence.timestamp.asc()).all()
        project = session.get(Project, alert.project_id)
        zone = session.get(Zone, alert.zone_id)
        cameras = {item.id: item for item in session.query(Camera).all()}
        observations = {
            item.id: item
            for item in session.query(Observation).filter(
                Observation.id.in_([row.observation_id for row in evidence if row.observation_id])
            )
        } if any(row.observation_id for row in evidence) else {}
        evidence_payload = []
        for item in evidence:
            dets = []
            if item.observation_id:
                dets = session.query(DetectionRecord).filter_by(observation_id=item.observation_id).all()
            observation = observations.get(item.observation_id) if item.observation_id else None
            camera = cameras.get(observation.camera_id) if observation else None
            evidence_payload.append(
                {
                    "id": item.id,
                    "media_id": item.media_id,
                    "media_path": item.media_path,
                    "media_url": public_media_url(item.media_path),
                    "viz_path": item.viz_path,
                    "viz_url": public_media_url(item.viz_path),
                    "timestamp": item.timestamp.isoformat(),
                    "note": item.note,
                    "observation_id": item.observation_id,
                    "source": observation.source if observation else None,
                    "camera_code": camera.code if camera else None,
                    "camera_name": camera.name if camera else None,
                    "detections": [
                        {
                            "class_name": d.class_name,
                            "confidence": d.confidence,
                            "bbox": [d.x1, d.y1, d.x2, d.y2],
                        }
                        for d in dets
                    ],
                }
            )
        events = (
            session.query(AlertEvent)
            .filter_by(alert_id=alert.id)
            .order_by(AlertEvent.created_at.asc())
            .all()
        )
        deviation = json.loads(alert.deviation.payload_json) if alert.deviation else {}
        times = [item.timestamp for item in evidence]
        model_layers: list[dict] = []
        reviews: list[dict] = []
        diagnostics: dict | None = None
        if alert.alert_type == "model_candidate":
            observation_ids = [row.observation_id for row in evidence if row.observation_id]
            model_layers = _shadow_layers(session, observation_ids, deviation)
            reviews = _shadow_reviews(session, alert.id)
            diagnostics = _shadow_diagnostics(alert.id, observation_ids, model_layers)
        return {
            "id": alert.id,
            "type": alert.alert_type,
            "severity": alert.severity,
            "status": alert.status,
            "status_label": status_label(alert.status),
            "fingerprint": alert.fingerprint,
            "decision_reason": alert.decision_reason,
            "decision_note": alert.decision_note,
            "decided_at": alert.decided_at.isoformat() if alert.decided_at else None,
            "decided_by": alert.decided_by,
            "message": alert.message,
            "title": deviation.get("title") or "",
            "created_at": alert.created_at.isoformat(),
            "project": project.code if project else None,
            "project_name": project.name if project else None,
            "zone": zone.code if zone else None,
            "zone_name": zone.name if zone else None,
            "expected": deviation.get("expected"),
            "observed": deviation.get("observed"),
            "rationale": deviation.get("rationale"),
            "first_observed_at": min(times).isoformat() if times else None,
            "last_observed_at": max(times).isoformat() if times else None,
            "related_dates": deviation.get("related_dates") or [],
            "deviation": deviation,
            "evidence": evidence_payload,
            "model_layers": model_layers,
            "candidate_reviews": reviews,
            "diagnostics": diagnostics,
            "events": [
                {
                    "id": item.id,
                    "action": item.action,
                    "from_status": item.from_status,
                    "to_status": item.to_status,
                    "reason": item.reason,
                    "note": item.note,
                    "actor": item.actor,
                    "created_at": item.created_at.isoformat(),
                }
                for item in events
            ],
        }


def get_evidence(evidence_id: str) -> dict:
    with _session() as session:
        item = session.get(Evidence, evidence_id)
        if item is None:
            raise KeyError(evidence_id)
        observation = session.get(Observation, item.observation_id) if item.observation_id else None
        media = session.get(MediaAsset, item.media_id) if item.media_id else None
        dets = []
        if item.observation_id:
            dets = session.query(DetectionRecord).filter_by(observation_id=item.observation_id).all()
        return {
            "id": item.id,
            "alert_id": item.alert_id,
            "media_id": item.media_id,
            "media_path": item.media_path or (media.path if media else ""),
            "media_url": public_media_url(item.media_path or (media.path if media else "")),
            "viz_path": item.viz_path,
            "viz_url": public_media_url(item.viz_path),
            "timestamp": item.timestamp.isoformat(),
            "note": item.note,
            "observation_id": item.observation_id,
            "detections": [
                {
                    "class_name": d.class_name,
                    "confidence": d.confidence,
                    "bbox": [d.x1, d.y1, d.x2, d.y2],
                }
                for d in dets
            ],
            "observation": (
                {
                    "id": observation.id,
                    "timestamp": observation.timestamp.isoformat(),
                    "source": observation.source,
                    "viz_path": observation.viz_path,
                    "prediction_path": observation.prediction_path,
                    "media_id": observation.media_id,
                }
                if observation
                else None
            ),
        }


def set_alert_status(
    alert_id: str,
    status: str,
    reason: str = "",
    note: str = "",
    actor: str | None = None,
) -> dict:
    with _session() as session:
        alert = session.get(Alert, alert_id)
        if alert is None:
            raise KeyError(alert_id)
        event = apply_decision(alert, status=status, reason=reason, note=note, actor=actor)
        session.add(event)
    return get_alert(alert_id)


def inspection_brief(alert_id: str) -> dict:
    detail = get_alert(alert_id)
    cfg = load_inspector_cfg()
    deviation = detail.get("deviation") or {}
    return {
        "alert_id": detail["id"],
        "disclaimer": str(cfg.get("disclaimer") or "").strip(),
        "status": detail["status"],
        "status_label": detail.get("status_label"),
        "type": detail["type"],
        "zone": detail.get("zone"),
        "project": detail.get("project"),
        "fingerprint": detail.get("fingerprint"),
        "expected": deviation.get("expected"),
        "observed": deviation.get("observed"),
        "rationale": deviation.get("rationale"),
        "message": detail.get("message"),
        "on_site_checks": on_site_checks(detail["type"]),
        "evidence": detail.get("evidence") or [],
        "events": detail.get("events") or [],
        "decision": {
            "reason": detail.get("decision_reason"),
            "note": detail.get("decision_note"),
            "at": detail.get("decided_at"),
            "by": detail.get("decided_by"),
        },
    }


def inspector_queue(status: str = "open") -> list[dict]:
    return list_alerts(status=status)


def latest_observed_state(project_code: str, zone_code: str) -> dict | None:
    with _session() as session:
        project = session.query(Project).filter_by(code=project_code).one_or_none()
        if project is None:
            return None
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none()
        if zone is None:
            return None
        row = (
            session.query(ObservedStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ObservedStateRecord.timestamp.desc())
            .first()
        )
        if row is None:
            return None
        payload = json.loads(row.payload_json)
        return {
            "id": row.id,
            "observation_id": row.observation_id,
            "pipeline_run_id": row.pipeline_run_id,
            "timestamp": row.timestamp.isoformat(),
            "observed_state": payload,
        }


def latest_actual_state(project_code: str, zone_code: str) -> dict | None:
    with _session() as session:
        project = session.query(Project).filter_by(code=project_code).one_or_none()
        if project is None:
            return None
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none()
        if zone is None:
            return None
        row = (
            session.query(ActualStateRecord)
            .filter_by(project_id=project.id, zone_id=zone.id)
            .order_by(ActualStateRecord.timestamp.desc(), text("rowid DESC"))
            .first()
        )
        if row is None:
            return None
        payload = json.loads(row.payload_json)
        return {
            "id": row.id,
            "observation_id": row.observation_id,
            "timestamp": row.timestamp.isoformat(),
            "actual_state": payload,
        }


def zone_plan_fact(project_code: str, zone_code: str) -> dict | None:
    """Thin plan/fact view for additive API — reuses object_page slices."""
    page = object_page(project_code, zone_code)
    if not page:
        return None
    return {
        "project": page.get("project"),
        "zone": page.get("zone"),
        "expected": page.get("expected"),
        "actual": page.get("actual"),
        "alerts": page.get("alerts"),
        "ksg": page.get("ksg"),
    }
