"""OpenCV image quality metrics — deterministic, no VLM."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from sitewatch.domain.contracts import ImageQuality
from sitewatch.perception.ontology import perception_config


def analyze_image_quality(image_path: Path) -> ImageQuality:
    cfg = (perception_config().get("quality") or {})
    img = cv2.imread(str(image_path))
    if img is None:
        return ImageQuality(
            usable=False,
            visibility=0.0,
            coverage=0.0,
            blur=1.0,
            exposure=0.0,
            darkness=1.0,
            resolution=(0, 0),
            issues=["unreadable_image"],
        )

    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # Laplacian variance — higher = sharper; normalize inversely to blur score in [0,1]
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur = float(1.0 / (1.0 + lap_var / 100.0))
    mean = float(np.mean(gray))
    exposure = float(np.clip(mean / 255.0, 0.0, 1.0))
    darkness = float(np.clip(1.0 - exposure, 0.0, 1.0))
    # crude coverage: fraction of mid-tone pixels (not clipped)
    mid = np.mean((gray > 15) & (gray < 240))
    coverage = float(mid)
    visibility = float(np.clip((1.0 - blur) * 0.6 + coverage * 0.4, 0.0, 1.0))

    issues: list[str] = []
    min_res = int(cfg.get("min_resolution") or 480)
    if min(h, w) < min_res:
        issues.append("low_resolution")
    blur_unusable = float(cfg.get("blur_unusable") or 0.85)
    if blur >= blur_unusable:
        issues.append("too_blurry")
    dark_mean = float(cfg.get("dark_mean") or 35)
    bright_mean = float(cfg.get("bright_mean") or 230)
    if mean < dark_mean:
        issues.append("too_dark")
    if mean > bright_mean:
        issues.append("too_bright")

    usable = "unreadable_image" not in issues and "too_blurry" not in issues
    if "low_resolution" in issues and min(h, w) < min_res // 2:
        usable = False

    return ImageQuality(
        usable=usable,
        visibility=round(visibility, 4),
        coverage=round(coverage, 4),
        blur=round(blur, 4),
        exposure=round(exposure, 4),
        darkness=round(darkness, 4),
        resolution=(int(w), int(h)),
        issues=issues,
    )
