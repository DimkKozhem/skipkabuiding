"""Daybook chronology text must stay Russian for the inspector UI."""

from datetime import datetime

from sitewatch.temporal.daybook import DayFrame, daily_summary, looks_english, russian_summary_for_frame


def test_looks_english_detects_vlm_prose():
    assert looks_english(
        "The building under construction has a completed facade with visible floor slabs."
    )
    assert not looks_english("На кадре видно корпус с фасадом. Признаки отделочных работ.")


def test_russian_summary_replaces_english_vlm_text():
    frame = DayFrame(
        observation_id="o1",
        camera_id="cam",
        timestamp=datetime(2023, 1, 29, 12, 0, 0),
        image_path="",
        summary="The building under construction has a completed facade. An excavator is present.",
        elements={"facade": {"count": 1}, "floors": {"count": 2}},
        equipment={"excavator": {"count": 1}},
    )
    text = russian_summary_for_frame(frame)
    assert "The building" not in text
    assert "экскаватор" in text
    assert looks_english(text) is False


def test_daily_summary_stays_russian():
    frames = [
        DayFrame(
            observation_id="o1",
            camera_id="cam",
            timestamp=datetime(2023, 1, 29, 12, 0, 0),
            image_path="",
            summary="The building under construction has a completed facade with visible floor slabs.",
            elements={"facade": {"count": 1}},
            equipment={},
        )
    ]
    summary = daily_summary(frames)
    assert "The building" not in summary
    assert looks_english(summary) is False
