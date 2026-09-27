from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cv2

from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import BBox, Detection
from sitewatch.settings import load_yaml


def sample_frame_indices(n_frames: int, src_fps: float, sample_fps: float) -> list[int]:
    if n_frames <= 0:
        return []
    step = max(int(round(src_fps / max(sample_fps, 0.1))), 1)
    return list(range(0, n_frames, step))


def aggregate_video_counts(detections_by_frame: list[list[Detection]]) -> dict[str, int]:
    """10:00–10:10 window → class counts via unique tracks, else max-per-frame."""
    tracks: dict[str, set[int]] = defaultdict(set)
    fallback: dict[str, int] = defaultdict(int)
    for frame in detections_by_frame:
        per_class: dict[str, int] = defaultdict(int)
        for det in frame:
            per_class[det.class_name] += 1
            if det.track_id is not None:
                tracks[det.class_name].add(det.track_id)
        for name, count in per_class.items():
            fallback[name] = max(fallback[name], count)
    result = dict(fallback)
    for name, ids in tracks.items():
        result[name] = max(len(ids), result.get(name, 0))
    return result


class VideoObserver:
    """sample 1–3 FPS → YOLO/track → temporal aggregation. Not frame-by-frame 30 FPS."""

    def __init__(self, detector) -> None:
        self.detector = detector
        cfg = load_yaml("thresholds.yaml")["video"]
        self.sample_fps = float(cfg["sample_fps"])

    def observe(self, video_path: Path) -> tuple[list[Detection], dict[str, int], int]:
        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise FileNotFoundError(video_path)
        src_fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
        n_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        indices = set(sample_frame_indices(n_frames, src_fps, self.sample_fps))
        sidecar = video_path.with_suffix(".json")
        if sidecar.exists():
            capture.release()
            detections = self.detector.detect(video_path)
            n_sampled = len(sample_frame_indices(n_frames, src_fps, self.sample_fps)) or 1
            return detections, aggregate_video_counts([detections]), n_sampled
        per_frame: list[list[Detection]] = []
        flat: list[Detection] = []
        frame_idx = 0
        use_track = hasattr(self.detector, "track_frame")
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if frame_idx in indices or not indices:
                if use_track:
                    dets = self.detector.track_frame(frame)
                else:
                    tmp = video_path.with_name(f"_tmp_frame_{frame_idx}.jpg")
                    cv2.imwrite(str(tmp), frame)
                    try:
                        dets = self.detector.detect(tmp)
                    finally:
                        tmp.unlink(missing_ok=True)
                per_frame.append(dets)
                flat.extend(dets)
            frame_idx += 1
        capture.release()
        return flat, aggregate_video_counts(per_frame), len(per_frame)


class YOLOTracker:
    """ByteTrack / BoT-SORT via Ultralytics persist=True."""

    def __init__(self, weights: Path, tracker: str = "bytetrack.yaml", device: str = "0") -> None:
        from ultralytics import YOLO

        self.model = YOLO(str(weights))
        self.tracker = tracker
        self.device = device

    def track_frame(self, frame) -> list[Detection]:
        results = self.model.track(
            source=frame,
            persist=True,
            tracker=self.tracker,
            device=self.device,
            verbose=False,
        )
        if not results or results[0].boxes is None:
            return []
        result = results[0]
        names = result.names or {}
        detections: list[Detection] = []
        for box in result.boxes:
            raw = str(names.get(int(box.cls[0].item()), ""))
            class_name = canonical_class(raw)
            if class_name is None:
                continue
            xyxy = [float(v) for v in box.xyxy[0].tolist()]
            track_id = int(box.id[0].item()) if box.id is not None else None
            detections.append(
                Detection(
                    class_name=class_name,
                    bbox=BBox(x1=xyxy[0], y1=xyxy[1], x2=xyxy[2], y2=xyxy[3]),
                    confidence=float(box.conf[0].item()),
                    track_id=track_id,
                    model_name="yolo26m-track",
                    model_version=self.tracker,
                )
            )
        return detections
