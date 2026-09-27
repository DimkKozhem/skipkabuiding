"""Pinned shadow detectors. They emit Detection boxes and never touch ActualState."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
from pathlib import Path

from sitewatch.cv.taxonomy import canonical_class
from sitewatch.domain.contracts import BBox, Detection
from sitewatch.domain.enums import StageStatus
from sitewatch.perception.providers.protocols import ProviderResult
from sitewatch.settings import project_root

_SHA_OK: dict[str, str] = {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_pinned_file(path: Path, *, expected_sha: str, expected_bytes: int | None) -> str | None:
    """Return an error code, or None when the pin matches. Result is cached per path."""
    key = str(path.resolve()) if path.exists() else str(path)
    if _SHA_OK.get(key) == expected_sha:
        return None
    if not path.is_file():
        return "weights_missing"
    if expected_bytes is not None and path.stat().st_size != int(expected_bytes):
        return "weights_size_mismatch"
    digest = sha256_file(path)
    if digest != expected_sha:
        return "weights_sha256_mismatch"
    _SHA_OK[key] = expected_sha
    return None


def transformers_available() -> bool:
    return importlib.util.find_spec("transformers") is not None


class GroundingDinoShadow:
    """IDEA-Research/grounding-dino-base. Unavailable without transformers. No invented boxes."""

    name = "grounding_dino"

    def __init__(self, spec: dict) -> None:
        self.spec = spec
        self.model = str(spec.get("model") or "IDEA-Research/grounding-dino-base")
        self.revision = str(spec.get("revision") or "n/a")
        self.device = str(spec.get("device") or "cuda:1")
        self.box_threshold = float(spec.get("box_threshold") or 0.35)
        self.text_threshold = float(spec.get("text_threshold") or 0.25)

    def detect(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        interpreter = str(self.spec.get("interpreter") or "").strip()
        if interpreter:
            return self._detect_via_interpreter(image_path, prompts, interpreter)
        if not transformers_available():
            return ProviderResult(
                status=StageStatus.UNAVAILABLE,
                error="grounding_dino_no_transformers",
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False},
            )
        try:
            return self._detect_local(image_path, prompts)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                status=StageStatus.FAILED,
                error=f"grounding_dino_failed:{exc}",
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False},
            )

    def _detect_via_interpreter(self, image_path: Path, prompts: list[str], interpreter: str) -> ProviderResult:
        import json
        import os
        import subprocess

        if not Path(interpreter).is_file():
            return ProviderResult(
                status=StageStatus.UNAVAILABLE,
                error="grounding_dino_interpreter_missing",
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False},
            )
        payload = {
            "image": str(image_path),
            "prompts": prompts,
            "model": self.model,
            "revision": self.revision,
            "device": self.device,
            "box_threshold": self.box_threshold,
            "text_threshold": self.text_threshold,
        }
        timeout = float(self.spec.get("timeout_seconds") or 45)
        try:
            completed = subprocess.run(
                [interpreter, "-m", "sitewatch.cv.dino_shadow_worker"],
                input=json.dumps(payload),
                text=True,
                capture_output=True,
                timeout=timeout,
                cwd=str(project_root()),
                env={
                    **os.environ,
                    "PYTHONPATH": str(project_root() / "src"),
                    "HF_HUB_DISABLE_PROGRESS_BARS": "1",
                    "TQDM_DISABLE": "1",
                },
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ProviderResult(
                status=StageStatus.FAILED,
                error="shadow_timeout",
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False},
            )
        line = [item for item in (completed.stdout or "").splitlines() if item.strip().startswith("{")]
        if not line and completed.returncode != 0:
            tail = [item for item in (completed.stderr or "").splitlines() if item.strip() and "it/s" not in item]
            detail = tail[-1] if tail else "no_output"
            return ProviderResult(
                status=StageStatus.FAILED,
                error=f"grounding_dino_failed:{detail}"[:300],
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False},
            )
        if not line:
            return ProviderResult(
                status=StageStatus.EMPTY_SUCCESS,
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False, "detections": []},
            )
        try:
            data = json.loads(line[-1])
        except json.JSONDecodeError:
            return ProviderResult(
                status=StageStatus.INVALID_RESPONSE,
                error="grounding_dino_invalid_response",
                model=self.model,
                model_version=self.revision,
                device=self.device,
                extras={"accepted_into_fact": False},
            )
        try:
            status = StageStatus(str(data.get("status") or "failed"))
        except ValueError:
            status = StageStatus.FAILED
        return ProviderResult(
            status=status,
            error=data.get("error"),
            latency_ms=data.get("latency_ms"),
            model=self.model,
            model_version=self.revision,
            device=self.device,
            extras={"accepted_into_fact": False, "detections": list(data.get("detections") or [])},
        )

    def _detect_local(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        import time

        import torch
        from PIL import Image
        from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor

        started = time.perf_counter()
        processor = AutoProcessor.from_pretrained(self.model, revision=self.revision)
        model = AutoModelForZeroShotObjectDetection.from_pretrained(self.model, revision=self.revision)
        model = model.to(self.device)
        model.eval()
        image = Image.open(image_path).convert("RGB")
        text = " . ".join(prompts) + " ."
        inputs = processor(images=image, text=text, return_tensors="pt").to(self.device)
        with torch.no_grad():
            outputs = model(**inputs)
        results = processor.post_process_grounded_object_detection(
            outputs,
            inputs.input_ids,
            box_threshold=self.box_threshold,
            text_threshold=self.text_threshold,
            target_sizes=[image.size[::-1]],
        )[0]
        detections = _boxes_to_detections(
            boxes=results["boxes"].tolist(),
            scores=results["scores"].tolist(),
            labels=_label_list(results),
            prompts=prompts,
            model_name=self.name,
            model_version=self.revision,
        )
        status = StageStatus.SUCCESS if detections else StageStatus.EMPTY_SUCCESS
        return ProviderResult(
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            model=self.model,
            model_version=self.revision,
            device=self.device,
            extras={"accepted_into_fact": False, "detections": [item.model_dump() for item in detections]},
        )


class Yoloe26lShadow:
    """Ultralytics YOLOE-26L text prompts. mobileclip2:b, not the YOLOE-11 encoder."""

    name = "yoloe_26l"

    def __init__(self, spec: dict) -> None:
        self.spec = spec
        raw = str(spec.get("weights") or "")
        path = Path(raw)
        self.weights = path if path.is_absolute() else project_root() / raw
        self.version = str(spec.get("version") or "v8.4.0")
        self.sha256 = str(spec.get("sha256") or "")
        self.expected_bytes = int(spec["bytes"]) if spec.get("bytes") is not None else None
        self.device = str(spec.get("device") or "cuda:1")
        self.imgsz = int(spec.get("imgsz") or 640)
        self.conf = float(spec.get("conf") or 0.25)
        self.text_model = str(spec.get("text_model") or "mobileclip2:b")
        self.ultralytics_version = str(spec.get("ultralytics_version") or "")

    def detect(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        pin_error = verify_pinned_file(
            self.weights,
            expected_sha=self.sha256,
            expected_bytes=self.expected_bytes,
        )
        if pin_error:
            status = StageStatus.UNAVAILABLE if pin_error == "weights_missing" else StageStatus.FAILED
            return ProviderResult(
                status=status,
                error=f"yoloe_26l_{pin_error}",
                model=self.name,
                model_version=self.version,
                device=self.device,
                extras={"accepted_into_fact": False, "weights": str(self.weights)},
            )
        if self.ultralytics_version:
            installed = importlib.metadata.version("ultralytics")
            if installed != self.ultralytics_version:
                return ProviderResult(
                    status=StageStatus.UNAVAILABLE,
                    error=f"yoloe_26l_ultralytics_pin:{installed}!={self.ultralytics_version}",
                    model=self.name,
                    model_version=self.version,
                    device=self.device,
                    extras={"accepted_into_fact": False},
                )
        try:
            return self._detect_local(image_path, prompts)
        except Exception as exc:  # noqa: BLE001
            return ProviderResult(
                status=StageStatus.FAILED,
                error=f"yoloe_26l_failed:{exc}",
                model=self.name,
                model_version=self.version,
                device=self.device,
                extras={"accepted_into_fact": False},
            )

    def _detect_local(self, image_path: Path, prompts: list[str]) -> ProviderResult:
        import time

        from ultralytics import YOLO

        started = time.perf_counter()
        model = YOLO(str(self.weights))
        labels: list[str] = []
        xyxy: list[list[float]] = []
        scores: list[float] = []
        try:
            # mobileclip2:b is pinned on the checkpoint. Do not pass the YOLOE-11 encoder.
            model.set_classes(prompts)
            results = model.predict(
                source=str(image_path),
                conf=self.conf,
                imgsz=self.imgsz,
                device=self.device,
                verbose=False,
            )
            if results and results[0].boxes is not None:
                for box in results[0].boxes:
                    cls_i = int(box.cls[0].item()) if box.cls is not None else 0
                    labels.append(prompts[cls_i] if cls_i < len(prompts) else str(cls_i))
                    xyxy.append([float(v) for v in box.xyxy[0].tolist()])
                    scores.append(float(box.conf[0].item()))
        finally:
            _release_cuda(model)
        detections = _boxes_to_detections(
            boxes=xyxy,
            scores=scores,
            labels=labels,
            prompts=prompts,
            model_name=self.name,
            model_version=self.version,
        )
        status = StageStatus.SUCCESS if detections else StageStatus.EMPTY_SUCCESS
        return ProviderResult(
            status=status,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            model=self.name,
            model_version=self.version,
            device=self.device,
            extras={
                "accepted_into_fact": False,
                "text_model": self.text_model,
                "detections": [item.model_dump() for item in detections],
            },
        )


def _release_cuda(model) -> None:
    """Drop YOLOE weights before the next model. Do not touch other GPU processes."""
    import gc

    try:
        del model
    except Exception:  # noqa: BLE001
        pass
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def _label_list(results: dict) -> list:
    labels = results.get("labels") or results.get("text_labels") or []
    if hasattr(labels, "tolist"):
        labels = labels.tolist()
    return list(labels)


def _boxes_to_detections(
    *,
    boxes: list,
    scores: list,
    labels: list,
    prompts: list[str],
    model_name: str,
    model_version: str,
) -> list[Detection]:
    out: list[Detection] = []
    if not labels:
        labels = ["?"] * len(boxes)
    for box, score, label in zip(boxes, scores, labels):
        class_name = _map_label(str(label), prompts)
        if class_name is None:
            continue
        if len(box) != 4:
            continue
        out.append(
            Detection(
                class_name=class_name,
                bbox=BBox(x1=float(box[0]), y1=float(box[1]), x2=float(box[2]), y2=float(box[3])),
                confidence=float(score),
                model_name=model_name,
                model_version=model_version,
                extra={"role": "shadow_candidate", "accepted_into_fact": False},
            )
        )
    return out


def _map_label(label: str, prompts: list[str]) -> str | None:
    text = label.lower().strip()
    mapped = None
    for prompt in prompts:
        token = prompt.lower().strip()
        if token and (token in text or text in token):
            mapped = prompt
            break
    canonical = canonical_class(mapped or label)
    if canonical in {None, "floor"}:
        return None
    return canonical
