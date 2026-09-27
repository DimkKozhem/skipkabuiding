"""Evidence fusion — explicit, testable rules. Qwen must not silently overwrite detectors."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sitewatch.domain.contracts import (
    EntityObservation,
    ImageQuality,
    ObservationNarrative,
    PerceptionEvidence,
)
from sitewatch.domain.enums import EntityVisibility, EvidenceSource, MeasurementType
from sitewatch.perception.ontology import (
    is_equipment,
    is_structure,
    measurement_for,
    perception_config,
    state_key_for,
    structure_keys,
)


_CONFIRM = {
    EntityVisibility.VISIBLE,
    EntityVisibility.PARTIALLY_VISIBLE,
}


class EvidenceFusionService:
    def __init__(self) -> None:
        cfg = perception_config().get("fusion") or {}
        self.count_agree_tol = int(cfg.get("count_agree_tol") or 0)
        self.min_confidence_confirm = float(cfg.get("min_confidence_confirm") or 0.55)
        self.disagreement_cap = float(cfg.get("disagreement_confidence_cap") or 0.45)
        self.prefer_detector_counts = bool(cfg.get("prefer_detector_counts", True))

    def fuse(
        self,
        *,
        quality: ImageQuality,
        evidence: list[PerceptionEvidence],
        vlm_structured: dict[str, Any] | None = None,
        detector_status: str = "not_run",
        vlm_status: str = "not_run",
    ) -> tuple[dict[str, EntityObservation], dict[str, EntityObservation], ObservationNarrative, dict[str, Any]]:
        by_label: dict[str, list[PerceptionEvidence]] = defaultdict(list)
        for item in evidence:
            by_label[item.normalized_label].append(item)

        vlm_by_label: dict[str, dict[str, Any]] = {}
        narrative = ObservationNarrative()
        scene: dict[str, Any] = {}
        if vlm_structured:
            summary = str(
                vlm_structured.get("professional_observation")
                or vlm_structured.get("summary")
                or ""
            )
            limitations = list(vlm_structured.get("limitations") or [])
            limitations.extend(vlm_structured.get("visibility_constraints") or [])
            narrative = ObservationNarrative(
                summary=summary,
                limitations=list(dict.fromkeys(limitations)),
                uncertainties=list(vlm_structured.get("uncertainties") or []),
            )
            for ent in vlm_structured.get("entities") or []:
                if isinstance(ent, dict) and ent.get("label"):
                    from sitewatch.perception.ontology import canonical_label

                    key = canonical_label(str(ent["label"])) or str(ent["label"])
                    vlm_by_label[key] = ent
            if vlm_structured.get("visible_floor_levels") is not None:
                scene["visible_floor_levels"] = vlm_structured.get("visible_floor_levels")
            if vlm_structured.get("foundation_visible") is not None:
                scene["foundation_visible"] = vlm_structured.get("foundation_visible")
            if vlm_structured.get("scene_type"):
                scene["scene_type"] = vlm_structured.get("scene_type")
            if vlm_structured.get("spatial_relations"):
                scene["spatial_relations"] = vlm_structured.get("spatial_relations")

        structures: dict[str, EntityObservation] = {}
        equipment: dict[str, EntityObservation] = {}

        # Unmentioned classes stay absent. A missing key is unknown, not a confirmed zero.
        labels = set(by_label.keys()) | set(vlm_by_label.keys())
        for label in sorted(labels):
            obs = self._fuse_label(
                label,
                by_label.get(label, []),
                vlm_by_label.get(label),
                quality=quality,
                detector_status=detector_status,
                vlm_status=vlm_status,
            )
            if is_equipment(label):
                equipment[label] = obs
            elif is_structure(label) or label in structure_keys():
                structures[label] = obs
            else:
                structures[label] = obs

        if not quality.usable:
            narrative.limitations = list(
                dict.fromkeys([*narrative.limitations, "frame_quality_unusable", *quality.issues])
            )
        if detector_status == "failed":
            narrative.limitations = list(dict.fromkeys([*narrative.limitations, "component_failed:detector"]))
        if vlm_status == "failed":
            narrative.limitations = list(dict.fromkeys([*narrative.limitations, "component_failed:vlm"]))

        return structures, equipment, narrative, scene

    def _fuse_label(
        self,
        label: str,
        items: list[PerceptionEvidence],
        vlm: dict[str, Any] | None,
        *,
        quality: ImageQuality,
        detector_status: str = "not_run",
        vlm_status: str = "not_run",
    ) -> EntityObservation:
        measurement = measurement_for(label)
        sam = [e for e in items if e.source == EvidenceSource.SAM3]
        dino = [e for e in items if e.source == EvidenceSource.GROUNDING_DINO]
        ann = [e for e in items if e.source == EvidenceSource.ANNOTATION]
        qwen = [e for e in items if e.source == EvidenceSource.QWEN_VL]
        box_detectors = [e for e in items if e.bbox is not None and e.source != EvidenceSource.QWEN_VL]

        sam_count = len(sam) if sam else None
        dino_count = len(dino) if dino else None
        ann_count = len(ann) if ann else None
        detector_count = ann_count if ann_count is not None else sam_count
        if detector_count is None:
            detector_count = dino_count

        disagreement = False
        if sam_count is not None and dino_count is not None:
            if abs(sam_count - dino_count) > self.count_agree_tol:
                disagreement = True

        vlm_visibility = None
        vlm_count = None
        vlm_ratio = None
        vlm_conf = 0.0
        if vlm:
            try:
                vlm_visibility = EntityVisibility(str(vlm.get("status")))
            except ValueError:
                vlm_visibility = EntityVisibility.UNCERTAIN
            raw_count = vlm.get("count_visible")
            vlm_count = int(raw_count) if isinstance(raw_count, (int, float)) and raw_count is not None else None
            vlm_ratio = vlm.get("visible_ratio")
            vlm_conf = float(vlm.get("confidence") or 0.0)

        # Detector vs VLM disagreement
        if detector_count is not None and vlm_count is not None:
            if abs(detector_count - vlm_count) > self.count_agree_tol:
                disagreement = True

        det_scores = [e.score for e in box_detectors]
        if det_scores:
            confidence = max(det_scores)
        elif qwen or vlm:
            confidence = min(vlm_conf or max((e.score for e in qwen), default=0.0), self.min_confidence_confirm)
        else:
            confidence = 0.0
        if disagreement:
            confidence = min(confidence, self.disagreement_cap)

        notes: list[str] = []
        localized = bool(box_detectors)
        vlm_only = (not localized) and bool(qwen or vlm)
        count_visible: int | None = None
        if localized and self.prefer_detector_counts and detector_count is not None:
            count_visible = detector_count
            if vlm_count is not None and vlm_count != detector_count:
                notes.append(f"vlm_count_ignored:{vlm_count}")
        elif localized and detector_count is not None:
            count_visible = detector_count
        # A text count without a box is context, not a detection.

        if detector_status == "failed":
            agreement = "component_failed"
        elif vlm_only and vlm_status == "failed":
            agreement = "component_failed"
        elif not quality.usable and not localized:
            agreement = "insufficient"
        elif disagreement:
            agreement = "conflict"
        elif localized and vlm_count is not None:
            agreement = "consensus"
        elif localized:
            agreement = "detector_only"
        elif vlm_only:
            agreement = "vlm_only"
        else:
            agreement = "insufficient"
        notes.append(f"agreement:{agreement}")

        if agreement == "component_failed":
            status = EntityVisibility.UNCERTAIN
            count_visible = None
            notes.append("component_failed")
        elif agreement == "conflict":
            status = EntityVisibility.UNCERTAIN
            notes.append("detector_count_disagreement")
            if detector_count is not None and vlm_count is not None and abs(detector_count - vlm_count) > 1:
                notes.append("count_disagreement_uncertain")
        elif agreement == "vlm_only":
            status = EntityVisibility.UNCERTAIN
            count_visible = None
            notes.append("vlm_only_not_a_detection")
            confidence = min(confidence, max(0.0, self.min_confidence_confirm - 0.01))
        elif not quality.usable:
            status = EntityVisibility.NOT_VISIBLE
            count_visible = None
            notes.append("not_visible")
        elif localized and count_visible and count_visible > 0:
            status = EntityVisibility.VISIBLE
        elif localized and count_visible == 0:
            # Detector ran and returned no box for this mentioned label.
            status = EntityVisibility.NOT_VISIBLE
            notes.append("not_detected")
            count_visible = None
        elif vlm_visibility == EntityVisibility.OCCLUDED:
            status = EntityVisibility.OCCLUDED
            notes.append("not_visible")
        elif vlm_visibility == EntityVisibility.OUTSIDE_VIEW:
            status = EntityVisibility.OUTSIDE_VIEW
            notes.append("not_visible")
        else:
            status = EntityVisibility.UNCERTAIN
            notes.append("not_detected")

        if disagreement and "detector_count_disagreement" not in notes:
            notes.append("detector_count_disagreement")
        if not quality.usable:
            notes.append("quality_degraded")

        value: float | int | bool | None = None
        visible_ratio = float(vlm_ratio) if vlm_ratio is not None else None
        if measurement == MeasurementType.COUNT:
            value = count_visible
        elif measurement == MeasurementType.LEVELS:
            value = count_visible
        elif measurement == MeasurementType.PRESENCE:
            if status in _CONFIRM and localized:
                value = True
                count_visible = int(count_visible or 1)
            else:
                value = None
        elif measurement in {MeasurementType.AREA, MeasurementType.AREA_OR_PRESENCE}:
            if visible_ratio is not None and localized:
                value = visible_ratio
            elif status in _CONFIRM and localized:
                value = 1.0
            else:
                value = None
        else:
            value = count_visible

        evidence_ids = [e.evidence_id for e in items]
        if qwen:
            evidence_ids.extend(e.evidence_id for e in qwen if e.evidence_id not in evidence_ids)

        _ = state_key_for(label)

        return EntityObservation(
            status=status,
            measurement=measurement,
            value=value,
            count_visible=count_visible,
            visible_ratio=visible_ratio,
            confidence=round(float(confidence), 4),
            evidence_ids=evidence_ids,
            notes=notes,
        )
