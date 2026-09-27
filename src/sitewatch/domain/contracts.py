from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from sitewatch.domain.enums import (
    AlertType,
    CheckOutcome,
    CoverageLevel,
    EntityNature,
    EntityVisibility,
    EvidenceSource,
    IndicatorKind,
    JobStatus,
    MeasurementType,
    ObservationCoverage,
    Severity,
    SourceType,
    StageStatus,
    StateChangeKind,
    Visibility,
    WorkCertainty,
)


class BBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float

    def as_xyxy(self) -> list[float]:
        return [self.x1, self.y1, self.x2, self.y2]


class Detection(BaseModel):
    class_name: str
    bbox: BBox
    confidence: float
    track_id: int | None = None
    mask_path: str | None = None
    model_name: str
    model_version: str = "n/a"
    extra: dict[str, Any] = Field(default_factory=dict)


class MediaRef(BaseModel):
    path: str
    timestamp: datetime
    camera_code: str
    source_type: SourceType = SourceType.PHOTO
    gps_lat: float | None = None
    gps_lon: float | None = None
    orientation: str | None = None


class ObservationQuality(BaseModel):
    visibility: Visibility = Visibility.GOOD
    coverage: CoverageLevel = CoverageLevel.FULL
    n_frames: int = 1
    mean_model_confidence: float = 0.0
    evidence_confidence: float = 0.0
    notes: list[str] = Field(default_factory=list)
    window_start: datetime | None = None
    window_end: datetime | None = None


class CountStat(BaseModel):
    count: int = 0
    max_confidence: float = 0.0


class PresenceStat(BaseModel):
    detected: bool = False
    count: int = 0
    max_confidence: float = 0.0


class ImageQuality(BaseModel):
    usable: bool = True
    visibility: float = 1.0
    coverage: float = 1.0
    blur: float = 0.0
    exposure: float = 0.5
    darkness: float = 0.0
    resolution: tuple[int, int] = (0, 0)
    issues: list[str] = Field(default_factory=list)


class PerceptionEvidence(BaseModel):
    """Raw model evidence for an observation. Origin must remain auditable.

    Extension point: future HumanCorrection can reference evidence_id without
    rewriting ObservedState schema (TODO: HumanCorrection workflow — not in MVP).
    """

    evidence_id: str
    source: EvidenceSource
    model: str
    model_version: str = "n/a"
    class_name: str
    bbox: BBox | None = None
    mask_reference: str | None = None
    score: float = 0.0
    raw_label: str | None = None
    normalized_label: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntityObservation(BaseModel):
    status: EntityVisibility = EntityVisibility.NOT_VISIBLE
    measurement: MeasurementType = MeasurementType.COUNT
    # count / levels / presence / area ratio depending on measurement
    value: float | int | bool | None = None
    count_visible: int | None = None
    visible_ratio: float | None = None
    confidence: float = 0.0
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ObservationNarrative(BaseModel):
    summary: str = ""
    limitations: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class PipelineStageResult(BaseModel):
    name: str
    status: StageStatus = StageStatus.PENDING
    latency_ms: float | None = None
    error: str | None = None
    model: str | None = None
    model_version: str | None = None
    device: str | None = None
    extras: dict[str, Any] = Field(default_factory=dict)


class PipelineRun(BaseModel):
    run_id: str
    frame_id: str | None = None
    object_id: str
    zone_id: str
    camera_id: str | None = None
    pipeline_version: str = "workfact-1"
    ontology_version: str = "1.0"
    prompt_version: str = "1.0"
    started_at: datetime
    finished_at: datetime | None = None
    processed_at: datetime | None = None
    total_latency_ms: float | None = None
    stages: list[PipelineStageResult] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    device: str | None = None
    outcome: str = "succeeded"  # PipelineRunOutcome value; kept str for JSON compat


class ObservedState(BaseModel):
    """Frame-level perception contract. Never contains plan/KSG conclusions."""

    frame_id: str
    object_id: str
    zone_id: str
    camera_id: str | None = None
    captured_at: datetime
    quality: ImageQuality = Field(default_factory=ImageQuality)
    structures: dict[str, EntityObservation] = Field(default_factory=dict)
    equipment: dict[str, EntityObservation] = Field(default_factory=dict)
    observation: ObservationNarrative = Field(default_factory=ObservationNarrative)
    evidence: list[PerceptionEvidence] = Field(default_factory=list)
    pipeline_run: PipelineRun | None = None
    scene_attributes: dict[str, Any] = Field(default_factory=dict)
    # visible_floor_levels is derived; total_floor_count may be null
    visible_floor_levels: int | None = None
    total_floor_count: int | None = None


class EntityHistoryEntry(BaseModel):
    at: datetime
    visibility: EntityVisibility
    value: float | int | bool | None = None
    confidence: float = 0.0
    note: str = ""


class EntityActualFact(BaseModel):
    measurement: MeasurementType = MeasurementType.COUNT
    nature: EntityNature = EntityNature.PERSISTENT
    last_confirmed_value: float | int | bool | None = None
    last_confirmed_at: datetime | None = None
    current_visibility: EntityVisibility = EntityVisibility.UNCERTAIN
    current_confidence: float = 0.0
    current_value: float | int | bool | None = None
    # fresh = this frame confirmed it; historical = carried; stale = too old or reprocessed
    freshness: str = "unknown"
    history: list[EntityHistoryEntry] = Field(default_factory=list)


class WorkFact(BaseModel):
    """Fact about one work indicator. Certainty ≠ work completed."""

    work_code: str
    indicator_id: str
    kind: IndicatorKind
    part: str = "target"
    certainty: WorkCertainty = WorkCertainty.UNKNOWN
    value: float | int | bool | None = None
    unit: str | None = None
    coverage: ObservationCoverage = ObservationCoverage.UNKNOWN
    captured_at: datetime
    processed_at: datetime | None = None
    as_of: date | None = None
    method: str = ""
    method_version: str = "1"
    pipeline_version: str = "workfact-1"
    evidence_ids: list[str] = Field(default_factory=list)
    work_zone: list[list[float]] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    confirms: str = ""  # what this indicator confirms (not whole stage)


class PlannedIndicator(BaseModel):
    """Normalized plan metric bound to one KSG schedule row."""

    schedule_row_id: str
    work_code: str
    indicator_id: str
    kind: IndicatorKind
    unit: str | None = None
    value: float | int | bool | None = None
    confirms: str = ""
    stage: str | None = None
    stage_label: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class IndicatorCheckResult(BaseModel):
    outcome: CheckOutcome
    planned: PlannedIndicator | None = None
    fact: WorkFact | None = None
    title: str = ""
    rationale: str = ""
    rule_id: str = ""
    evaluation_as_of: date | None = None


class ActualState(BaseModel):
    """Cumulative object state. work_facts are the plan/fact source of truth.

    elements/equipment remain legacy projections for older UI paths.
    """

    object_id: str
    zone_id: str
    timestamp: datetime
    camera_code: str | None = None
    elements: dict[str, CountStat | PresenceStat] = Field(default_factory=dict)
    equipment: dict[str, CountStat] = Field(default_factory=dict)
    quality: ObservationQuality = Field(default_factory=ObservationQuality)
    scene_attributes: dict[str, Any] = Field(default_factory=dict)
    entities: dict[str, EntityActualFact] = Field(default_factory=dict)
    work_facts: dict[str, WorkFact] = Field(default_factory=dict)  # keyed by indicator_id
    pipeline_run_id: str | None = None
    observed_state_id: str | None = None
    change_notes: list[str] = Field(default_factory=list)
    processed_at: datetime | None = None

    def element_count(self, key: str) -> int:
        stat = self.elements.get(key)
        raw = int(stat.count) if stat is not None else 0
        if key == "floors" and raw <= 0:
            levels = self.scene_attributes.get("structural_levels")
            if levels is not None:
                return int(levels)
        if stat is None:
            return 0
        return raw

    def element_present(self, key: str) -> bool:
        stat = self.elements.get(key)
        if stat is None:
            return False
        if isinstance(stat, PresenceStat):
            return stat.detected
        return stat.count > 0

    def equipment_count(self, key: str) -> int:
        stat = self.equipment.get(key)
        return 0 if stat is None else int(stat.count)

    def equipment_counts(self) -> dict[str, int]:
        return {name: stat.count for name, stat in self.equipment.items()}

    def construction(self) -> dict[str, Any]:
        """Aggregated structural view (not a detector dump)."""
        out: dict[str, Any] = {}
        for key, stat in self.elements.items():
            if isinstance(stat, PresenceStat):
                out[key] = stat.detected
            else:
                out[key] = int(stat.count)
        levels = self.scene_attributes.get("structural_levels")
        if levels is not None:
            out.setdefault("structural_levels", levels)
        return out


class ExpectedState(BaseModel):
    date: date
    object_id: str
    zone_id: str
    stage: str
    stage_label: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    expected: dict[str, Any] = Field(default_factory=dict)
    required_equipment: list[dict[str, Any]] = Field(default_factory=list)
    unexpected_equipment: list[str] = Field(default_factory=list)
    schedule_row_id: str | None = None
    planned_indicators: list[PlannedIndicator] = Field(default_factory=list)


class StateChangeAnalysis(BaseModel):
    """CV-agnostic temporal comparison of two ActualState snapshots."""

    changed: bool
    change_score: float = 0.0
    changed_elements: list[str] = Field(default_factory=list)
    stable_elements: list[str] = Field(default_factory=list)
    changed_equipment: list[str] = Field(default_factory=list)
    kind: StateChangeKind = StateChangeKind.UNKNOWN
    comparable: bool = False
    same_camera: bool = False
    visual_change: float | None = None
    notes: list[str] = Field(default_factory=list)


class StateTransition(BaseModel):
    from_timestamp: datetime
    to_timestamp: datetime
    period_days: float
    change_kind: StateChangeKind = StateChangeKind.UNKNOWN
    element_deltas: dict[str, int] = Field(default_factory=dict)
    equipment_deltas: dict[str, int] = Field(default_factory=dict)
    relative_change: float = 0.0
    visual_change: float | None = None
    same_camera: bool = False
    comparable: bool = False
    changed: bool = False
    change_score: float = 0.0
    changed_elements: list[str] = Field(default_factory=list)
    stable_elements: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class EvidenceRef(BaseModel):
    media_path: str
    timestamp: datetime
    observation_id: str | None = None
    media_id: str | None = None
    detection_ids: list[str] = Field(default_factory=list)
    viz_path: str | None = None
    camera_code: str | None = None


class DeviationCandidate(BaseModel):
    alert_type: AlertType
    severity: Severity
    zone_id: str
    object_id: str
    stage: str | None = None
    stage_label: str | None = None
    title: str
    message: str = ""
    rationale: str
    expected: dict[str, Any] = Field(default_factory=dict)
    observed: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    rule_id: str
    model_confidence: float | None = None
    evidence_confidence: float | None = None
    rule_confidence: float | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)
    related_dates: list[str] = Field(default_factory=list)


class AlertDraft(BaseModel):
    deviation: DeviationCandidate
    message: str


class FrameAnalysisJobInfo(BaseModel):
    job_id: str
    status: JobStatus = JobStatus.QUEUED
    project_code: str
    zone_code: str
    camera_code: str
    image_path: str
    error: str | None = None
    observed_state_id: str | None = None
    actual_state_id: str | None = None
    pipeline_run_id: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


class HumanCorrection(BaseModel):
    """Extension point only — not implemented in MVP.

    Future: engineer corrects ObservedState/Evidence → training dataset.
    """

    correction_id: str | None = None
    target_evidence_id: str | None = None
    note: str = ""
