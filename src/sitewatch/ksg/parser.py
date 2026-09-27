from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd


TRUE_VALUES = {"1", "true", "yes", "да", "y", "t"}

# Columns that describe the schedule row itself, not ExpectedState.expected payload.
META_COLUMNS = {
    "project",
    "project_code",
    "zone",
    "zone_code",
    "date",
    "start_date",
    "end_date",
    "stage",
    "stage_label",
    "name",
    "id",
}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in TRUE_VALUES


def _as_date(value: Any) -> date | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    return pd.to_datetime(value).date()


def _coerce_expected_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        return value
    text = str(value).strip()
    if not text:
        return None
    lower = text.lower()
    if lower in TRUE_VALUES:
        return True
    if lower in {"0", "false", "no", "нет", "n", "f"}:
        return False
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _normalize_row(
    raw: dict[str, Any],
    *,
    default_zone: str | None = None,
    default_project: str | None = None,
) -> dict[str, Any]:
    """Accept both flat CSV rows and nested JSON stage objects."""
    nested = raw.get("expected")
    if isinstance(nested, dict):
        expected = {str(k): _coerce_expected_value(v) for k, v in nested.items()}
        expected = {k: v for k, v in expected.items() if v is not None}
    else:
        expected = {}
        for key, value in raw.items():
            if key.lower() in META_COLUMNS:
                continue
            if key.lower() == "expected":
                continue
            coerced = _coerce_expected_value(value)
            if coerced is not None:
                expected[key] = coerced

    start = _as_date(raw.get("start_date") or raw.get("date"))
    end = _as_date(raw.get("end_date"))
    stage = str(raw.get("stage") or raw.get("name") or "").strip().lower()
    zone = str(raw.get("zone") or raw.get("zone_code") or default_zone or "").strip()
    if not stage:
        raise ValueError("KSG row missing stage")
    if not zone:
        raise ValueError("KSG row missing zone")
    if start is None:
        raise ValueError(f"KSG row for stage={stage} missing start_date/date")

    return {
        "project_code": str(
            raw.get("project") or raw.get("project_code") or default_project or "site_001"
        ),
        "zone": zone,
        "date": start,
        "start_date": start,
        "end_date": end,
        "stage": stage,
        "stage_label": str(raw.get("stage_label") or raw.get("name") or "").strip() or None,
        "expected": expected,
    }


def _parse_json(
    path: Path,
    *,
    default_zone: str | None = None,
    default_project: str | None = None,
) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        if "stages" in payload:
            items = payload["stages"]
        elif "rows" in payload:
            items = payload["rows"]
        else:
            items = [payload]
    elif isinstance(payload, list):
        items = payload
    else:
        raise ValueError(f"Unsupported JSON KSG root type: {type(payload)}")
    return [
        _normalize_row(item, default_zone=default_zone, default_project=default_project)
        for item in items
    ]


def parse_ksg(
    path: Path,
    *,
    default_zone: str | None = None,
    default_project: str | None = None,
) -> list[dict[str, Any]]:
    """CSV / Excel / JSON → list of schedule rows. No CV knowledge."""
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _parse_json(path, default_zone=default_zone, default_project=default_project)

    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        frame = pd.read_csv(path)
    frame.columns = [str(col).strip().lower() for col in frame.columns]
    if "zone_code" in frame.columns and "zone" not in frame.columns:
        frame = frame.rename(columns={"zone_code": "zone"})
    if "start_date" not in frame.columns and "date" not in frame.columns:
        raise ValueError("KSG file missing columns: start_date or date")
    if "stage" not in frame.columns:
        raise ValueError("KSG file missing columns: ['stage']")
    if "zone" not in frame.columns and not default_zone:
        raise ValueError("KSG file missing columns: ['zone']")

    rows: list[dict[str, Any]] = []
    for _, series in frame.iterrows():
        raw = {str(k): series[k] for k in frame.columns}
        rows.append(_normalize_row(raw, default_zone=default_zone, default_project=default_project))
    return rows
