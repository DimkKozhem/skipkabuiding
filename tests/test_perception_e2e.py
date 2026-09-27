"""E2E perception chain with mocked providers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from sitewatch.domain.contracts import BBox, PerceptionEvidence
from sitewatch.domain.enums import EvidenceSource, StageStatus
from sitewatch.perception.fusion.service import EvidenceFusionService
from sitewatch.perception.pipeline import PerceptionPipeline
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.temporal.state_engine import TemporalStateEngine
from sitewatch.deviation.plan_fact import PlanFactEngine
from sitewatch.domain.contracts import ExpectedState
from sitewatch.domain.enums import EntityVisibility


class _MockSam:
    name = "sam3"
    device = "cpu"

    def segment(self, image_path, prompts, *, artifact_dir=None):
        return ProviderResult(
            status=StageStatus.SUCCESS,
            evidence=[
                PerceptionEvidence(
                    evidence_id="s1",
                    source=EvidenceSource.SAM3,
                    model="sam3-mock",
                    model_version="test",
                    class_name="excavator",
                    bbox=BBox(x1=10, y1=10, x2=100, y2=100),
                    score=0.92,
                    raw_label="excavator",
                    normalized_label="excavator",
                ),
                PerceptionEvidence(
                    evidence_id="s2",
                    source=EvidenceSource.SAM3,
                    model="sam3-mock",
                    model_version="test",
                    class_name="floor_slab",
                    bbox=BBox(x1=20, y1=20, x2=200, y2=80),
                    score=0.88,
                    raw_label="floor slab",
                    normalized_label="floor_slab",
                ),
            ],
            latency_ms=5.0,
            model="sam3-mock",
            model_version="test",
        )


class _MockDino:
    name = "grounding_dino"
    verify_classes = ["excavator", "floor_slab"]

    def detect(self, image_path, prompts, *, class_filter=None, artifact_dir=None):
        return ProviderResult(
            status=StageStatus.FAILED,
            error="dino_timeout",
            latency_ms=1.0,
            model="dino-mock",
        )


class _MockQwen:
    name = "qwen_vl"

    def interpret(self, image_path, *, evidence, quality, ontology_hints):
        return ProviderResult(
            status=StageStatus.SUCCESS,
            evidence=[],
            latency_ms=8.0,
            model="qwen-mock",
            extras={
                "vlm_structured": {
                    "summary": "Visible excavator and floor slabs; foundation not clearly in view.",
                    "limitations": ["partial_view"],
                    "uncertainties": ["exact_slab_count"],
                    "entities": [
                        {
                            "label": "excavator",
                            "status": "visible",
                            "count_visible": 1,
                            "confidence": 0.91,
                        },
                        {
                            "label": "floor_slab",
                            "status": "visible",
                            "count_visible": 2,
                            "confidence": 0.8,
                        },
                        {
                            "label": "foundation",
                            "status": "outside_view",
                            "count_visible": None,
                            "confidence": 0.5,
                        },
                    ],
                    "visible_floor_levels": 2,
                    "foundation_visible": False,
                }
            },
        )


def test_perception_pipeline_graceful_degradation(tmp_path: Path):
    img = tmp_path / "frame.jpg"
    # textured frame so OpenCV blur metric stays usable
    rng = np.random.default_rng(0)
    frame = rng.integers(40, 200, size=(640, 800, 3), dtype=np.uint8)
    cv2.imwrite(str(img), frame)

    from sitewatch.domain.enums import PerceptionMode

    pipe = PerceptionPipeline(
        mode=PerceptionMode.FULL,
        sam3=_MockSam(),
        dino=_MockDino(),
        qwen=_MockQwen(),
        fusion=EvidenceFusionService(),
    )
    observed = pipe.run(
        img,
        object_id="site_001",
        zone_id="zone_a",
        camera_id="cam_a",
        captured_at=datetime(2026, 9, 22, 12, 0, 0),
        artifact_dir=tmp_path / "artifacts",
    )
    assert observed.quality.usable is True
    assert observed.equipment["excavator"].status == EntityVisibility.VISIBLE
    assert observed.visible_floor_levels == 2
    assert observed.total_floor_count is None  # foundation not visible
    assert any(s.name == "grounding_dino" and s.status == StageStatus.FAILED for s in observed.pipeline_run.stages)
    assert "dino_timeout" in observed.pipeline_run.errors

    actual = TemporalStateEngine().update(None, observed)
    assert actual.entities["excavator"].current_value in (1, True) or actual.equipment_count("excavator") >= 1

    # plan/fact without raw frame
    expected = ExpectedState(
        date=datetime(2026, 9, 22).date(),
        object_id="site_001",
        zone_id="zone_a",
        stage="earthworks",
        expected={"floors": 2},
        required_equipment=[{"type": "excavator", "min_count": 1}],
    )
    candidates = PlanFactEngine().evaluate(expected, actual)
    assert isinstance(candidates, list)
