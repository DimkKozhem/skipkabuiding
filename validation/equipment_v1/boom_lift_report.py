"""Compare frozen R0 / ED predictions with RD. Does not rerun R0 or ED."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import cv2

ROOT = Path("/home/dimk/my_project/LCT2026")
OUT = ROOT / "validation/equipment_v1"
SHEETS = OUT / "boom_lift_review" / "errors"


def load(name: str) -> list[dict]:
    path = OUT / f"boom_lift_predictions_{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def gt_key(row: dict) -> tuple:
    return (row["date"], tuple(row["bbox"]))


def index_gt(rows: list[dict]) -> dict[tuple, dict]:
    return {gt_key(r): r for r in rows if r["label"] in {"TP", "FN"}}


def draw_pair(gt: dict, pred: dict | None, title: str) -> any:
    img = cv2.imread(str(ROOT / gt["image"]))
    x1, y1, x2, y2 = [int(v) for v in gt["bbox"]]
    h, w = img.shape[:2]
    pad = 40
    crop = img[max(0, y1 - pad):min(h, y2 + pad), max(0, x1 - pad):min(w, x2 + pad)].copy()
    ox, oy = max(0, x1 - pad), max(0, y1 - pad)
    cv2.rectangle(crop, (x1 - ox, y1 - oy), (x2 - ox, y2 - oy), (0, 255, 0), 2)
    if pred and pred.get("prediction_bbox"):
        px = [int(v) for v in pred["prediction_bbox"]]
        cv2.rectangle(crop, (px[0] - ox, px[1] - oy), (px[2] - ox, px[3] - oy), (0, 0, 255), 2)
    crop = cv2.resize(crop, (320, 200))
    cv2.rectangle(crop, (0, 0), (320, 36), (0, 0, 0), -1)
    cv2.putText(crop, title[:42], (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
    extra = ""
    if pred and pred.get("prediction_class"):
        extra = f"{pred['prediction_class'][:16]} {pred.get('confidence')}"
    cv2.putText(crop, extra[:42], (4, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 255), 1)
    return crop


def sheet(tiles: list, name: str) -> None:
    if not tiles:
        print(name, "empty")
        return
    cols = 4
    pages = (len(tiles) + 15) // 16
    for p in range(pages):
        chunk = tiles[p * 16:(p + 1) * 16]
        while len(chunk) % cols:
            chunk.append(chunk[-1] * 0)
        rows = len(chunk) // cols
        canvas = cv2.vconcat([cv2.hconcat(chunk[i * cols:(i + 1) * cols]) for i in range(rows)])
        path = SHEETS / f"{name}_{p:02d}.jpg"
        cv2.imwrite(str(path), canvas, [cv2.IMWRITE_JPEG_QUALITY, 82])
        print(path.name, min(16, len(tiles) - p * 16))


def main() -> None:
    SHEETS.mkdir(parents=True, exist_ok=True)
    ed = index_gt(load("ED"))
    rd = index_gt(load("RD"))
    r0 = index_gt(load("R0"))
    both_tp, both_fn, ed_fn_rd_tp, ed_tp_rd_fn = [], [], [], []
    for key, gt in ed.items():
        other = rd[key]
        title = f"{gt['date'][5:]} {gt['area_frac']*100:.2f}%"
        if gt["label"] == "TP" and other["label"] == "TP":
            both_tp.append(draw_pair(gt, other, "TP both " + title))
        elif gt["label"] == "FN" and other["label"] == "FN":
            both_fn.append(draw_pair(gt, other, "FN both " + title))
        elif gt["label"] == "FN" and other["label"] == "TP":
            ed_fn_rd_tp.append(draw_pair(gt, other, "ED FN RD TP " + title))
        elif gt["label"] == "TP" and other["label"] == "FN":
            ed_tp_rd_fn.append(draw_pair(gt, other, "ED TP RD FN " + title))
    # smallest objects
    small = sorted(ed.values(), key=lambda r: r["area_frac"])[:16]
    small_tiles = []
    for gt in small:
        other = rd[gt_key(gt)]
        small_tiles.append(draw_pair(gt, other, f"small {gt['date'][5:]} {gt['area_frac']*100:.2f}% {other['label']}"))
    rd_fps = [r for r in load("RD") if r["label"] == "FP"]
    ed_fps = [r for r in load("ED") if r["label"] == "FP"]
    # new AWP and mobile_crane FPs: RD boxes whose center is not near an ED box of the same class
    def centers(rows, cls):
        out = []
        for r in rows:
            if r["prediction_class"] != cls or not r.get("prediction_bbox"):
                continue
            b = r["prediction_bbox"]
            out.append(((b[0] + b[2]) / 2, (b[1] + b[3]) / 2, r))
        return out
    new_fp_tiles = []
    for cls in ("aerial_work_platform", "mobile_crane"):
        old = centers(ed_fps, cls)
        for cx, cy, row in centers(rd_fps, cls):
            if any(abs(cx - ox) < 40 and abs(cy - oy) < 40 for ox, oy, _ in old):
                continue
            img = cv2.imread(str(ROOT / row["image"]))
            x1, y1, x2, y2 = [int(v) for v in row["prediction_bbox"]]
            h, w = img.shape[:2]
            crop = img[max(0, y1 - 30):min(h, y2 + 30), max(0, x1 - 30):min(w, x2 + 30)].copy()
            crop = cv2.resize(crop, (320, 200))
            cv2.rectangle(crop, (0, 0), (320, 20), (0, 0, 0), -1)
            cv2.putText(crop, f"newFP {cls[:18]} {row['date'][5:]}", (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)
            new_fp_tiles.append(crop)
    sheet(both_tp, "tp_both")
    sheet(both_fn[:32], "fn_both_sample")
    sheet(ed_fn_rd_tp, "ed_fn_rd_tp")
    sheet(ed_tp_rd_fn, "ed_tp_rd_fn")
    sheet(new_fp_tiles, "new_fp")
    sheet(small_tiles, "smallest")
    # R0 agreement
    r0_tp = sum(1 for k, r in r0.items() if r["label"] == "TP")
    print("r0_tp", r0_tp, "ed_tp", sum(1 for r in ed.values() if r["label"] == "TP"), "rd_tp", sum(1 for r in rd.values() if r["label"] == "TP"))
    print("changed_to_tp", len(ed_fn_rd_tp), "lost_tp", len(ed_tp_rd_fn), "new_fp_tiles", len(new_fp_tiles))


if __name__ == "__main__":
    main()
