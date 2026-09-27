"""Оценка отдельно от ответа провайдера и от разбора.

Неподтверждённая оценка агента не входит в знаменатель точности.
Фиктивные ответы в метрики качества не входят.
"""

from __future__ import annotations

from typing import Any

from sitewatch.experiments.vlm_compare.common import load_yaml

SCORER_VERSION = "2"


def load_labels(path: str | Any) -> dict[str, Any]:
    from pathlib import Path

    data = load_yaml(Path(path))
    if not isinstance(data, dict):
        raise ValueError("labels_invalid")
    return data


def _label_index(labels: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    index = {}
    for item in labels.get("items") or []:
        key_id = item.get("sample_id") or item.get("pair_id")
        if key_id and item.get("task"):
            index[(str(key_id), str(item["task"]))] = item
    return index


def _usable(label: dict[str, Any] | None, call: dict[str, Any]) -> bool:
    if not label or call.get("synthetic"):
        return False
    if label.get("author_kind") == "agent_preliminary":
        return False
    if label.get("review_status") != "confirmed":
        return False
    return bool(label.get("counts_toward_accuracy"))


def score_calls(
    calls: list[dict[str, Any]],
    parses: dict[str, dict[str, Any]],
    labels: dict[str, Any],
    *,
    scorer_version: str = SCORER_VERSION,
) -> dict[str, Any]:
    index = _label_index(labels)
    comparisons = []
    numeric_errors: list[float] = []
    numeric_hits = 0
    numeric_total = 0
    with_number = 0
    refusals = 0
    completed = 0
    empty_scene_errors = 0
    empty_scene_total = 0
    presence_hits = 0
    presence_total = 0
    localization_hits = 0
    localization_total = 0
    change_hits = 0
    change_total = 0
    technical = 0
    perception = 0
    latencies = []
    costs = []
    unknown_cost = 0
    result_kinds: dict[str, int] = {}
    for call in calls:
        key = call.get("cache_key")
        parsed = parses.get(key) or {}
        subject = call.get("sample_id") or call.get("pair_id")
        label = index.get((str(subject), str(call.get("task"))))
        technical_error = call.get("status") in {
            "http_error",
            "provider_error",
            "ambiguous_after_send",
            "truncated",
            "unsupported",
        } or parsed.get("outcome") == "parse_error"
        synthetic = bool(call.get("synthetic"))
        if technical_error and not synthetic:
            technical += 1
        if call.get("status") == "completed" and not synthetic:
            completed += 1
        outcome = parsed.get("outcome")
        body = parsed.get("parsed") or {}
        if not synthetic and outcome == "count" and isinstance(body.get("count"), int):
            with_number += 1
        if not synthetic and outcome == "refusal":
            refusals += 1
        if not synthetic and call.get("duration_ms") is not None:
            latencies.append(call["duration_ms"])
        if synthetic:
            pass
        elif call.get("cost_status") == "unknown" or call.get("cost_usd") is None:
            if call.get("invoked", True) and call.get("status") != "unsupported":
                unknown_cost += 1
        else:
            costs.append(call["cost_usd"])
        row = {
            "sample_id": call.get("sample_id"),
            "pair_id": call.get("pair_id"),
            "task": call.get("task"),
            "response_mode": call.get("response_mode"),
            "requested_model": call.get("requested_model"),
            "model_id": call.get("model_id"),
            "provider_status": call.get("status"),
            "parse_outcome": outcome,
            "synthetic": bool(call.get("synthetic")),
            "parsed": body if parsed.get("parse_status") == "ok" else None,
            "label": _public_label(label),
            "counts_toward_accuracy": False,
            "technical_error": technical_error,
            "result_kind": parsed.get("result_kind") or ("transport_or_api" if technical_error else "accepted_unmeasured"),
            "semantic_flags": list(parsed.get("semantic_flags") or []),
            "explanation": parsed.get("explanation"),
            "measurement_vs_gt": "not_evaluated",
        }
        result_kinds[row["result_kind"]] = result_kinds.get(row["result_kind"], 0) + 1
        if _usable(label, call) and call.get("task") == "floors" and label.get("expected_outcome") == "count" and isinstance(label.get("value"), int):
            numeric_total += 1
            row["counts_toward_accuracy"] = True
            if outcome == "count" and isinstance(body.get("count"), int):
                error = abs(body["count"] - int(label["value"]))
                numeric_errors.append(error)
                if error == 0:
                    numeric_hits += 1
                else:
                    perception += 1
            else:
                perception += 1
        if _usable(label, call) and label.get("expected_outcome") == "refusal":
            empty_scene_total += 1
            row["counts_toward_accuracy"] = True
            wrong = outcome == "count" and body.get("count") is not None
            if wrong:
                empty_scene_errors += 1
                perception += 1
        categories = (label or {}).get("categories") if _usable(label, call) else None
        if categories and call.get("task") == "elements":
            by_name = {item.get("category"): item for item in (body.get("items") or []) if isinstance(item, dict)}
            for name, expected in categories.items():
                presence_total += 1
                got = (by_name.get(name) or {}).get("presence")
                if got == (expected or {}).get("presence"):
                    presence_hits += 1
                else:
                    perception += 1
                expected_box = (expected or {}).get("boxes")
                if expected_box:
                    localization_total += 1
                    if (by_name.get(name) or {}).get("localization") == "provided":
                        localization_hits += 1
        if _usable(label, call) and call.get("task") == "change" and label.get("viewpoint"):
            change_total += 1
            row["counts_toward_accuracy"] = True
            if body.get("viewpoint") == label.get("viewpoint"):
                change_hits += 1
            else:
                perception += 1
        comparisons.append(row)
    def ratio(hit: int, total: int) -> float | None:
        if total == 0:
            return None
        return hit / total

    mae = (sum(numeric_errors) / len(numeric_errors)) if numeric_errors else None
    answered = sum(1 for call in calls if not call.get("synthetic"))
    return {
        "scorer_version": scorer_version,
        "agent_labels_are_not_human_gold": labels.get("author_kind") == "agent_preliminary",
        "accuracy": {
            "count_exact": ratio(numeric_hits, numeric_total),
            "count_support": numeric_total,
            "mae": mae,
            "note": "Считается только на нефиктивных ответах с подтверждённым точным эталоном.",
        },
        "answer_rate": {
            "with_number": with_number,
            "refusals": refusals,
            "completed_provider": completed,
            "calls": len(calls),
        },
        "empty_scene_error_rate": ratio(empty_scene_errors, empty_scene_total),
        "presence_accuracy": ratio(presence_hits, presence_total),
        "localization_accuracy": ratio(localization_hits, localization_total),
        "localization_support": localization_total,
        "change_viewpoint_accuracy": ratio(change_hits, change_total),
        "result_kinds": result_kinds,
        "measurement_vs_gt": "not_evaluated",
        "accuracy_is_not_an_error_count": True,
        "task_spec_defect_is_not_model_error": True,
        "technical_errors": technical,
        "perception_errors": perception,
        "latency_ms_mean": (sum(latencies) / len(latencies)) if latencies else None,
        "cost_usd_sum": sum(costs) if costs else None,
        "unknown_cost_calls": unknown_cost,
        "synthetic_calls_excluded_from_metrics": sum(1 for call in calls if call.get("synthetic")),
        "non_synthetic_calls": answered,
        "comparisons": comparisons,
    }


def _public_label(label: dict[str, Any] | None) -> dict[str, Any] | None:
    if not label:
        return None
    keep = (
        "author",
        "author_kind",
        "review_status",
        "counts_toward_accuracy",
        "visibility",
        "ambiguity",
        "value",
        "allowed_range",
        "expected_outcome",
        "notes",
        "categories",
        "viewpoint",
        "regions",
    )
    return {key: label.get(key) for key in keep if key in label}
