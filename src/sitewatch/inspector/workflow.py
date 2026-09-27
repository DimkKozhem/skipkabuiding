from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import TYPE_CHECKING

from sitewatch.domain.contracts import DeviationCandidate
from sitewatch.domain.enums import AlertStatus
from sitewatch.settings import load_yaml

if TYPE_CHECKING:
    from sitewatch.storage.models import Alert, AlertEvent


@lru_cache(maxsize=1)
def load_inspector_cfg() -> dict:
    return load_yaml("inspector.yaml")


def candidate_fingerprint(candidate: DeviationCandidate) -> str:
    dates = sorted(candidate.related_dates or [])
    expected = dict(candidate.expected or {})
    # Progress grows inside one episode. The episode is the window start.
    expected.pop("schedule_progress", None)
    material = {
        "zone": candidate.zone_id,
        "type": candidate.alert_type.value,
        "rule_id": candidate.rule_id,
        "episode_start": dates[0] if dates else "",
        "expected": expected,
    }
    raw = json.dumps(material, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def reasons_for_status(status: str) -> dict[str, str]:
    cfg = load_inspector_cfg()
    block = (cfg.get("reasons") or {}).get(status) or {}
    out: dict[str, str] = {}
    for code, meta in block.items():
        if isinstance(meta, dict):
            out[code] = str(meta.get("label") or code)
        else:
            out[code] = str(meta)
    return out


def on_site_checks(alert_type: str) -> list[str]:
    cfg = load_inspector_cfg()
    items = (cfg.get("on_site_checks") or {}).get(alert_type) or []
    return [str(item) for item in items]


def status_label(status: str) -> str:
    cfg = load_inspector_cfg()
    meta = (cfg.get("statuses") or {}).get(status) or {}
    if isinstance(meta, dict):
        return str(meta.get("label") or status)
    return str(meta or status)


def allowed_statuses() -> set[str]:
    cfg = load_inspector_cfg()
    return set((cfg.get("statuses") or {}).keys()) or {item.value for item in AlertStatus}


def validate_decision(status: str, reason: str) -> None:
    if status not in allowed_statuses():
        raise ValueError(f"unknown inspector status: {status}")
    if status == AlertStatus.OPEN.value:
        return
    if not reason:
        raise ValueError("inspector decision requires a reason code")
    known = reasons_for_status(status)
    if reason not in known:
        raise ValueError(f"unknown reason '{reason}' for status '{status}'")


def should_create_alert(existing: Alert | None, cfg: dict | None = None) -> bool:
    """One fingerprint = one alert card. Re-evaluate must not spawn duplicates."""
    if existing is None:
        return True
    cfg = cfg or load_inspector_cfg()
    suppression = cfg.get("suppression") or {}
    if not suppression:
        return False
    mapping = {
        AlertStatus.OPEN.value: "duplicate_open",
        AlertStatus.REJECTED.value: "rejected",
        AlertStatus.CONFIRMED.value: "confirmed",
        AlertStatus.NEEDS_MORE_DATA.value: "needs_more_data",
    }
    key = mapping.get(existing.status, "duplicate_open")
    return not bool(suppression.get(key, True))


def _attach_new_evidence(session, alert, candidate: DeviationCandidate) -> int:
    """Keep the inspector decision. Add frames that were not linked yet."""
    from sitewatch.storage.models import AlertEvent, Evidence

    rows = session.query(Evidence).filter_by(alert_id=alert.id).all()
    known_obs = {row.observation_id for row in rows if row.observation_id}
    known_paths = {row.media_path for row in rows if row.media_path}
    added = 0
    for ref in candidate.evidence:
        if ref.observation_id and ref.observation_id in known_obs:
            continue
        if ref.media_path and ref.media_path in known_paths:
            continue
        if not ref.observation_id and not ref.media_path:
            continue
        session.add(
            Evidence(
                alert_id=alert.id,
                media_id=ref.media_id,
                observation_id=ref.observation_id,
                media_path=ref.media_path,
                viz_path=ref.viz_path or "",
                timestamp=ref.timestamp,
                note=candidate.rationale,
            )
        )
        added += 1
        if ref.observation_id:
            known_obs.add(ref.observation_id)
        if ref.media_path:
            known_paths.add(ref.media_path)
    if added:
        session.add(
            AlertEvent(
                alert_id=alert.id,
                action="evidence_added",
                from_status=alert.status,
                to_status=alert.status,
                actor="system",
                note=candidate.rule_id,
            )
        )
    return added


def persist_candidate(session, *, project_id: str, zone_id: str, candidate: DeviationCandidate) -> tuple[str, bool]:
    """Insert alert or reuse existing fingerprint. Returns (alert_id, created)."""
    from sitewatch.storage.models import Alert, AlertEvent, DeviationRecord, Evidence

    fingerprint = candidate_fingerprint(candidate)
    existing = (
        session.query(Alert)
        .filter_by(project_id=project_id, fingerprint=fingerprint)
        .order_by(Alert.created_at.asc())
        .first()
    )
    if existing is not None:
        _attach_new_evidence(session, existing, candidate)
        return existing.id, False

    deviation = DeviationRecord(
        project_id=project_id,
        zone_id=zone_id,
        alert_type=candidate.alert_type.value,
        severity=candidate.severity.value,
        payload_json=candidate.model_dump_json(),
    )
    session.add(deviation)
    session.flush()
    alert = Alert(
        deviation_id=deviation.id,
        project_id=project_id,
        zone_id=zone_id,
        alert_type=candidate.alert_type.value,
        severity=candidate.severity.value,
        message=candidate.message or candidate.title,
        fingerprint=fingerprint,
        status=AlertStatus.OPEN.value,
    )
    session.add(alert)
    session.flush()
    for ref in candidate.evidence:
        session.add(
            Evidence(
                alert_id=alert.id,
                media_id=ref.media_id,
                observation_id=ref.observation_id,
                media_path=ref.media_path,
                viz_path=ref.viz_path or "",
                timestamp=ref.timestamp,
                note=candidate.rationale,
            )
        )
    session.add(
        AlertEvent(
            alert_id=alert.id,
            action="created",
            from_status="",
            to_status=AlertStatus.OPEN.value,
            actor="system",
            note=candidate.rule_id,
        )
    )
    return alert.id, True


def apply_decision(
    alert: Alert,
    *,
    status: str,
    reason: str = "",
    note: str = "",
    actor: str | None = None,
) -> AlertEvent:
    from sitewatch.storage.models import AlertEvent

    validate_decision(status, reason)
    cfg = load_inspector_cfg()
    actor_name = actor or str(cfg.get("actor_default") or "inspector")
    event = AlertEvent(
        alert_id=alert.id,
        action="decided",
        from_status=alert.status,
        to_status=status,
        reason=reason,
        note=note,
        actor=actor_name,
    )
    alert.status = status
    alert.decision_reason = reason
    alert.decision_note = note
    alert.decided_by = actor_name
    if status == AlertStatus.OPEN.value:
        alert.decided_at = None
        alert.decision_reason = ""
        alert.decided_by = ""
        alert.decision_note = note
    else:
        alert.decided_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return event
