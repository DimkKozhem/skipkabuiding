from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from sitewatch.domain.contracts import PerceptionEvidence
from sitewatch.domain.enums import StageStatus


@dataclass
class ProviderResult:
    status: StageStatus
    evidence: list[PerceptionEvidence] = field(default_factory=list)
    latency_ms: float | None = None
    error: str | None = None
    model: str | None = None
    model_version: str | None = None
    device: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class SegmentationProvider(Protocol):
    name: str

    def segment(
        self,
        image_path: Path,
        prompts: list[str],
        *,
        artifact_dir: Path | None = None,
    ) -> ProviderResult: ...


@runtime_checkable
class DetectionProvider(Protocol):
    name: str

    def detect(
        self,
        image_path: Path,
        prompts: list[str],
        *,
        class_filter: list[str] | None = None,
        artifact_dir: Path | None = None,
    ) -> ProviderResult: ...


@runtime_checkable
class VisionLanguageProvider(Protocol):
    name: str

    def interpret(
        self,
        image_path: Path,
        *,
        evidence: list[PerceptionEvidence],
        quality: dict[str, Any],
        ontology_hints: dict[str, Any],
    ) -> ProviderResult: ...
