"""Манифест, кроп и текст запроса. Проверочные оценки сюда не попадают."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from sitewatch.experiments.vlm_compare.common import PROJECT_ROOT, load_yaml, sha256_bytes, sha256_file, sha256_json
from sitewatch.experiments.vlm_compare.transport import ImagePayload

TEXT_FORMAT = {
    "floors": (
        "\nФормат, каждое поле с новой строки:\n"
        "count: <целое или unknown>\n"
        "visibility: full | partial | none\n"
        "grounds: <одна или две фразы>\n"
        "uncertainty: low | medium | high\n"
        "refusal: yes | no\n"
    ),
    "elements": "",
    "works": "",
    "change": "",
}

STRUCTURED_NOTE = (
    "\nВерни один JSON-объект по переданной схеме, без markdown. "
    "Неизвестное число — null, а не 0.\n"
)


@dataclass
class PreparedView:
    payload: ImagePayload
    source_sha256: str
    crop_xyxy: list[int] | None
    stored_name: str


def resolve(path: str | Path, root: Path | None = None) -> Path:
    raw = Path(path)
    if raw.is_absolute():
        return raw
    return (root or PROJECT_ROOT) / raw


def load_config(path: Path | None = None) -> dict[str, Any]:
    cfg_path = path or (PROJECT_ROOT / "config" / "vlm_compare.yaml")
    data = load_yaml(cfg_path)
    if not isinstance(data, dict):
        raise ValueError("config_not_object")
    if int(data.get("concurrency") or 1) != 1:
        raise ValueError("concurrency_must_be_1")
    data["_path"] = str(cfg_path)
    return data


def load_manifest(path: Path, *, check_hashes: bool = True) -> dict[str, Any]:
    data = load_yaml(path)
    if not isinstance(data, dict) or not isinstance(data.get("samples"), list):
        raise ValueError("manifest_invalid")
    for sample in data["samples"]:
        image = resolve(sample["image"])
        if not image.is_file():
            raise FileNotFoundError(sample["image"])
        digest = sha256_file(image)
        if check_hashes and sample.get("sha256") and sample["sha256"] != digest:
            raise ValueError(f"hash_mismatch:{sample.get('sample_id')}")
        sample["sha256"] = digest
    known = {sample["sample_id"] for sample in data["samples"]}
    for pair in data.get("pairs") or []:
        if pair["earlier"] not in known or pair["later"] not in known:
            raise ValueError(f"pair_unknown_sample:{pair.get('pair_id')}")
        if pair.get("usable_for_calendar_delay"):
            raise ValueError(f"calendar_delay_not_allowed:{pair.get('pair_id')}")
    data["_path"] = str(path)
    return data


def config_fingerprint(config: dict[str, Any]) -> dict[str, str]:
    parts: list[bytes] = []
    cfg_path = Path(config["_path"])
    parts.append(cfg_path.read_bytes())
    files: dict[str, str] = {}
    for group in ("prompts", "schemas"):
        for name, rel in (config.get(group) or {}).items():
            path = resolve(rel)
            digest = sha256_file(path)
            files[f"{group}:{name}"] = digest
            parts.append(digest.encode("ascii"))
    return {"config_sha256": sha256_bytes(b"".join(parts)), "files": files, "revision": str(config.get("revision"))}


def _resize(image: Image.Image, max_side: int) -> tuple[Image.Image, float]:
    width, height = image.size
    longest = max(width, height)
    if max_side <= 0 or longest <= max_side:
        return image, 1.0
    scale = max_side / float(longest)
    resized = image.resize((max(1, int(width * scale)), max(1, int(height * scale))), Image.Resampling.LANCZOS)
    return resized, scale


def _jpeg(image: Image.Image, quality: int) -> bytes:
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _store(image_dir: Path, data: bytes) -> tuple[str, str]:
    digest = sha256_bytes(data)
    image_dir.mkdir(parents=True, exist_ok=True)
    name = f"{digest}.jpg"
    path = image_dir / name
    if not path.is_file():
        path.write_bytes(data)
    return digest, name


def clock_visible(sample: dict[str, Any], *, send_full: bool, crop_xyxy: list[int]) -> bool:
    if not sample.get("camera_clock_burned_in"):
        return False
    if send_full:
        return True
    overlay = sample.get("overlay_bbox")
    if not overlay:
        return False
    return _intersects(overlay, crop_xyxy)


def _intersects(a: list[int], b: list[int]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def prepare_sample_views(sample: dict[str, Any], config: dict[str, Any], image_dir: Path) -> list[PreparedView]:
    prep = config.get("preprocessing") or {}
    max_side = int(prep.get("max_side") or 1280)
    quality = int(prep.get("jpeg_quality") or 90)
    source = resolve(sample["image"])
    with Image.open(source) as raw:
        image = raw.convert("RGB")
        full, full_scale = _resize(image, max_side)
        full_bytes = _jpeg(full, quality)
        crop_box = [int(v) for v in sample["crop_xyxy"]]
        cropped = image.crop(tuple(crop_box))
        cropped, crop_scale = _resize(cropped, max_side)
        crop_bytes = _jpeg(cropped, quality)
    full_sha, full_name = _store(image_dir, full_bytes)
    crop_sha, crop_name = _store(image_dir, crop_bytes)
    with Image.open(BytesIO(full_bytes)) as check:
        full_size = check.size
    with Image.open(BytesIO(crop_bytes)) as check:
        crop_size = check.size
    source_sha = sample["sha256"]
    return [
        PreparedView(
            payload=ImagePayload("img_" + full_sha[:8], "full_frame", full_sha, full_bytes, full_size[0], full_size[1]),
            source_sha256=source_sha,
            crop_xyxy=None,
            stored_name=full_name,
        ),
        PreparedView(
            payload=ImagePayload("img_" + crop_sha[:8], "crop", crop_sha, crop_bytes, crop_size[0], crop_size[1]),
            source_sha256=source_sha,
            crop_xyxy=crop_box,
            stored_name=crop_name,
        ),
    ]


def render_prompt(task: str, response_mode: str, template: str, mapping: dict[str, str]) -> str:
    text = template
    for key, value in mapping.items():
        text = text.replace("{" + key + "}", value)
    if response_mode == "structured":
        text += STRUCTURED_NOTE
    elif task == "floors":
        text += TEXT_FORMAT["floors"]
    if response_mode not in {"text", "structured"}:
        raise ValueError(f"unknown_response_mode:{response_mode}")
    return text


def load_template(config: dict[str, Any], task: str) -> str:
    rel = (config.get("prompts") or {})[task]
    return resolve(rel).read_text(encoding="utf-8")


def load_schema(config: dict[str, Any], task: str) -> dict[str, Any]:
    rel = (config.get("schemas") or {})[task]
    import json

    return json.loads(resolve(rel).read_text(encoding="utf-8"))


def single_mapping(views: list[PreparedView]) -> dict[str, str]:
    full = next(view.payload.neutral_id for view in views if view.payload.role == "full_frame")
    crop = next(view.payload.neutral_id for view in views if view.payload.role == "crop")
    return {"full_id": full, "crop_id": crop}


def pair_mapping(earlier: list[PreparedView], later: list[PreparedView]) -> dict[str, str]:
    def pick(views: list[PreparedView], role: str) -> str:
        return next(view.payload.neutral_id for view in views if view.payload.role == role)

    return {
        "earlier_full_id": pick(earlier, "full_frame"),
        "earlier_crop_id": pick(earlier, "crop"),
        "later_full_id": pick(later, "full_frame"),
        "later_crop_id": pick(later, "crop"),
    }


def inference_cache_key(
    *,
    image_sha256: list[str],
    crops: list[list[int] | None],
    preprocessing: dict[str, Any],
    prompt_text: str,
    requested_model: str,
    route: dict[str, Any],
    generation: dict[str, Any],
    response_mode: str,
    schema: dict[str, Any] | None,
) -> str:
    return sha256_json(
        {
            "images": image_sha256,
            "crops": crops,
            "preprocessing": preprocessing,
            "prompt_text": prompt_text,
            "requested_model": requested_model,
            "route": route,
            "generation": generation,
            "response_mode": response_mode,
            "schema": schema,
        }
    )


def route_of(model: dict[str, Any], *, structured: bool) -> dict[str, Any]:
    return {
        "order": list(model.get("provider_order") or []),
        "only": list(model.get("provider_only") or []),
        "ignore": list(model.get("provider_ignore") or []),
        "allow_fallbacks": bool(model.get("allow_fallbacks", False)) if model.get("transport") == "openrouter" else None,
        "require_parameters": True if structured and model.get("transport") == "openrouter" else False,
    }


def openrouter_pin_error(model: dict[str, Any]) -> str | None:
    """Пустой order не фиксирует маршрут: OpenRouter сам выбирает первый endpoint."""
    if model.get("transport") != "openrouter":
        return None
    model_id = str(model.get("model") or "")
    order = [str(item).strip() for item in (model.get("provider_order") or []) if str(item).strip()]
    only = [str(item).strip() for item in (model.get("provider_only") or []) if str(item).strip()]
    if not order:
        return "provider_order_empty"
    if any(item == model_id for item in order):
        return "provider_slug_equals_model_id"
    if model.get("allow_fallbacks") is not False:
        return "fallbacks_not_disabled"
    if only != order:
        return "provider_only_must_equal_order"
    return None


def generation_of(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("generation") or {}
    return {
        "temperature": raw.get("temperature"),
        "max_tokens": raw.get("max_tokens"),
        "top_p": raw.get("top_p"),
        "seed": raw.get("seed"),
    }


def generation_for_model(config: dict[str, Any], model: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Параметр, которого нет у зафиксированного endpoint, не отправляется.

    Иначе provider.require_parameters отклоняет весь маршрут, хотя схема ответа ему доступна.
    """
    generation = generation_of(config)
    omitted: list[str] = []
    supported = model.get("endpoint_supported_parameters")
    allowed = {str(item) for item in supported} if isinstance(supported, list) else None
    for key in ("temperature", "max_tokens", "top_p", "seed"):
        if generation.get(key) is None:
            continue
        blocked = key in {str(item) for item in (model.get("omit_generation") or [])}
        if allowed is not None and key not in allowed:
            blocked = True
        if blocked:
            generation[key] = None
            omitted.append(key)
    reasoning = model.get("reasoning")
    if isinstance(reasoning, dict) and "enabled" in reasoning:
        generation["reasoning"] = {"enabled": bool(reasoning["enabled"])}
    return generation, omitted


def preprocessing_of(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("preprocessing") or {}
    return {"max_side": int(raw.get("max_side") or 1280), "jpeg_quality": int(raw.get("jpeg_quality") or 90)}


def image_meta(views: list[PreparedView], *, clock: bool) -> list[dict[str, Any]]:
    rows = []
    for view in views:
        rows.append(
            {
                "neutral_id": view.payload.neutral_id,
                "role": view.payload.role,
                "sha256": view.payload.sha256,
                "stored_name": view.stored_name,
                "width": view.payload.width,
                "height": view.payload.height,
                "source_sha256": view.source_sha256,
                "crop_xyxy": view.crop_xyxy,
                "camera_clock_visible": clock if view.payload.role == "full_frame" else False,
                "clock_stripped": False,
            }
        )
    return rows


def assert_prompt_isolated(prompt: str, *, manifest_text: str = "", label_text: str = "") -> None:
    """Защита стенда: в запрос не попадают пути, канарские оценки и имена с числом этажей."""
    banned = [
        "Жилой дом",
        "6 этаж",
        "2 этажа",
        "КСГ",
        "ExpectedState",
        "leak_canary",
        "gold answer",
        "no_dynamics",
        "schedule_delay",
    ]
    for item in banned:
        if item in prompt:
            raise ValueError(f"prompt_leak:{item}")
    if "data/sources/" in prompt or "data/source/" in prompt:
        raise ValueError("prompt_contains_path")
    if label_text and "leak_canary" in label_text and "Жилой дом, 6 этажей" in prompt:
        raise ValueError("label_leaked")
    _ = manifest_text
