from __future__ import annotations

from datetime import date
from functools import lru_cache
from typing import Any

from sitewatch.domain.contracts import ExpectedState
from sitewatch.settings import load_yaml
from sitewatch.works.planned import planned_indicators_from_expected


@lru_cache(maxsize=1)
def load_equipment_rules() -> dict:
    return load_yaml("equipment_rules.yaml")


def rules_for_stage(stage: str) -> dict:
    stages = load_equipment_rules().get("stages", {})
    return stages.get(stage, {"required_equipment": [], "unexpected_equipment": [], "label": stage})


def stage_label(stage: str, override: str | None = None) -> str:
    if override:
        return override
    rules = rules_for_stage(stage)
    return str(rules.get("label") or stage)


def build_expected_state(
    *,
    object_id: str,
    zone_id: str,
    on_date: date,
    stage: str,
    expected: dict,
    start_date: date | None = None,
    end_date: date | None = None,
    stage_label_override: str | None = None,
    schedule_row_id: str | None = None,
) -> ExpectedState:
    rules = rules_for_stage(stage)
    row_id = schedule_row_id or f"{object_id}:{zone_id}:{stage}:{on_date.isoformat()}"
    expected_dict = dict(expected or {})
    required = list(rules.get("required_equipment") or [])
    indicators = planned_indicators_from_expected(
        schedule_row_id=row_id,
        work_code=stage,
        expected=expected_dict,
        stage_label=stage_label(stage, stage_label_override),
        start_date=start_date or on_date,
        end_date=end_date,
        required_equipment=required,
    )
    return ExpectedState(
        date=on_date,
        object_id=object_id,
        zone_id=zone_id,
        stage=stage,
        stage_label=stage_label(stage, stage_label_override),
        start_date=start_date or on_date,
        end_date=end_date,
        expected=expected_dict,
        required_equipment=required,
        unexpected_equipment=list(rules.get("unexpected_equipment") or []),
        schedule_row_id=row_id,
        planned_indicators=indicators,
    )


def nearest_stage_row(rows: list[dict], zone: str, on_date: date) -> dict | None:
    candidates = [row for row in rows if row["zone"] == zone and row["date"] <= on_date]
    if not candidates:
        zoned = [row for row in rows if row["zone"] == zone]
        return min(zoned, key=lambda row: row["date"]) if zoned else None
    return max(candidates, key=lambda row: row["date"])
