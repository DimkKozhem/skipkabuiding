from datetime import date

import pytest

from sitewatch.domain.contracts import DeviationCandidate
from sitewatch.domain.enums import AlertType, Severity
from sitewatch.inspector.workflow import candidate_fingerprint, reasons_for_status, validate_decision
from sitewatch.pipeline.evaluate import evaluate_zone_date
from sitewatch.pipeline.seed import seed_demo
from sitewatch.services.queries import get_alert, inspection_brief, list_alerts, set_alert_status
from sitewatch.storage.db import get_session
from sitewatch.storage.models import Alert, AlertEvent


def _candidate(**extra) -> DeviationCandidate:
    payload = {
        "alert_type": AlertType.MISSING_EQUIPMENT,
        "severity": Severity.WARNING,
        "zone_id": "zone_b",
        "object_id": "site_001",
        "title": "t",
        "rationale": "r",
        "rule_id": "equipment.required.excavation",
        "expected": {"dump_truck": 2},
        "observed": {"dump_truck": 0},
        "related_dates": ["2026-09-18"],
    }
    payload.update(extra)
    return DeviationCandidate(**payload)


def test_fingerprint_is_stable_and_sensitive_to_expected():
    a = _candidate()
    b = _candidate()
    assert candidate_fingerprint(a) == candidate_fingerprint(b)
    c = _candidate(expected={"dump_truck": 3})
    assert candidate_fingerprint(a) != candidate_fingerprint(c)


def test_decision_requires_known_reason():
    validate_decision("open", "")
    with pytest.raises(ValueError, match="reason"):
        validate_decision("rejected", "")
    with pytest.raises(ValueError, match="unknown reason"):
        validate_decision("rejected", "not_a_reason")
    validate_decision("rejected", "false_detection")
    assert "false_detection" in reasons_for_status("rejected")
    assert "need_other_camera" in reasons_for_status("needs_more_data")


def test_reevaluate_does_not_duplicate_alerts():
    seed_demo()
    with get_session() as session:
        before = session.query(Alert).count()
        events_before = session.query(AlertEvent).count()
    again = evaluate_zone_date(project_code="site_001", zone_code="zone_b", on_date=date(2026, 9, 18))
    with get_session() as session:
        after = session.query(Alert).count()
        missing = session.query(Alert).filter_by(alert_type="missing_equipment").count()
    assert after == before
    assert missing == 1
    assert again
    with get_session() as session:
        assert session.query(AlertEvent).count() == events_before


def test_inspector_decision_and_brief():
    seed_demo()
    missing = next(item for item in list_alerts() if item["type"] == "missing_equipment")
    assert missing["status"] == "open"
    assert missing["fingerprint"]

    with pytest.raises(ValueError):
        set_alert_status(missing["id"], "rejected")

    detail = set_alert_status(
        missing["id"],
        "rejected",
        reason="false_detection",
        note="самосвал вне кадра",
        actor="inspector",
    )
    assert detail["status"] == "rejected"
    assert detail["decision_reason"] == "false_detection"
    assert detail["decided_by"] == "inspector"
    actions = [item["action"] for item in detail["events"]]
    assert "created" in actions
    assert "decided" in actions

    brief = inspection_brief(missing["id"])
    assert brief["expected"]["dump_truck"] == 2
    assert brief["observed"]["dump_truck"] == 0
    assert brief["on_site_checks"]
    assert brief["evidence"]
    assert "не принимает юридическое" in brief["disclaimer"].lower()
    assert "остановлен" not in (brief["message"] or "").lower()

    open_ids = {item["id"] for item in list_alerts(status="open")}
    assert missing["id"] not in open_ids
    rejected_ids = {item["id"] for item in list_alerts(status="rejected")}
    assert missing["id"] in rejected_ids

    evaluate_zone_date(project_code="site_001", zone_code="zone_b", on_date=date(2026, 9, 18))
    still = get_alert(missing["id"])
    assert still["status"] == "rejected"
    with get_session() as session:
        assert session.query(Alert).filter_by(alert_type="missing_equipment").count() == 1


def test_needs_more_data_stays_on_same_card():
    seed_demo()
    nd = next(item for item in list_alerts() if item["type"] == "no_dynamics")
    updated = set_alert_status(nd["id"], "needs_more_data", reason="need_other_camera")
    assert updated["status"] == "needs_more_data"
    evaluate_zone_date(project_code="site_001", zone_code="building_01", on_date=date(2026, 9, 22))
    again = get_alert(nd["id"])
    assert again["status"] == "needs_more_data"
