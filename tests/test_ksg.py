from datetime import date
from pathlib import Path

from sitewatch.ksg.expected import build_expected_state
from sitewatch.ksg.parser import parse_ksg
from sitewatch.pipeline.seed import KSG_CSV


def test_parse_ksg_csv(tmp_path: Path):
    path = tmp_path / "ksg.csv"
    path.write_text(KSG_CSV, encoding="utf-8")
    rows = parse_ksg(path)
    assert len(rows) == 6
    building = [row for row in rows if row["zone"] == "building_01"]
    assert building[0]["expected"]["floors"] == 4
    assert building[-1]["expected"]["floors"] == 6
    assert building[-1]["date"] == date(2026, 9, 22)
    assert building[-1]["start_date"] == date(2026, 9, 22)
    assert building[-1]["end_date"] == date(2026, 9, 28)


def test_parse_ksg_uses_default_zone(tmp_path: Path):
    path = tmp_path / "ksg.csv"
    path.write_text("date,stage,floors\n2026-09-01,superstructure,4\n", encoding="utf-8")
    rows = parse_ksg(path, default_zone="building_02", default_project="site_field")
    assert rows[0]["zone"] == "building_02"
    assert rows[0]["project_code"] == "site_field"
    assert rows[0]["expected"]["floors"] == 4


def test_parse_ksg_json(tmp_path: Path):
    path = tmp_path / "ksg.json"
    path.write_text(
        """
        {
          "stages": [
            {
              "stage": "foundation",
              "zone": "zone_01",
              "start_date": "2026-09-01",
              "end_date": "2026-09-15",
              "expected": {"foundation": true, "columns": 12}
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    rows = parse_ksg(path)
    assert len(rows) == 1
    assert rows[0]["stage"] == "foundation"
    assert rows[0]["expected"]["foundation"] is True
    assert rows[0]["expected"]["columns"] == 12
    assert rows[0]["end_date"] == date(2026, 9, 15)


def test_expected_state_loads_rules_from_yaml():
    state = build_expected_state(
        object_id="site_001",
        zone_id="zone_a",
        on_date=date(2026, 9, 18),
        stage="excavation",
        expected={"floors": 0, "foundation": False},
    )
    types = {item["type"] for item in state.required_equipment}
    assert types == {"excavator", "dump_truck"}
    assert "concrete_mixer" in state.unexpected_equipment
    assert state.stage_label == "Разработка котлована"
