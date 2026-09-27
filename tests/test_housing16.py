from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from sitewatch.api.main import create_app
from sitewatch.ksg.expected import load_equipment_rules
from sitewatch.pipeline import housing16
from sitewatch.pipeline.seed import seed_demo
from sitewatch.settings import project_root


@pytest.fixture
def housing_files(tmp_path, monkeypatch):
    load_equipment_rules.cache_clear()
    src = project_root() / "data" / "scenarios" / "housing_16"
    dest = tmp_path / "scenarios" / "housing_16"
    dest.mkdir(parents=True)
    shutil.copy2(src / "ksg.csv", dest / "ksg.csv")
    shutil.copy2(src / "catalog.json", dest / "catalog.json")
    monkeypatch.setattr(housing16, "scenario_dir", lambda: dest)
    return dest


def _write_blank_video(path: Path, *, seconds: float = 8.0, fps: float = 5.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    w, h = 64, 48
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    assert writer.isOpened(), "opencv cannot write test mp4"
    n = int(seconds * fps)
    for i in range(max(n, 1)):
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:, :] = (i * 3) % 255
        writer.write(frame)
    writer.release()
    return path


def test_housing_schedule_get(housing_files):
    client = TestClient(create_app())
    resp = client.get("/api/projects/housing_16/schedule")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["project_id"] == "housing_16"
    assert body["title"] == "Жилой дом, 16 этажей"
    assert body["video_url"] == "/media/video/triumph_park_phase5.mp4"
    assert body["videos"][0]["url"] == "/media/video/triumph_park_phase5.mp4"
    assert body["videos"][0]["runs_pipeline"] is True
    assert body["videos"][1]["id"] == "huntington_apartments"
    assert body["videos"][1]["url"] == "/media/video/huntington_apartments.mp4"
    assert body["videos"][1]["runs_pipeline"] is False
    assert body["frame_interval_minutes"] == 30
    assert len(body["rows"]) == 21
    floors = [row["plan_floors"] for row in body["rows"] if row["stage"] == "superstructure"]
    assert floors == list(range(1, 17))
    assert all(row["fact_floors"] is None for row in body["rows"])
    assert all(row["status"] == "planned" for row in body["rows"])
    sample = next(row for row in body["rows"] if row["title"] == "Каркас, этаж 3")
    assert sample["catalog_code"] == "12.4.29"
    # 2+4+2+2 frames before the frame, then floors 1 and 2: этаж 3 starts at 08:00+12*30min
    assert sample["date_start"] == "2026-04-01T14:00:00"
    assert sample["date_end"] == "2026-04-01T14:30:00"
    frame_rows = [row for row in body["rows"] if row["stage"] == "superstructure"]
    first = datetime.fromisoformat(frame_rows[0]["date_start"])
    second = datetime.fromisoformat(frame_rows[1]["date_start"])
    assert second - first == timedelta(minutes=30)


def test_housing_schedule_upload_valid_and_reject(housing_files, tmp_path):
    client = TestClient(create_app())
    valid = housing_files / "ksg.csv"
    ok = client.post(
        "/api/projects/housing_16/schedule",
        files={"file": ("ksg.csv", valid.read_bytes(), "text/csv")},
    )
    assert ok.status_code == 200, ok.text
    assert len(ok.json()["rows"]) == 21

    bad = tmp_path / "bad.csv"
    lines = valid.read_text(encoding="utf-8").splitlines()
    # Drop floors 11–16 so max floors = 10
    kept = [lines[0]]
    for line in lines[1:]:
        if ",superstructure," in line:
            floors = int(line.split(",")[5])
            if floors > 10:
                continue
        kept.append(line)
    bad.write_text("\n".join(kept) + "\n", encoding="utf-8")
    rejected = client.post(
        "/api/projects/housing_16/schedule",
        files={"file": ("bad.csv", bad.read_bytes(), "text/csv")},
    )
    assert rejected.status_code == 400
    assert "16" in rejected.json()["detail"]


def test_housing_run_synthetic_video(housing_files, tmp_path, monkeypatch):
    video = _write_blank_video(tmp_path / "triumph_park_phase5.mp4", seconds=8.0, fps=5.0)
    monkeypatch.setattr(housing16, "video_path", lambda: video)
    monkeypatch.setattr(
        housing16,
        "VIDEO_WINDOWS",
        [
            ("site_setup", 0.2, 1.0, 1),
            ("excavation", 1.0, 2.0, 1),
            ("foundation", 2.0, 3.0, 1),
            ("underground", 3.0, 4.0, 1),
            ("superstructure", 4.0, 6.5, 16),
            ("facade", 6.5, 7.8, 2),
        ],
    )
    client = TestClient(create_app())
    # Ensure schedule is loaded
    assert client.get("/api/projects/housing_16/schedule").status_code == 200

    first = client.post("/api/projects/housing_16/run")
    assert first.status_code == 200, first.text
    body = first.json()
    assert "run" in body
    assert body["run"]["frames_processed"] == 22
    assert body["run"]["frame_interval_minutes"] == 30
    assert body["run"]["video_duration_sec"] > 0
    assert isinstance(body["run"]["signals"], list)
    # Scenario fills floors → some rows leave planned
    assert any(row["fact_floors"] is not None for row in body["rows"])
    assert any(row["status"] in {"done", "attention"} for row in body["rows"])
    for signal in body["run"]["signals"]:
        text = signal["text"].lower()
        assert "остановлен" not in text
        assert "нарушил" not in text
        assert "не соответствует проекту" not in text

    signal_count = len(body["run"]["signals"])
    second = client.post("/api/projects/housing_16/run")
    assert second.status_code == 200
    # Fingerprint: open signal count must not grow on re-run
    assert len(second.json()["run"]["signals"]) == signal_count


def test_housing_run_missing_video_404(housing_files, tmp_path, monkeypatch):
    missing = tmp_path / "no_such.mp4"
    monkeypatch.setattr(housing16, "video_path", lambda: missing)
    client = TestClient(create_app())
    resp = client.post("/api/projects/housing_16/run")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "видео ещё не загружено"


def test_media_video_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "sitewatch.api.main.project_root",
        lambda: tmp_path,
    )
    (tmp_path / "video").mkdir()
    client = TestClient(create_app())
    resp = client.get("/media/video/triumph_park_phase5.mp4")
    assert resp.status_code == 404
    assert "видео" in resp.json()["detail"]


def test_housing_does_not_break_site_001(housing_files):
    seed_demo()
    client = TestClient(create_app())
    # housing schedule still works
    assert client.get("/api/projects/housing_16/schedule").status_code == 200
    page_a = client.get("/api/projects/site_001/zones/zone_a").json()
    assert page_a["observations"]
    page_b = client.get("/api/projects/site_001/zones/zone_b").json()
    assert any(item["type"] == "missing_equipment" for item in page_b["alerts"])
    page_c = client.get("/api/projects/site_001/zones/building_01").json()
    types = {item["type"] for item in page_c["alerts"]}
    assert "no_dynamics" in types
