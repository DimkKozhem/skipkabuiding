"""Camera target ROI — fixed before reading model answers."""

from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sitewatch.settings import project_root


@lru_cache(maxsize=1)
def camera_targets_config() -> dict[str, Any]:
    path = project_root() / "config" / "camera_targets.yaml"
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def resolve_crop_xyxy(camera_code: str, captured_at: datetime | date | str | None) -> list[int] | None:
    """Return inclusive-start exclusive-end xyxy for the camera period, or None."""
    cams = (camera_targets_config().get("cameras") or {})
    spec = cams.get(camera_code) or {}
    periods = list(spec.get("crop_xyxy_by_period") or [])
    if not periods:
        return None
    day: date | None = None
    if isinstance(captured_at, datetime):
        day = captured_at.date()
    elif isinstance(captured_at, date):
        day = captured_at
    elif isinstance(captured_at, str) and len(captured_at) >= 10:
        try:
            day = date.fromisoformat(captured_at[:10])
        except ValueError:
            day = None
    if day is None:
        xyxy = periods[-1].get("xyxy")
        return [int(v) for v in xyxy] if xyxy else None
    for period in periods:
        start = date.fromisoformat(str(period["from"]))
        end = date.fromisoformat(str(period["to"]))
        if start <= day <= end:
            xyxy = period.get("xyxy")
            return [int(v) for v in xyxy] if xyxy else None
    xyxy = periods[-1].get("xyxy")
    return [int(v) for v in xyxy] if xyxy else None


def apply_crop(image_path: Path, xyxy: list[int], dest: Path) -> Path:
    """Crop with PIL exclusive bottom-right. Writes JPEG to dest."""
    from PIL import Image

    x0, y0, x1, y1 = [int(v) for v in xyxy]
    with Image.open(image_path) as img:
        img = img.convert("RGB")
        w, h = img.size
        x0 = max(0, min(x0, w - 1))
        y0 = max(0, min(y0, h - 1))
        x1 = max(x0 + 1, min(x1, w))
        y1 = max(y0 + 1, min(y1, h))
        cropped = img.crop((x0, y0, x1, y1))
        dest.parent.mkdir(parents=True, exist_ok=True)
        cropped.save(dest, format="JPEG", quality=90)
    return dest


def target_meta(camera_code: str) -> dict[str, Any]:
    cams = (camera_targets_config().get("cameras") or {})
    spec = cams.get(camera_code) or {}
    return {
        "revision": camera_targets_config().get("revision"),
        "camera_code": camera_code,
        "zone": spec.get("zone"),
        "target_label": spec.get("target_label"),
        "date_reliability": spec.get("date_reliability"),
        "date_note": spec.get("date_note"),
        "empty_state": bool(spec.get("empty_state")),
        "measurement_limits": list(spec.get("measurement_limits") or []),
    }
