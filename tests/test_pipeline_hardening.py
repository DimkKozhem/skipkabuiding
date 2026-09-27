"""Confirmed failure modes: unknown is not zero, time is not a single snapshot, jobs stay bounded."""

from __future__ import annotations

from datetime import datetime, timedelta

import cv2
import numpy as np

from sitewatch.domain.contracts import (
    EntityObservation,
    EvidenceRef,
    ImageQuality,
    ObservedState,
    PerceptionEvidence,
    PipelineRun,
)
from sitewatch.domain.enums import (
    EntityVisibility,
    EvidenceSource,
    JobStatus,
    MeasurementType,
    PerceptionMode,
)
from sitewatch.inspector.workflow import candidate_fingerprint, persist_candidate
from sitewatch.perception.fusion.service import EvidenceFusionService
from sitewatch.pipeline.benchmark import build_run_manifest, run_benchmark
from sitewatch.pipeline.jobs import enqueue_frame_analysis, recover_stale_jobs
from sitewatch.storage.db import get_session, init_db
from sitewatch.storage.models import Alert, Evidence, FrameAnalysisJob
from sitewatch.temporal.engine import TemporalEngine
from sitewatch.temporal.state_engine import TemporalStateEngine
from tests.test_inspector import _candidate
from tests.test_temporal import _state


def _quality(usable: bool = True) -> ImageQuality:
    return ImageQuality(usable=usable, visibility=0.9 if usable else 0.1, blur=0.1)


def _obs(
    ts: datetime,
    *,
    equipment: dict[str, EntityObservation] | None = None,
    structures: dict[str, EntityObservation] | None = None,
    camera: str = "cam",
    usable: bool = True,
    viewpoint: str | None = None,
    version: str | None = None,
) -> ObservedState:
    scene = {}
    if viewpoint:
        scene["viewpoint"] = viewpoint
    run = None
    if version:
        run = PipelineRun(
            run_id="run",
            object_id="site",
            zone_id="zone",
            started_at=ts,
            pipeline_version=version,
        )
    return ObservedState(
        frame_id="f",
        object_id="site",
        zone_id="zone",
        camera_id=camera,
        captured_at=ts,
        quality=_quality(usable),
        structures=structures or {},
        equipment=equipment or {},
        scene_attributes=scene,
        pipeline_run=run,
    )


def _machine(count: int | None, status: EntityVisibility, confidence: float = 0.9) -> EntityObservation:
    return EntityObservation(
        status=status,
        measurement=MeasurementType.COUNT,
        value=count,
        count_visible=count,
        confidence=confidence,
    )


def test_vlm_text_is_not_a_detection_and_unknown_is_not_zero():
    fusion = EvidenceFusionService()
    structures, equipment, narrative, _scene = fusion.fuse(
        quality=_quality(),
        evidence=[],
        vlm_structured={
            "summary": "кажется, четыре экскаватора",
            "entities": [
                {"label": "excavator", "status": "visible", "count_visible": 4, "confidence": 0.9}
            ],
        },
        detector_status="success",
        vlm_status="success",
    )
    assert "excavator" not in structures
    machine = equipment["excavator"]
    assert machine.status == EntityVisibility.UNCERTAIN
    assert machine.count_visible is None
    assert machine.value is None
    assert "vlm_only_not_a_detection" in machine.notes
    assert machine.confidence < 0.55
    assert "component_failed:detector" not in narrative.limitations


def test_detector_failure_does_not_become_a_zero_count():
    fusion = EvidenceFusionService()
    _structures, equipment, narrative, _scene = fusion.fuse(
        quality=_quality(),
        evidence=[],
        vlm_structured={
            "entities": [{"label": "dump_truck", "status": "visible", "count_visible": 2, "confidence": 0.8}]
        },
        detector_status="failed",
        vlm_status="success",
    )
    truck = equipment["dump_truck"]
    assert truck.value is None
    assert "agreement:component_failed" in truck.notes
    assert "component_failed:detector" in narrative.limitations


def test_conflict_does_not_enter_plan_fact_counts():
    engine = TemporalStateEngine()
    machine = _machine(2, EntityVisibility.UNCERTAIN, confidence=0.45)
    machine.notes = ["agreement:conflict", "detector_count_disagreement"]
    state = engine.update(None, _obs(datetime(2026, 9, 1, 12, 0, 0), equipment={"excavator": machine}))
    assert state.entities["excavator"].current_value == 2
    assert state.entities["excavator"].last_confirmed_value is None
    assert "excavator" not in state.equipment


def test_bad_frame_keeps_confirmed_machine_and_order_is_respected():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 9, 1, 12, 0, 0)
    t1 = datetime(2026, 9, 1, 12, 30, 0)
    t2 = datetime(2026, 9, 1, 13, 0, 0)
    seen = _obs(t0, equipment={"excavator": _machine(1, EntityVisibility.VISIBLE)})
    state = engine.update(None, seen)
    assert state.entities["excavator"].last_confirmed_value == 1

    hidden = _obs(
        t1,
        equipment={"excavator": _machine(None, EntityVisibility.OCCLUDED, confidence=0.1)},
        usable=False,
    )
    state = engine.update(state, hidden)
    assert state.entities["excavator"].last_confirmed_value == 1
    assert state.entities["excavator"].current_value is None
    assert state.entities["excavator"].freshness in {"historical", "stale"}

    late = _obs(t0 - timedelta(hours=1), equipment={"excavator": _machine(0, EntityVisibility.VISIBLE)})
    returned = engine.update(state, late)
    assert "out_of_order: newer fact left intact" in returned.change_notes
    assert state.entities["excavator"].last_confirmed_value == 1

    again = _obs(t2, equipment={"excavator": _machine(1, EntityVisibility.VISIBLE)})
    state = engine.update(state, again)
    assert state.entities["excavator"].last_confirmed_value == 1
    assert state.entities["excavator"].freshness == "fresh"


def test_other_camera_viewpoint_and_duplicate_do_not_merge():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 9, 2, 12, 0, 0)
    t1 = t0 + timedelta(minutes=30)
    first = _obs(
        t0,
        equipment={"excavator": _machine(2, EntityVisibility.VISIBLE)},
        viewpoint="front",
        version="1.1.0",
    )
    state = engine.update(None, first)
    other = engine.update(
        state,
        _obs(t1, equipment={"excavator": _machine(9, EntityVisibility.VISIBLE)}, camera="other"),
    )
    assert "different_camera: sequence not merged" in other.change_notes
    assert other.entities["excavator"].last_confirmed_value == 9

    turned = engine.update(
        state,
        _obs(
            t1,
            equipment={"excavator": _machine(9, EntityVisibility.VISIBLE)},
            viewpoint="side",
            version="1.1.0",
        ),
    )
    assert "viewpoint_changed: sequence not merged" in turned.change_notes

    duplicate = engine.update(state, _obs(t0, equipment={"excavator": _machine(0, EntityVisibility.VISIBLE)}, viewpoint="front", version="1.1.0"))
    assert duplicate.change_notes == ["same_timestamp: entities kept, derived facts replaced"]
    assert duplicate.entities["excavator"].last_confirmed_value == 2


def test_persistent_count_can_be_revised_after_a_repeated_reading():
    engine = TemporalStateEngine()
    t0 = datetime(2026, 9, 3, 12, 0, 0)

    def slabs(ts: datetime, count: int, confidence: float = 0.9) -> ObservedState:
        return _obs(
            ts,
            structures={
                "floor_slab": EntityObservation(
                    status=EntityVisibility.VISIBLE,
                    measurement=MeasurementType.LEVELS,
                    value=count,
                    count_visible=count,
                    confidence=confidence,
                )
            },
        )

    state = engine.update(None, slabs(t0, 5))
    assert state.entities["floor_slab"].last_confirmed_value == 5
    state = engine.update(state, slabs(t0 + timedelta(days=1), 3, confidence=0.9))
    assert state.entities["floor_slab"].last_confirmed_value == 5
    assert any("revision_candidate" in note for note in state.change_notes)
    state = engine.update(state, slabs(t0 + timedelta(days=2), 3, confidence=0.9))
    assert state.entities["floor_slab"].last_confirmed_value == 3


def test_clustered_frames_plus_a_gap_are_not_no_dynamics():
    engine = TemporalEngine()
    start = datetime(2026, 9, 1, 12, 0, 0)
    states = [
        _state(start.isoformat(), 4),
        _state((start + timedelta(minutes=30)).isoformat(), 4),
        _state((start + timedelta(minutes=60)).isoformat(), 4),
        _state((start + timedelta(days=14)).isoformat(), 4),
    ]
    from sitewatch.domain.contracts import ExpectedState

    series = [
        ExpectedState(date=item.timestamp.date(), object_id="s", zone_id="z", stage="superstructure", expected={"floors": n})
        for item, n in zip(states, [4, 4, 5, 6])
    ]
    assert engine.no_dynamics_signal(states, series) is None


def test_new_episode_is_not_the_same_fingerprint_and_decision_survives_new_evidence():
    early = _candidate(related_dates=["2026-09-01", "2026-09-22"])
    later_same = _candidate(related_dates=["2026-09-01", "2026-10-01"], expected={"dump_truck": 2, "schedule_progress": 3})
    # schedule_progress must not split one episode; a later start must.
    grown = _candidate(related_dates=["2026-09-01", "2026-09-29"])
    fresh = _candidate(related_dates=["2026-11-01", "2026-11-20"])
    assert candidate_fingerprint(early) == candidate_fingerprint(grown)
    assert candidate_fingerprint(early) == candidate_fingerprint(later_same)
    assert candidate_fingerprint(early) != candidate_fingerprint(fresh)

    init_db()
    ref = EvidenceRef(media_path="/tmp/a.jpg", timestamp=datetime(2026, 9, 18, 12, 0, 0), observation_id="obs-1")
    extra = EvidenceRef(media_path="/tmp/b.jpg", timestamp=datetime(2026, 9, 19, 12, 0, 0), observation_id="obs-2")
    with get_session() as session:
        alert_id, created = persist_candidate(
            session, project_id="p", zone_id="zone_b", candidate=_candidate(evidence=[ref])
        )
        assert created is True
        alert = session.get(Alert, alert_id)
        alert.status = "rejected"
        alert.decision_reason = "false_detection"
        session.flush()
        again_id, created_again = persist_candidate(
            session,
            project_id="p",
            zone_id="zone_b",
            candidate=_candidate(evidence=[ref, extra]),
        )
        assert created_again is False
        assert again_id == alert_id
        kept = session.get(Alert, alert_id)
        assert kept.status == "rejected"
        assert kept.decision_reason == "false_detection"
        session.flush()
        paths = {row.media_path for row in session.query(Evidence).filter_by(alert_id=alert_id)}
    assert paths == {"/tmp/a.jpg", "/tmp/b.jpg"}


def test_queue_cap_duplicate_and_stale_job():
    init_db()
    with get_session() as session:
        for index in range(4):
            session.add(
                FrameAnalysisJob(
                    status=JobStatus.QUEUED.value,
                    project_code="p",
                    zone_code="z",
                    camera_code="cam",
                    image_path=f"/tmp/queued-{index}.jpg",
                )
            )
        session.add(
            FrameAnalysisJob(
                status=JobStatus.COMPLETED.value,
                project_code="p",
                zone_code="z",
                camera_code="cam",
                image_path="/tmp/done.jpg",
            )
        )
        session.add(
            FrameAnalysisJob(
                status=JobStatus.PROCESSING.value,
                project_code="p",
                zone_code="z",
                camera_code="cam",
                image_path="/tmp/hung.jpg",
                created_at=datetime.utcnow() - timedelta(hours=5),
            )
        )
    assert recover_stale_jobs() == 1
    with get_session() as session:
        hung = session.query(FrameAnalysisJob).filter_by(image_path="/tmp/hung.jpg").one()
        assert hung.status == JobStatus.FAILED.value
        assert hung.error == "stale_running"
    same = enqueue_frame_analysis(
        image_path=__import__("pathlib").Path("/tmp/done.jpg"),
        project_code="p",
        zone_code="z",
        camera_code="cam",
    )
    with get_session() as session:
        done = session.query(FrameAnalysisJob).filter_by(image_path="/tmp/done.jpg").one()
        assert same == done.id
    try:
        enqueue_frame_analysis(
            image_path=__import__("pathlib").Path("/tmp/new.jpg"),
            project_code="p",
            zone_code="z",
            camera_code="cam",
        )
        raised = False
    except RuntimeError as exc:
        raised = "analysis_queue_full" in str(exc)
    assert raised is True


def test_run_manifest_records_checksum_without_claiming_model_quality(tmp_path):
    image = tmp_path / "frame.jpg"
    cv2.imwrite(str(image), np.zeros((64, 64, 3), dtype=np.uint8))
    root = tmp_path / "bench"
    case = root / "cases" / "blank"
    case.mkdir(parents=True)
    (case / "expected.json").write_text(
        '{"id":"blank","role":"dev","episode":"blank","camera_id":"cam","object_id":"site"}',
        encoding="utf-8",
    )
    import shutil

    shutil.copy(image, case / "image.jpg")
    summary = run_benchmark(root, out_dir=tmp_path / "out", mode=PerceptionMode.ANNOTATION)
    manifest = build_run_manifest(
        root=root,
        cases=[{"id": "blank", "image": str(case / "image.jpg"), "role": "dev", "episode": "blank"}],
        mode="annotation",
        summary=summary,
        out_dir=tmp_path / "out",
    )
    assert manifest["frames"][0]["sha256"]
    assert manifest["pipeline_version"]
    assert "annotation mode does not measure" in manifest["limitations"][0]
    assert (tmp_path / "out" / "run_manifest.json").is_file()
