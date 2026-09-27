from types import SimpleNamespace

from sitewatch.services.queries import frame_usable, pick_baseline


def _obs(oid: str, camera: str, media: str):
    return SimpleNamespace(id=oid, camera_id=camera, media_id=media)


def test_baseline_is_the_first_usable_frame_of_the_same_camera():
    history = [
        _obs("poor", "cam-a", "m1"),
        _obs("first", "cam-a", "m2"),
        _obs("other", "cam-b", "m3"),
        _obs("yesterday", "cam-a", "m4"),
        _obs("now", "cam-a", "m5"),
    ]
    quality = {
        "poor": {"quality": {"visibility": "poor", "coverage": "full"}},
        "first": {"quality": {"visibility": "good", "coverage": "full"}},
        "yesterday": {"quality": {"visibility": "good", "coverage": "full"}},
        "now": {"quality": {"visibility": "good", "coverage": "full"}},
    }
    picked = pick_baseline(history, history[-1], lambda obs: frame_usable(quality.get(obs.id)))
    assert picked.id == "first"


def test_baseline_hidden_when_only_another_camera_exists():
    history = [
        _obs("old", "cam-b", "m1"),
        _obs("now", "cam-a", "m2"),
    ]
    picked = pick_baseline(history, history[-1], lambda obs: True)
    assert picked is None


def test_different_viewpoint_is_skipped_for_the_next_matching_frame():
    history = [
        _obs("side", "cam-a", "m1"),
        _obs("front", "cam-a", "m2"),
        _obs("now", "cam-a", "m3"),
    ]
    quality = {
        "side": {"quality": {"visibility": "good", "coverage": "full"}, "scene_attributes": {"viewpoint": "side"}},
        "front": {"quality": {"visibility": "good", "coverage": "full"}, "scene_attributes": {"viewpoint": "front"}},
        "now": {"quality": {"visibility": "good", "coverage": "full"}, "scene_attributes": {"viewpoint": "front"}},
    }
    current_view = "front"

    def usable(obs):
        payload = quality.get(obs.id)
        view = (payload or {}).get("scene_attributes", {}).get("viewpoint")
        if not frame_usable(payload):
            return False
        return not (current_view and view and view != current_view)

    picked = pick_baseline(history, history[-1], usable)
    assert picked.id == "front"


def test_unknown_coverage_is_not_a_baseline():
    assert frame_usable({"quality": {"visibility": "good", "coverage": "unknown"}}) is False
    assert frame_usable({"quality": {"visibility": "good", "coverage": "full"}}) is True
