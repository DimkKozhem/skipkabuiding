from datetime import datetime

from sitewatch.cv.video import aggregate_video_counts, sample_frame_indices
from sitewatch.domain.contracts import BBox, Detection
from sitewatch.pipeline.demo_assets import generate_demo_assets
from sitewatch.pipeline.observe import observe_video
from sitewatch.pipeline.seed import seed_catalog


def test_sample_1_to_3_fps_from_30fps():
    indices = sample_frame_indices(300, src_fps=30, sample_fps=2)
    assert indices[0] == 0
    assert indices[1] - indices[0] == 15
    assert len(indices) == 20


def test_video_window_aggregation_uses_tracks():
    frames = [
        [
            Detection(
                class_name="dump_truck",
                bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                confidence=0.9,
                track_id=1,
                model_name="t",
            ),
            Detection(
                class_name="excavator",
                bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                confidence=0.9,
                track_id=7,
                model_name="t",
            ),
        ],
        [
            Detection(
                class_name="dump_truck",
                bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                confidence=0.8,
                track_id=1,
                model_name="t",
            ),
            Detection(
                class_name="dump_truck",
                bbox=BBox(x1=0, y1=0, x2=1, y2=1),
                confidence=0.8,
                track_id=2,
                model_name="t",
            ),
        ],
    ]
    counts = aggregate_video_counts(frames)
    assert counts["dump_truck"] == 2
    assert counts["excavator"] == 1


class _FakeDetector:
    name = "fake"

    def detect(self, image_path):
        return [
            Detection(
                class_name="excavator",
                bbox=BBox(x1=10, y1=10, x2=40, y2=40),
                confidence=0.9,
                model_name="fake",
            ),
            Detection(
                class_name="dump_truck",
                bbox=BBox(x1=50, y1=10, x2=90, y2=40),
                confidence=0.88,
                model_name="fake",
            ),
            Detection(
                class_name="dump_truck",
                bbox=BBox(x1=100, y1=10, x2=140, y2=40),
                confidence=0.84,
                model_name="fake",
            ),
        ]


def test_observe_video_builds_observation_window():
    seed_catalog()
    root = generate_demo_assets()
    video = root / "video" / "zone_a_window.mp4"
    state = observe_video(
        video_path=video,
        project_code="site_001",
        zone_code="zone_a",
        camera_code="cam_pit_a",
        timestamp=datetime.fromisoformat("2026-09-18T10:00:00"),
        detector=_FakeDetector(),
    )
    assert state.quality.n_frames >= 1
    assert state.quality.window_start is not None
    assert state.quality.window_end is not None
    assert state.equipment_count("excavator") >= 1
    assert state.scene_attributes["video"]["sample_fps"] > 0
    assert state.scene_attributes["video"]["source_fps"] > 0
    assert state.quality.window_end > state.quality.window_start
