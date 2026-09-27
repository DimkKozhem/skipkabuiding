"""Read an alerts HTTP body without treating a transport or parse failure as an empty queue."""

from __future__ import annotations

import json
from pathlib import Path


class AlertReadError(RuntimeError):
    def __init__(self, message: str, path: Path) -> None:
        super().__init__(message)
        self.path = path


def load_alert_payload(raw: bytes, dest: Path) -> dict | list:
    """Save the full body, then parse it.

    An empty body or invalid JSON raises AlertReadError. It does not become [].
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(raw)
    if not raw.strip():
        raise AlertReadError(f"alerts response is empty; body saved to {dest}", dest)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AlertReadError(f"alerts response is not JSON ({exc}); body saved to {dest}", dest) from exc
    if not isinstance(payload, (dict, list)):
        raise AlertReadError(f"alerts response has unexpected JSON type; body saved to {dest}", dest)
    return payload
