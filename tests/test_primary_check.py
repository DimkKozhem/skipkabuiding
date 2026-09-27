from types import SimpleNamespace

from sitewatch.services.queries import primary_check


def _row(id_: str, alert_type: str, status: str = "open"):
    return SimpleNamespace(id=id_, alert_type=alert_type, status=status)


def test_primary_check_prefers_open_dynamics():
    chosen = primary_check([
        _row("equip", "missing_equipment"),
        _row("dyn", "no_dynamics"),
        _row("closed", "schedule_delay", "rejected"),
    ])
    assert chosen == {"id": "dyn", "type": "no_dynamics", "status": "open"}


def test_primary_check_keeps_needs_more_data_when_nothing_is_open():
    chosen = primary_check([
        _row("ask", "insufficient_evidence", "needs_more_data"),
        _row("done", "schedule_delay", "confirmed"),
    ])
    assert chosen == {"id": "ask", "type": "insufficient_evidence", "status": "needs_more_data"}


def test_primary_check_empty():
    assert primary_check([]) is None


def test_primary_check_ignores_model_candidate():
    assert primary_check([_row("shadow", "model_candidate")]) is None
    chosen = primary_check([
        _row("shadow", "model_candidate"),
        _row("equip", "missing_equipment"),
    ])
    assert chosen == {"id": "equip", "type": "missing_equipment", "status": "open"}
