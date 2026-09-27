from __future__ import annotations

from functools import lru_cache

from sitewatch.settings import load_yaml


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    """Prefer construction ontology projection; fall back to classes.yaml."""
    try:
        from sitewatch.perception.ontology import as_classes_yaml_compat, raw_ontology

        if raw_ontology():
            return as_classes_yaml_compat()
    except Exception:
        pass
    return load_yaml("classes.yaml")


def canonical_class(raw_name: str) -> str | None:
    try:
        from sitewatch.perception.ontology import canonical_label as ontology_canonical

        mapped = ontology_canonical(raw_name)
    except Exception:
        mapped = None
    if mapped:
        if mapped == "floor_slab":
            return "slab"
        if mapped == "window_opening":
            return "window"
        if mapped == "road_roller":
            return "roller"
        return mapped
    data = taxonomy()
    name = raw_name.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {str(k).lower().replace(" ", "_"): v for k, v in (data.get("aliases") or {}).items()}
    mapped2 = aliases.get(name, name)
    if mapped2 in data.get("elements", {}):
        return mapped2
    if mapped2 in data.get("equipment", {}):
        return mapped2
    if mapped2 in data.get("other", {}):
        return mapped2
    return None


def is_element(class_name: str) -> bool:
    return class_name in taxonomy().get("elements", {})


def is_equipment(class_name: str) -> bool:
    return class_name in taxonomy().get("equipment", {})


def element_spec(class_name: str) -> dict:
    return taxonomy().get("elements", {}).get(class_name, {})
