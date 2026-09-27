"""Localize storey levels on a subject-building crop, then count.

Scalar VLM floor counts are not evidence. This module:
1) crops the subject building (base→roof),
2) asks Qwen for per-level horizontal bands,
3) draws an overlay for human check,
4) returns a proposed count from the bands (not from a free number alone).
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from sitewatch.domain.contracts import BBox, Detection
from sitewatch.perception.ontology import perception_config
from sitewatch.settings import get_settings, project_root


@dataclass
class FloorBand:
    index: int
    y0: float  # crop-relative, 0=top
    y1: float
    cues: list[str] = field(default_factory=list)
    ambiguous: bool = False
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    def height(self) -> float:
        return max(0.0, float(self.y1) - float(self.y0))


@dataclass
class FloorLocalizeResult:
    image_path: str
    crop_box_xyxy: list[float]  # full-image pixels
    crop_path: str | None
    overlay_path: str | None
    levels: list[FloorBand]
    level_count_proposed: int | None
    level_count_from_bands: int
    unambiguous_count: int
    building_focus: bool | None
    limitations: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


def _load_floor_prompt() -> str:
    path = project_root() / "config" / "prompts" / "qwen_floor_levels_v2.txt"
    return path.read_text(encoding="utf-8")


def _load_floor_schema() -> dict[str, Any]:
    path = project_root() / "config" / "prompts" / "qwen_floor_levels_v1.schema.json"
    return json.loads(path.read_text(encoding="utf-8"))


def subject_building_box(
    image: np.ndarray,
    detections: list[Detection] | None = None,
    *,
    prefer_labels: tuple[str, ...] = ("facade", "wall", "roof", "building"),
) -> tuple[int, int, int, int]:
    """Return xyxy crop that prefers structure envelope; fallback = central tall box."""
    h, w = image.shape[:2]
    boxes: list[BBox] = []
    for det in detections or []:
        if det.bbox is None:
            continue
        if prefer_labels and det.class_name not in prefer_labels:
            continue
        boxes.append(det.bbox)
    if not boxes and detections:
        boxes = [d.bbox for d in detections if d.bbox is not None]
    if boxes:
        # Largest area structure box, expand vertically toward base/roof.
        best = max(boxes, key=lambda b: max(1.0, (b.x2 - b.x1) * (b.y2 - b.y1)))
        x1, y1, x2, y2 = best.x1, best.y1, best.x2, best.y2
        bw, bh = x2 - x1, y2 - y1
        x1 = max(0, int(x1 - 0.08 * bw))
        x2 = min(w - 1, int(x2 + 0.08 * bw))
        # Prefer base+roof: expand down more (podium/commercial often below facade box).
        y1 = max(0, int(y1 - 0.28 * bh))
        y2 = min(h - 1, int(y2 + 0.40 * bh))
        # Ensure crop is at least ~55% of frame height so base+roof fit.
        if (y2 - y1) < 0.55 * h:
            cy = (y1 + y2) / 2
            half = 0.30 * h
            y1 = max(0, int(cy - half))
            y2 = min(h - 1, int(cy + half))
        return x1, y1, x2, y2
    # Fallback: central vertical strip (subject often mid-frame on these timelapses).
    x1 = int(0.22 * w)
    x2 = int(0.82 * w)
    y1 = int(0.08 * h)
    y2 = int(0.95 * h)
    return x1, y1, x2, y2


_GROUND_CUES = frozenset(
    {"ground", "road", "sidewalk", "pavement", "earth", "soil", "parking", "yard", "земля", "дорога"}
)
_ROOF_CUES = frozenset(
    {"roof", "parapet", "sky", "canopy_only", "кровля", "парапет", "небо"}
)


def _cue_hit(cues: list[str], vocab: frozenset[str]) -> bool:
    for cue in cues:
        low = str(cue).lower()
        if any(tok in low for tok in vocab):
            return True
    return False


def _normalize_bands(raw_levels: list[dict[str, Any]]) -> list[FloorBand]:
    bands: list[FloorBand] = []
    for item in raw_levels:
        if not isinstance(item, dict):
            continue
        try:
            y0 = float(item.get("y0"))
            y1 = float(item.get("y1"))
        except (TypeError, ValueError):
            continue
        # Accept either top-origin or bottom-origin; force y0 < y1 in top-origin.
        if y0 > y1:
            y0, y1 = y1, y0
        y0 = min(1.0, max(0.0, y0))
        y1 = min(1.0, max(0.0, y1))
        if y1 - y0 < 0.02:
            continue
        bands.append(
            FloorBand(
                index=int(item.get("index") or len(bands) + 1),
                y0=y0,
                y1=y1,
                cues=[str(c) for c in (item.get("cues") or [])],
                ambiguous=bool(item.get("ambiguous")),
                confidence=float(item.get("confidence") or 0.0),
                notes=[str(n) for n in (item.get("notes") or [])],
            )
        )
    # Sort top→bottom by y0, reindex bottom→top for display.
    bands.sort(key=lambda b: b.y0)
    # Merge heavy overlaps (same level split) and near-adjacent thin strips.
    merged: list[FloorBand] = []
    for band in bands:
        if not merged:
            merged.append(band)
            continue
        prev = merged[-1]
        inter = max(0.0, min(prev.y1, band.y1) - max(prev.y0, band.y0))
        union = max(prev.y1, band.y1) - min(prev.y0, band.y0)
        gap = max(0.0, band.y0 - prev.y1)
        overlap_ok = union > 0 and inter / union >= 0.40
        # Merge near-adjacent thin splits of the same storey — never absorb
        # ground/roof strips into a real level (that inflates office counts).
        cue_conflict = (
            (_cue_hit(prev.cues, _GROUND_CUES) or _cue_hit(prev.cues, _ROOF_CUES))
            != (_cue_hit(band.cues, _GROUND_CUES) or _cue_hit(band.cues, _ROOF_CUES))
        ) or (
            _cue_hit(prev.cues, _GROUND_CUES | _ROOF_CUES)
            != _cue_hit(band.cues, _GROUND_CUES | _ROOF_CUES)
            and (_cue_hit(prev.cues, _GROUND_CUES | _ROOF_CUES) or _cue_hit(band.cues, _GROUND_CUES | _ROOF_CUES))
        )
        adjacent_thin = (
            gap <= 0.035
            and min(prev.height(), band.height()) < 0.07
            and not cue_conflict
        )
        if overlap_ok or adjacent_thin:
            prev.y0 = min(prev.y0, band.y0)
            prev.y1 = max(prev.y1, band.y1)
            prev.ambiguous = prev.ambiguous or band.ambiguous
            prev.confidence = max(prev.confidence, band.confidence)
            prev.cues = list(dict.fromkeys([*prev.cues, *band.cues]))
            continue
        merged.append(band)

    filtered = _filter_ground_roof_bands(merged)
    # Re-number bottom-up (lowest band in image = highest y1 = index 1).
    filtered.sort(key=lambda b: b.y1, reverse=True)
    for i, band in enumerate(filtered, start=1):
        band.index = i
    filtered.sort(key=lambda b: b.index)
    return filtered


def _filter_ground_roof_bands(bands: list[FloorBand]) -> list[FloorBand]:
    """Drop ground plane / roof parapet / sky strips that inflate office counts."""
    if not bands:
        return bands
    heights = sorted(b.height() for b in bands)
    median_h = heights[len(heights) // 2]
    min_h = max(0.045, 0.38 * median_h)
    kept: list[FloorBand] = []
    for band in bands:
        h = band.height()
        # Top edge parapet/sky (y≈0).
        if band.y1 <= 0.10 and (h < min_h or _cue_hit(band.cues, _ROOF_CUES)):
            continue
        if band.y0 <= 0.02 and h < 0.08 and _cue_hit(band.cues, _ROOF_CUES):
            continue
        # Bottom edge ground/road (y≈1).
        if band.y0 >= 0.88 and (h < min_h or _cue_hit(band.cues, _GROUND_CUES)):
            continue
        if band.y1 >= 0.97 and h < 0.09 and _cue_hit(band.cues, _GROUND_CUES):
            continue
        if h < min_h and (_cue_hit(band.cues, _GROUND_CUES) or _cue_hit(band.cues, _ROOF_CUES)):
            continue
        kept.append(band)
    return kept or bands


def gate_bands_on_facade(
    crop: np.ndarray,
    bands: list[FloorBand],
) -> tuple[list[FloorBand], list[str]]:
    """Keep proposed bands. Brightness and edge energy do not delete a level.

    A commercial storey can be darker than the floors above and can lack a
    repeating window row. Notes record weak edge energy; they do not remove
    the band. Proven/not-proven is decided later, not by this filter.
    """
    notes: list[str] = []
    if crop is None or crop.size == 0 or not bands:
        return list(bands), notes
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    gy = np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
    gx = np.abs(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3))
    row = np.where(gy > gx * 1.2, gy, 0).mean(axis=1)
    height = int(len(row))
    median = float(np.median(row)) if height else 0.0
    for band in bands:
        y0 = min(height - 1, max(0, int(band.y0 * height)))
        y1 = min(height, max(y0 + 1, int(band.y1 * height)))
        if float(row[y0:y1].mean()) < median * 0.85:
            notes.append(f"low_edge_energy:{band.index}")
    return list(bands), notes


def drop_ground_plane_band(
    crop: np.ndarray,
    bands: list[FloorBand],
) -> tuple[list[FloorBand], list[str]]:
    """Drop the lowest band when it is snow or roadway, not a storey.

    A band that reaches the bottom of the crop and is much brighter (snow)
    or much darker (asphalt) than the other bands is the ground plane.
    Window rows above it stay.
    """
    if crop is None or crop.size == 0 or len(bands) < 2:
        return list(bands), []
    lowest = max(bands, key=lambda band: (band.y1, band.y0))
    if lowest.y1 < 0.85:
        return list(bands), []
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]

    def _mean(band: FloorBand) -> float:
        y0 = min(height - 1, max(0, int(band.y0 * height)))
        y1 = min(height, max(y0 + 1, int(band.y1 * height)))
        x0, x1 = int(0.2 * width), int(0.8 * width)
        return float(gray[y0:y1, x0:x1].mean())

    others = [band for band in bands if band is not lowest]
    other_means = [_mean(band) for band in others]
    median = float(np.median(other_means)) if other_means else 0.0
    if median <= 1.0:
        return list(bands), []
    lowest_mean = _mean(lowest)
    if lowest_mean > median * 1.25 or lowest_mean < median * 0.85:
        return others, [f"dropped_ground_plane:{lowest.index}"]
    return list(bands), []


def assess_floors_proven(
    result: FloorLocalizeResult,
    *,
    reference_bands: list[FloorBand] | None = None,
    coverage_full: bool = True,
) -> tuple[bool, list[str]]:
    """Decide whether band localization is strong enough for floors_status=proven.

    VLM bands alone stay proposed. Proven needs open-frame/GT IoU match plus
    clean bands. Annotation/scene_label set proven outside this helper.
    """
    reasons: list[str] = []
    if result.error:
        return False, [f"localize_error:{result.error}"]
    if not coverage_full:
        reasons.append("coverage_not_full")
    if result.building_focus is False:
        reasons.append("building_focus_false")
    if result.level_count_from_bands < 1:
        reasons.append("no_bands")
    if result.unambiguous_count < result.level_count_from_bands:
        reasons.append("ambiguous_bands")
    if result.level_count_proposed is not None:
        if abs(int(result.level_count_proposed) - result.level_count_from_bands) > 1:
            reasons.append("proposed_vs_bands_conflict")
    if result.uncertainties:
        reasons.append("vlm_uncertainties")
    for note in result.limitations or []:
        if note.startswith("bands_miss_facade") or note == "no_structural_bands":
            reasons.append(note)
    if not reference_bands:
        reasons.append("needs_open_frame_or_gt_match")
    else:
        score = band_match_score(result.levels, [{"y0": b.y0, "y1": b.y1} for b in reference_bands])
        if score["recall"] < 0.55 or score["precision"] < 0.55:
            reasons.append(
                f"open_frame_mismatch:p={score['precision']}:r={score['recall']}"
            )
    proven = not reasons
    return proven, reasons


def draw_level_overlay(
    crop_bgr: np.ndarray,
    bands: list[FloorBand],
    *,
    title: str = "",
) -> np.ndarray:
    out = crop_bgr.copy()
    h, w = out.shape[:2]
    colors = [
        (40, 180, 80),
        (40, 160, 220),
        (40, 80, 220),
        (180, 80, 220),
        (220, 140, 40),
        (220, 60, 60),
        (180, 180, 40),
        (80, 200, 180),
    ]
    for band in bands:
        color = colors[(band.index - 1) % len(colors)]
        ya = int(band.y0 * h)
        yb = int(band.y1 * h)
        overlay = out.copy()
        cv2.rectangle(overlay, (0, ya), (w - 1, yb), color, -1)
        out = cv2.addWeighted(overlay, 0.28, out, 0.72, 0)
        cv2.rectangle(out, (0, ya), (w - 1, yb), color, 2)
        label = f"L{band.index}"
        if band.ambiguous:
            label += "?"
        cv2.putText(
            out,
            label,
            (8, max(18, ya + 18)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
            cv2.LINE_AA,
        )
    if title:
        cv2.putText(out, title, (8, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 2, cv2.LINE_AA)
    return out


def _image_data_url(bgr: np.ndarray, max_side: int) -> str:
    h, w = bgr.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w)) if max_side > 0 else 1.0
    img = bgr
    if scale < 1.0:
        img = cv2.resize(bgr, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise ValueError("jpeg_encode_failed")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def localize_floor_levels(
    image_path: Path,
    *,
    detections: list[Detection] | None = None,
    out_dir: Path | None = None,
    crop_box: tuple[int, int, int, int] | None = None,
) -> FloorLocalizeResult:
    started = time.perf_counter()
    image_path = Path(image_path)
    img = cv2.imread(str(image_path))
    if img is None:
        return FloorLocalizeResult(
            image_path=str(image_path),
            crop_box_xyxy=[0, 0, 0, 0],
            crop_path=None,
            overlay_path=None,
            levels=[],
            level_count_proposed=None,
            level_count_from_bands=0,
            unambiguous_count=0,
            building_focus=None,
            error="image_read_failed",
        )

    box = crop_box or subject_building_box(img, detections)
    x1, y1, x2, y2 = box
    crop = img[y1:y2, x1:x2].copy()
    if crop.size == 0:
        return FloorLocalizeResult(
            image_path=str(image_path),
            crop_box_xyxy=[float(x1), float(y1), float(x2), float(y2)],
            crop_path=None,
            overlay_path=None,
            levels=[],
            level_count_proposed=None,
            level_count_from_bands=0,
            unambiguous_count=0,
            building_focus=None,
            error="empty_crop",
        )

    settings = get_settings()
    cfg = perception_config().get("qwen_vl") or {}
    base_url = (settings.qwen_vl_base_url or str(cfg.get("base_url") or "http://127.0.0.1:8001/v1")).rstrip("/")
    model = settings.qwen_vl_model or str(cfg.get("model") or "Qwen/Qwen3-VL-8B-Instruct")
    timeout = float(settings.qwen_vl_timeout_seconds or cfg.get("timeout_seconds") or 180)
    max_side = int(cfg.get("max_image_side") or 1280)
    temperature = float(cfg.get("temperature") or 0.1)
    max_tokens = int(settings.qwen_vl_max_tokens or cfg.get("max_tokens") or 2048)

    body = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": _load_floor_prompt()},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "task": "localize_storey_levels",
                                "note": (
                                    "Image is a crop of the subject building. y=0 at top. "
                                    "Include podium/commercial and open framing levels. "
                                    "Exclude ground plane, sky, and roof-only parapet."
                                ),
                            },
                            ensure_ascii=False,
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": _image_data_url(crop, max_side)}},
                ],
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "floor_levels",
                "schema": _load_floor_schema(),
                "strict": False,
            },
        },
    }
    headers = {"Content-Type": "application/json"}
    api_key = settings.qwen_vl_api_key or str(cfg.get("api_key") or "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(f"{base_url}/chat/completions", json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        content = data["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "\n".join(p.get("text", "") for p in content if isinstance(p, dict))
        parsed = json.loads(content) if isinstance(content, str) else content
        if not isinstance(parsed, dict):
            raise ValueError("non_object_json")
    except Exception as exc:  # noqa: BLE001
        return FloorLocalizeResult(
            image_path=str(image_path),
            crop_box_xyxy=[float(x1), float(y1), float(x2), float(y2)],
            crop_path=None,
            overlay_path=None,
            levels=[],
            level_count_proposed=None,
            level_count_from_bands=0,
            unambiguous_count=0,
            building_focus=None,
            error=f"qwen_floor_levels:{exc}",
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    bands = _normalize_bands(list(parsed.get("levels") or []))
    bands, gate_notes = gate_bands_on_facade(crop, bands)
    proposed = parsed.get("level_count_proposed")
    try:
        proposed_n = int(proposed) if proposed is not None else None
    except (TypeError, ValueError):
        proposed_n = None
    # Authoritative count for this method = bands after merge, not the free integer alone.
    count_bands = len(bands)
    unambiguous = sum(1 for b in bands if not b.ambiguous)
    if not bands and gate_notes and proposed_n is not None:
        gate_notes.append(f"rejected_scalar:{proposed_n}")
        proposed_n = None

    out_dir = Path(out_dir) if out_dir else None
    crop_path = overlay_path = None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        stem = f"{image_path.stem}_{uuid.uuid4().hex[:8]}"
        crop_path = str(out_dir / f"{stem}_crop.jpg")
        overlay_path = str(out_dir / f"{stem}_levels.jpg")
        cv2.imwrite(crop_path, crop)
        overlay = draw_level_overlay(
            crop,
            bands,
            title=f"bands={count_bands} proposed={proposed_n} unambiguous={unambiguous}",
        )
        cv2.imwrite(overlay_path, overlay)

    return FloorLocalizeResult(
        image_path=str(image_path),
        crop_box_xyxy=[float(x1), float(y1), float(x2), float(y2)],
        crop_path=crop_path,
        overlay_path=overlay_path,
        levels=bands,
        level_count_proposed=proposed_n,
        level_count_from_bands=count_bands,
        unambiguous_count=unambiguous,
        building_focus=bool(parsed.get("building_focus")) if "building_focus" in parsed else None,
        limitations=[str(x) for x in (parsed.get("limitations") or [])] + gate_notes,
        uncertainties=[str(x) for x in (parsed.get("uncertainties") or [])],
        raw=parsed,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


def band_match_score(pred: list[FloorBand], gt: list[dict[str, float]], *, iou_thr: float = 0.3) -> dict[str, Any]:
    """Match predicted bands to manual GT bands by IoU on 1D y-intervals."""
    gt_bands = []
    for item in gt:
        y0, y1 = float(item["y0"]), float(item["y1"])
        if y0 > y1:
            y0, y1 = y1, y0
        gt_bands.append((y0, y1))
    matched_gt: set[int] = set()
    matched_pred: set[int] = set()
    pairs = []
    for pi, pb in enumerate(pred):
        best_j, best_iou = -1, 0.0
        for ji, (gy0, gy1) in enumerate(gt_bands):
            if ji in matched_gt:
                continue
            inter = max(0.0, min(pb.y1, gy1) - max(pb.y0, gy0))
            union = max(pb.y1, gy1) - min(pb.y0, gy0)
            iou = inter / union if union > 0 else 0.0
            if iou > best_iou:
                best_iou, best_j = iou, ji
        if best_j >= 0 and best_iou >= iou_thr:
            matched_gt.add(best_j)
            matched_pred.add(pi)
            pairs.append({"pred": pb.index, "gt": best_j + 1, "iou": round(best_iou, 3)})
    tp = len(pairs)
    fp = len(pred) - tp
    fn = len(gt_bands) - tp
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": round(tp / max(tp + fp, 1), 3),
        "recall": round(tp / max(tp + fn, 1), 3),
        "pairs": pairs,
        "pred_count": len(pred),
        "gt_count": len(gt_bands),
    }
