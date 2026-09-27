from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


def load_bgr(path: Path) -> np.ndarray:
    image = cv2.imread(str(path))
    if image is None:
        raise FileNotFoundError(path)
    return image


def resize_long_edge(image: np.ndarray, max_size: int = 1280) -> np.ndarray:
    h, w = image.shape[:2]
    long_edge = max(h, w)
    if long_edge <= max_size:
        return image
    scale = max_size / long_edge
    return cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)


def match_same_view(image_a: np.ndarray, image_b: np.ndarray) -> dict:
    """OpenCV feature matching for same-camera views. A signal, not a verdict."""
    gray_a = cv2.cvtColor(image_a, cv2.COLOR_BGR2GRAY)
    gray_b = cv2.cvtColor(image_b, cv2.COLOR_BGR2GRAY)
    orb = cv2.ORB_create(nfeatures=1500)
    kp_a, des_a = orb.detectAndCompute(gray_a, None)
    kp_b, des_b = orb.detectAndCompute(gray_b, None)
    if des_a is None or des_b is None or len(kp_a) < 8 or len(kp_b) < 8:
        return {"aligned": False, "inliers": 0, "match_ratio": 0.0}
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    matches = matcher.match(des_a, des_b)
    if len(matches) < 8:
        return {"aligned": False, "inliers": 0, "match_ratio": 0.0}
    src = np.float32([kp_a[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
    dst = np.float32([kp_b[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 5.0)
    inliers = int(mask.sum()) if mask is not None else 0
    ratio = inliers / max(len(matches), 1)
    return {
        "aligned": homography is not None and ratio >= 0.15,
        "inliers": inliers,
        "match_ratio": round(ratio, 4),
    }
