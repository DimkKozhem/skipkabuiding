"""Construction ontology loader — SSOT for class names, prompts, measurement, nature."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from sitewatch.domain.enums import EntityNature, MeasurementType
from sitewatch.settings import load_yaml


@lru_cache(maxsize=1)
def raw_ontology() -> dict[str, Any]:
    return load_yaml("construction_ontology.yaml")


@lru_cache(maxsize=1)
def perception_config() -> dict[str, Any]:
    return load_yaml("perception.yaml")


def ontology_version() -> str:
    return str(raw_ontology().get("version") or perception_config().get("ontology_version") or "1.0")


def _flatten_entities() -> dict[str, dict[str, Any]]:
    data = raw_ontology()
    out: dict[str, dict[str, Any]] = {}
    for group in ("structures", "temporary_structures", "equipment", "other"):
        for key, spec in (data.get(group) or {}).items():
            item = dict(spec or {})
            item["group"] = group
            item["canonical"] = key
            out[key] = item
            for alias in item.get("class_aliases") or []:
                out.setdefault(str(alias), {**item, "canonical": key})
    return out


@lru_cache(maxsize=1)
def entity_index() -> dict[str, dict[str, Any]]:
    return _flatten_entities()


def structure_keys() -> list[str]:
    data = raw_ontology()
    keys = list((data.get("structures") or {}).keys())
    keys.extend((data.get("temporary_structures") or {}).keys())
    return keys


def equipment_keys() -> list[str]:
    return list((raw_ontology().get("equipment") or {}).keys())


def canonical_label(raw_name: str) -> str | None:
    data = raw_ontology()
    name = raw_name.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        str(k).lower().replace(" ", "_").replace("-", "_"): v
        for k, v in (data.get("aliases") or {}).items()
    }
    mapped = aliases.get(name, name)
    idx = entity_index()
    if mapped in idx:
        return str(idx[mapped].get("canonical") or mapped)
    # soft normalize: floor_slab vs slab already in aliases
    if name in idx:
        return str(idx[name].get("canonical") or name)
    return None


def measurement_for(canonical: str) -> MeasurementType:
    spec = entity_index().get(canonical) or {}
    raw = str(spec.get("measurement") or "count")
    try:
        return MeasurementType(raw)
    except ValueError:
        return MeasurementType.COUNT


def nature_for(canonical: str) -> EntityNature:
    spec = entity_index().get(canonical) or {}
    raw = str(spec.get("nature") or "persistent")
    try:
        return EntityNature(raw)
    except ValueError:
        return EntityNature.PERSISTENT


def state_key_for(canonical: str) -> str:
    spec = entity_index().get(canonical) or {}
    return str(spec.get("state_key") or canonical)


def prompts_for(canonical: str) -> list[str]:
    spec = entity_index().get(canonical) or {}
    prompts = list(spec.get("prompts") or [])
    if not prompts:
        prompts = [canonical.replace("_", " ")]
    return prompts


def is_structure(canonical: str) -> bool:
    spec = entity_index().get(canonical) or {}
    return spec.get("group") in {"structures", "temporary_structures"}


def is_equipment(canonical: str) -> bool:
    spec = entity_index().get(canonical) or {}
    return spec.get("group") == "equipment"


def as_classes_yaml_compat() -> dict[str, Any]:
    """Legacy shape expected by cv.taxonomy / aggregator / equipment_rules consumers."""
    data = raw_ontology()
    elements: dict[str, Any] = {}
    for key, spec in (data.get("structures") or {}).items():
        kind = "presence" if spec.get("measurement") in {"presence", "area", "area_or_presence"} else "count"
        if spec.get("measurement") == "levels":
            kind = "count"
        elements[key if key != "floor_slab" else "slab"] = {
            "kind": kind if key != "floor_slab" else "count",
            "state_key": spec.get("state_key") or key,
        }
        if key == "floor_slab":
            elements["slab"] = {"kind": "count", "state_key": "slabs"}
        if key == "window_opening":
            elements["window"] = {"kind": "count", "state_key": "windows"}
        if key == "column":
            elements["column"] = {"kind": "count", "state_key": "columns"}
        if key == "wall":
            elements["wall"] = {"kind": "count", "state_key": "walls"}
        if key == "foundation":
            elements["foundation"] = {"kind": "presence", "state_key": "foundation"}
        if key == "roof":
            elements["roof"] = {"kind": "presence", "state_key": "roof"}
        if key == "facade":
            elements["facade"] = {"kind": "presence", "state_key": "facade"}

    # Keep legacy element keys used by demo / deviation
    legacy_elements = {
        "foundation": {"kind": "presence", "state_key": "foundation"},
        "column": {"kind": "count", "state_key": "columns"},
        "wall": {"kind": "count", "state_key": "walls"},
        "slab": {"kind": "count", "state_key": "slabs"},
        "roof": {"kind": "presence", "state_key": "roof"},
        "window": {"kind": "count", "state_key": "windows"},
        "facade": {"kind": "presence", "state_key": "facade"},
    }
    elements = {**legacy_elements, **{k: v for k, v in elements.items() if k in legacy_elements or k in {"slab", "window"}}}

    equipment = {}
    for key, spec in (data.get("equipment") or {}).items():
        equipment[key] = {}
        for alias in spec.get("class_aliases") or []:
            equipment[str(alias)] = {}
    # Legacy demo equipment names
    for legacy in ("excavator", "dump_truck", "roller", "crane_manipulator", "concrete_mixer", "bulldozer", "truck", "mobile_crane"):
        equipment.setdefault(legacy, {})

    aliases = dict(data.get("aliases") or {})
    # Map ontology canonicals used by detectors back to legacy class names for aggregator
    aliases.setdefault("floor_slab", "slab")
    aliases.setdefault("window_opening", "window")
    aliases.setdefault("road_roller", "roller")

    return {
        "elements": elements,
        "equipment": equipment,
        "other": dict(data.get("other") or {}),
        "aliases": aliases,
    }


def all_text_prompts() -> list[str]:
    prompts: list[str] = []
    for key in list(structure_keys()) + equipment_keys():
        prompts.extend(prompts_for(key))
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for p in prompts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def mvp_class_list() -> list[str]:
    """Real-MVP class set from perception.yaml (fallback: core structures+equipment)."""
    cfg = perception_config()
    listed = list(cfg.get("mvp_classes") or [])
    if listed:
        return [str(x) for x in listed]
    return [
        "foundation",
        "column",
        "beam",
        "floor_slab",
        "wall",
        "facade",
        "roof",
        "window_opening",
        "excavator",
        "dump_truck",
        "loader",
        "bulldozer",
        "concrete_mixer",
        "mobile_crane",
        "tower_crane",
        "truck",
    ]


def mvp_prompts() -> list[str]:
    """Ontology-driven prompts for real SAM3 (primary prompt per class by default)."""
    cfg = perception_config().get("sam3") or {}
    primary_only = bool(cfg.get("primary_prompt_only", True))
    out: list[str] = []
    seen: set[str] = set()
    for key in mvp_class_list():
        prompts = prompts_for(key)
        chosen = prompts[:1] if primary_only else prompts
        for p in chosen:
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out
