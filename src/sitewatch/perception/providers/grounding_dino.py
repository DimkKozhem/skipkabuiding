"""Grounding DINO optional verifier / fallback detector."""

from __future__ import annotations

import time
from pathlib import Path

from sitewatch.domain.enums import StageStatus
from sitewatch.perception.ontology import perception_config
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.settings import get_settings


class GroundingDinoProvider:
    name = "grounding_dino"

    def __init__(self, *, enabled: bool | None = None) -> None:
        settings = get_settings()
        cfg = perception_config().get("grounding_dino") or {}
        if enabled is None:
            if settings.grounding_dino_enabled is not None:
                enabled = settings.grounding_dino_enabled
            else:
                enabled = bool(cfg.get("enabled", False))
        self.enabled = bool(enabled)
        self.device = settings.grounding_dino_device or str(cfg.get("device") or "cuda:0")
        self.box_threshold = float(
            settings.grounding_dino_box_threshold
            if settings.grounding_dino_box_threshold is not None
            else (cfg.get("box_threshold") or 0.35)
        )
        self.text_threshold = float(
            settings.grounding_dino_text_threshold
            if settings.grounding_dino_text_threshold is not None
            else (cfg.get("text_threshold") or 0.25)
        )
        self.model = str(cfg.get("model") or "grounding-dino")
        self.model_version = str(cfg.get("model_version") or "n/a")
        self.verify_classes = list(cfg.get("verify_classes") or [])

    def detect(
        self,
        image_path: Path,
        prompts: list[str],
        *,
        class_filter: list[str] | None = None,
        artifact_dir: Path | None = None,
    ) -> ProviderResult:
        started = time.perf_counter()
        if not self.enabled:
            return ProviderResult(
                status=StageStatus.SKIPPED,
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=0.0,
            )
        try:
            import importlib

            importlib.import_module("groundingdino")  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                status=StageStatus.UNAVAILABLE,
                error=f"grounding_dino_unavailable:{exc}",
                model=self.model,
                model_version=self.model_version,
                device=self.device,
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
        _ = (image_path, prompts, class_filter, artifact_dir)
        # Package present but no wired inference weights yet — do not fake SUCCESS.
        return ProviderResult(
            status=StageStatus.UNAVAILABLE,
            error="grounding_dino_no_weights",
            model=self.model,
            model_version=self.model_version,
            device=self.device,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            extras={"verify_classes": class_filter or self.verify_classes},
        )
