"""One sheet for the five diagnostic frames. Includes empty answers."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path("/home/dimk/my_project/LCT2026")
TASKS = json.loads((ROOT / "validation/model_selection/localization_tasks_frozen.json").read_text())
OUT = ROOT / "artifacts/model_selection/runs/window_localization_sheet.html"


def _load(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _line_note(points):
    if len(points) < 4:
        return ""
    ys = [row[3] for row in points]
    if max(ys) - min(ys) < 12:
        return "Точки лежат почти на одной горизонтали."
    return ""


NOTES = {
    "s-dev-earth-1:window": "MolmoPoint: 16 точек одной горизонталью по кровле соседнего дома, не по площадке. CountGD: рамки на окнах того же соседнего дома и на дальнем фоне, не на грунте.",
    "s-dev-earth-1:window_opening": "MolmoPoint: 17 точек, пара ближе 16 px. Площадка без проёмов.",
    "s-dev-earth-1:door": "CountGD пустой, максимум до порога 0.05.",
    "s-dev-frame:window": "MolmoPoint стоит на кровле соседнего дома. Деревянные ячейки объекта пустые.",
    "s-dev-frame:window_opening": "CountGD мешает окна соседнего дома с широкими рамками по деревянному каркасу, крану и экскаватору.",
    "s-dev-empty:window": "MolmoPoint попадает в стекло кабины грузовика и кабины крана.",
    "s-dev-empty:door": "CountGD: две большие рамки на стреле и кабине крана, это не двери.",
    "s-dev-early:window": "Единственный кадр, где оба метода попадают в проёмы кладки. CountGD часть проёмов сливает, часть пропускает. MolmoPoint на задаче window даёт только 2 точки на стене.",
    "s-dev-early:window_opening": "MolmoPoint: 9 точек вдоль фасада, часть на простенках. Это не полный набор проёмов.",
    "s-dev-early:door": "MolmoPoint пустой.",
    "s-dev-frame:door": "MolmoPoint пустой. CountGD пустой, максимум 0.10.",
}

def main() -> None:
    frames = TASKS["diagnostic_frames"]
    tasks = TASKS["tasks"]
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Окна и проёмы</title>",
        "<style>body{font-family:sans-serif;margin:24px} img{max-width:320px;vertical-align:top} td{padding:8px;border-top:1px solid #ccc} .miss{color:#8a1f1f}</style>",
        "</head><body>",
        "<h1>Локализация окон, проёмов и дверей</h1>",
        "<p>Пять кадров Скрипки — только диагностика. Число этажей из числа точек или рамок не выводится. Пустой ответ показан как пустой. Больше точек или рамок само по себе не считается полезной локализацией.</p>",
        "<p>CountGD text-only — автоматический режим, порог sigmoid max logit 0.23, CPU, чистый PyTorch attention: nvcc в системе нет. Visual exemplar на этих кадрах не запускался: на самом объекте не отмечен ни один пример. Окно соседнего корпуса примером не бралось.</p>",
    ]
    for sample_id in frames:
        parts.append(f"<h2>{sample_id}</h2>")
        clean = ROOT / f"artifacts/model_selection/runs/molmopoint_windows_dev/{sample_id}/clean.jpg"
        parts.append(f"<p>Чистый кадр</p><img src='{clean}'>")
        parts.append("<table>")
        for task in tasks:
            molmo = _load(ROOT / f"artifacts/model_selection/runs/molmopoint_windows_dev/{sample_id}/{task['task_id']}/result.json")
            count = _load(ROOT / f"artifacts/model_selection/runs/countgd_text_windows_dev/{sample_id}/{task['task_id']}/result.json")
            molmo_img = ROOT / f"artifacts/model_selection/runs/molmopoint_windows_dev/{sample_id}/{task['task_id']}/overlay.jpg"
            count_img = ROOT / f"artifacts/model_selection/runs/countgd_text_windows_dev/{sample_id}/{task['task_id']}/overlay.jpg"
            molmo_n = "нет прогона" if molmo is None else molmo["n_points"]
            count_n = "нет прогона" if count is None else count["n_boxes"]
            notes = []
            if molmo is None:
                notes.append("MolmoPoint ещё не записан.")
            else:
                notes.append(_line_note(molmo["points"]))
                flags = molmo.get("flags") or {}
                if flags.get("on_image_edge_2pct"):
                    notes.append(f"край изображения: {len(flags['on_image_edge_2pct'])}")
                if flags.get("in_top_15pct"):
                    notes.append(f"верхние 15%: {len(flags['in_top_15pct'])}")
                if flags.get("in_bottom_15pct"):
                    notes.append(f"нижние 15%: {len(flags['in_bottom_15pct'])}")
                if flags.get("near_duplicate_pairs_under_16px"):
                    notes.append(f"повторы ближе 16 px: {len(flags['near_duplicate_pairs_under_16px'])}")
                if molmo.get("hit_token_cap"):
                    notes.append("выход упёрся в лимит токенов")
                if molmo["n_points"] == 0:
                    notes.append("MolmoPoint вернул пустой ответ.")
            if count is None:
                notes.append("CountGD ещё не записан.")
            elif count["n_boxes"] == 0:
                notes.append("CountGD text-only вернул пустой ответ.")
            note = " ".join(item for item in notes if item)
            extra = NOTES.get(f"{sample_id}:{task['task_id']}", "")
            if extra:
                note = (note + " " + extra).strip()
            parts.append("<tr>")
            parts.append(f"<td><b>{task['task_id']}</b><br>MolmoPoint: {molmo_n}<br>CountGD: {count_n}<br><span class='miss'>{note}</span></td>")
            if molmo_img.exists():
                parts.append(f"<td>MolmoPoint<br><img src='{molmo_img}'></td>")
            else:
                parts.append("<td>MolmoPoint<br>нет оверлея</td>")
            if count_img.exists():
                parts.append(f"<td>CountGD<br><img src='{count_img}'></td>")
            else:
                parts.append("<td>CountGD<br>нет оверлея</td>")
            parts.append("</tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    OUT.write_text("\n".join(parts), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
