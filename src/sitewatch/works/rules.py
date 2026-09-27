"""Load work_rules.yaml."""

from __future__ import annotations

from functools import lru_cache

from sitewatch.settings import load_yaml


@lru_cache(maxsize=1)
def work_rules() -> dict:
    return load_yaml("work_rules.yaml")


def indicator_rule(indicator_id: str) -> dict | None:
    return (work_rules().get("indicators") or {}).get(indicator_id)


def method_name(indicator_id: str) -> str | None:
    rule = indicator_rule(indicator_id)
    if not rule:
        return None
    name = rule.get("method")
    return str(name) if name else None
