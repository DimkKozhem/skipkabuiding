#!/usr/bin/env python3
"""Dry-run WorkFact chain on sample frames WITHOUT GPU (synthetic ObservedState).

Uses visual expectations from docs/engineering/workfact_sample_expectations.md.
Does not claim real CV precision.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from sitewatch.domain.contracts import (
    EntityObservation,
    ObservationNarrative,
    ObservedState,
    PipelineRun,
    PipelineStageResult,
)
from sitewatch.domain.enums import (
    EntityVisibility,
    MeasurementType,
    StageStatus,
    WorkCertainty,
)
from sitewatch.ksg.expected import build_expected_state
from sitewatch.works.compare import check_indicators
from sitewatch.works.derive import derive_work_facts

ROOT = Path(__file__).resolve().parents[1]


def _run(name: str, stages: list[str]) -> PipelineRun:
    return PipelineRun(
        run_id=name,
        object_id="site_001",
        zone_id="sample",
        camera_id="cam",
        pipeline_version="workfact-1",
        started_at=datetime(2026, 1, 1),
        finished_at=datetime(2026, 1, 1),
        processed_at=datetime(2026, 1, 1),
        stages=[PipelineStageResult(name=s, status=StageStatus.SUCCESS) for s in stages],
        outcome="succeeded",
    )


def sample_house6_early() -> ObservedState:
    # Visual: excavation, excavators; neighbors ≠ target floors
    return ObservedState(
        frame_id="house6-early",
        object_id="site_001",
        zone_id="house6",
        camera_id="cam_house6",
        captured_at=datetime(2026, 1, 2, 12, 0, 0),
        equipment={
            "excavator": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.COUNT,
                value=2,
                count_visible=2,
                confidence=0.9,
                evidence_ids=["ex1"],
            )
        },
        observation=ObservationNarrative(summary="котлован, экскаваторы"),
        pipeline_run=_run("h-early", ["annotation"]),
        scene_attributes={"work_zone": [[0.3, 0.4], [0.7, 0.4], [0.7, 0.85], [0.3, 0.85]], "work_code": "excavation"},
    )


def sample_office_final() -> ObservedState:
    # Visual: 2 floors, facade, roof, windows
    return ObservedState(
        frame_id="office-final",
        object_id="site_001",
        zone_id="office_01",
        camera_id="cam_office",
        captured_at=datetime(2023, 1, 29, 17, 40, 0),
        structures={
            "facade": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.PRESENCE,
                value=True,
                confidence=0.85,
                evidence_ids=["f1"],
            ),
            "roof": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.PRESENCE,
                value=True,
                confidence=0.8,
                evidence_ids=["r1"],
            ),
            "window_opening": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.COUNT,
                value=8,
                count_visible=8,
                confidence=0.8,
                evidence_ids=["w1"],
            ),
        },
        observation=ObservationNarrative(summary="офис 2 этажа, фасад, кровля"),
        pipeline_run=_run("o-final", ["annotation"]),
        scene_attributes={
            "work_zone": [[0.2, 0.2], [0.85, 0.2], [0.85, 0.8], [0.2, 0.8]],
            "work_code": "facade",
            "floors": 2,
            "visible_floor_levels": 2,
        },
        visible_floor_levels=2,
    )


def sample_road_final() -> ObservedState:
    return ObservedState(
        frame_id="road-final",
        object_id="site_001",
        zone_id="road_alley",
        camera_id="cam_road",
        captured_at=datetime(2016, 11, 3, 12, 0, 0),
        equipment={
            "excavator": EntityObservation(
                status=EntityVisibility.VISIBLE,
                measurement=MeasurementType.COUNT,
                value=1,
                count_visible=1,
                confidence=0.7,
                evidence_ids=["re1"],
            )
        },
        observation=ObservationNarrative(summary="отсыпка разделителя, экскаватор"),
        pipeline_run=_run("road", ["annotation"]),
        scene_attributes={"work_code": "divider"},
    )


def main() -> None:
    cases = [
        (
            "house6_early",
            sample_house6_early(),
            build_expected_state(
                object_id="site_001",
                zone_id="house6",
                on_date=date(2026, 1, 12),
                stage="excavation",
                expected={},
                schedule_row_id="ksg-house6-exc",
            ),
        ),
        (
            "office_final",
            sample_office_final(),
            build_expected_state(
                object_id="site_001",
                zone_id="office_01",
                on_date=date(2023, 1, 29),
                stage="facade",
                expected={"floors": 2, "facade": True, "roof": True, "windows": 2},
                schedule_row_id="ksg-office-facade",
            ),
        ),
        (
            "road_final",
            sample_road_final(),
            build_expected_state(
                object_id="site_001",
                zone_id="road_alley",
                on_date=date(2016, 11, 3),
                stage="divider",
                expected={"dividing_line_m": 18},
                schedule_row_id="ksg-road",
            ),
        ),
    ]
    report = []
    for name, observed, expected in cases:
        facts = derive_work_facts(observed, work_code=expected.stage)
        from sitewatch.domain.contracts import ActualState
        from sitewatch.domain.enums import CoverageLevel, Visibility
        from sitewatch.domain.contracts import ObservationQuality

        actual = ActualState(
            object_id=observed.object_id,
            zone_id=observed.zone_id,
            timestamp=observed.captured_at,
            camera_code=observed.camera_id,
            work_facts=facts,
            quality=ObservationQuality(visibility=Visibility.GOOD, coverage=CoverageLevel.FULL, n_frames=1),
        )
        checks = check_indicators(
            expected.planned_indicators,
            actual,
            evaluation_as_of=expected.date,
            last_observation_date=observed.captured_at.date(),
        )
        report.append(
            {
                "case": name,
                "facts": {
                    k: {
                        "certainty": f.certainty.value,
                        "value": f.value,
                        "method": f.method,
                        "confirms": f.confirms,
                    }
                    for k, f in facts.items()
                },
                "checks": [
                    {
                        "indicator": c.planned.indicator_id if c.planned else None,
                        "outcome": c.outcome.value,
                        "title": c.title,
                    }
                    for c in checks
                ],
            }
        )
    out = ROOT / "docs" / "engineering" / "workfact_sample_dryrun.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
