import importlib.util
from pathlib import Path

_PATH = Path("/home/dimk/my_project/LCT2026/validation/model_selection/cmp_point_eval.py")
_SPEC = importlib.util.spec_from_file_location("cmp_point_eval", _PATH)
evalmod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(evalmod)


def test_disjoint_points_match_one_to_one():
    boxes = [(0, 0, 1, 1), (2, 2, 3, 3)]
    points = [(0.5, 0.5), (2.5, 2.5)]
    scored = evalmod.score_points(points, boxes)
    assert scored["tp"] == 2
    assert scored["fp"] == 0
    assert scored["fn"] == 0
    assert scored["identity_ambiguous_count"] == 0


def test_intersection_stays_in_the_denominator():
    boxes = [(0, 0, 2, 2), (1, 1, 3, 3)]
    scored = evalmod.score_points([(1.5, 1.5)], boxes)
    assert scored["tp"] == 1
    assert scored["fp"] == 0
    assert scored["fn"] == 1
    assert scored["n_gt"] == 2
    assert scored["n_pred"] == 1
    assert scored["identity_ambiguous_count"] == 1
    assert scored["pairs"] == [{"point": 0, "object": 0}]


def test_two_points_in_one_intersection_keep_maximum_cardinality():
    boxes = [(0, 0, 2, 2), (0, 0, 2, 2)]
    scored = evalmod.score_points([(1, 1), (1.2, 1.2)], boxes)
    assert scored["tp"] == 2
    assert scored["fp"] == 0
    assert scored["fn"] == 0
    assert len(scored["identity_ambiguous_pairs"]) == 2


def test_tie_break_preserves_maximum_cardinality():
    boxes = [(0, 0, 2, 2), (1, 0, 3, 2)]
    points = [(1.5, 1), (2.5, 1)]
    scored = evalmod.score_points(points, boxes)
    assert (scored["tp"], scored["fp"], scored["fn"]) == (2, 0, 0)
    assert scored["pairs"] == [{"point": 0, "object": 0}, {"point": 1, "object": 1}]


def test_extra_point_inside_a_taken_box_is_fp_and_count_is_separate():
    boxes = [(0, 0, 1, 1)]
    scored = evalmod.score_points([(0.2, 0.2), (0.8, 0.8)], boxes)
    assert scored["tp"] == 1
    assert scored["fp"] == 1
    assert scored["fn"] == 0
    assert scored["count_error"] == 1
    assert scored["abs_count_error"] == 1


def test_range_in_text_is_not_a_decoded_point():
    text = '<points coords="1">visible window</point> 30–39: 30. 31.'
    audit = evalmod.decode_audit(text, [[1, 0, 10, 20]], 100, 200, False)
    assert audit["undecoded_range_in_text"] is True
    assert audit["n_points_decoded"] == 1
    assert audit["coordinates_outside_image"] == []
    outside = evalmod.decode_audit(text, [[1, 0, 500, 20]], 100, 200, False)
    assert outside["coordinates_outside_image"] == [0]
