"""TemporalStateEngine: ObservedState + previous ActualState → cumulative ActualState."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime

from sitewatch.domain.contracts import (
    ActualState,
    EntityActualFact,
    EntityHistoryEntry,
    ObservedState,
    WorkFact,
)
from sitewatch.domain.enums import EntityNature, EntityVisibility, WorkCertainty
from sitewatch.perception.ontology import nature_for, perception_config
from sitewatch.perception.project import observed_to_frame_actual, sync_legacy_projection


_CONFIRM_VIS = {
    EntityVisibility.VISIBLE,
    EntityVisibility.PARTIALLY_VISIBLE,
}


class TemporalStateEngine:
    def __init__(self) -> None:
        cfg = perception_config().get("temporal") or {}
        self.confirm_min_confidence = float(cfg.get("confirm_min_confidence") or 0.55)
        self.revision_min_confidence = float(cfg.get("revision_min_confidence") or 0.75)
        self.stale_after_hours = float(cfg.get("stale_after_hours") or 48)
        raw = cfg.get("confirm_visibilities") or ["visible", "partially_visible"]
        self.confirm_visibilities = {EntityVisibility(v) for v in raw}

    def update(
        self,
        previous: ActualState | None,
        observed: ObservedState,
    ) -> ActualState:
        frame = observed_to_frame_actual(observed)
        version = observed.pipeline_run.pipeline_version if observed.pipeline_run else None
        if version:
            frame.scene_attributes["perception_version"] = version
        if previous is None:
            return sync_legacy_projection(frame)

        if previous.camera_code and observed.camera_id and previous.camera_code != observed.camera_id:
            frame.change_notes.append("different_camera: sequence not merged")
            return sync_legacy_projection(frame)

        prev_view = _viewpoint(previous.scene_attributes)
        curr_view = _viewpoint(observed.scene_attributes)
        if prev_view and curr_view and prev_view != curr_view:
            frame.change_notes.append("viewpoint_changed: sequence not merged")
            return sync_legacy_projection(frame)

        prev_version = (previous.scene_attributes or {}).get("perception_version")
        version_changed = bool(prev_version and version and prev_version != version)
        if observed.captured_at == previous.timestamp and not version_changed:
            # Same photo, same perception version: keep confirmed entities.
            # Derived WorkFacts and floor scene come from this observation,
            # so a new interpretation is not discarded as a duplicate.
            kept = previous.model_copy(deep=True)
            if frame.work_facts:
                kept.work_facts = {
                    key: fact.model_copy(deep=True) for key, fact in frame.work_facts.items()
                }
            incoming = frame.scene_attributes or {}
            scene = dict(kept.scene_attributes or {})
            for key in (
                "visible_floor_levels",
                "floors_status",
                "floors_derivation",
                "floor_bands",
                "floor_bands_overlay",
                "floor_bands_crop",
                "floor_bands_unambiguous",
                "floor_bands_proposed",
                "floors_prove_reasons",
                "artifact_paths",
            ):
                if key in incoming:
                    scene[key] = incoming[key]
            if incoming.get("floors_status") != "proven":
                scene.pop("structural_levels", None)
            if "visible_floor_levels" not in incoming:
                scene.pop("visible_floor_levels", None)
            kept.scene_attributes = scene
            kept.pipeline_run_id = frame.pipeline_run_id
            kept.change_notes = ["same_timestamp: entities kept, derived facts replaced"]
            return sync_legacy_projection(kept)
        if previous.timestamp and observed.captured_at < previous.timestamp:
            frame.change_notes.append("out_of_order: newer fact left intact")
            return sync_legacy_projection(frame)

        stale_gap = _hours_between(previous.timestamp, observed.captured_at) > self.stale_after_hours

        merged = previous.model_copy(deep=True)
        merged.timestamp = observed.captured_at
        merged.camera_code = observed.camera_id or previous.camera_code
        merged.pipeline_run_id = frame.pipeline_run_id
        merged.change_notes = []

        # merge quality notes
        merged.quality = frame.quality
        scene = dict(previous.scene_attributes)
        frame_scene = dict(frame.scene_attributes or {})
        # structural_levels / visible_floor_levels — отдельно ниже (proven vs proposed).
        frame_scene.pop("structural_levels", None)
        frame_scene.pop("visible_floor_levels", None)
        frame_scene.pop("floors_status", None)
        scene.update(frame_scene)
        merged.scene_attributes = scene

        entities = deepcopy(previous.entities) if previous.entities else {}
        frame_entities = frame.entities or {}

        for label, new_fact in frame_entities.items():
            old = entities.get(label)
            nature = nature_for(label) if label else new_fact.nature
            if old is None:
                entities[label] = new_fact
                if new_fact.last_confirmed_value not in (None, 0, False):
                    merged.change_notes.append(f"{label}: appeared={new_fact.current_value}")
                elif new_fact.current_value not in (None, 0, False):
                    merged.change_notes.append(f"{label}: seen_unconfirmed={new_fact.current_value}")
                continue

            updated = old.model_copy(deep=True)
            updated.current_visibility = new_fact.current_visibility
            updated.current_confidence = new_fact.current_confidence
            updated.current_value = new_fact.current_value
            updated.measurement = new_fact.measurement
            updated.nature = nature

            confirmable = (
                new_fact.current_visibility in self.confirm_visibilities
                and new_fact.current_confidence >= self.confirm_min_confidence
                and observed.quality.usable
            )

            if nature == EntityNature.PERSISTENT:
                if confirmable and new_fact.current_value is not None:
                    prev_val = updated.last_confirmed_value
                    allow = self._should_update_confirmed(
                        prev_val,
                        new_fact.current_value,
                        new_fact.measurement.value,
                    )
                    repeated_lower = self._repeated_lower(
                        updated.history,
                        new_fact.current_value,
                        new_fact.measurement.value,
                    )
                    if allow or version_changed or repeated_lower:
                        if prev_val != new_fact.current_value:
                            merged.change_notes.append(
                                f"{label}: {prev_val} → {new_fact.current_value}"
                            )
                        updated.last_confirmed_value = new_fact.current_value
                        updated.last_confirmed_at = observed.captured_at
                        updated.freshness = "fresh"
                    else:
                        merged.change_notes.append(f"{label}: revision_candidate={new_fact.current_value}")
                        updated.freshness = "historical"
                elif new_fact.current_visibility in {
                    EntityVisibility.NOT_VISIBLE,
                    EntityVisibility.OCCLUDED,
                    EntityVisibility.OUTSIDE_VIEW,
                    EntityVisibility.UNCERTAIN,
                }:
                    updated.freshness = "stale" if stale_gap else "historical"
            else:
                prev_cur = old.current_value
                if confirmable and new_fact.current_value is not None:
                    updated.last_confirmed_value = new_fact.current_value
                    updated.last_confirmed_at = observed.captured_at
                    updated.freshness = "fresh"
                    if prev_cur != new_fact.current_value:
                        merged.change_notes.append(f"{label}: {prev_cur} → {new_fact.current_value}")
                else:
                    # A bad or empty frame does not erase the last confirmed machine.
                    updated.current_value = new_fact.current_value
                    updated.freshness = "stale" if stale_gap else "historical"
                    if prev_cur not in (None, new_fact.current_value):
                        merged.change_notes.append(f"{label}: not_observed_this_frame")

            if not (updated.history and _same_history_tail(updated.history[-1], observed.captured_at, new_fact)):
                updated.history = list(old.history or [])
                updated.history.append(
                    EntityHistoryEntry(
                        at=observed.captured_at,
                        visibility=new_fact.current_visibility,
                        value=new_fact.current_value,
                        confidence=new_fact.current_confidence,
                    )
                )
            # cap history
            if len(updated.history) > 50:
                updated.history = updated.history[-50:]
            entities[label] = updated

        # Persistent entities missing from this frame → mark not_visible, keep confirmed
        for label, old in list(entities.items()):
            if label in frame_entities:
                continue
            if old.nature != EntityNature.PERSISTENT:
                if old.current_value not in (None, 0, False):
                    merged.change_notes.append(f"{label}: not_observed_this_frame")
                old.current_visibility = EntityVisibility.NOT_VISIBLE
                # Usable frame: not in view is unknown for this frame, not a stored zero.
                old.current_value = None
                old.current_confidence = 0.0
                old.freshness = "stale" if stale_gap else "historical"
                entities[label] = old
            else:
                old.current_visibility = EntityVisibility.NOT_VISIBLE
                old.freshness = "stale" if stale_gap else "historical"
                entities[label] = old

        merged.entities = entities

        # Merge WorkFacts (certainty ≠ completion); resources reset across large gaps.
        merged.work_facts = _merge_work_facts(
            previous.work_facts or {},
            frame.work_facts or {},
            captured_at=observed.captured_at,
            stale_gap=stale_gap,
            change_notes=merged.change_notes,
        )

        _reconcile_floors(
            merged,
            frame=frame,
            previous=previous,
            change_notes=merged.change_notes,
        )
        foundation = entities.get("foundation")
        foundation_ok = bool(
            foundation
            and foundation.last_confirmed_value
            and foundation.current_visibility not in {EntityVisibility.OUTSIDE_VIEW}
        )
        if foundation_ok and merged.scene_attributes.get("structural_levels") is not None:
            merged.scene_attributes["total_floor_count"] = merged.scene_attributes["structural_levels"]
        elif merged.scene_attributes.get("structural_levels") is None:
            merged.scene_attributes["total_floor_count"] = None

        return sync_legacy_projection(merged)

    def _should_update_confirmed(self, prev, new, measurement: str) -> bool:
        if prev is None:
            return True
        if measurement in {"count", "levels"}:
            try:
                return int(new) >= int(prev)
            except (TypeError, ValueError):
                return True
        if measurement in {"area", "area_or_presence"}:
            try:
                return float(new) >= float(prev)
            except (TypeError, ValueError):
                return True
        return True

    def _repeated_lower(self, history: list[EntityHistoryEntry], new, measurement: str) -> bool:
        """A lower structure count sticks only after a second confident reading."""
        for entry in reversed(history or []):
            if entry.confidence < self.revision_min_confidence:
                continue
            if entry.visibility not in self.confirm_visibilities:
                continue
            if entry.value is None:
                continue
            try:
                if measurement in {"count", "levels"} and int(entry.value) == int(new):
                    return True
                if measurement in {"area", "area_or_presence"} and float(entry.value) == float(new):
                    return True
            except (TypeError, ValueError):
                continue
        return False


def _viewpoint(scene: dict | None) -> str:
    scene = scene or {}
    return str(scene.get("orientation") or scene.get("viewpoint") or "")


_PROVEN_DERIVATIONS = frozenset(
    {
        "annotation",
        "scene_label",
        "floor_bands_proven",
        "manual_gt",
    }
)


def _floors_status(scene: dict | None) -> str:
    """proposed = VLM/scalar observation; proven = verified levels / annotation."""
    scene = scene or {}
    raw = scene.get("floors_status")
    if raw in {"proven", "proposed"}:
        return str(raw)
    derivation = str(scene.get("floors_derivation") or "")
    if derivation in _PROVEN_DERIVATIONS:
        return "proven"
    return "proposed"


def _hours_between(previous: datetime | None, current: datetime | None) -> float:
    if previous is None or current is None:
        return 0.0
    return max((current - previous).total_seconds() / 3600.0, 0.0)


def _same_history_tail(entry: EntityHistoryEntry, at: datetime, fact: EntityActualFact) -> bool:
    return (
        entry.at == at
        and entry.visibility == fact.current_visibility
        and entry.value == fact.current_value
        and entry.confidence == fact.current_confidence
    )


def _allow_floors_revision_down(
    previous_facts: dict[str, WorkFact],
    new_fact: WorkFact | None,
    *,
    prev_n: int,
    new_n: int,
) -> bool:
    """Allow lowering proven floors only with a confirmed stronger reading (not a poor frame)."""
    if new_fact is None or new_fact.certainty != WorkCertainty.CONFIRMED:
        return False
    if new_fact.coverage.value == "partial" or new_fact.coverage.value == "target_not_in_frame":
        return False
    old = previous_facts.get("visible_floor_levels")
    if old is None or old.value is None:
        return True
    method = new_fact.method or ""
    if "bands" in method or method in {"visible_floor_levels", "floors_localize"}:
        return new_n < prev_n and len(new_fact.evidence_ids) >= 1
    return False


def _merge_floor_indicator(
    old: WorkFact,
    new: WorkFact,
    change_notes: list[str],
) -> WorkFact:
    """Merge visible_floor_levels WorkFact.

    Confirmed (proven) ratchet: upward freely; downward only via confirmed
    stronger evidence. Proposed/unknown never overwrites confirmed and never
    drives UI max from history of proposals.
    """
    key = "visible_floor_levels"
    if new.certainty == WorkCertainty.CONFIRMED and new.value is not None:
        if old.certainty != WorkCertainty.CONFIRMED or old.value is None:
            change_notes.append(f"work:{key}:confirmed={new.value}")
            return new
        try:
            old_n, new_n = int(old.value), int(new.value)
        except (TypeError, ValueError):
            change_notes.append(f"work:{key}:{old.value}→{new.value}")
            return new
        if new_n >= old_n:
            if new_n != old_n:
                change_notes.append(f"work:{key}:{old_n}→{new_n}")
            return new
        # Downward revision of confirmed
        if _allow_floors_revision_down(
            {key: old}, new, prev_n=old_n, new_n=new_n
        ):
            change_notes.append(f"work:{key}:revision:{old_n}→{new_n}")
            return new
        kept = old.model_copy(deep=True)
        kept.captured_at = new.captured_at
        kept.limitations = list(old.limitations) + [
            f"rejected_down:{new_n} (need stronger proven evidence)"
        ]
        return kept

    # Non-confirmed frame: keep confirmed; else take latest observation value.
    if old.certainty == WorkCertainty.CONFIRMED:
        kept = old.model_copy(deep=True)
        kept.captured_at = new.captured_at
        # Surface latest proposed reading in limitations for inspector, not as value.
        if new.value is not None:
            kept.limitations = list(old.limitations) + [
                f"proposed_frame={new.value}",
                "carried: frame not confirmed",
            ]
        else:
            kept.limitations = list(old.limitations) + ["carried: frame not confirmed"]
        return kept
    return new


def _reconcile_floors(
    merged: ActualState,
    *,
    frame: ActualState,
    previous: ActualState,
    change_notes: list[str],
) -> None:
    """Update scene floors: proposed observation vs proven structural_levels.

    UI / WorkFact.value must not come from max(history of proposed).
    Ratchet up only for proven; revision down only with stronger confirmed evidence.
    """
    floors_fact = (merged.work_facts or {}).get("visible_floor_levels")
    frame_levels = frame.scene_attributes.get("visible_floor_levels")
    if frame_levels is None and frame.scene_attributes.get("floors_status") == "proven":
        frame_levels = frame.scene_attributes.get("structural_levels")
    if frame_levels is None and floors_fact is not None and floors_fact.value is not None:
        frame_levels = floors_fact.value
    prev_levels = previous.scene_attributes.get("structural_levels")
    frame_status = _floors_status(frame.scene_attributes)
    if floors_fact is not None and floors_fact.certainty == WorkCertainty.CONFIRMED:
        if frame.scene_attributes.get("floors_derivation") in {
            "floor_bands_proven",
            "scene_label",
            "annotation",
            "manual_gt",
            "work_fact:visible_floor_levels",
        } or frame_status == "proven":
            frame_status = "proven"

    if frame_levels is not None:
        try:
            levels = int(frame_levels)
        except (TypeError, ValueError):
            levels = None
        if levels is not None:
            merged.scene_attributes["visible_floor_levels"] = levels
            merged.scene_attributes["floors_status_latest"] = frame_status
            merged.scene_attributes["floors_status"] = frame_status
            # Carry band evidence metadata for overlays / API
            for key in (
                "floor_bands",
                "floor_bands_overlay",
                "floor_bands_crop",
                "floor_bands_unambiguous",
                "floor_bands_proposed",
                "floors_prove_reasons",
            ):
                if key in frame.scene_attributes:
                    merged.scene_attributes[key] = frame.scene_attributes[key]
            if frame_status == "proven":
                try:
                    prev_n = int(prev_levels) if prev_levels is not None else None
                except (TypeError, ValueError):
                    prev_n = None
                allow_down = False
                if prev_n is not None and levels < prev_n:
                    allow_down = _allow_floors_revision_down(
                        previous.work_facts or {},
                        floors_fact,
                        prev_n=prev_n,
                        new_n=levels,
                    )
                if prev_n is None or levels >= prev_n or allow_down:
                    merged.scene_attributes["structural_levels"] = levels
                    merged.scene_attributes["floors_derivation"] = frame.scene_attributes.get(
                        "floors_derivation", "visible_floor_levels"
                    )
                    if allow_down:
                        change_notes.append(f"floors_revision:{prev_n}→{levels}")
                else:
                    # Keep previous proven; mark latest as proposed observation
                    merged.scene_attributes["floors_status"] = "proven"
                    if prev_levels is not None:
                        merged.scene_attributes["structural_levels"] = prev_levels
            else:
                # Proposed does not rewrite confirmed / does not raise historical max.
                merged.scene_attributes["floors_derivation"] = frame.scene_attributes.get(
                    "floors_derivation", "visible_floor_levels"
                )
                if prev_levels is not None:
                    merged.scene_attributes.setdefault("structural_levels", prev_levels)
                    merged.scene_attributes["floors_status"] = "proven"
    elif "structural_levels" not in merged.scene_attributes and prev_levels is not None:
        merged.scene_attributes["structural_levels"] = prev_levels
        merged.scene_attributes.setdefault("floors_status", "proven")


def _merge_work_facts(
    previous: dict[str, WorkFact],
    frame: dict[str, WorkFact],
    *,
    captured_at,
    stale_gap: bool,
    change_notes: list[str],
) -> dict[str, WorkFact]:
    """Accumulate work facts. Persistent can revise down on confirmed stronger reading.

    Transient equipment does not carry across a large capture gap.
    """
    out = {k: v.model_copy(deep=True) for k, v in previous.items()}
    for key, new in frame.items():
        old = out.get(key)
        if old is None:
            out[key] = new
            if new.certainty == WorkCertainty.CONFIRMED and new.value not in (None, 0, False):
                change_notes.append(f"work:{key}:appeared={new.value}")
            continue

        if new.kind.value == "resource_count" and stale_gap:
            out[key] = new
            change_notes.append(f"work:{key}:gap_reset")
            continue

        if key == "visible_floor_levels":
            out[key] = _merge_floor_indicator(old, new, change_notes)
            continue

        if new.certainty == WorkCertainty.CONFIRMED and new.value is not None:
            if old.certainty != WorkCertainty.CONFIRMED or old.value is None:
                out[key] = new
                change_notes.append(f"work:{key}:confirmed={new.value}")
                continue
            if new.value != old.value:
                change_notes.append(f"work:{key}:{old.value}→{new.value}")
            out[key] = new
            continue

        if old.certainty == WorkCertainty.CONFIRMED and new.kind.value != "resource_count":
            kept = old.model_copy(deep=True)
            kept.captured_at = captured_at
            kept.limitations = list(old.limitations) + ["carried: frame not confirmed"]
            out[key] = kept
            continue
        out[key] = new
    return out


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _floor_suitable(fact: WorkFact | None) -> bool:
    """Full-object confirmed count. Partial and unconfirmed readings are observations only."""
    if fact is None or fact.certainty != WorkCertainty.CONFIRMED or fact.value is None:
        return False
    coverage = getattr(fact.coverage, "value", fact.coverage)
    return coverage not in {"partial", "target_not_in_frame"}


_STRONGER_FLOOR_DERIVATIONS = frozenset({"floor_bands_proven", "manual_gt"})


def _merge_floor_indicator(old: WorkFact, new: WorkFact, change_notes: list[str]) -> WorkFact:
    """Keep a confirmed object count. A partial or weaker frame does not replace it."""
    if not _floor_suitable(new):
        if old.certainty == WorkCertainty.CONFIRMED:
            kept = old.model_copy(deep=True)
            note = "кадр не заменяет подтверждённую этажность"
            if note not in kept.limitations:
                kept.limitations = [*old.limitations, note]
            return kept
        return new
    old_n = _as_int(old.value) if old.certainty == WorkCertainty.CONFIRMED else None
    new_n = _as_int(new.value)
    if old_n is None:
        change_notes.append(f"work:visible_floor_levels:confirmed={new_n}")
        return new
    if new_n is not None and new_n >= old_n:
        if new_n != old_n:
            change_notes.append(f"work:visible_floor_levels:{old_n}→{new_n}")
        return new
    return old


def _reconcile_floors(merged: ActualState, *, frame: ActualState, previous: ActualState, change_notes: list[str]) -> None:
    """Split current observation, confirmed count, and a disputed candidate.

    A bad or partial frame never lowers the confirmed count. A lower full reading
    replaces it only after a second identical confirmation, or immediately when a
    stronger method (band localization / manual) corrects a weaker one.
    Future frames are not visible here: only previous + this capture.
    """
    scene = merged.scene_attributes
    frame_scene = frame.scene_attributes or {}
    frame_fact = (frame.work_facts or {}).get("visible_floor_levels")
    obs = _as_int(frame_scene.get("visible_floor_levels"))
    if obs is None and frame_fact is not None:
        obs = _as_int(frame_fact.value)
    status = _floors_status(frame_scene)
    if obs is not None:
        scene["visible_floor_levels"] = obs
    scene["floors_status_latest"] = status

    prev_n = _as_int((previous.scene_attributes or {}).get("structural_levels"))
    suitable = _floor_suitable(frame_fact) and status == "proven"
    deriv = str(frame_scene.get("floors_derivation") or "")
    prev_deriv = str((previous.scene_attributes or {}).get("floors_derivation") or "")

    if not suitable or obs is None:
        if prev_n is not None:
            scene["structural_levels"] = prev_n
            scene["floors_status"] = "proven"
        else:
            scene.pop("structural_levels", None)
            scene["floors_status"] = status
        if obs is not None and prev_n is not None and obs != prev_n:
            scene["floors_disputed"] = obs
            scene["floors_dispute_reason"] = "кадр не подтверждает этажность объекта"
        else:
            scene.pop("floors_disputed", None)
            scene.pop("floors_dispute_reason", None)
        return

    if prev_n is None or obs >= prev_n:
        scene["structural_levels"] = obs
        scene["floors_status"] = "proven"
        scene["floors_derivation"] = deriv or "visible_floor_levels"
        scene.pop("floors_disputed", None)
        scene.pop("floors_dispute_reason", None)
        scene["floors_lower_support"] = 0
        scene.pop("floors_lower_candidate", None)
        if prev_n is not None and obs > prev_n:
            change_notes.append(f"floors_confirmed:{prev_n}→{obs}")
        return

    stronger = deriv in _STRONGER_FLOOR_DERIVATIONS and prev_deriv not in _STRONGER_FLOOR_DERIVATIONS
    candidate = _as_int(scene.get("floors_lower_candidate"))
    support = int(scene.get("floors_lower_support") or 0)
    support = support + 1 if candidate == obs else 1
    scene["floors_lower_candidate"] = obs
    scene["floors_lower_support"] = support
    if stronger or support >= 2:
        scene["structural_levels"] = obs
        scene["floors_status"] = "proven"
        scene["floors_derivation"] = deriv or "visible_floor_levels"
        scene.pop("floors_disputed", None)
        scene.pop("floors_dispute_reason", None)
        scene["floors_lower_support"] = 0
        scene.pop("floors_lower_candidate", None)
        if frame_fact is not None:
            merged.work_facts["visible_floor_levels"] = frame_fact
        change_notes.append(f"floors_revision:{prev_n}→{obs}")
        return

    scene["structural_levels"] = prev_n
    scene["floors_status"] = "proven"
    scene["floors_disputed"] = obs
    scene["floors_dispute_reason"] = (
        "более низкое чтение ещё не подтверждено повторно или более сильным методом"
    )
