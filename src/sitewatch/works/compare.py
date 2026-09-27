"""Compare PlannedIndicator ↔ WorkFact. Never invent schedule_delay from unknown."""

from __future__ import annotations

from datetime import date, datetime

from sitewatch.domain.contracts import (
    ActualState,
    IndicatorCheckResult,
    PlannedIndicator,
    WorkFact,
)
from sitewatch.domain.enums import (
    CheckOutcome,
    IndicatorKind,
    ObservationCoverage,
    WorkCertainty,
)
from sitewatch.works.rules import work_rules


def freshness_hours(*, captured_at: datetime, evaluation_as_of: date) -> float:
    """Age of the observation relative to evaluation_as_of (not wall-clock today)."""
    as_of_dt = datetime.combine(evaluation_as_of, datetime.min.time())
    return max((as_of_dt - captured_at.replace(tzinfo=None)).total_seconds() / 3600.0, 0.0)


def check_one(
    planned: PlannedIndicator,
    fact: WorkFact | None,
    *,
    evaluation_as_of: date,
    last_observation_date: date | None = None,
) -> IndicatorCheckResult:
    if last_observation_date is not None and evaluation_as_of > last_observation_date:
        if fact is None or fact.as_of is None or fact.as_of < evaluation_as_of:
            # only emit no_observation_after when evaluating past the series tip
            if fact is None:
                return IndicatorCheckResult(
                    outcome=CheckOutcome.NO_OBSERVATION_AFTER,
                    planned=planned,
                    fact=None,
                    title="Нет нового наблюдения после последнего кадра",
                    rationale=(
                        f"Оценка на {evaluation_as_of.isoformat()}, последний кадр "
                        f"{last_observation_date.isoformat()}. Это не остановка работ."
                    ),
                    rule_id="time.no_observation_after",
                    evaluation_as_of=evaluation_as_of,
                )

    if fact is None:
        return IndicatorCheckResult(
            outcome=CheckOutcome.INSUFFICIENT_DATA,
            planned=planned,
            fact=None,
            title="Недостаточно данных по показателю",
            rationale=f"Нет WorkFact для индикатора «{planned.indicator_id}».",
            rule_id="work.insufficient_data",
            evaluation_as_of=evaluation_as_of,
        )

    if fact.certainty == WorkCertainty.MEASUREMENT_UNIMPLEMENTED or planned.kind == IndicatorKind.LENGTH_M and (
        fact.certainty == WorkCertainty.MEASUREMENT_UNIMPLEMENTED or fact.method in {"", "unimplemented"}
    ):
        return IndicatorCheckResult(
            outcome=CheckOutcome.MEASUREMENT_UNIMPLEMENTED,
            planned=planned,
            fact=fact,
            title="Метод измерения отсутствует",
            rationale=(
                f"План задаёт «{planned.indicator_id}» ({planned.unit or 'без единицы'}), "
                "но метод измерения не реализован. Нужна калибровка/масштаб — не отставание графика."
            ),
            rule_id="work.measurement_unimplemented",
            evaluation_as_of=evaluation_as_of,
        )

    if fact.certainty == WorkCertainty.NOT_OBSERVABLE or fact.coverage == ObservationCoverage.TARGET_NOT_IN_FRAME:
        return IndicatorCheckResult(
            outcome=CheckOutcome.NEEDS_CAPTURE_OR_CALIBRATION,
            planned=planned,
            fact=fact,
            title="Нужна дополнительная съёмка или зона объекта",
            rationale="; ".join(fact.limitations) or "целевой объект не наблюдается на кадре",
            rule_id="work.needs_capture",
            evaluation_as_of=evaluation_as_of,
        )

    if fact.certainty == WorkCertainty.PROCESSING_ERROR:
        return IndicatorCheckResult(
            outcome=CheckOutcome.INSUFFICIENT_DATA,
            planned=planned,
            fact=fact,
            title="Ошибка обработки показателя",
            rationale="; ".join(fact.limitations) or "сбой метода",
            rule_id="work.processing_error",
            evaluation_as_of=evaluation_as_of,
        )

    if fact.certainty in {WorkCertainty.UNKNOWN, WorkCertainty.CONTRADICTION}:
        return IndicatorCheckResult(
            outcome=CheckOutcome.INSUFFICIENT_DATA,
            planned=planned,
            fact=fact,
            title="Недостаточно подтверждения факта",
            rationale="; ".join(fact.limitations) or fact.certainty.value,
            rule_id="work.insufficient_certainty",
            evaluation_as_of=evaluation_as_of,
        )

    if planned.kind != fact.kind and not (
        planned.kind == IndicatorKind.RESOURCE_COUNT and fact.kind == IndicatorKind.RESOURCE_COUNT
    ):
        return IndicatorCheckResult(
            outcome=CheckOutcome.INCOMPARABLE,
            planned=planned,
            fact=fact,
            title="План и наблюдение несопоставимы",
            rationale=f"Разный смысл показателей: план {planned.kind.value}, факт {fact.kind.value}.",
            rule_id="work.incomparable_kind",
            evaluation_as_of=evaluation_as_of,
        )

    if planned.unit and fact.unit and planned.unit != fact.unit:
        return IndicatorCheckResult(
            outcome=CheckOutcome.INCOMPARABLE,
            planned=planned,
            fact=fact,
            title="Несовместимые единицы",
            rationale=f"План: {planned.unit}, факт: {fact.unit}.",
            rule_id="work.incomparable_unit",
            evaluation_as_of=evaluation_as_of,
        )

    if (
        fact.coverage == ObservationCoverage.PARTIAL
        and planned.kind in {IndicatorKind.COUNT, IndicatorKind.LENGTH_M}
    ):
        return IndicatorCheckResult(
            outcome=CheckOutcome.INSUFFICIENT_DATA,
            planned=planned,
            fact=fact,
            title="Частичное покрытие не является фактом по всему объекту",
            rationale=(
                "На кадре видна только часть области. Число нельзя сравнивать с планом объекта "
                "и нельзя превращать в отставание графика."
            ),
            rule_id="work.partial_not_whole_object",
            evaluation_as_of=evaluation_as_of,
        )

    if fact.certainty != WorkCertainty.CONFIRMED or fact.value is None:
        return IndicatorCheckResult(
            outcome=CheckOutcome.INSUFFICIENT_DATA,
            planned=planned,
            fact=fact,
            title="Факт не подтверждён",
            rationale="Нет подтверждённого значения индикатора.",
            rule_id="work.unconfirmed",
            evaluation_as_of=evaluation_as_of,
        )

    # Confirmed value vs plan
    tol = work_rules().get("tolerance") or {}
    if planned.kind in {IndicatorKind.COUNT, IndicatorKind.RESOURCE_COUNT, IndicatorKind.LENGTH_M}:
        try:
            exp = float(planned.value) if planned.value is not None else None
            got = float(fact.value)
        except (TypeError, ValueError):
            return IndicatorCheckResult(
                outcome=CheckOutcome.INCOMPARABLE,
                planned=planned,
                fact=fact,
                title="Несопоставимые значения",
                rationale="Не удалось сравнить числовые значения.",
                rule_id="work.incomparable_value",
                evaluation_as_of=evaluation_as_of,
            )
        if exp is None:
            return IndicatorCheckResult(
                outcome=CheckOutcome.INCOMPARABLE,
                planned=planned,
                fact=fact,
                title="В плане нет числового значения",
                rationale="Показатель без планового значения.",
                rule_id="work.incomparable_plan",
                evaluation_as_of=evaluation_as_of,
            )
        allow = float(tol.get("count" if planned.kind != IndicatorKind.RESOURCE_COUNT else "resource_count") or 0)
        if exp - got > allow:
            return IndicatorCheckResult(
                outcome=CheckOutcome.DEVIATION,
                planned=planned,
                fact=fact,
                title="Возможное отклонение по показателю",
                rationale=(
                    f"План «{planned.confirms or planned.indicator_id}»: {exp} {planned.unit or ''}. "
                    f"Факт: {got} {fact.unit or ''}. Подтверждает только этот индикатор, не завершение этапа."
                ),
                rule_id="work.deviation_count",
                evaluation_as_of=evaluation_as_of,
            )
        return IndicatorCheckResult(
            outcome=CheckOutcome.MATCH,
            planned=planned,
            fact=fact,
            title="Соответствие по показателю",
            rationale=f"План {exp}, факт {got} ({planned.indicator_id}).",
            rule_id="work.match_count",
            evaluation_as_of=evaluation_as_of,
        )

    if planned.kind in {IndicatorKind.PRESENCE, IndicatorKind.STAGE_SIGN}:
        want = bool(planned.value) if planned.value is not None else True
        got = bool(fact.value)
        if want and not got:
            return IndicatorCheckResult(
                outcome=CheckOutcome.DEVIATION,
                planned=planned,
                fact=fact,
                title="Возможное отклонение: признак не наблюдается",
                rationale=(
                    f"План ожидает признак «{planned.confirms or planned.indicator_id}». "
                    "Факт: не наблюдается. Это не вердикт о завершении работы."
                ),
                rule_id="work.deviation_presence",
                evaluation_as_of=evaluation_as_of,
            )
        return IndicatorCheckResult(
            outcome=CheckOutcome.MATCH,
            planned=planned,
            fact=fact,
            title="Соответствие по признаку",
            rationale=f"Признак «{planned.indicator_id}»: план={want}, факт={got}.",
            rule_id="work.match_presence",
            evaluation_as_of=evaluation_as_of,
        )

    return IndicatorCheckResult(
        outcome=CheckOutcome.INCOMPARABLE,
        planned=planned,
        fact=fact,
        title="Несопоставимый тип показателя",
        rationale=str(planned.kind),
        rule_id="work.incomparable_fallback",
        evaluation_as_of=evaluation_as_of,
    )


def check_indicators(
    planned: list[PlannedIndicator],
    actual: ActualState,
    *,
    evaluation_as_of: date,
    last_observation_date: date | None = None,
) -> list[IndicatorCheckResult]:
    facts = actual.work_facts or {}
    return [
        check_one(
            item,
            facts.get(item.indicator_id),
            evaluation_as_of=evaluation_as_of,
            last_observation_date=last_observation_date,
        )
        for item in planned
    ]


def indicator_changed(prev: WorkFact | None, curr: WorkFact | None) -> bool | None:
    """True/False if both confirmed; None if not comparable."""
    if prev is None or curr is None:
        return None
    if prev.certainty != WorkCertainty.CONFIRMED or curr.certainty != WorkCertainty.CONFIRMED:
        return None
    return prev.value != curr.value
