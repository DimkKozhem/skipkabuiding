"""SAM3 bootstrap boxes. Category is a hint. Output is not ground truth."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "1")

from sitewatch.perception.providers.sam3 import Sam3Provider

ROOT = Path("/home/dimk/my_project/LCT2026/data/external/construction_equipment_v1")
PROMPTS = {
    "excavator": "excavator",
    "bulldozer": "bulldozer",
    "loader": "wheel loader",
    "dump_truck": "dump truck",
    "truck": "flatbed truck",
    "tower_crane": "tower crane",
    "mobile_crane": "mobile crane",
    "concrete_pump": "concrete pump truck",
    "aerial_work_platform": "aerial work platform",
    "concrete_mixer": "cement mixer truck",
    "person": "construction worker",
}
RIVALS = {
    "concrete_pump": ["mobile crane"],
    "mobile_crane": ["concrete pump truck", "tower crane"],
    "tower_crane": ["mobile crane"],
    "dump_truck": ["flatbed truck"],
    "truck": ["dump truck"],
    "excavator": ["bulldozer"],
    "bulldozer": ["excavator"],
    "loader": ["excavator"],
    "aerial_work_platform": ["mobile crane"],
}


def boxes(result) -> list[dict]:
    out = []
    for ev in result.evidence:
        bb = ev.bbox
        if bb is None:
            continue
        out.append({
            "prompt": ev.raw_label,
            "score": round(float(ev.score), 4),
            "xyxy": [round(bb.x1, 1), round(bb.y1, 1), round(bb.x2, 1), round(bb.y2, 1)],
        })
    return out


def main() -> None:
    provider = Sam3Provider(enabled=True)
    done_path = ROOT / "proposals.jsonl"
    done = set()
    if done_path.exists():
        for line in done_path.read_text().splitlines():
            if line.strip():
                done.add(json.loads(line)["file"])
    files = []
    for hint in list(PROMPTS) + ["negative"]:
        folder = ROOT / "raw" / hint
        if folder.is_dir():
            files.extend(sorted(folder.glob("*")))
    with done_path.open("a") as fh:
        for path in files:
            rel = str(path.relative_to(ROOT))
            if rel in done:
                continue
            hint = path.parent.name
            if hint == "negative":
                rec = {"file": rel, "hint": hint, "primary": [], "rival": [], "status": "negative_candidate"}
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                continue
            primary = boxes(provider.segment(path, [PROMPTS[hint]]))
            rival = []
            for rival_prompt in RIVALS.get(hint, []):
                rival.extend(boxes(provider.segment(path, [rival_prompt])))
            status = "proposal"
            if not primary:
                status = "no_box"
            elif rival:
                rec_status = _ambiguous(primary, rival)
                status = rec_status or status
            rec = {"file": rel, "hint": hint, "primary": primary, "rival": rival, "status": status}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(status, rel, len(primary))


def _ambiguous(primary: list[dict], rival: list[dict]) -> str | None:
    if not primary or not rival:
        return None
    best_p = max(primary, key=lambda b: b["score"])
    best_r = max(rival, key=lambda b: b["score"])
    if best_r["score"] + 0.05 < best_p["score"]:
        return None
    if _iou(best_p["xyxy"], best_r["xyxy"]) < 0.3:
        return None
    return "ambiguous"


def _iou(a, b) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0, x2 - x1) * max(0, y2 - y1)
    if inter <= 0:
        return 0.0
    area_a = max(0, a[2] - a[0]) * max(0, a[3] - a[1])
    area_b = max(0, b[2] - b[0]) * max(0, b[3] - b[1])
    return inter / (area_a + area_b - inter)


if __name__ == "__main__":
    main()
