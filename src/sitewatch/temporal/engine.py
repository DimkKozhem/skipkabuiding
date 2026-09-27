from __future__ import annotations

from datetime import date

from sitewatch.domain.contracts import ActualState, ExpectedState, PresenceStat, StateChangeAnalysis, StateTransition
from sitewatch.domain.enums import StateChangeKind
from sitewatch.settings import load_yaml

DEFAULT_STRUCTURAL_KEYS = (
    "foundation",
    "columns",
    "walls",
    "slabs",
    "roof",
    "facade",
    "floors",
)


def _state_usable_for_dynamics(state: ActualState) -> bool:
    """A poor or unscoped frame does not sample the period.

    Пустой annotation/CV без evidence (все max_confidence=0) — тоже не выборка
    динамики: иначе «стабильный ноль» даёт ложный no_dynamics.
    """
    quality = state.quality
    if quality.visibility.value == "poor":
        return False
    if quality.coverage.value == "unknown":
        return False
    if state.scene_attributes.get("structural_levels") is not None:
        return True
    for stat in list(state.elements.values()) + list(state.equipment.values()):
        if float(getattr(stat, "max_confidence", 0.0) or 0.0) > 0:
            return True
    return False

def _temporal_cfg(thresholds: dict | None = None) -> dict:
    if thresholds is not None:
        return thresholds.get("temporal", {}) if "temporal" in thresholds else thresholds
    return load_yaml("thresholds.yaml").get("temporal", {})


def _numeric_snapshot(state: ActualState) -> dict[str, int]:
    values: dict[str, int] = {}
    for key, stat in state.elements.items():
        values[f"el:{key}"] = int(stat.count)
    for key, stat in state.equipment.items():
        values[f"eq:{key}"] = int(stat.count)
    return values


def _element_value(state: ActualState, key: str) -> int:
    stat = state.elements.get(key)
    if stat is None:
        if key == "floors":
            levels = state.scene_attributes.get("structural_levels")
            if levels is not None:
                return int(levels)
        return 0
    if isinstance(stat, PresenceStat):
        return int(stat.detected)
    return int(stat.count)


def _structural_snapshot(state: ActualState, keys: tuple[str, ...] | list[str]) -> dict[str, int]:
    values: dict[str, int] = {}
    for key in keys:
        if key in state.elements or (key == "floors" and state.scene_attributes.get("structural_levels") is not None):
            values[key] = _element_value(state, key)
    return values


def analyze_state_change(
    previous_state: ActualState | None,
    current_state: ActualState | None,
    visual_change: float | None = None,
    thresholds: dict | None = None,
) -> StateChangeAnalysis:
    """Compare two aggregated ActualState snapshots. Not a YOLO helper.

    Level 1: structural presence/counts (foundation, slabs, columns, …).
    Level 2: quantitative deltas, including equipment (reported separately).
    Level 3: optional visual similarity — used only when structural keys are absent.
    """
    cfg = _temporal_cfg(thresholds)
    structural_keys = tuple(cfg.get("structural_keys") or DEFAULT_STRUCTURAL_KEYS)
    max_rel = float(cfg.get("max_relative_change_for_stable", 0.08))
    max_visual = float(cfg.get("max_visual_change_for_stable", 0.12))

    if previous_state is None or current_state is None:
        return StateChangeAnalysis(
            changed=False,
            kind=StateChangeKind.UNKNOWN,
            notes=["missing_state"],
            visual_change=visual_change,
        )
    if not previous_state.camera_code or not current_state.camera_code:
        return StateChangeAnalysis(
            changed=False,
            kind=StateChangeKind.UNKNOWN,
            notes=["missing_camera"],
            visual_change=visual_change,
        )
    if previous_state.camera_code != current_state.camera_code:
        return StateChangeAnalysis(
            changed=False,
            kind=StateChangeKind.UNKNOWN,
            same_camera=False,
            comparable=False,
            notes=["different_camera: observations are not comparable"],
            visual_change=visual_change,
        )
    prev_view = (previous_state.scene_attributes or {}).get("orientation") or (
        previous_state.scene_attributes or {}
    ).get("viewpoint")
    curr_view = (current_state.scene_attributes or {}).get("orientation") or (
        current_state.scene_attributes or {}
    ).get("viewpoint")
    if prev_view and curr_view and prev_view != curr_view:
        return StateChangeAnalysis(
            changed=False,
            kind=StateChangeKind.UNKNOWN,
            same_camera=True,
            comparable=False,
            notes=["different_orientation: viewpoints are not comparable"],
            visual_change=visual_change,
        )
    if previous_state.quality.coverage.value == "unknown" or current_state.quality.coverage.value == "unknown":
        return StateChangeAnalysis(
            changed=False,
            kind=StateChangeKind.UNKNOWN,
            same_camera=True,
            comparable=False,
            notes=["unknown_coverage"],
            visual_change=visual_change,
        )

    prev = _structural_snapshot(previous_state, structural_keys)
    curr = _structural_snapshot(current_state, structural_keys)
    keys = list(dict.fromkeys([*prev.keys(), *curr.keys()]))
    changed_elements: list[str] = []
    stable_elements: list[str] = []
    abs_delta = 0
    for key in keys:
        delta = abs(curr.get(key, 0) - prev.get(key, 0))
        abs_delta += delta
        if delta:
            changed_elements.append(key)
        else:
            stable_elements.append(key)
    baseline = max(sum(prev.values()), 1)
    change_score = round(abs_delta / baseline, 4)

    prev_eq = {k: int(v.count) for k, v in previous_state.equipment.items()}
    curr_eq = {k: int(v.count) for k, v in current_state.equipment.items()}
    changed_equipment = sorted(
        name for name in set(prev_eq) | set(curr_eq) if prev_eq.get(name, 0) != curr_eq.get(name, 0)
    )

    notes: list[str] = []
    if not changed_elements:
        changed = False
    elif change_score > max_rel:
        changed = True
    else:
        # Tiny count jitter below the stable threshold is not a material change.
        changed = False
        notes.append("structural_delta_below_stable_threshold")
        stable_elements = [*stable_elements, *changed_elements]
        changed_elements = []

    if not keys:
        notes.append("no_structural_keys")
        if visual_change is not None:
            if visual_change > max_visual:
                changed = True
                notes.append("visual_similarity_fallback")
            else:
                changed = False
                notes.append("visual_similarity_stable")
        elif changed_equipment:
            changed = True
            notes.append("equipment_only_fallback")
        else:
            changed = False

    kind = StateChangeKind.CHANGED if changed else StateChangeKind.UNCHANGED
    return StateChangeAnalysis(
        changed=changed,
        change_score=change_score,
        changed_elements=changed_elements,
        stable_elements=stable_elements,
        changed_equipment=changed_equipment,
        kind=kind,
        comparable=True,
        same_camera=True,
        visual_change=visual_change,
        notes=notes,
    )


class TemporalEngine:
    def __init__(self, thresholds: dict | None = None) -> None:
        raw = thresholds or load_yaml("thresholds.yaml")
        self.thresholds = raw
        self.cfg = raw.get("temporal", raw if "min_period_days_for_no_dynamics" in (raw or {}) else {})

    def analyze_state_change(
        self,
        previous_state: ActualState | None,
        current_state: ActualState | None,
        visual_change: float | None = None,
    ) -> StateChangeAnalysis:
        return analyze_state_change(
            previous_state,
            current_state,
            visual_change=visual_change,
            thresholds=self.thresholds,
        )

    def transition(
        self,
        previous: ActualState,
        current: ActualState,
        visual_change: float | None = None,
    ) -> StateTransition:
        prev = _numeric_snapshot(previous)
        curr = _numeric_snapshot(current)
        keys = set(prev) | set(curr)
        element_deltas = {
            key.removeprefix("el:"): curr.get(key, 0) - prev.get(key, 0)
            for key in keys
            if key.startswith("el:")
        }
        equipment_deltas = {
            key.removeprefix("eq:"): curr.get(key, 0) - prev.get(key, 0)
            for key in keys
            if key.startswith("eq:")
        }
        period = max((current.timestamp - previous.timestamp).total_seconds() / 86400.0, 0.0)
        analysis = self.analyze_state_change(previous, current, visual_change=visual_change)
        notes = list(analysis.notes)
        if not analysis.same_camera:
            notes.append("different_or_missing_camera: visual comparison is weak")
        return StateTransition(
            from_timestamp=previous.timestamp,
            to_timestamp=current.timestamp,
            period_days=round(period, 3),
            change_kind=analysis.kind,
            element_deltas=element_deltas,
            equipment_deltas=equipment_deltas,
            relative_change=analysis.change_score,
            visual_change=visual_change,
            same_camera=analysis.same_camera,
            comparable=analysis.comparable,
            changed=analysis.changed,
            change_score=analysis.change_score,
            changed_elements=analysis.changed_elements,
            stable_elements=analysis.stable_elements,
            notes=notes,
        )

    def is_state_stable(self, transition: StateTransition) -> bool:
        if not transition.comparable:
            return False
        return not transition.changed

    def is_visually_stable(self, transition: StateTransition) -> bool:
        """Visual similarity is a supporting signal, not a standalone verdict."""
        if transition.visual_change is None or not transition.same_camera:
            return True
        return transition.visual_change <= float(self.cfg.get("max_visual_change_for_stable", 0.12))

    def schedule_progress(self, series: list[ExpectedState], start: date, end: date) -> dict:
        window = [item for item in series if start <= item.date <= end]
        if len(window) < 2:
            return {"progress": 0.0, "from": None, "to": None}
        first, last = window[0], window[-1]
        keys = tuple(self.thresholds.get("schedule", {}).get("progress_keys") or ("floors", "columns", "slabs", "walls"))
        progress = 0.0
        for key in keys:
            progress += float(last.expected.get(key, 0) or 0) - float(first.expected.get(key, 0) or 0)
        return {"progress": progress, "from": first.date.isoformat(), "to": last.date.isoformat()}

    def no_dynamics_signal(
        self,
        states: list[ActualState],
        expected_series: list[ExpectedState],
        visual_changes: list[float | None] | None = None,
    ) -> dict | None:
        """Stable comparable ActualState series while KSG still advances."""
        min_states = int(self.cfg.get("min_states_for_no_dynamics", 3))
        if len(states) < min_states:
            return None
        ordered = [
            item
            for item in sorted(states, key=lambda item: item.timestamp)
            if _state_usable_for_dynamics(item)
        ]
        if len(ordered) < min_states:
            return None
        first, last = ordered[0], ordered[-1]
        period = (last.timestamp - first.timestamp).total_seconds() / 86400.0
        min_days = float(self.cfg.get("min_period_days_for_no_dynamics", 14))
        if period < min_days:
            return None
        max_gap = float(self.cfg.get("max_observation_gap_days", 7))
        gaps = [
            (ordered[idx].timestamp - ordered[idx - 1].timestamp).total_seconds() / 86400.0
            for idx in range(1, len(ordered))
        ]
        widest = max(gaps) if gaps else 0.0
        if widest > max_gap:
            return None
        if self.cfg.get("same_camera_required", True):
            cameras = {item.camera_code for item in ordered if item.camera_code}
            if len(cameras) != 1:
                return None

        analyses: list[StateChangeAnalysis] = []
        visuals = visual_changes if visual_changes and len(ordered) == len(states) else None
        for idx in range(1, len(ordered)):
            visual = None
            if visuals and idx - 1 < len(visuals):
                visual = visuals[idx - 1]
            analysis = self.analyze_state_change(ordered[idx - 1], ordered[idx], visual)
            analyses.append(analysis)
            if not analysis.comparable or analysis.changed:
                return None

        progress = self.schedule_progress(expected_series, first.timestamp.date(), last.timestamp.date())
        if progress["progress"] <= 0:
            return None

        stable: list[str] = []
        for analysis in analyses:
            for key in analysis.stable_elements:
                if key not in stable:
                    stable.append(key)
        return {
            "changed": False,
            "change_score": round(
                sum(item.change_score for item in analyses) / max(len(analyses), 1),
                4,
            ),
            "visual_change": round(
                sum((item.visual_change or item.change_score) for item in analyses) / len(analyses),
                4,
            ),
            "schedule_progress": progress["progress"],
            "observation_period_days": round(period, 2),
            "n_states": len(ordered),
            "max_gap_days": round(widest, 2),
            "same_camera": True,
            "camera_code": first.camera_code,
            "stable_elements": stable,
            "changed_elements": [],
        }
