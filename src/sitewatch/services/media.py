from __future__ import annotations

from pathlib import Path

from sitewatch.settings import get_settings


def public_media_url(path: str | None) -> str:
    """Filesystem path → /media/... for the FastAPI StaticFiles mount."""
    if not path:
        return ""
    raw = Path(path)
    data = get_settings().data_dir.resolve()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(data / raw)
    for item in candidates:
        try:
            resolved = item.resolve()
        except OSError:
            continue
        try:
            rel = resolved.relative_to(data)
        except ValueError:
            continue
        return "/media/" + rel.as_posix()
    return ""
