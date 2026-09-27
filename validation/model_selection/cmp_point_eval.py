"""Сопоставление точек с прямоугольниками XML одного класса.

Точка внутри прямоугольника — допустимая пара. Среди сопоставлений
максимальной мощности берётся лексикографически первое: точки по
возрастанию индекса, для каждой — наименьший индекс объекта, при котором
остаток всё ещё допускает максимальную мощность. Непопавшие точки — FP,
непопавшие объекты — FN. Точка в нескольких прямоугольниках помечается
как неоднозначная по идентичности и остаётся в числителе и знаменателе.
"""

from __future__ import annotations

import re


def _inside(point: tuple[float, float], box: tuple[float, float, float, float]) -> bool:
    x, y = point
    x0, y0, x1, y1 = box
    return x0 <= x <= x1 and y0 <= y <= y1


def _maximum_matching(adj: list[list[int]]) -> int:
    n_obj = 1 + max((obj for row in adj for obj in row), default=-1)
    match_obj = [-1] * n_obj

    def dfs(point: int, seen: list[bool]) -> bool:
        for obj in adj[point]:
            if seen[obj]:
                continue
            seen[obj] = True
            if match_obj[obj] == -1 or dfs(match_obj[obj], seen):
                match_obj[obj] = point
                return True
        return False

    size = 0
    for point in range(len(adj)):
        if dfs(point, [False] * n_obj):
            size += 1
    return size


def maximum_cardinality_pairs(points: list[tuple[float, float]], boxes: list[tuple[float, float, float, float]]) -> list[tuple[int, int]]:
    """Пары (индекс точки, индекс прямоугольника)."""
    adj = [[obj for obj, box in enumerate(boxes) if _inside(point, box)] for point in points]
    pairs: list[tuple[int, int]] = []
    remaining_points = list(range(len(points)))
    remaining_objects = list(range(len(boxes)))
    target = _maximum_matching(adj)
    while target:
        placed = False
        for point in remaining_points:
            candidates = [obj for obj in remaining_objects if obj in adj[point]]
            for obj in candidates:
                trial_points = [item for item in remaining_points if item != point]
                trial_objects = [item for item in remaining_objects if item != obj]
                trial_adj = [[item for item in adj[index] if item in trial_objects] for index in trial_points]
                if _maximum_matching(trial_adj) == target - 1:
                    pairs.append((point, obj))
                    remaining_points.remove(point)
                    remaining_objects.remove(obj)
                    target -= 1
                    placed = True
                    break
            if placed:
                break
        if not placed:
            break
    return pairs


def score_points(
    points: list[tuple[float, float]],
    boxes: list[tuple[float, float, float, float]],
) -> dict:
    membership = [[obj for obj, box in enumerate(boxes) if _inside(point, box)] for point in points]
    pairs = maximum_cardinality_pairs(points, boxes)
    matched_points = {point for point, _obj in pairs}
    matched_objects = {obj for _point, obj in pairs}
    ambiguous_pairs = [
        {"point": point, "object": obj, "also_inside": membership[point]}
        for point, obj in pairs
        if len(membership[point]) > 1
    ]
    ambiguous_unmatched_points = [
        {"point": index, "inside": membership[index]}
        for index in range(len(points))
        if index not in matched_points and len(membership[index]) > 1
    ]
    tp = len(pairs)
    fp = len(points) - tp
    fn = len(boxes) - tp
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "n_pred": len(points),
        "n_gt": len(boxes),
        "pairs": [{"point": point, "object": obj} for point, obj in pairs],
        "identity_ambiguous_pairs": ambiguous_pairs,
        "identity_ambiguous_unmatched_points": ambiguous_unmatched_points,
        "identity_ambiguous_count": len(ambiguous_pairs) + len(ambiguous_unmatched_points),
        "count_error": len(points) - len(boxes),
        "abs_count_error": abs(len(points) - len(boxes)),
        "denominators_include_intersections": True,
    }


_RANGE = re.compile(r"\d+\s*[–—-]\s*\d+")


def decode_audit(text: str, points: list, width: int, height: int, hit_token_cap: bool) -> dict:
    """Проверка декодера: кадр, потолок токенов и замена хвоста точек диапазоном."""
    outside = []
    for index, row in enumerate(points):
        x, y = float(row[2]), float(row[3])
        if x < 0 or y < 0 or x > width or y > height:
            outside.append(index)
    ranges = _RANGE.findall(text or "")
    return {
        "hit_token_cap": hit_token_cap,
        "n_points_decoded": len(points),
        "range_summaries_in_text": ranges,
        "undecoded_range_in_text": bool(ranges),
        "coordinates_outside_image": outside,
        "coord_space": "pixel",
        "point_schema": ["object_id", "image_num", "x", "y"],
    }
