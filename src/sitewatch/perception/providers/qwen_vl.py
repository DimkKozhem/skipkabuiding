"""Qwen3-VL via vLLM OpenAI-compatible API. Structured JSON only."""

from __future__ import annotations

import base64
import json
import mimetypes
import time
import uuid
from pathlib import Path
from typing import Any

import cv2
import httpx
import numpy as np

from sitewatch.domain.contracts import PerceptionEvidence
from sitewatch.domain.enums import EntityVisibility, EvidenceSource, StageStatus
from sitewatch.perception.ontology import canonical_label, perception_config
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.settings import get_settings, project_root


def _sanitize_vlm_payload(parsed: dict[str, Any]) -> None:
    """Drop schema values the ontology does not define. Keep the raw text elsewhere."""
    allowed = {item.value for item in EntityVisibility}
    entities = parsed.get("entities")
    if not isinstance(entities, list):
        return
    for ent in entities:
        if not isinstance(ent, dict):
            continue
        status = str(ent.get("status") or "")
        if status not in allowed:
            ent["status"] = EntityVisibility.UNCERTAIN.value
            ent["count_visible"] = None
            notes = list(ent.get("notes") or [])
            notes.append("unsupported_status")
            ent["notes"] = notes


def _load_prompt_text() -> str:
    cfg = perception_config().get("qwen_vl") or {}
    rel = str(cfg.get("prompt_file") or "prompts/qwen_construction_observer_v1.txt")
    path = project_root() / "config" / rel
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return (
        "You are a construction-site visual observer. "
        "Describe only what is visible. not_visible != absent. Return JSON only."
    )


def _load_schema() -> dict[str, Any]:
    cfg = perception_config().get("qwen_vl") or {}
    rel = str(cfg.get("prompt_file") or "prompts/qwen_construction_observer_v1.txt")
    schema_path = project_root() / "config" / Path(rel).with_suffix(".schema.json")
    if schema_path.is_file():
        return json.loads(schema_path.read_text(encoding="utf-8"))
    return {
        "type": "object",
        "properties": {
            "professional_observation": {"type": "string"},
            "limitations": {"type": "array", "items": {"type": "string"}},
            "uncertainties": {"type": "array", "items": {"type": "string"}},
            "entities": {"type": "array"},
        },
        "required": ["professional_observation", "limitations", "uncertainties", "entities"],
    }


def _image_data_url(image_path: Path, max_side: int) -> str:
    img = cv2.imread(str(image_path))
    if img is None:
        raw = image_path.read_bytes()
        mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        b64 = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{b64}"
    h, w = img.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w)) if max_side > 0 else 1.0
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    if not ok:
        raise ValueError("jpeg_encode_failed")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


class QwenVlProvider:
    name = "qwen_vl"

    def __init__(self, *, enabled: bool | None = None) -> None:
        settings = get_settings()
        cfg = perception_config().get("qwen_vl") or {}
        if enabled is None:
            enabled = settings.qwen_vl_enabled if settings.qwen_vl_enabled is not None else bool(cfg.get("enabled", True))
        self.enabled = bool(enabled)
        self.base_url = (
            settings.qwen_vl_base_url or str(cfg.get("base_url") or "http://127.0.0.1:8001/v1")
        ).rstrip("/")
        self.model = settings.qwen_vl_model or str(cfg.get("model") or "Qwen/Qwen3-VL-8B-Instruct")
        self.model_version = str(cfg.get("model_version") or "n/a")
        self.timeout = float(
            settings.qwen_vl_timeout_seconds
            if settings.qwen_vl_timeout_seconds is not None
            else (cfg.get("timeout_seconds") or 180)
        )
        self.max_retries = int(cfg.get("max_retries") or 1)
        self.temperature = float(cfg.get("temperature") or 0.1)
        self.max_tokens = int(
            settings.qwen_vl_max_tokens if settings.qwen_vl_max_tokens is not None else (cfg.get("max_tokens") or 2048)
        )
        self.api_key = settings.qwen_vl_api_key or str(cfg.get("api_key") or "")
        self.max_image_side = int(cfg.get("max_image_side") or 1280)

    def interpret(
        self,
        image_path: Path,
        *,
        evidence: list[PerceptionEvidence],
        quality: dict[str, Any],
        ontology_hints: dict[str, Any],
    ) -> ProviderResult:
        started = time.perf_counter()
        if not self.enabled:
            return ProviderResult(
                status=StageStatus.SKIPPED,
                model=self.model,
                model_version=self.model_version,
                latency_ms=0.0,
            )
        if not self.base_url:
            return ProviderResult(
                status=StageStatus.UNAVAILABLE,
                error="qwen_vl_base_url_missing",
                model=self.model,
                model_version=self.model_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        payload_evidence = [
            {
                "normalized_label": e.normalized_label,
                "score": e.score,
                "source": e.source.value if hasattr(e.source, "value") else str(e.source),
                "bbox": e.bbox.model_dump() if e.bbox else None,
                "mask_reference": e.mask_reference,
            }
            for e in evidence[:80]
        ]
        user_payload = {
            "task": "construction_scene_observation",
            "quality": quality,
            "detections": payload_evidence,
            "ontology_hints": ontology_hints,
        }
        schema = _load_schema()
        system_prompt = _load_prompt_text()
        try:
            image_url = _image_data_url(image_path, self.max_image_side)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                status=StageStatus.FAILED,
                error=f"qwen_vl_image_encode:{exc}",
                model=self.model,
                model_version=self.model_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        body = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": json.dumps(user_payload, ensure_ascii=False)},
                        {"type": "image_url", "image_url": {"url": image_url}},
                    ],
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "construction_observation",
                    "schema": schema,
                    "strict": False,
                },
            },
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        last_error: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
                    if resp.status_code >= 400:
                        # do not retry client errors except 429
                        snippet = resp.text[:400]
                        last_error = f"qwen_vl_http_{resp.status_code}:{snippet}"
                        if resp.status_code < 500 and resp.status_code != 429:
                            break
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    # some servers return content parts
                    texts = [p.get("text", "") for p in content if isinstance(p, dict)]
                    content = "\n".join(texts)
                raw_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                try:
                    parsed = json.loads(raw_text) if isinstance(content, str) else content
                except json.JSONDecodeError as exc:
                    last_error = f"qwen_vl_invalid_json:{exc}"
                    self._last_raw = raw_text[:8000]
                    time.sleep(0.3 * (attempt + 1))
                    continue
                if not isinstance(parsed, dict):
                    raise ValueError("vlm_non_object_json")
                _sanitize_vlm_payload(parsed)
                # normalize narrative fields used by fusion
                if "professional_observation" in parsed and "summary" not in parsed:
                    parsed["summary"] = parsed.get("professional_observation") or ""
                if "visibility_constraints" in parsed:
                    lim = list(parsed.get("limitations") or [])
                    lim.extend(parsed.get("visibility_constraints") or [])
                    parsed["limitations"] = list(dict.fromkeys(lim))
                evidence_out = self._entities_to_evidence(parsed)
                return ProviderResult(
                    status=StageStatus.SUCCESS,
                    evidence=evidence_out,
                    model=self.model,
                    model_version=self.model_version,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    extras={
                        "vlm_structured": parsed,
                        "raw_content": raw_text[:8000],
                        "endpoint": self.base_url,
                        "attempt": attempt,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"qwen_vl_error:{exc}"
                time.sleep(0.3 * (attempt + 1))

        return ProviderResult(
            status=StageStatus.FAILED if last_error else StageStatus.UNAVAILABLE,
            error=last_error or "qwen_vl_failed",
            model=self.model,
            model_version=self.model_version,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            extras={"endpoint": self.base_url, "raw_content": getattr(self, "_last_raw", "")},
        )

    def _entities_to_evidence(self, parsed: dict[str, Any]) -> list[PerceptionEvidence]:
        out: list[PerceptionEvidence] = []
        for item in parsed.get("entities") or []:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("label") or "")
            norm = canonical_label(raw) or raw
            out.append(
                PerceptionEvidence(
                    evidence_id=uuid.uuid4().hex,
                    source=EvidenceSource.QWEN_VL,
                    model=self.model,
                    model_version=self.model_version,
                    class_name=norm,
                    score=float(item.get("confidence") or 0.0),
                    raw_label=raw,
                    normalized_label=norm,
                    metadata={
                        "status": item.get("status"),
                        "count_visible": item.get("count_visible"),
                        "visible_ratio": item.get("visible_ratio"),
                        "notes": item.get("notes") or [],
                    },
                )
            )
        return out
