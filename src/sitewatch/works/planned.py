"""Build PlannedIndicator list from a KSG schedule row / ExpectedState fields."""

from __future__ import annotations

from datetime import date
from typing import Any

from sitewatch.domain.contracts import PlannedIndicator
from sitewatch.domain.enums import IndicatorKind
from sitewatch.works.rules import indicator_rule, work_rules


def _kind(indicator_id: str) -> IndicatorKind:
    rule = indicator_rule(indicator_id) or {}
    raw = str(rule.get("kind") or "presence")
    try:
        return IndicatorKind(raw)
    except ValueError:
        return IndicatorKind.PRESENCE


def _unit(indicator_id: str) -> str | None:
    rule = indicator_rule(indicator_id) or {}
    unit = rule.get("unit")
    return str(unit) if unit is not None else None


def _confirms(indicator_id: str) -> str:
    rule = indicator_rule(indicator_id) or {}
    return str(rule.get("confirms") or "")


def _value_for_indicator(indicator_id: str, expected: dict[str, Any]) -> float | int | bool | None:
    """Pull plan value from expected JSON using reverse key map + stage defaults."""
    key_map = work_rules().get("expected_key_map") or {}
    for raw_key, mapped in key_map.items():
        if mapped == indicator_id and raw_key in expected:
            return _coerce(expected[raw_key], indicator_id)
    # divider meters
    if indicator_id == "dividing_line_m" and "dividing_line_m" in expected:
        return _coerce(expected["dividing_line_m"], indicator_id)
    # presence indicators: true when stage expects the feature
    if indicator_id.endswith("_visible"):
        # map foundation_visible ← foundation bool, etc.
        base = indicator_id.replace("_visible", "")
        if base in expected:
            return _coerce(expected[base], indicator_id)
        if indicator_id == "excavation_visible":
            return True  # stage itself implies excavation work planned
    if indicator_id == "finishing_observable":
        return None  # plan does not claim exterior observability
    if indicator_id == "divider_stage_sign":
        return True
    if indicator_id == "visible_floor_levels" and "floors" in expected:
        return _coerce(expected["floors"], indicator_id)
    return None


def _coerce(raw: Any, indicator_id: str) -> float | int | bool | None:
    kind = _kind(indicator_id)
    if raw is None:
        return None
    if kind == IndicatorKind.PRESENCE:
        if isinstance(raw, bool):
            return raw
        try:
            return bool(int(raw))
        except (TypeError, ValueError):
            return bool(raw)
    if kind in {IndicatorKind.COUNT, IndicatorKind.LENGTH_M, IndicatorKind.RESOURCE_COUNT}:
        try:
            n = float(raw)
        except (TypeError, ValueError):
            return None
        return int(n) if n == int(n) else n
    if kind == IndicatorKind.STAGE_SIGN:
        return True
    return raw


def planned_indicators_from_expected(
    *,
    schedule_row_id: str,
    work_code: str,
    expected: dict[str, Any],
    stage_label: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    required_equipment: list[dict] | None = None,
) -> list[PlannedIndicator]:
    """Expand one KSG row into comparable indicators. Composite stages → many rows."""
    rules = work_rules()
    stage_map = rules.get("stage_indicators") or {}
    key_map = rules.get("expected_key_map") or {}
    indicator_ids: list[str] = []

    for ind in stage_map.get(work_code) or []:
        if ind not in indicator_ids:
            indicator_ids.append(ind)

    for raw_key, mapped in key_map.items():
        if mapped and raw_key in expected and mapped not in indicator_ids:
            # skip null / false presence that is not part of this stage intent
            val = expected.get(raw_key)
            if mapped.endswith("_visible") and val in (False, 0, "0", None):
                continue
            if mapped == "visible_floor_levels":
                try:
                    if int(val or 0) <= 0:
                        continue
                except (TypeError, ValueError):
                    continue
            indicator_ids.append(mapped)

    out: list[PlannedIndicator] = []
    for indicator_id in indicator_ids:
        value = _value_for_indicator(indicator_id, expected or {})
        # Skip count indicators with non-positive plan (not yet due)
        if _kind(indicator_id) == IndicatorKind.COUNT:
            try:
                if value is None or float(value) <= 0:
                    continue
            except (TypeError, ValueError):
                continue
        out.append(
            PlannedIndicator(
                schedule_row_id=schedule_row_id,
                work_code=work_code,
                indicator_id=indicator_id,
                kind=_kind(indicator_id),
                unit=_unit(indicator_id),
                value=value,
                confirms=_confirms(indicator_id),
                stage=work_code,
                stage_label=stage_label,
                start_date=start_date,
                end_date=end_date,
            )
        )

    # Equipment resource indicators from stage rules
    for req in required_equipment or []:
        cls = str(req.get("class") or "")
        if not cls:
            continue
        min_count = int(req.get("min_count") or 1)
        out.append(
            PlannedIndicator(
                schedule_row_id=schedule_row_id,
                work_code=work_code,
                indicator_id=f"equipment:{cls}",
                kind=IndicatorKind.RESOURCE_COUNT,
                unit="count",
                value=min_count,
                confirms=f"минимальное число единиц техники «{cls}» (ресурс, не объём работ)",
                stage=work_code,
                stage_label=stage_label,
                start_date=start_date,
                end_date=end_date,
            )
        )
    return out
