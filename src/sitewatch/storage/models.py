from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uid() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    address: Mapped[str] = mapped_column(String(512), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    zones: Mapped[list[Zone]] = relationship(back_populates="project")


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(256))
    description: Mapped[str] = mapped_column(Text, default="")
    construction_type_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    project: Mapped[Project] = relationship(back_populates="zones")
    cameras: Mapped[list[Camera]] = relationship(back_populates="zone")
    notes: Mapped[list["ZoneNote"]] = relationship(back_populates="zone")


class ZoneNote(Base):
    __tablename__ = "zone_notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    body: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    zone: Mapped[Zone] = relationship(back_populates="notes")


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(256))
    location: Mapped[str] = mapped_column(String(256), default="")
    orientation: Mapped[str] = mapped_column(String(128), default="")
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), default="photo")
    uri: Mapped[str] = mapped_column(String(1024), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    last_captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str] = mapped_column(Text, default="")

    zone: Mapped[Zone] = relationship(back_populates="cameras")


class ScheduleStage(Base):
    __tablename__ = "schedule_stages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    date: Mapped[date] = mapped_column(Date)  # alias of start_date for legacy queries
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    stage: Mapped[str] = mapped_column(String(64))
    stage_label: Mapped[str] = mapped_column(String(256), default="")
    expected_json: Mapped[str] = mapped_column(Text, default="{}")


class ExpectedStateRecord(Base):
    __tablename__ = "expected_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    date: Mapped[date] = mapped_column(Date)
    stage: Mapped[str] = mapped_column(String(64))
    payload_json: Mapped[str] = mapped_column(Text)


class MediaAsset(Base):
    __tablename__ = "media_assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    path: Mapped[str] = mapped_column(String(1024))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    source_type: Mapped[str] = mapped_column(String(32), default="photo")
    gps_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    gps_lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    meta_json: Mapped[str] = mapped_column(Text, default="{}")


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    camera_id: Mapped[str] = mapped_column(ForeignKey("cameras.id"))
    media_id: Mapped[str] = mapped_column(ForeignKey("media_assets.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    source: Mapped[str] = mapped_column(String(64), default="photo")
    quality_json: Mapped[str] = mapped_column(Text, default="{}")
    prediction_path: Mapped[str] = mapped_column(String(1024), default="")
    viz_path: Mapped[str] = mapped_column(String(1024), default="")

    detections: Mapped[list[DetectionRecord]] = relationship(back_populates="observation")
    actual_state: Mapped[ActualStateRecord | None] = relationship(back_populates="observation")


class DetectionRecord(Base):
    __tablename__ = "detections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"))
    class_name: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float)
    x1: Mapped[float] = mapped_column(Float)
    y1: Mapped[float] = mapped_column(Float)
    x2: Mapped[float] = mapped_column(Float)
    y2: Mapped[float] = mapped_column(Float)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mask_path: Mapped[str] = mapped_column(String(1024), default="")
    model_name: Mapped[str] = mapped_column(String(64))
    model_version: Mapped[str] = mapped_column(String(64), default="n/a")

    observation: Mapped[Observation] = relationship(back_populates="detections")


class ActualStateRecord(Base):
    __tablename__ = "actual_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    payload_json: Mapped[str] = mapped_column(Text)

    observation: Mapped[Observation] = relationship(back_populates="actual_state")


class StateTransitionRecord(Base):
    __tablename__ = "state_transitions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    from_state_id: Mapped[str] = mapped_column(ForeignKey("actual_states.id"))
    to_state_id: Mapped[str] = mapped_column(ForeignKey("actual_states.id"))
    payload_json: Mapped[str] = mapped_column(Text)


class DeviationRecord(Base):
    __tablename__ = "deviations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    alert_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    payload_json: Mapped[str] = mapped_column(Text)

    alerts: Mapped[list[Alert]] = relationship(back_populates="deviation")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    deviation_id: Mapped[str] = mapped_column(ForeignKey("deviations.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    alert_type: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), default="open")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    fingerprint: Mapped[str] = mapped_column(String(64), default="")
    decision_reason: Mapped[str] = mapped_column(String(64), default="")
    decision_note: Mapped[str] = mapped_column(Text, default="")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    decided_by: Mapped[str] = mapped_column(String(128), default="")

    deviation: Mapped[DeviationRecord] = relationship(back_populates="alerts")
    evidence: Mapped[list["Evidence"]] = relationship(back_populates="alert")
    events: Mapped[list["AlertEvent"]] = relationship(back_populates="alert")


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"))
    action: Mapped[str] = mapped_column(String(32))
    from_status: Mapped[str] = mapped_column(String(32), default="")
    to_status: Mapped[str] = mapped_column(String(32), default="")
    reason: Mapped[str] = mapped_column(String(64), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(128), default="inspector")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    alert: Mapped[Alert] = relationship(back_populates="events")


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"))
    media_id: Mapped[str | None] = mapped_column(ForeignKey("media_assets.id"), nullable=True)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("observations.id"), nullable=True)
    media_path: Mapped[str] = mapped_column(String(1024), default="")
    viz_path: Mapped[str] = mapped_column(String(1024), default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str] = mapped_column(Text, default="")

    alert: Mapped[Alert] = relationship(back_populates="evidence")


class PipelineRunRecord(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    observation_id: Mapped[str | None] = mapped_column(ForeignKey("observations.id"), nullable=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    camera_code: Mapped[str] = mapped_column(String(64), default="")
    pipeline_version: Mapped[str] = mapped_column(String(32), default="")
    ontology_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_version: Mapped[str] = mapped_column(String(32), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    errors_json: Mapped[str] = mapped_column(Text, default="[]")


class ObservedStateRecord(Base):
    __tablename__ = "observed_states"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"))
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"))
    zone_id: Mapped[str] = mapped_column(ForeignKey("zones.id"))
    pipeline_run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime)
    payload_json: Mapped[str] = mapped_column(Text)


class EvidenceArtifactRecord(Base):
    __tablename__ = "evidence_artifacts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    observation_id: Mapped[str] = mapped_column(ForeignKey("observations.id"))
    pipeline_run_id: Mapped[str | None] = mapped_column(ForeignKey("pipeline_runs.id"), nullable=True)
    evidence_id: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(64), default="")
    class_name: Mapped[str] = mapped_column(String(64), default="")
    path: Mapped[str] = mapped_column(String(1024), default="")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class FrameAnalysisJob(Base):
    __tablename__ = "frame_analysis_jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    project_code: Mapped[str] = mapped_column(String(64))
    zone_code: Mapped[str] = mapped_column(String(64))
    camera_code: Mapped[str] = mapped_column(String(64))
    image_path: Mapped[str] = mapped_column(String(1024))
    capture_origin: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    observed_state_id: Mapped[str] = mapped_column(String(32), default="")
    actual_state_id: Mapped[str] = mapped_column(String(32), default="")
    pipeline_run_id: Mapped[str] = mapped_column(String(32), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ShadowCandidateReview(Base):
    """Точечная проверка предложения модели. Не факт и не полная разметка кадра."""

    __tablename__ = "shadow_candidate_reviews"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alerts.id"))
    observation_id: Mapped[str] = mapped_column(String(32), default="")
    source: Mapped[str] = mapped_column(String(64), default="")
    verdict: Mapped[str] = mapped_column(String(32))
    wrong_type: Mapped[str] = mapped_column(String(128), default="")
    missed_object: Mapped[str] = mapped_column(String(256), default="")
    completeness: Mapped[str] = mapped_column(String(32), default="spot_check")
    actor: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
