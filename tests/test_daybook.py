from datetime import datetime
from pathlib import Path

from PIL import Image

from sitewatch.temporal.daybook import DayFrame, hamming, keep_distinct, roll_day


def _image(path: Path, color: tuple[int, int, int], *, band: bool = False) -> None:
    image = Image.new("RGB", (64, 64), color)
    if band:
        for x in range(64):
            for y in range(24):
                image.putpixel((x, y), (0, 0, 0))
    image.save(path)


def _frame(obs: str, path: Path, hour: int, summary: str, floors: int, camera: str = "cam-1") -> DayFrame:
    return DayFrame(
        observation_id=obs,
        camera_id=camera,
        timestamp=datetime(2026, 9, 1, hour, 0),
        image_path=str(path),
        summary=summary,
        elements={"floors": {"count": floors}},
        equipment={},
    )


def test_near_duplicate_frames_are_dropped_and_day_is_one_story(tmp_path: Path):
    morning = tmp_path / "morning.jpg"
    twin = tmp_path / "twin.jpg"
    evening = tmp_path / "evening.jpg"
    _image(morning, (30, 30, 30))
    _image(twin, (30, 30, 30))
    _image(evening, (210, 160, 40), band=True)
    frames = [
        _frame("a", morning, 8, "Утро: каркас четвёртого этажа.", 4),
        _frame("b", twin, 8, "Почти тот же кадр.", 4),
        _frame("c", evening, 18, "Вечер: виден ещё один этаж.", 5),
    ]
    roll = roll_day(frames, max_distance=6)
    assert roll.dropped_ids == ["b"]
    assert roll.kept_ids == ["a", "c"]
    assert roll.summary.startswith("К началу суток: Утро:")
    assert "К концу суток: Вечер:" in roll.summary
    assert roll.done == "По кадрам за сутки отмечено: этажи 4 → 5."


def test_same_view_on_another_camera_is_kept(tmp_path: Path):
    left = tmp_path / "left.jpg"
    right = tmp_path / "right.jpg"
    _image(left, (10, 10, 10))
    _image(right, (10, 10, 10))
    kept, dropped = keep_distinct(
        [
            _frame("a", left, 9, "Север.", 2, camera="north"),
            _frame("b", right, 9, "Юг.", 2, camera="south"),
        ],
        max_distance=0,
    )
    assert dropped == []
    assert [item.observation_id for item in kept] == ["a", "b"]
    assert hamming(0b111, 0b101) == 1
