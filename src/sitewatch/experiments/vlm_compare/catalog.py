"""Публичный каталог OpenRouter. Запрос не отправляет изображения и не требует ключа."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from sitewatch.experiments.vlm_compare.common import dump_json, load_json


def load_catalog(path: Path) -> dict[str, Any]:
    data = load_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("catalog_invalid")
    return data


def model_index(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(item.get("id")): item for item in catalog.get("models") or [] if item.get("id")}


def token_prices(entry: dict[str, Any] | None) -> tuple[float, float] | None:
    if not entry:
        return None
    pricing = entry.get("pricing_usd_per_token") or entry.get("pricing") or {}
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    if prompt is None or completion is None:
        return None
    try:
        return float(prompt), float(completion)
    except (TypeError, ValueError):
        return None


def refresh_catalog(model_ids: list[str], dest: Path) -> dict[str, Any]:
    response = httpx.get("https://openrouter.ai/api/v1/models", timeout=60)
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError("catalog_response_invalid")
    wanted = set(model_ids)
    kept = []
    for row in rows:
        if not isinstance(row, dict) or row.get("id") not in wanted:
            continue
        arch = row.get("architecture") or {}
        kept.append(
            {
                "id": row.get("id"),
                "input_modalities": arch.get("input_modalities"),
                "output_modalities": arch.get("output_modalities"),
                "supported_parameters": row.get("supported_parameters"),
                "pricing_usd_per_token": row.get("pricing"),
                "context_length": row.get("context_length"),
                "per_request_limits": row.get("per_request_limits"),
            }
        )
    snapshot = {
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "https://openrouter.ai/api/v1/models",
        "note": "Публичный каталог. Идентификатор, провайдер и цена могли измениться.",
        "models": kept,
        "missing": sorted(wanted - {item["id"] for item in kept}),
    }
    dump_json(dest, snapshot)
    return snapshot
