"""Qwen VLM: local OpenAI-compatible server or OpenRouter (pinned provider)."""

from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import os
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


def _resolve_api_key(cfg: dict[str, Any], settings_key: str) -> str:
    if settings_key:
        return settings_key
    env_name = str(cfg.get("api_key_env") or "OPENROUTR_KEY")
    return os.environ.get(env_name) or os.environ.get("OPENROUTER_KEY") or str(cfg.get("api_key") or "")


def _image_bytes(image_path: Path, max_side: int, jpeg_quality: int = 90) -> tuple[bytes, str]:
    img = cv2.imread(str(image_path))
    if img is None:
        raw = image_path.read_bytes()
        mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
        return raw, mime
    h, w = img.shape[:2]
    scale = min(1.0, float(max_side) / max(h, w)) if max_side > 0 else 1.0
    if scale < 1.0:
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), int(jpeg_quality)])
    if not ok:
        raise ValueError("jpeg_encode_failed")
    return buf.tobytes(), "image/jpeg"


def _image_data_url(image_path: Path, max_side: int, jpeg_quality: int = 90) -> tuple[str, str]:
    raw, mime = _image_bytes(image_path, max_side, jpeg_quality)
    digest = hashlib.sha256(raw).hexdigest()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}", digest


class QwenVlProvider:
    name = "qwen_vl"

    def __init__(self, *, enabled: bool | None = None) -> None:
        settings = get_settings()
        cfg = perception_config().get("qwen_vl") or {}
        if enabled is None:
            enabled = settings.qwen_vl_enabled if settings.qwen_vl_enabled is not None else bool(cfg.get("enabled", True))
        self.enabled = bool(enabled)
        self.transport = str(cfg.get("transport") or "openai_compat").strip().lower()
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
        self.temperature = float(cfg.get("temperature") if cfg.get("temperature") is not None else 0.1)
        self.max_tokens = int(
            settings.qwen_vl_max_tokens if settings.qwen_vl_max_tokens is not None else (cfg.get("max_tokens") or 2048)
        )
        self.top_p = float(cfg.get("top_p") if cfg.get("top_p") is not None else 1.0)
        self.seed = cfg.get("seed")
        self.api_key = _resolve_api_key(cfg, settings.qwen_vl_api_key or "")
        self.max_image_side = int(cfg.get("max_image_side") or 1280)
        self.jpeg_quality = int(cfg.get("jpeg_quality") or 90)
        self.provider_order = list(cfg.get("provider_order") or [])
        self.provider_only = list(cfg.get("provider_only") or [])
        self.allow_fallbacks = bool(cfg.get("allow_fallbacks", False))
        self.reasoning = dict(cfg.get("reasoning") or {})
        self.apply_camera_target_crop = bool(cfg.get("apply_camera_target_crop", False))
        self.strip_plan_hints = bool(cfg.get("strip_plan_hints", True))

    def interpret(
        self,
        image_path: Path,
        *,
        evidence: list[PerceptionEvidence],
        quality: dict[str, Any],
        ontology_hints: dict[str, Any],
        camera_code: str | None = None,
        captured_at: Any = None,
        artifact_dir: Path | None = None,
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
        if self.transport == "openrouter" and not self.api_key:
            return ProviderResult(
                status=StageStatus.UNAVAILABLE,
                error="qwen_vl_api_key_missing",
                model=self.model,
                model_version=self.model_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        send_path = image_path
        crop_meta: dict[str, Any] = {}
        if self.apply_camera_target_crop and camera_code:
            from sitewatch.perception.camera_targets import apply_crop, resolve_crop_xyxy, target_meta

            xyxy = resolve_crop_xyxy(camera_code, captured_at)
            crop_meta = {**target_meta(camera_code), "crop_xyxy": xyxy}
            if xyxy and artifact_dir is not None:
                crop_path = artifact_dir / "qwen_input_crop.jpg"
                send_path = apply_crop(image_path, xyxy, crop_path)

        # Perception must not receive plan quantities / KSG dates / object names that hint floors.
        safe_hints = {
            "structures": ontology_hints.get("structures") or [],
            "equipment": ontology_hints.get("equipment") or [],
            "mvp_classes": ontology_hints.get("mvp_classes") or [],
        }
        if not self.strip_plan_hints:
            safe_hints = dict(ontology_hints)

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
            "ontology_hints": safe_hints,
        }
        schema = _load_schema()
        system_prompt = _load_prompt_text()
        try:
            image_url, image_sha = _image_data_url(send_path, self.max_image_side, self.jpeg_quality)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                status=StageStatus.FAILED,
                error=f"qwen_vl_image_encode:{exc}",
                model=self.model,
                model_version=self.model_version,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )

        if artifact_dir is not None:
            meta_path = artifact_dir / "qwen_request_meta.json"
            meta_path.write_text(
                json.dumps(
                    {
                        "model": self.model,
                        "transport": self.transport,
                        "provider_only": self.provider_only,
                        "reasoning": self.reasoning,
                        "image_sha256": image_sha,
                        "source_image": str(image_path),
                        "sent_image": str(send_path),
                        "crop": crop_meta,
                        "prompt_file": (perception_config().get("qwen_vl") or {}).get("prompt_file"),
                        "max_tokens": self.max_tokens,
                        "temperature": self.temperature,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        body: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
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
        if self.seed is not None:
            body["seed"] = int(self.seed)
        if self.transport == "openrouter":
            if not self.provider_order or not self.provider_only:
                return ProviderResult(
                    status=StageStatus.FAILED,
                    error="qwen_vl_provider_pin_missing",
                    model=self.model,
                    model_version=self.model_version,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            if self.provider_order != self.provider_only:
                return ProviderResult(
                    status=StageStatus.FAILED,
                    error="qwen_vl_provider_pin_mismatch",
                    model=self.model,
                    model_version=self.model_version,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                )
            body["provider"] = {
                "order": list(self.provider_order),
                "only": list(self.provider_only),
                "allow_fallbacks": bool(self.allow_fallbacks),
                "require_parameters": True,
            }
            if self.reasoning:
                body["reasoning"] = {"enabled": bool(self.reasoning.get("enabled", False))}

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if self.transport == "openrouter":
            headers["X-OpenRouter-Title"] = "Skripka-recompute"

        last_error: str | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(f"{self.base_url}/chat/completions", json=body, headers=headers)
                    if resp.status_code >= 400:
                        snippet = resp.text[:400]
                        last_error = f"qwen_vl_http_{resp.status_code}:{snippet}"
                        if resp.status_code < 500 and resp.status_code != 429:
                            break
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    data = resp.json()
                content = data["choices"][0]["message"]["content"]
                if isinstance(content, list):
                    texts = [p.get("text", "") for p in content if isinstance(p, dict)]
                    content = "\n".join(texts)
                raw_text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
                # Strip accidental markdown fences
                text = raw_text.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.lower().startswith("json"):
                        text = text[4:].lstrip()
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError as exc:
                    last_error = f"qwen_vl_invalid_json:{exc}"
                    self._last_raw = raw_text[:8000]
                    time.sleep(0.3 * (attempt + 1))
                    continue
                if not isinstance(parsed, dict):
                    raise ValueError("vlm_non_object_json")
                _sanitize_vlm_payload(parsed)
                if "professional_observation" in parsed and "summary" not in parsed:
                    parsed["summary"] = parsed.get("professional_observation") or ""
                if "visibility_constraints" in parsed:
                    lim = list(parsed.get("limitations") or [])
                    lim.extend(parsed.get("visibility_constraints") or [])
                    parsed["limitations"] = list(dict.fromkeys(lim))
                evidence_out = self._entities_to_evidence(parsed)
                usage = data.get("usage") or {}
                cost = data.get("usage", {}).get("cost") if isinstance(data.get("usage"), dict) else None
                if cost is None:
                    cost = data.get("cost")
                actual_model = data.get("model") or self.model
                provider_slug = None
                if isinstance(data.get("provider"), str):
                    provider_slug = data.get("provider")
                extras = {
                    "vlm_structured": parsed,
                    "raw_content": raw_text[:12000],
                    "endpoint": self.base_url,
                    "attempt": attempt,
                    "transport": self.transport,
                    "requested_model": self.model,
                    "actual_model": actual_model,
                    "provider_slug": provider_slug or (self.provider_only[0] if self.provider_only else None),
                    "image_sha256": image_sha,
                    "sent_image": str(send_path),
                    "crop": crop_meta,
                    "usage": usage,
                    "cost_usd": float(cost) if cost is not None else None,
                    "cost_status": "api" if cost is not None else "unknown",
                    "finish_reason": (data.get("choices") or [{}])[0].get("finish_reason"),
                    "reasoning": self.reasoning,
                }
                if artifact_dir is not None:
                    # Keep transport/cost separate — write_run_artifacts overwrites qwen_result.json
                    (artifact_dir / "qwen_transport.json").write_text(
                        json.dumps(
                            {
                                k: extras.get(k)
                                for k in (
                                    "transport",
                                    "requested_model",
                                    "actual_model",
                                    "provider_slug",
                                    "image_sha256",
                                    "sent_image",
                                    "crop",
                                    "usage",
                                    "cost_usd",
                                    "cost_status",
                                    "finish_reason",
                                    "reasoning",
                                    "attempt",
                                    "endpoint",
                                    "raw_content",
                                )
                            },
                            ensure_ascii=False,
                            indent=2,
                            default=str,
                        ),
                        encoding="utf-8",
                    )
                    (artifact_dir / "qwen_result.json").write_text(
                        json.dumps(parsed, ensure_ascii=False, indent=2, default=str),
                        encoding="utf-8",
                    )
                if str(extras.get("finish_reason") or "") == "length":
                    return ProviderResult(
                        status=StageStatus.FAILED,
                        error="qwen_vl_truncated",
                        evidence=evidence_out,
                        model=self.model,
                        model_version=self.model_version,
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                        extras=extras,
                    )
                if actual_model and "qwen3.5-397b" not in str(actual_model).lower() and self.transport == "openrouter":
                    # Refuse silent model swap
                    return ProviderResult(
                        status=StageStatus.FAILED,
                        error=f"qwen_vl_model_swap:{actual_model}",
                        model=self.model,
                        model_version=self.model_version,
                        latency_ms=round((time.perf_counter() - started) * 1000, 2),
                        extras=extras,
                    )
                return ProviderResult(
                    status=StageStatus.SUCCESS,
                    evidence=evidence_out,
                    model=self.model,
                    model_version=self.model_version,
                    latency_ms=round((time.perf_counter() - started) * 1000, 2),
                    extras=extras,
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
            extras={"endpoint": self.base_url, "raw_content": getattr(self, "_last_raw", ""), "transport": self.transport},
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
