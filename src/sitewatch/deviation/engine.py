from __future__ import annotations

from datetime import date, datetime, timedelta

from sitewatch.deviation.quality import (
    evidence_confidence,
    sufficient_for_absence,
    sufficient_for_positive,
)
from sitewatch.domain.contracts import (
    ActualState,
    DeviationCandidate,
    EvidenceRef,
    ExpectedState,
)
from sitewatch.domain.enums import AlertType, CheckOutcome, Severity
from sitewatch.settings import load_yaml
from sitewatch.temporal.engine import TemporalEngine
from sitewatch.works.compare import check_indicators, indicator_changed
from sitewatch.works.planned import planned_indicators_from_expected


EQUIPMENT_LABELS = {
    "excavator": "Экскаватор",
    "dump_truck": "Самосвал",
    "roller": "Каток",
    "crane_manipulator": "Кран-манипулятор",
    "concrete_mixer": "Бетоносмеситель",
    "bulldozer": "Бульдозер",
    "truck": "Грузовик",
    "mobile_crane": "Мобильный кран",
}

ELEMENT_LABELS = {
    "foundation": "Фундамент",
    "columns": "Колонны",
    "walls": "Стены",
    "slabs": "Плиты",
    "floors": "Этажи",
    "windows": "Окна",
    "roof": "Кровля",
    "facade": "Фасад",
    "structural_levels": "Конструктивные уровни",
}


def _severity(name: str, default: str) -> Severity:
    try:
        return Severity(name)
    except ValueError:
        return Severity(default)


def _label_equipment(name: str) -> str:
    return EQUIPMENT_LABELS.get(name, name)


def _label_element(name: str) -> str:
    return ELEMENT_LABELS.get(name, name)


def _is_presence_value(value) -> bool:
    return isinstance(value, bool)


def _fmt_ts(value: datetime) -> str:
    return value.strftime("%d.%m.%Y %H:%M")


def _fmt_date(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def _evidence_lines(evidence: list[EvidenceRef]) -> str:
    if not evidence:
        return "нет привязанных наблюдений"
    lines = []
    for ref in evidence:
        oid = (ref.observation_id or "")[:8] or "—"
        name = ref.media_path.rsplit("/", 1)[-1] if ref.media_path else "—"
        lines.append(f"[{oid}] {name}")
    return "\n".join(lines)


def inspector_message(
    *,
    title: str,
    object_id: str,
    zone_id: str,
    expected_block: str,
    observed_block: str,
    deviation_block: str,
    last_ts: datetime,
    basis: str,
    evidence: list[EvidenceRef],
    status: str = "требуется проверка инспектором",
) -> str:
    return (
        f"{title}\n\n"
        f"Объект: {object_id}\n"
        f"Зона: {zone_id}\n\n"
        f"По КСГ:\n{expected_block}\n\n"
        f"По последнему наблюдению:\n{observed_block}\n\n"
        f"Последнее наблюдение:\n{_fmt_ts(last_ts)}\n\n"
        f"Основание:\n{basis}\n\n"
        f"Доказательства:\n{_evidence_lines(evidence)}\n\n"
        f"Статус:\n{status}"
    )


class DeviationEngine:
    """Deterministic plan/fact + temporal rules. Does not import YOLO or any CV model.

    Rules live in config/*.yaml. This class only interprets ExpectedState / ActualState.
    """

    def __init__(self) -> None:
        self.cfg = load_yaml("thresholds.yaml")
        self.temporal = TemporalEngine(self.cfg)

    def evaluate(
        self,
        expected: ExpectedState,
        actual: ActualState,
        history: list[ActualState] | None = None,
        expected_series: list[ExpectedState] | None = None,
        evidence: list[EvidenceRef] | None = None,
        visual_changes: list[float | None] | None = None,
    ) -> list[DeviationCandidate]:
        evidence = evidence or []
        actual.quality.evidence_confidence = evidence_confidence(actual.quality, self.cfg)
        enough_positive = sufficient_for_positive(actual.quality, self.cfg)
        enough_absence = sufficient_for_absence(actual.quality, self.cfg)
        found: list[DeviationCandidate] = []

        # Primary path: PlannedIndicator ↔ WorkFact (no legacy progress_keys).
        found.extend(self._work_checks(expected, actual, evidence, history or []))
        found.extend(self._equipment(expected, actual, evidence, enough_absence, enough_positive))
        found.extend(
            self._no_dynamics(
                expected,
                actual,
                history or [],
                expected_series or [],
                evidence,
                visual_changes,
            )
        )
        return found

    def _planned_list(self, expected: ExpectedState):
        if expected.planned_indicators:
            return list(expected.planned_indicators)
        return planned_indicators_from_expected(
            schedule_row_id=expected.schedule_row_id
            or f"{expected.object_id}:{expected.zone_id}:{expected.stage}:{expected.date.isoformat()}",
            work_code=expected.stage,
            expected=expected.expected or {},
            stage_label=expected.stage_label,
            start_date=expected.start_date,
            end_date=expected.end_date,
            required_equipment=[],  # equipment handled separately as resource alerts
        )

    def _work_checks(
        self,
        expected: ExpectedState,
        actual: ActualState,
        evidence: list[EvidenceRef],
        history: list[ActualState],
    ) -> list[DeviationCandidate]:
        planned = [
            item
            for item in self._planned_list(expected)
            if not item.indicator_id.startswith("equipment:")
        ]
        if not planned:
            return []

        last_obs = actual.timestamp.date() if actual.timestamp else None
        # If history tip is earlier, use that as series tip for no_observation_after
        if history:
            tip = max((h.timestamp.date() for h in history if h.timestamp), default=last_obs)
            if last_obs and tip and tip > last_obs:
                last_obs = tip

        results = check_indicators(
            planned,
            actual,
            evaluation_as_of=expected.date,
            last_observation_date=last_obs,
        )
        found: list[DeviationCandidate] = []
        for result in results:
            cand = self._candidate_from_check(result, expected, actual, evidence)
            if cand is not None:
                found.append(cand)
        return found

    def _candidate_from_check(self, result, expected, actual, evidence) -> DeviationCandidate | None:
        outcome = result.outcome
        planned = result.planned
        fact = result.fact
        expected_payload = {
            "indicator_id": planned.indicator_id if planned else None,
            "value": planned.value if planned else None,
            "unit": planned.unit if planned else None,
            "confirms": planned.confirms if planned else None,
            "schedule_row_id": planned.schedule_row_id if planned else None,
        }
        observed_payload = {
            "indicator_id": fact.indicator_id if fact else None,
            "certainty": fact.certainty.value if fact else None,
            "value": fact.value if fact else None,
            "unit": fact.unit if fact else None,
            "method": fact.method if fact else None,
            "coverage": fact.coverage.value if fact else None,
            "limitations": list(fact.limitations) if fact else [],
            "evidence_ids": list(fact.evidence_ids) if fact else [],
        }
        # Legacy UI keys for floors / presence until consumers read indicator_id.
        if planned and planned.indicator_id == "visible_floor_levels":
            expected_payload["floors"] = planned.value
            observed_payload["floors"] = fact.value if fact else None
        if planned and planned.indicator_id.endswith("_visible"):
            key = planned.indicator_id.replace("_visible", "")
            if key in {"foundation", "facade", "roof", "windows"}:
                expected_payload[key] = planned.value
                observed_payload[key] = fact.value if fact else None


        if outcome == CheckOutcome.MATCH:
            return None

        if outcome == CheckOutcome.DEVIATION:
            is_resource = planned and planned.indicator_id.startswith("equipment:")
            alert = AlertType.MISSING_EQUIPMENT if is_resource else AlertType.SCHEDULE_DELAY
            sev = _severity(
                self.cfg["alert"].get(
                    "missing_equipment_severity" if is_resource else "no_dynamics_severity",
                    "warning",
                ),
                "warning",
            )
            return self._candidate(
                alert,
                sev,
                expected,
                actual,
                evidence,
                title=result.title,
                message=inspector_message(
                    title=result.title,
                    object_id=expected.object_id,
                    zone_id=expected.zone_id,
                    expected_block=(
                        f"{planned.indicator_id}: {planned.value} {planned.unit or ''}\n{planned.confirms}"
                        if planned
                        else "—"
                    ),
                    observed_block=(
                        f"{fact.indicator_id}: {fact.value} ({fact.certainty.value})"
                        if fact
                        else "—"
                    ),
                    deviation_block=result.rationale,
                    last_ts=actual.timestamp,
                    basis=result.rationale,
                    evidence=evidence,
                ),
                rationale=result.rationale,
                rule_id=result.rule_id,
                expected_payload=expected_payload,
                observed_payload=observed_payload,
                rule_confidence=0.75,
            )

        alert_map = {
            CheckOutcome.INSUFFICIENT_DATA: AlertType.INSUFFICIENT_EVIDENCE,
            CheckOutcome.INCOMPARABLE: AlertType.INCOMPARABLE,
            CheckOutcome.MEASUREMENT_UNIMPLEMENTED: AlertType.MEASUREMENT_UNIMPLEMENTED,
            CheckOutcome.NEEDS_CAPTURE_OR_CALIBRATION: AlertType.NEEDS_CAPTURE_OR_CALIBRATION,
            CheckOutcome.NO_OBSERVATION_AFTER: AlertType.NO_OBSERVATION_AFTER,
        }
        alert = alert_map.get(outcome)
        if alert is None:
            return None
        return self._candidate(
            alert,
            Severity.INFO,
            expected,
            actual,
            evidence,
            title=result.title,
            message=inspector_message(
                title=result.title,
                object_id=expected.object_id,
                zone_id=expected.zone_id,
                expected_block=f"{planned.indicator_id if planned else '—'}: {planned.value if planned else '—'}",
                observed_block=f"{fact.certainty.value if fact else 'нет факта'}: {fact.value if fact else '—'}",
                deviation_block=result.rationale,
                last_ts=actual.timestamp,
                basis=result.rationale,
                evidence=evidence,
                status="не schedule_delay / не no_dynamics",
            ),
            rationale=result.rationale,
            rule_id=result.rule_id,
            expected_payload=expected_payload,
            observed_payload=observed_payload,
            rule_confidence=0.5,
        )

    def _equipment(
        self,
        expected: ExpectedState,
        actual: ActualState,
        evidence: list[EvidenceRef],
        enough_absence: bool,
        enough_positive: bool,
    ) -> list[DeviationCandidate]:
        found: list[DeviationCandidate] = []
        min_gap = int(self.cfg["equipment"]["missing_min_gap"])
        missing: dict[str, dict[str, int]] = {}
        for rule in expected.required_equipment:
            kind = rule["type"]
            need = int(rule.get("min_count", 1))
            fact = (actual.work_facts or {}).get(f"equipment:{kind}")
            if fact is not None and fact.value is not None and fact.certainty.value == "confirmed":
                got = int(fact.value)
            elif fact is not None and fact.certainty.value in {"unknown", "contradiction", "processing_error"}:
                # Do not treat unknown as observed 0
                got = -10_000  # force insufficient path below via special marker
                missing[kind] = {"expected": need, "observed": -1}
                continue
            else:
                got = actual.equipment_count(kind)
            if need - got >= min_gap:
                missing[kind] = {"expected": need, "observed": max(got, 0)}
        # Unknown equipment facts → insufficient, not missing_equipment
        unknown_keys = [k for k, v in missing.items() if v.get("observed") == -1]
        if unknown_keys:
            found.append(
                self._candidate(
                    AlertType.INSUFFICIENT_EVIDENCE,
                    Severity.INFO,
                    expected,
                    actual,
                    evidence,
                    title="Недостаточно данных по технике",
                    message=inspector_message(
                        title="ℹ Недостаточно данных по технике",
                        object_id=expected.object_id,
                        zone_id=expected.zone_id,
                        expected_block="\n".join(f"{_label_equipment(k)}" for k in unknown_keys),
                        observed_block="факт техники не подтверждён",
                        deviation_block="ресурсный показатель без подтверждения — не отставание работ",
                        last_ts=actual.timestamp,
                        basis="WorkFact equipment certainty ≠ confirmed",
                        evidence=evidence,
                        status="нужны дополнительные наблюдения",
                    ),
                    rationale="equipment WorkFact not confirmed",
                    rule_id="equipment.insufficient",
                    expected_payload={k: missing[k]["expected"] for k in unknown_keys},
                    observed_payload={k: None for k in unknown_keys},
                    rule_confidence=0.4,
                )
            )
            for k in unknown_keys:
                missing.pop(k, None)
        if missing and not enough_absence:
            found.append(
                self._candidate(
                    AlertType.INSUFFICIENT_EVIDENCE,
                    _severity(self.cfg["alert"]["insufficient_evidence_severity"], "info"),
                    expected,
                    actual,
                    evidence,
                    title="Недостаточно данных, чтобы доказывать отсутствие техники",
                    message=inspector_message(
                        title="ℹ Недостаточно данных",
                        object_id=expected.object_id,
                        zone_id=expected.zone_id,
                        expected_block="\n".join(
                            f"{_label_equipment(k)} — минимум {v['expected']}" for k, v in missing.items()
                        ),
                        observed_block=(
                            f"кадров: {actual.quality.n_frames}; "
                            f"coverage={actual.quality.coverage.value}; "
                            f"visibility={actual.quality.visibility.value}"
                        ),
                        deviation_block="нет детекции ≠ доказанное отсутствие; не schedule_delay",
                        last_ts=actual.timestamp,
                        basis=(
                            "Отсутствие детекции не равно доказанному отсутствию. "
                            "Ресурсный сигнал, не отставание выполненных работ."
                        ),
                        evidence=evidence,
                        status="нужны дополнительные наблюдения",
                    ),
                    rationale="insufficient evidence for missing equipment",
                    rule_id="evidence.insufficient_for_absence",
                    expected_payload=missing,
                    observed_payload=actual.quality.model_dump(mode="json"),
                    rule_confidence=actual.quality.evidence_confidence,
                )
            )
            missing = {}
        if missing:
            expected_block = "\n".join(
                f"{_label_equipment(k)} — минимум {v['expected']}" for k, v in missing.items()
            )
            observed_block = "\n".join(f"{_label_equipment(k)} — {v['observed']}" for k, v in missing.items())
            message = inspector_message(
                title="Признаки отсутствия техники. Требуется проверка.",
                object_id=expected.object_id,
                zone_id=expected.zone_id,
                expected_block=expected_block,
                observed_block=observed_block,
                deviation_block="Ресурсный сигнал. Не доказательство отставания объёма работ.",
                last_ts=actual.timestamp,
                basis="required equipment > observed equipment (resource indicator).",
                evidence=evidence,
            )
            found.append(
                self._candidate(
                    AlertType.MISSING_EQUIPMENT,
                    _severity(self.cfg["alert"]["missing_equipment_severity"], "warning"),
                    expected,
                    actual,
                    evidence,
                    title="Признаки отсутствия техники",
                    message=message,
                    rationale="resource gap; not work-volume delay",
                    rule_id=f"equipment.required.{expected.stage}",
                    expected_payload={k: v["expected"] for k, v in missing.items()},
                    observed_payload={k: v["observed"] for k, v in missing.items()},
                    rule_confidence=0.7,
                )
            )
        unexpected = {
            name: actual.equipment_count(name)
            for name in expected.unexpected_equipment
            if actual.equipment_count(name) >= int(self.cfg["equipment"]["unexpected_min_count"])
        }
        if unexpected and enough_positive:
            names = ", ".join(_label_equipment(n) for n in unexpected)
            found.append(
                self._candidate(
                    AlertType.UNEXPECTED_EQUIPMENT,
                    _severity(self.cfg["alert"]["unexpected_equipment_severity"], "info"),
                    expected,
                    actual,
                    evidence,
                    title="Нетипичная техника для этапа",
                    message=inspector_message(
                        title="Нетипичная техника для этапа. Требуется проверка.",
                        object_id=expected.object_id,
                        zone_id=expected.zone_id,
                        expected_block="не ожидается: " + ", ".join(_label_equipment(n) for n in expected.unexpected_equipment),
                        observed_block=names,
                        deviation_block="observed equipment не типична для правил этапа",
                        last_ts=actual.timestamp,
                        basis="правило unexpected_equipment из config/equipment_rules.yaml",
                        evidence=evidence,
                    ),
                    rationale="observed equipment не типична для правил этапа.",
                    rule_id=f"equipment.unexpected.{expected.stage}",
                    expected_payload={"unexpected": expected.unexpected_equipment},
                    observed_payload=unexpected,
                    rule_confidence=0.55,
                )
            )
        return found

    def _no_dynamics(
        self,
        expected: ExpectedState,
        actual: ActualState,
        history: list[ActualState],
        expected_series: list[ExpectedState],
        evidence: list[EvidenceRef],
        visual_changes: list[float | None] | None,
    ) -> list[DeviationCandidate]:
        """No-dynamics only for a confirmed work indicator that should have moved.

        Absence of observations is not no_dynamics. Stable floors with changing
        facade are not treated as a single global stop.
        """
        states = list(history or []) + [actual]
        # Prefer visible_floor_levels when that planned indicator advances
        indicator_id = "visible_floor_levels"
        series_vals: list[tuple] = []
        for state in sorted(states, key=lambda s: s.timestamp):
            fact = (state.work_facts or {}).get(indicator_id)
            if fact is None or fact.certainty.value != "confirmed" or fact.value is None:
                continue
            series_vals.append((state, fact))
        if len(series_vals) < int(self.cfg.get("temporal", {}).get("min_states_for_no_dynamics", 3)):
            return []

        first_state, first_fact = series_vals[0]
        last_state, last_fact = series_vals[-1]
        period = (last_state.timestamp - first_state.timestamp).total_seconds() / 86400.0
        min_days = float(self.cfg.get("temporal", {}).get("min_period_days_for_no_dynamics", 14))
        if period < min_days:
            return []
        max_gap = float(self.cfg.get("temporal", {}).get("max_observation_gap_days", 7))
        gaps = [
            (series_vals[i][0].timestamp - series_vals[i - 1][0].timestamp).total_seconds() / 86400.0
            for i in range(1, len(series_vals))
        ]
        if gaps and max(gaps) > max_gap:
            return []
        cameras = {s.camera_code for s, _ in series_vals if s.camera_code}
        if self.cfg.get("temporal", {}).get("same_camera_required", True) and len(cameras) != 1:
            return []

        # Indicator itself unchanged
        if any(indicator_changed(series_vals[i - 1][1], series_vals[i][1]) for i in range(1, len(series_vals))):
            return []
        if first_fact.value != last_fact.value:
            return []

        # Plan for THIS indicator must advance
        plan_progress = 0.0
        window = [
            item
            for item in (expected_series or [])
            if first_state.timestamp.date() <= item.date <= last_state.timestamp.date()
        ]
        if len(window) >= 2:
            def _plan_val(exp):
                for ind in exp.planned_indicators or planned_indicators_from_expected(
                    schedule_row_id=exp.schedule_row_id or "x",
                    work_code=exp.stage,
                    expected=exp.expected or {},
                ):
                    if ind.indicator_id == indicator_id and ind.value is not None:
                        return float(ind.value)
                try:
                    return float((exp.expected or {}).get("floors") or 0)
                except (TypeError, ValueError):
                    return 0.0

            plan_progress = _plan_val(window[-1]) - _plan_val(window[0])
        if plan_progress <= 0:
            return []

        # Facade changed while floors stable → not global stop
        facade_changed = False
        for i in range(1, len(states)):
            prev_f = (states[i - 1].work_facts or {}).get("facade_visible")
            cur_f = (states[i].work_facts or {}).get("facade_visible")
            ch = indicator_changed(prev_f, cur_f)
            if ch:
                facade_changed = True
                break
        if facade_changed:
            return []

        related = sorted({s.timestamp.date().isoformat() for s, _ in series_vals})
        message = inspector_message(
            title="Выявлены признаки отсутствия строительной динамики. Требуется проверка.",
            object_id=expected.object_id,
            zone_id=expected.zone_id,
            expected_block=f"индикатор {indicator_id}: план +{plan_progress}",
            observed_block=f"{indicator_id} стабилен: {first_fact.value} → {last_fact.value}",
            deviation_block=(
                "По конкретному индикатору нет изменения при движении плана. "
                "Это не остановка всех работ и не отсутствие наблюдений."
            ),
            last_ts=actual.timestamp,
            basis=f"{len(series_vals)} подтверждённых фактов {indicator_id}, period={period:.1f}d",
            evidence=evidence,
        )
        return [
            self._candidate(
                AlertType.NO_DYNAMICS,
                _severity(self.cfg["alert"]["no_dynamics_severity"], "warning"),
                expected,
                actual,
                evidence,
                title="Признаки отсутствия строительной динамики",
                message=message,
                rationale="confirmed work indicator stable while plan advances",
                rule_id=f"temporal.no_dynamics.{indicator_id}",
                expected_payload={
                    "indicator_id": indicator_id,
                    "plan_progress": plan_progress,
                    "floors": (expected.expected or {}).get("floors"),
                    "schedule_progress": plan_progress,
                },
                observed_payload={
                    "indicator_id": indicator_id,
                    "value": last_fact.value,
                    "floors": last_fact.value,
                    "n_states": len(series_vals),
                    "period_days": round(period, 2),
                    "schedule_progress": plan_progress,
                    "same_camera": True,
                    "camera_code": next(iter(cameras)) if cameras else None,
                },
                rule_confidence=0.6,
                related_dates=related,
            )
        ]

    def _candidate(
        self,
        alert_type: AlertType,
        severity: Severity,
        expected: ExpectedState,
        actual: ActualState,
        evidence: list[EvidenceRef],
        *,
        title: str,
        message: str,
        rationale: str,
        rule_id: str,
        expected_payload: dict,
        observed_payload: dict,
        rule_confidence: float,
        related_dates: list[str] | None = None,
    ) -> DeviationCandidate:
        evidence_ids = [ref.observation_id for ref in evidence if ref.observation_id]
        return DeviationCandidate(
            alert_type=alert_type,
            severity=severity,
            zone_id=expected.zone_id,
            object_id=expected.object_id,
            stage=expected.stage,
            stage_label=expected.stage_label,
            title=title,
            message=message or title,
            rationale=rationale,
            expected=expected_payload,
            observed=observed_payload,
            evidence_ids=evidence_ids,
            rule_id=rule_id,
            model_confidence=actual.quality.mean_model_confidence,
            evidence_confidence=actual.quality.evidence_confidence,
            rule_confidence=rule_confidence,
            evidence=evidence,
            related_dates=related_dates or [expected.date.isoformat()],
        )
