"""Domain contracts for ObservedState / Evidence / temporal persistence."""

from __future__ import annotations

from datetime import datetime

from sitewatch.domain.contracts import (
    EntityObservation,
    ImageQuality,
    ObservedState,
    PerceptionEvidence,
    PipelineRun,
)
from sitewatch.domain.enums import (
    EntityVisibility,
    EvidenceSource,
    MeasurementType,
)
from sitewatch.perception.fusion.service import EvidenceFusionService
from sitewatch.temporal.state_engine import TemporalStateEngine


def test_observed_state_roundtrip():
    obs = ObservedState(
        frame_id="f1",
        object_id="site_001",
        zone_id="building_01",
        camera_id="cam",
        captured_at=datetime(2026, 9, 22, 12, 0, 0),
        quality=ImageQuality(usable=True, visibility=0.9, blur=0.1),
        structures={
            "floor_slab": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.LEVELS,
                value=3,
                count_visible=3,
                confidence=0.9,
            )
        },
        equipment={},
        evidence=[
            PerceptionEvidence(
                evidence_id="e1",
                source=EvidenceSource.ANNOTATION,
                model="annotation",
                class_name="floor_slab",
                score=0.9,
                normalized_label="floor_slab",
            )
        ],
        pipeline_run=PipelineRun(
            run_id="r1",
            object_id="site_001",
            zone_id="building_01",
            started_at=datetime(2026, 9, 22, 12, 0, 0),
        ),
        visible_floor_levels=3,
        total_floor_count=None,
    )
    restored = ObservedState.model_validate_json(obs.model_dump_json())
    assert restored.structures["floor_slab"].count_visible == 3
    assert restored.total_floor_count is None
    assert restored.evidence[0].source == EvidenceSource.ANNOTATION


def test_fusion_disagreement_marks_uncertain():
    fusion = EvidenceFusionService()
    evidence = [
        PerceptionEvidence(
            evidence_id="a",
            source=EvidenceSource.SAM3,
            model="sam3",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
        PerceptionEvidence(
            evidence_id="b",
            source=EvidenceSource.SAM3,
            model="sam3",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
        PerceptionEvidence(
            evidence_id="c",
            source=EvidenceSource.SAM3,
            model="sam3",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
        PerceptionEvidence(
            evidence_id="d",
            source=EvidenceSource.GROUNDING_DINO,
            model="dino",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
        PerceptionEvidence(
            evidence_id="e",
            source=EvidenceSource.GROUNDING_DINO,
            model="dino",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
        PerceptionEvidence(
            evidence_id="f",
            source=EvidenceSource.GROUNDING_DINO,
            model="dino",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
        PerceptionEvidence(
            evidence_id="g",
            source=EvidenceSource.GROUNDING_DINO,
            model="dino",
            class_name="column",
            score=0.9,
            normalized_label="column",
        ),
    ]
    structures, _, _, _ = fusion.fuse(
        quality=ImageQuality(usable=True),
        evidence=evidence,
        vlm_structured={
            "summary": "columns partially visible",
            "limitations": [],
            "uncertainties": ["count"],
            "entities": [
                {
                    "label": "column",
                    "status": "uncertain",
                    "count_visible": None,
                    "confidence": 0.4,
                }
            ],
        },
    )
    col = structures["column"]
    assert "detector_count_disagreement" in col.notes
    assert col.confidence <= 0.45


def test_persistent_not_erased_when_not_visible():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 9, 22, 10, 0, 0)
    t1 = datetime(2026, 9, 23, 10, 0, 0)
    first = ObservedState(
        frame_id="f0",
        object_id="site_001",
        zone_id="building_01",
        camera_id="cam",
        captured_at=t0,
        quality=ImageQuality(usable=True, visibility=0.9),
        structures={
            "floor_slab": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.LEVELS,
                value=3,
                count_visible=3,
                confidence=0.95,
            ),
            "foundation": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.PRESENCE,
                value=True,
                count_visible=1,
                confidence=0.9,
            ),
        },
        equipment={},
    )
    actual0 = engine.update(None, first)
    assert actual0.entities["floor_slab"].last_confirmed_value == 3

    second = ObservedState(
        frame_id="f1",
        object_id="site_001",
        zone_id="building_01",
        camera_id="cam",
        captured_at=t1,
        quality=ImageQuality(usable=True, visibility=0.5),
        structures={
            "floor_slab": EntityObservation(
                status=EntityVisibility.OCCLUDED,
                measurement=MeasurementType.LEVELS,
                value=None,
                count_visible=None,
                confidence=0.2,
            ),
            "foundation": EntityObservation(
                status=EntityVisibility.OCCLUDED,
                measurement=MeasurementType.PRESENCE,
                value=None,
                confidence=0.1,
            ),
        },
        equipment={},
    )
    actual1 = engine.update(actual0, second)
    assert actual1.entities["floor_slab"].last_confirmed_value == 3
    assert actual1.entities["floor_slab"].current_visibility == EntityVisibility.OCCLUDED
    assert actual1.entities["foundation"].last_confirmed_value is True
    # плиты сохраняются; этажность без visible_floor_levels не выводится из count боксов
    assert actual1.element_count("slabs") == 3
    assert actual1.scene_attributes.get("structural_levels") is None
    assert actual1.element_count("floors") == 0


def test_visible_floor_levels_persist_when_slabs_occluded():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 9, 22, 10, 0, 0)
    t1 = datetime(2026, 9, 23, 10, 0, 0)
    first = ObservedState(
        frame_id="f0",
        object_id="site_001",
        zone_id="building_01",
        camera_id="cam",
        captured_at=t0,
        quality=ImageQuality(usable=True, visibility=0.9),
        structures={
            "floor_slab": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.LEVELS,
                value=3,
                count_visible=3,
                confidence=0.95,
            ),
        },
        equipment={},
        visible_floor_levels=3,
        scene_attributes={"floors_status": "proven", "floors_derivation": "annotation"},
    )
    actual0 = engine.update(None, first)
    assert actual0.scene_attributes.get("structural_levels") == 3
    assert actual0.element_count("floors") == 3

    second = ObservedState(
        frame_id="f1",
        object_id="site_001",
        zone_id="building_01",
        camera_id="cam",
        captured_at=t1,
        quality=ImageQuality(usable=True, visibility=0.5),
        structures={
            "floor_slab": EntityObservation(
                status=EntityVisibility.OCCLUDED,
                measurement=MeasurementType.LEVELS,
                value=None,
                count_visible=None,
                confidence=0.2,
            ),
        },
        equipment={},
    )
    actual1 = engine.update(actual0, second)
    assert actual1.scene_attributes.get("structural_levels") == 3
    assert actual1.element_count("floors") == 3
    assert actual1.entities["floor_slab"].last_confirmed_value == 3