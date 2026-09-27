"""Contact sheets of SAM proposals for visual review. Not ground truth."""

from __future__ import annotations

import json
from pathlib import Path

import cv2

ROOT = Path("/home/dimk/my_project/LCT2026/data/external/construction_equipment_v1")
OUT = ROOT / "review"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in (ROOT / "proposals.jsonl").read_text().splitlines() if line.strip()]
    by_hint: dict[str, list] = {}
    for rec in rows:
        by_hint.setdefault(rec["hint"], []).append(rec)
    for hint, items in by_hint.items():
        tiles = []
        for rec in items:
            if rec["status"] not in {"proposal", "ambiguous"}:
                continue
            img = cv2.imread(str(ROOT / rec["file"]))
            if img is None:
                continue
            color = (0, 180, 0) if rec["status"] == "proposal" else (0, 140, 255)
            for box in rec["primary"][:2]:
                x1, y1, x2, y2 = [int(v) for v in box["xyxy"]]
                cv2.rectangle(img, (x1, y1), (x2, y2), color, 3)
                cv2.putText(img, f"{rec['status'][:3]} {box['score']:.2f}", (x1, max(20, y1 - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            thumb = cv2.resize(img, (320, 180))
            tiles.append(thumb)
        if not tiles:
            continue
        cols = 4
        for page, start in enumerate(range(0, len(tiles), 16)):
            chunk = tiles[start:start + 16]
            rows_n = (len(chunk) + cols - 1) // cols
            canvas = cv2.copyMakeBorder(
                cv2.vconcat([
                    cv2.hconcat(chunk[r * cols:(r + 1) * cols] + [chunk[-1]] * (cols - len(chunk[r * cols:(r + 1) * cols])))
                    for r in range(rows_n)
                ]),
                0, 0, 0, 0, cv2.BORDER_CONSTANT,
            )
            path = OUT / f"{hint}_{page:02d}.jpg"
            cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 80])
            print(path, len(chunk))


if __name__ == "__main__":
    main()
