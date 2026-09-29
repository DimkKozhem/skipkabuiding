"""Inspector review of model observations → confirmed / corrected / rejected facts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import ActualStateRecord, Observation, Project, Zone


ALLOWED_ACTIONS = {"confirm", "correct", "reject", "needs_other_frame"}


def review_work_observation(
    *,
    project_code: str,
    zone_code: str,
    observation_id: str,
    indicator_id: str,
    action: str,
    value: Any = None,
    actor: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    """Apply a human decision to one observation indicator.

    Original model answer is preserved under scene_attributes.model_observations.
    Confirmed values write WorkFact.certainty=confirmed with evidence binding.
    """
    action = str(action or "").strip()
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"action must be one of {sorted(ALLOWED_ACTIONS)}")
    init_db()
    with get_session() as session:
        project = session.query(Project).filter_by(code=project_code).one_or_none()
        if project is None:
            raise KeyError("project not found")
        zone = session.query(Zone).filter_by(project_id=project.id, code=zone_code).one_or_none()
        if zone is None:
            raise KeyError("zone not found")
        obs = session.query(Observation).filter_by(id=observation_id, zone_id=zone.id).one_or_none()
        if obs is None:
            raise KeyError("observation not found")
        actual = (
            session.query(ActualStateRecord)
            .filter_by(observation_id=observation_id)
            .order_by(ActualStateRecord.timestamp.desc())
            .first()
        )
        if actual is None:
            raise KeyError("actual state not found")
        payload = json.loads(actual.payload_json or "{}")
        scene = dict(payload.get("scene_attributes") or {})
        facts = dict(payload.get("work_facts") or {})
        archive = list(scene.get("model_observations") or [])
        prior = facts.get(indicator_id) if isinstance(facts.get(indicator_id), dict) else {}
        model_value = prior.get("value")
        if model_value is None and indicator_id == "visible_floor_levels":
            cand = scene.get("floor_level_candidate") or {}
            model_value = cand.get("value")
            if model_value is None:
                model_value = scene.get("visible_floor_levels")

        entry = {
            "at": datetime.utcnow().isoformat() + "Z",
            "actor": actor or "inspector",
            "action": action,
            "indicator_id": indicator_id,
            "model_value": model_value,
            "human_value": value,
            "note": note,
            "observation_id": observation_id,
            "observation_timestamp": str(obs.timestamp),
        }
        archive.append(entry)
        scene["model_observations"] = archive

        fact = dict(prior) if prior else {
            "indicator_id": indicator_id,
            "kind": "count" if indicator_id == "visible_floor_levels" else "presence",
            "method": "human_review",
        }
        fact["source_observation_id"] = observation_id
        fact["reviewed_at"] = entry["at"]
        fact["reviewed_by"] = entry["actor"]
        fact["model_value_original"] = model_value

        if action == "confirm":
            confirmed_value = value if value is not None else model_value
            if confirmed_value is None:
                raise ValueError("confirm requires a value (model had none)")
            fact["value"] = confirmed_value
            fact["certainty"] = "confirmed"
            fact["method"] = "human_confirm"
            fact["reason"] = note or "Подтверждено инспектором"
            if indicator_id == "visible_floor_levels":
                scene["visible_floor_levels"] = int(confirmed_value)
                scene["floors_status"] = "proven"
                scene["floors_derivation"] = "human_confirm"
                scene["floor_level_candidate"] = {
                    "value": int(confirmed_value),
                    "origin": "human_confirm",
                    "reason": note or "confirmed",
                    "confirmed": True,
                    "observation_id": observation_id,
                    "observation_day": str(obs.timestamp)[:10],
                }
        elif action == "correct":
            if value is None:
                raise ValueError("correct requires a value")
            fact["value"] = value
            fact["certainty"] = "confirmed"
            fact["method"] = "human_correct"
            fact["reason"] = note or "Исправлено инспектором; исходный ответ модели сохранён"
            if indicator_id == "visible_floor_levels":
                scene["visible_floor_levels"] = int(value)
                scene["floors_status"] = "proven"
                scene["floors_derivation"] = "human_correct"
                scene["floor_level_candidate"] = {
                    "value": int(value),
                    "origin": "human_correct",
                    "reason": note or "corrected",
                    "confirmed": True,
                    "model_value_original": model_value,
                    "observation_id": observation_id,
                    "observation_day": str(obs.timestamp)[:10],
                }
        elif action == "reject":
            fact["certainty"] = "unknown"
            fact["value"] = None
            fact["method"] = "human_reject"
            fact["reason"] = note or "Отклонено инспектором"
            if indicator_id == "visible_floor_levels":
                scene["floors_status"] = "disputed"
                scene["floors_derivation"] = "human_reject"
                if isinstance(scene.get("floor_level_candidate"), dict):
                    scene["floor_level_candidate"]["confirmed"] = False
                    scene["floor_level_candidate"]["reason"] = note or "rejected"
        else:  # needs_other_frame
            fact["certainty"] = "unknown"
            fact["method"] = "needs_other_frame"
            fact["reason"] = note or "Нужен другой кадр"
            if indicator_id == "visible_floor_levels":
                scene["floors_status"] = "proposed"
                scene["floors_derivation"] = "needs_other_frame"

        facts[indicator_id] = fact
        payload["work_facts"] = facts
        payload["scene_attributes"] = scene
        if action in {"confirm", "correct"} and indicator_id == "visible_floor_levels":
            elements = dict(payload.get("elements") or {})
            floors = dict(elements.get("floors") or {})
            floors["count"] = int(fact["value"])
            floors["max_confidence"] = 1.0
            elements["floors"] = floors
            payload["elements"] = elements
        # Keep list summary in sync with dict facts (UI reads work_facts_summary).
        summary = list(payload.get("work_facts_summary") or [])
        replaced = False
        for idx, row in enumerate(summary):
            if isinstance(row, dict) and row.get("indicator_id") == indicator_id:
                summary[idx] = {
                    **row,
                    "certainty": fact.get("certainty"),
                    "value": fact.get("value"),
                    "method": fact.get("method"),
                    "limitations": [fact.get("reason")] if fact.get("reason") else row.get("limitations") or [],
                }
                replaced = True
                break
        if not replaced and indicator_id == "visible_floor_levels":
            summary.insert(
                0,
                {
                    "indicator_id": indicator_id,
                    "certainty": fact.get("certainty"),
                    "value": fact.get("value"),
                    "unit": "levels",
                    "method": fact.get("method"),
                    "confirms": "число видимых этажей/уровней целевого корпуса в зоне наблюдения",
                    "limitations": [fact.get("reason")] if fact.get("reason") else [],
                },
            )
        payload["work_facts_summary"] = summary

        actual.payload_json = json.dumps(payload, ensure_ascii=False, default=str)
        session.commit()
        return {
            "ok": True,
            "observation_id": observation_id,
            "indicator_id": indicator_id,
            "action": action,
            "fact": fact,
            "model_value_original": model_value,
            "day": str(obs.timestamp)[:10],
        }


def seed_office_b_floors_confirm(*, observation_day: str = "2023-01-29", value: int = 2) -> dict[str, Any]:
    """Record user-confirmed office B = 2 floors on a specific frame day. Not backdated."""
    init_db()
    with get_session() as session:
        project = session.query(Project).filter_by(code="site_001").one()
        zone = session.query(Zone).filter_by(project_id=project.id, code="office_01").one()
        day_prefix = observation_day[:10]
        candidates = (
            session.query(Observation)
            .filter(Observation.zone_id == zone.id)
            .order_by(Observation.timestamp.desc())
            .all()
        )
        obs = next((row for row in candidates if str(row.timestamp)[:10] == day_prefix), None)
        if obs is None:
            raise KeyError(f"no observation for office_01 on {observation_day}")
        obs_id = obs.id
    return review_work_observation(
        project_code="site_001",
        zone_code="office_01",
        observation_id=obs_id,
        indicator_id="visible_floor_levels",
        action="confirm",
        value=value,
        actor="user",
        note="Офис B: 2 этажа подтверждены пользователем. Не распространять на ранние даты.",
    )
