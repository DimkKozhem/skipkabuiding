from __future__ import annotations

from pathlib import Path


class PaddleOCRModule:
    """Optional OCR for markings / plates / signs. Not on the critical path."""

    name = "paddleocr"

    def read(self, image_path: Path) -> list[dict]:
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            return []
        engine = PaddleOCR(use_angle_cls=True, lang="en")
        result = engine.ocr(str(image_path), cls=True)
        texts: list[dict] = []
        for page in result or []:
            for line in page or []:
                texts.append({"text": line[1][0], "confidence": float(line[1][1])})
        return texts
