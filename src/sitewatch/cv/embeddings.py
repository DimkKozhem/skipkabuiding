from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from sitewatch.cv.preprocess import load_bgr, resize_long_edge


def histogram_embedding(image_path: Path) -> np.ndarray:
    image = resize_long_edge(load_bgr(image_path), 640)
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
    hist = cv2.normalize(hist, hist).flatten()
    return hist.astype(np.float32)


def cosine_distance(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 1.0
    return float(1.0 - np.dot(a, b) / denom)


def visual_change(path_a: Path, path_b: Path) -> float:
    """Default visual change signal. DINOv2 can replace this later."""
    return round(cosine_distance(histogram_embedding(path_a), histogram_embedding(path_b)), 4)


def dino_embedding(image_path: Path) -> np.ndarray:
    """Optional DINOv2. Raises if transformers/torch are unavailable."""
    from PIL import Image
    import torch
    from transformers import AutoImageProcessor, AutoModel

    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
    model = AutoModel.from_pretrained("facebook/dinov2-small")
    image = Image.open(image_path).convert("RGB")
    inputs = processor(images=image, return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs)
    vec = outputs.last_hidden_state.mean(dim=1).squeeze().cpu().numpy()
    return vec.astype(np.float32)
