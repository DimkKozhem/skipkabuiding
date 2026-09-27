"""Утилиты стенда: хеши, сериализация, вырезание секретов."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(payload: Any) -> str:
    return sha256_bytes(canonical_json(payload).encode("utf-8"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_yaml(path: Path) -> Any:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


_SECRET_RE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([A-Za-z0-9._\-]+)")


def redact(text: str, secrets: list[str] | None = None) -> str:
    """Убирает ключи и заголовки авторизации. Неизвестные поля не подменяет нулём."""
    cleaned = _SECRET_RE.sub(r"\1[redacted]", text or "")
    for secret in secrets or []:
        if secret and secret in cleaned:
            cleaned = cleaned.replace(secret, "[redacted]")
    return cleaned


def redact_tree(payload: Any, secrets: list[str] | None = None) -> Any:
    if isinstance(payload, str):
        return redact(payload, secrets)
    if isinstance(payload, list):
        return [redact_tree(item, secrets) for item in payload]
    if isinstance(payload, dict):
        blocked = {"authorization", "api_key", "api-key", "headers"}
        out = {}
        for key, value in payload.items():
            if str(key).lower() in blocked:
                out[key] = "[redacted]"
            else:
                out[key] = redact_tree(value, secrets)
        return out
    return payload
