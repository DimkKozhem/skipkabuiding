"""Разбор ответа отдельно от результата провайдера и от оценки.

Обрезанный ответ, отказ, ошибка разбора и неверный счёт — разные исходы.
unknown не превращается в 0. Отсутствие координат не превращается в отсутствие объекта.
"""

from __future__ import annotations

import json
import re
from typing import Any

PARSER_VERSION = "1"
VALIDATOR_VERSION = "2"
CLASSIFIER_VERSION = "2"
PRODUCT_PHRASES = ("no_dynamics", "schedule_delay")


def parse_provider_output(*, task: str, response_mode: str, provider_status: str, raw_text: str | None) -> dict[str, Any]:
    if provider_status != "completed":
        return {
            "parser_version": PARSER_VERSION,
            "validator_version": VALIDATOR_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
            "parse_status": "skipped",
            "outcome": provider_status,
            "parsed": None,
            "field_validation": [],
            "explanation": None,
            "semantic_flags": [],
            "observations": [],
            "result_kind": "transport_or_api",
            "measurement_vs_gt": "not_evaluated",
            "ignored_product_phrases": [],
        }
    text = raw_text or ""
    ignored = [phrase for phrase in PRODUCT_PHRASES if phrase in text]
    cleaned = text
    for phrase in PRODUCT_PHRASES:
        cleaned = cleaned.replace(phrase, "")
    if response_mode == "structured":
        parsed, error = _parse_json(cleaned)
    else:
        parsed, error = _parse_lines(task, cleaned)
    if error:
        return {
            "parser_version": PARSER_VERSION,
            "validator_version": VALIDATOR_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
            "parse_status": "parse_error",
            "outcome": "parse_error",
            "parsed": None,
            "error": error,
            "field_validation": ["json_not_parsed"],
            "explanation": None,
            "semantic_flags": [],
            "observations": [],
            "result_kind": "structure",
            "measurement_vs_gt": "not_evaluated",
            "ignored_product_phrases": ignored,
        }
    field_validation = validate_fields(task, parsed)
    normalized = _normalize(task, parsed)
    outcome = _outcome(task, normalized)
    explanation = explanation_record(task, parsed)
    semantic = semantic_flags(task, parsed) if not field_validation else []
    return {
        "parser_version": PARSER_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "classifier_version": CLASSIFIER_VERSION,
        "parse_status": "ok",
        "outcome": outcome,
        "parsed": normalized,
        "field_validation": field_validation,
        "explanation": explanation,
        "semantic_flags": semantic,
        "observations": observation_flags(task, parsed) if not field_validation else [],
        "result_kind": result_kind(provider_status="completed", parse_status="ok", field_validation=field_validation, semantic_flags=semantic),
        "task_spec_defect_is_not_model_error": True,
        "measurement_vs_gt": "not_evaluated",
        "ignored_product_phrases": ignored,
    }


def _parse_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    raw = text.strip()
    raw = re.sub(r"^\[FIXTURE\][^\n]*\n?", "", raw).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None, "json_missing"
    try:
        payload = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None, "json_invalid"
    if not isinstance(payload, dict):
        return None, "json_not_object"
    return payload, None


def _parse_lines(task: str, text: str) -> tuple[dict[str, Any] | None, str | None]:
    if task == "floors":
        return _floors_lines(text)
    if task == "elements":
        return _elements_lines(text)
    if task == "works":
        return _works_lines(text)
    if task == "change":
        return _change_lines(text)
    return None, "unknown_task"


def _fields(text: str) -> dict[str, str]:
    found: dict[str, str] = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        found[key.strip().lower()] = value.strip()
    return found


def _optional_count(raw: str | None) -> tuple[int | None, str | None]:
    if raw is None or raw == "":
        return None, "count_missing"
    token = raw.strip().lower()
    if token in {"unknown", "null", "none", "неизвестно"}:
        return None, None
    try:
        return int(token), None
    except ValueError:
        return None, "count_not_integer"


def _floors_lines(text: str) -> tuple[dict[str, Any] | None, str | None]:
    fields = _fields(text)
    if "count" not in fields:
        return None, "count_missing"
    count, error = _optional_count(fields.get("count"))
    if error:
        return None, error
    refusal = fields.get("refusal", "").lower() in {"yes", "true", "да"}
    return {
        "count": count,
        "visibility": fields.get("visibility") or "unknown",
        "grounds": fields.get("grounds") or "",
        "uncertainty": fields.get("uncertainty") or "unknown",
        "refusal": refusal or count is None,
    }, None


def _elements_lines(text: str) -> tuple[dict[str, Any] | None, str | None]:
    items = []
    grounds = ""
    for line in text.splitlines():
        if line.lower().startswith("grounds:"):
            grounds = line.split(":", 1)[1].strip()
            continue
        if ":" not in line or "presence=" not in line:
            continue
        name, rest = line.split(":", 1)
        item: dict[str, Any] = {"category": name.strip(), "presence": "uncertain", "count": None, "boxes": None}
        for part in rest.split(";"):
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key == "presence":
                item["presence"] = value
            elif key == "count":
                count, error = _optional_count(value)
                if error:
                    return None, error
                item["count"] = count
            elif key == "boxes":
                item["boxes"] = None if value.lower() in {"none", "null", "unknown"} else value
        item["localization"] = "not_provided" if item["boxes"] is None else "provided"
        items.append(item)
    if not items:
        return None, "elements_missing"
    return {"items": items, "grounds": grounds}, None


def _works_lines(text: str) -> tuple[dict[str, Any] | None, str | None]:
    aspects = []
    grounds = ""
    for line in text.splitlines():
        if line.lower().startswith("grounds:"):
            grounds = line.split(":", 1)[1].strip()
            continue
        if ":" not in line or "presence=" not in line:
            continue
        name, rest = line.split(":", 1)
        aspect = {"name": name.strip(), "presence": "uncertain", "completion": "unknown", "equipment_role": "not_applicable"}
        for part in rest.split(";"):
            if "=" not in part:
                continue
            key, value = [chunk.strip() for chunk in part.split("=", 1)]
            if key == "presence":
                aspect["presence"] = value
            elif key == "completion":
                aspect["completion"] = value
            elif key == "role":
                aspect["equipment_role"] = "resource" if value == "resource" else value
        aspects.append(aspect)
    if not aspects:
        return None, "works_missing"
    return {"aspects": aspects, "grounds": grounds}, None


def _change_lines(text: str) -> tuple[dict[str, Any] | None, str | None]:
    fields = _fields(text)
    if "added" not in fields and "viewpoint" not in fields:
        return None, "change_missing"

    def pieces(key: str) -> list[str]:
        raw = fields.get(key, "none")
        if raw.lower() in {"none", "null", "unknown", ""}:
            return []
        return [part.strip() for part in raw.split(",") if part.strip() and part.strip() not in PRODUCT_PHRASES]

    return {
        "added": pieces("added"),
        "removed": pieces("removed"),
        "changed": pieces("changed"),
        "viewpoint": fields.get("viewpoint") or "unknown",
        "limitations": fields.get("limitations") or "",
    }, None


def _normalize(task: str, parsed: dict[str, Any]) -> dict[str, Any]:
    if task == "elements":
        items = []
        for item in parsed.get("items") or []:
            if not isinstance(item, dict):
                continue
            boxes = item.get("boxes")
            localization = "not_provided" if boxes is None else "provided"
            presence = item.get("presence") or "uncertain"
            items.append(
                {
                    "category": item.get("category"),
                    "presence": presence,
                    "count": item.get("count", None),
                    "boxes": boxes,
                    "localization": localization,
                }
            )
        return {"items": items, "grounds": parsed.get("grounds") or ""}
    if task == "floors" and _is_floors_v2(parsed):
        return _normalize_floors_v2(parsed)
    if task == "floors":
        count = parsed.get("count", None)
        refusal = bool(parsed.get("refusal")) or count is None
        return {
            "count": count,
            "visibility": parsed.get("visibility") or "unknown",
            "grounds": parsed.get("grounds") or "",
            "uncertainty": parsed.get("uncertainty") or "unknown",
            "refusal": refusal,
        }
    return parsed


def validate_fields(task: str, parsed: dict[str, Any] | None) -> list[str]:
    """Типы, диапазоны и согласованность полей. Это не оценка правильности счёта."""
    if not isinstance(parsed, dict):
        return ["not_object"]
    if task != "floors":
        return []
    if _is_floors_v2(parsed):
        return _validate_floors_v2(parsed)
    issues: list[str] = []
    count = parsed.get("count")
    if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
        issues.append("count_out_of_range")
    if parsed.get("visibility") not in {"full", "partial", "none"}:
        issues.append("visibility_invalid")
    if parsed.get("uncertainty") not in {"low", "medium", "high"}:
        issues.append("uncertainty_invalid")
    refusal = parsed.get("refusal")
    if not isinstance(refusal, bool):
        issues.append("refusal_not_bool")
    if refusal is True and count is not None:
        issues.append("refusal_with_count")
    if refusal is False and count is None:
        issues.append("count_missing_without_refusal")
    grounds = parsed.get("grounds")
    if not isinstance(grounds, str) or not grounds.strip():
        issues.append("grounds_empty")
    return issues


def _is_floors_v2(parsed: dict[str, Any]) -> bool:
    return "applicability" in parsed or "visible_level_count" in parsed or "total_floor_count" in parsed


def _normalize_floors_v2(parsed: dict[str, Any]) -> dict[str, Any]:
    return {
        "applicability": parsed.get("applicability"),
        "visible_level_count": parsed.get("visible_level_count", None),
        "total_floor_count": parsed.get("total_floor_count", None),
        "base_visibility": parsed.get("base_visibility"),
        "upper_boundary_visibility": parsed.get("upper_boundary_visibility"),
        "uncertainty_reason": parsed.get("uncertainty_reason") or "",
        "grounds_source": parsed.get("grounds_source"),
        "grounds": parsed.get("grounds") or "",
    }


def _count_ok(value: Any) -> bool:
    return value is None or (isinstance(value, int) and not isinstance(value, bool) and value >= 0)


def _validate_floors_v2(parsed: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    applicability = parsed.get("applicability")
    if applicability not in {"applicable", "not_applicable"}:
        issues.append("applicability_invalid")
    visible = parsed.get("visible_level_count", None)
    total = parsed.get("total_floor_count", None)
    if not _count_ok(visible):
        issues.append("visible_level_count_out_of_range")
    if not _count_ok(total):
        issues.append("total_floor_count_out_of_range")
    vis_ok = {"visible", "partial", "not_visible", "not_applicable"}
    base = parsed.get("base_visibility")
    upper = parsed.get("upper_boundary_visibility")
    if base not in vis_ok:
        issues.append("base_visibility_invalid")
    if upper not in vis_ok:
        issues.append("upper_boundary_visibility_invalid")
    if parsed.get("grounds_source") not in {"full_frame", "crop", "both", "none"}:
        issues.append("grounds_source_invalid")
    if not isinstance(parsed.get("grounds"), str) or not str(parsed.get("grounds") or "").strip():
        issues.append("grounds_empty")
    reason = parsed.get("uncertainty_reason")
    reason_present = isinstance(reason, str) and bool(reason.strip())
    if not _definite_floors_answer(parsed) and not reason_present:
        issues.append("uncertainty_reason_required")
    if applicability == "not_applicable":
        if visible is not None or total is not None:
            issues.append("not_applicable_must_be_null")
        if base != "not_applicable" or upper != "not_applicable":
            issues.append("not_applicable_visibility")
    if applicability == "applicable" and (base == "not_applicable" or upper == "not_applicable"):
        issues.append("applicable_visibility_not_applicable")
    if total is not None and (base != "visible" or upper != "visible"):
        issues.append("total_without_both_boundaries")
    if isinstance(visible, int) and isinstance(total, int) and visible > total:
        issues.append("visible_exceeds_total")
    return issues


def _definite_floors_answer(parsed: dict[str, Any]) -> bool:
    """Оба числа — целые, обе границы целиком видны. Пустое пояснение здесь не ошибка структуры."""
    visible = parsed.get("visible_level_count", None)
    total = parsed.get("total_floor_count", None)
    return (
        parsed.get("applicability") == "applicable"
        and isinstance(visible, int)
        and not isinstance(visible, bool)
        and isinstance(total, int)
        and not isinstance(total, bool)
        and parsed.get("base_visibility") == "visible"
        and parsed.get("upper_boundary_visibility") == "visible"
    )


def explanation_record(task: str, parsed: dict[str, Any] | None) -> dict[str, Any] | None:
    if task != "floors" or not isinstance(parsed, dict) or not _is_floors_v2(parsed):
        return None
    reason = parsed.get("uncertainty_reason")
    present = isinstance(reason, str) and bool(reason.strip())
    required = not _definite_floors_answer(parsed)
    if required:
        status = "present_required" if present else "missing_required"
    else:
        status = "present_optional" if present else "empty_allowed"
    return {"required": required, "present": present, "status": status}


def semantic_flags(task: str, parsed: dict[str, Any] | None) -> list[str]:
    """Смысл ответа, не структура и не сравнение с эталоном."""
    if task != "floors" or not isinstance(parsed, dict) or not _is_floors_v2(parsed):
        return []
    flags: list[str] = []
    text = f"{parsed.get('uncertainty_reason') or ''} {parsed.get('grounds') or ''}".lower()
    if parsed.get("applicability") == "not_applicable" and any(word in text for word in ("готов", "заверш")):
        flags.append("applicability_tied_to_construction_stage")
    total = parsed.get("total_floor_count", None)
    if isinstance(total, int) and not isinstance(total, bool):
        if any(phrase in text for phrase in ("не позволяет", "невозможно", "нельзя установить", "не установлен")):
            flags.append("total_filled_despite_stated_uncertainty")
    return flags


def observation_flags(task: str, parsed: dict[str, Any] | None) -> list[str]:
    """Видимость границ и читаемость уровней не сводятся друг к другу."""
    if task != "floors" or not isinstance(parsed, dict) or not _is_floors_v2(parsed):
        return []
    notes: list[str] = []
    if (
        parsed.get("base_visibility") == "visible"
        and parsed.get("upper_boundary_visibility") == "visible"
        and parsed.get("total_floor_count", None) is None
    ):
        notes.append("boundaries_visible_total_unknown")
    return notes


def result_kind(*, provider_status: str, parse_status: str, field_validation: list[str], semantic_flags: list[str]) -> str:
    if provider_status != "completed":
        return "transport_or_api"
    if parse_status != "ok" or field_validation:
        return "structure"
    if "applicability_tied_to_construction_stage" in semantic_flags:
        return "task_spec_defect"
    if semantic_flags:
        return "semantic"
    return "accepted_unmeasured"


def _outcome(task: str, parsed: dict[str, Any]) -> str:
    if task == "floors" and _is_floors_v2(parsed):
        return "diagnostic"
    if task == "floors" and parsed.get("refusal"):
        return "refusal"
    if task == "floors":
        return "count"
    return "parsed"
