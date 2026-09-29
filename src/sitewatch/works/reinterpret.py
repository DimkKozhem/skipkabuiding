"""Recompute derived WorkFacts from stored raw observations.

Raw detections, narratives and floor-band JSON stay in the payload.
This module only changes the interpretation (facts-2). It does not call a model.
"""

from __future__ import annotations

import copy
from typing import Any

DERIVATION_VERSION = "facts-2"

_EMPTY_OR_EQUIPMENT = (
    "по технике в зоне",
    "успешный пустой результат",
    "видимых признаков стадии разделителя нет",
    "отсутствие классов техники не доказывает",
)


def detach_unconfirmed_floor_value(payload: dict[str, Any]) -> dict[str, Any]:
    """Unknown floor fact must not carry a numeric value.

    The model count stays on scene as floor_level_candidate.
    """
    if not isinstance(payload, dict):
        return payload
    facts = payload.get("work_facts")
    if not isinstance(facts, dict):
        return payload
    fact = facts.get("visible_floor_levels")
    if not isinstance(fact, dict) or fact.get("certainty") != "unknown":
        return payload
    value = fact.get("value")
    if value is None:
        return payload
    scene = payload.get("scene_attributes")
    if not isinstance(scene, dict):
        scene = {}
        payload["scene_attributes"] = scene
    limitations = [str(item) for item in (fact.get("limitations") or [])]
    scene.setdefault(
        "floor_level_candidate",
        {
            "value": value,
            "origin": fact.get("method") or scene.get("floors_derivation") or "stored",
            "reason": "; ".join(limitations) or "число не подтверждено",
            "confirmed": False,
        },
    )
    fact["value"] = None
    return payload


def reinterpret_work_facts(payload: dict[str, Any], *, archive: bool = False) -> dict[str, Any]:
    """Return payload whose active work_facts follow facts-2.

    When archive is true, the previous derived dict is appended to
    work_facts_archive. Read paths leave the stored row unchanged.
    Idempotent once derivation_version is facts-2.
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("derivation_version") == DERIVATION_VERSION:
        return payload
    facts = payload.get("work_facts")
    if not isinstance(facts, dict):
        payload["derivation_version"] = DERIVATION_VERSION
        return payload

    if archive:
        stored = payload.get("work_facts_archive")
        if not isinstance(stored, list):
            stored = []
            payload["work_facts_archive"] = stored
        stored.append(
            {
                "derivation_version": payload.get("derivation_version") or "facts-1",
                "work_facts": copy.deepcopy(facts),
            }
        )

    scene = payload.get("scene_attributes") if isinstance(payload.get("scene_attributes"), dict) else {}
    floors_proven = scene.get("floors_status") == "proven" and scene.get("floors_derivation") in {
        "annotation",
        "scene_label",
        "floor_bands_proven",
        "manual_gt",
        "human_confirm",
        "human_correct",
    }

    for key, fact in facts.items():
        if not isinstance(fact, dict):
            continue
        limitations = [str(item) for item in (fact.get("limitations") or [])]
        text = " ".join(limitations)
        reason = _retire_reason(key, fact, text, floors_proven=floors_proven)
        if reason and fact.get("certainty") == "confirmed":
            fact["certainty"] = "unknown"
            fact["value"] = None
            fact["limitations"] = limitations + [
                f"{DERIVATION_VERSION}: {reason} Сырой ответ модели сохранён."
            ]
        fact["method_version"] = DERIVATION_VERSION
    payload["derivation_version"] = DERIVATION_VERSION
    return payload


def _retire_reason(key: str, fact: dict[str, Any], text: str, *, floors_proven: bool) -> str:
    if any(marker in text for marker in _EMPTY_OR_EQUIPMENT):
        return "прежнее подтверждение снято: пустой ответ или техника не доказывают работу."
    if key == "excavation_visible" and fact.get("value") is True and "техник" in text:
        return "земляная техника — ресурс, не признак котлована."
    if (
        key == "divider_stage_sign"
        and fact.get("value") is True
        and "equipment:" in text
        and "narrative:" not in text
    ):
        return "техника не подтверждает стадию разделителя."
    if key == "visible_floor_levels" and not floors_proven:
        return "число уровней не подтверждено конструктивными границами."
    if fact.get("value") is False and not fact.get("evidence_ids"):
        return "подтверждённое отсутствие без evidence снято."
    return ""
