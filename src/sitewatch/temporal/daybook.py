"""Суточный сбор кадров: похожие отбрасываются, остаётся одно описание и признак изменений.

Это не вердикт «работа выполнена». Текст говорит, что видно по сопоставимым кадрам за сутки.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from sitewatch.settings import get_settings, load_yaml

_NOUNS = {
    "floors": "этажи",
    "slabs": "плиты",
    "columns": "колонны",
    "walls": "стены",
    "facade": "фасад",
    "roof": "кровля",
    "foundation": "фундамент",
    "scaffolding": "леса",
    "excavator": "экскаватор",
    "dump_truck": "грузовик",
    "bulldozer": "бульдозер",
    "crane": "кран",
    "tower_crane": "башенный кран",
    "mobile_crane": "автокран",
    "concrete_mixer": "бетономешалка",
    "loader": "погрузчик",
}


@dataclass
class DayFrame:
    observation_id: str
    camera_id: str
    timestamp: datetime
    image_path: str
    summary: str
    elements: dict
    equipment: dict


@dataclass
class DayRoll:
    summary: str
    done: str
    kept_ids: list[str] = field(default_factory=list)
    dropped_ids: list[str] = field(default_factory=list)


def similarity_max_distance() -> int:
    cfg = load_yaml("thresholds.yaml").get("temporal") or {}
    return int(cfg.get("frame_similarity_max_distance", 6))


def resolve_image(path: str) -> Path | None:
    if not path:
        return None
    raw = Path(path)
    data = get_settings().data_dir
    for item in (raw, data / raw):
        try:
            if item.is_file():
                return item
        except OSError:
            continue
    return None


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


@lru_cache(maxsize=2048)
def _hash_file(path: str, mtime_ns: int) -> int | None:
    del mtime_ns
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(path) as image:
            gray = image.convert("L").resize((8, 8))
            pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())
    except OSError:
        return None
    if not pixels:
        return None
    average = sum(pixels) / len(pixels)
    bits = 0
    for index, pixel in enumerate(pixels):
        if pixel >= average:
            bits |= 1 << index
    return bits


def frame_hash(path: str) -> int | None:
    resolved = resolve_image(path)
    if resolved is None:
        return None
    try:
        stamp = resolved.stat().st_mtime_ns
    except OSError:
        return None
    return _hash_file(str(resolved), stamp)


def _count(blob: dict, key: str) -> int:
    raw = blob.get(key)
    if isinstance(raw, dict):
        try:
            return int(raw.get("count") or 0)
        except (TypeError, ValueError):
            return 0
    if isinstance(raw, bool) or raw is None:
        return 0
    if isinstance(raw, (int, float)):
        return int(raw)
    return 0


def looks_english(text: str) -> bool:
    """Heuristic: Latin-heavy / raw JSON from VLM should not go to the inspector UI."""
    raw = (text or "").strip()
    if raw.startswith("{") or raw.startswith("["):
        return True
    letters = [ch for ch in raw if ch.isalpha()]
    if len(letters) < 16:
        return False
    latin = sum(1 for ch in letters if "a" <= ch.lower() <= "z")
    return (latin / len(letters)) >= 0.72


def _counts_blob(blob: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in blob or {}:
        n = _count(blob, key)
        if n > 0:
            out[str(key)] = n
    return out


def russian_summary_for_frame(frame: DayFrame) -> str:
    """Prefer stored Russian text; rebuild from counts if VLM left English."""
    text = " ".join((frame.summary or "").split())
    if text and not looks_english(text):
        return text
    from sitewatch.perception.scene_narrative import describe_visible_work

    equipment = _counts_blob(frame.equipment)
    structures = {key for key, n in _counts_blob(frame.elements).items() if n > 0}
    return describe_visible_work(equipment=equipment, structures_present=structures)


def keep_distinct(frames: list[DayFrame], max_distance: int) -> tuple[list[DayFrame], list[str]]:
    """Одинаковые и очень похожие кадры одной камеры за сутки не повторяем."""
    kept: list[DayFrame] = []
    hashes: list[int | None] = []
    dropped: list[str] = []
    for frame in sorted(frames, key=lambda item: item.timestamp):
        digest = frame_hash(frame.image_path)
        similar = False
        if digest is not None:
            for previous, previous_hash in zip(kept, hashes):
                if previous.camera_id != frame.camera_id or previous_hash is None:
                    continue
                if hamming(digest, previous_hash) <= max_distance:
                    similar = True
                    break
        if similar:
            dropped.append(frame.observation_id)
            continue
        kept.append(frame)
        hashes.append(digest)
    return kept, dropped


def daily_summary(kept: list[DayFrame]) -> str:
    texts: list[str] = []
    for frame in kept:
        text = russian_summary_for_frame(frame)
        if text and text not in texts:
            texts.append(text)
    if not texts:
        return "За сутки по кадрам отдельного описания нет."
    if len(texts) == 1:
        return texts[0]
    return f"К началу суток: {texts[0]} К концу суток: {texts[-1]}"


def _lookup(frame: DayFrame, key: str) -> int:
    if key in frame.elements:
        return _count(frame.elements, key)
    if key in frame.equipment:
        return _count(frame.equipment, key)
    return 0


def day_done(kept: list[DayFrame]) -> str:
    if not kept:
        return "За сутки сопоставимых кадров нет."
    first, last = kept[0], kept[-1]
    parts: list[str] = []
    keys = set(first.elements) | set(last.elements) | set(first.equipment) | set(last.equipment)
    for key in sorted(keys):
        noun = _NOUNS.get(key)
        if not noun:
            continue
        before = _lookup(first, key)
        after = _lookup(last, key)
        if before != after:
            parts.append(f"{noun} {before} → {after}")
    if not parts:
        return "По сопоставимым кадрам за сутки заметных изменений состава не отмечено."
    return "По кадрам за сутки отмечено: " + "; ".join(parts) + "."


def roll_day(frames: list[DayFrame], max_distance: int | None = None) -> DayRoll:
    distance = similarity_max_distance() if max_distance is None else max_distance
    kept, dropped = keep_distinct(frames, distance)
    return DayRoll(
        summary=daily_summary(kept),
        done=day_done(kept),
        kept_ids=[frame.observation_id for frame in kept],
        dropped_ids=dropped,
    )
