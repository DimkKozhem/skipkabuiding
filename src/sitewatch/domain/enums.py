from __future__ import annotations

from enum import Enum


class SourceType(str, Enum):
    PHOTO = "photo"
    VIDEO = "video"
    PANO_360 = "360"
    UAV = "uav"


class Visibility(str, Enum):
    GOOD = "good"
    DEGRADED = "degraded"
    POOR = "poor"


class CoverageLevel(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    UNKNOWN = "unknown"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(str, Enum):
    MISSING_ELEMENT = "missing_element"
    MISSING_EQUIPMENT = "missing_equipment"
    UNEXPECTED_EQUIPMENT = "unexpected_equipment"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    SCHEDULE_DELAY = "schedule_delay"
    NO_DYNAMICS = "no_dynamics"
    INCOMPARABLE = "incomparable"
    MEASUREMENT_UNIMPLEMENTED = "measurement_unimplemented"
    NEEDS_CAPTURE_OR_CALIBRATION = "needs_capture_or_calibration"
    NO_OBSERVATION_AFTER = "no_observation_after"
    # Proposed boxes from a shadow model. Not a plan/fact deviation.
    MODEL_CANDIDATE = "model_candidate"


class WorkCertainty(str, Enum):
    """How trustworthy the observation is. Not «work completed»."""

    CONFIRMED = "confirmed"
    UNKNOWN = "unknown"
    CONTRADICTION = "contradiction"
    NOT_OBSERVABLE = "not_observable"
    MEASUREMENT_UNIMPLEMENTED = "measurement_unimplemented"
    PROCESSING_ERROR = "processing_error"


class IndicatorKind(str, Enum):
    PRESENCE = "presence"
    COUNT = "count"
    STAGE_SIGN = "stage_sign"
    COVERAGE = "coverage"
    LENGTH_M = "length_m"
    RESOURCE_COUNT = "resource_count"


class CheckOutcome(str, Enum):
    MATCH = "match"
    DEVIATION = "deviation"
    INSUFFICIENT_DATA = "insufficient_data"
    INCOMPARABLE = "incomparable"
    MEASUREMENT_UNIMPLEMENTED = "measurement_unimplemented"
    NEEDS_CAPTURE_OR_CALIBRATION = "needs_capture_or_calibration"
    NO_OBSERVATION_AFTER = "no_observation_after"


class PipelineRunOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


class ObservationCoverage(str, Enum):
    FULL = "full"
    PARTIAL = "partial"
    TARGET_NOT_IN_FRAME = "target_not_in_frame"
    UNKNOWN = "unknown"


class StateChangeKind(str, Enum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    UNKNOWN = "unknown"


class AlertStatus(str, Enum):
    OPEN = "open"
    NEEDS_MORE_DATA = "needs_more_data"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class DetectorName(str, Enum):
    ANNOTATION = "annotation"
    YOLO26M = "yolo26m"
    YOLO26M_SEG = "yolo26m-seg"
    HYBRID = "hybrid"


class EntityVisibility(str, Enum):
    """Per-entity visibility on a frame. not_visible ≠ absent."""

    VISIBLE = "visible"
    PARTIALLY_VISIBLE = "partially_visible"
    NOT_VISIBLE = "not_visible"
    OCCLUDED = "occluded"
    OUTSIDE_VIEW = "outside_view"
    UNCERTAIN = "uncertain"


class MeasurementType(str, Enum):
    COUNT = "count"
    LEVELS = "levels"
    AREA = "area"
    AREA_OR_PRESENCE = "area_or_presence"
    PRESENCE = "presence"


class EntityNature(str, Enum):
    PERSISTENT = "persistent"
    TRANSIENT = "transient"


class EvidenceSource(str, Enum):
    SAM3 = "sam3"
    GROUNDING_DINO = "grounding_dino"
    QWEN_VL = "qwen_vl"
    FUSION = "fusion"
    QUALITY = "quality"
    ANNOTATION = "annotation"
    YOLOE_26L = "yoloe_26l"


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    EMPTY_SUCCESS = "empty_success"  # model ran; no objects of the requested class
    INVALID_RESPONSE = "invalid_response"


class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class PerceptionMode(str, Enum):
    ANNOTATION = "annotation"
    FULL = "full"  # alias of real (legacy)
    REAL = "real"
