"""Minimal GPU/VRAM telemetry helpers. Never raise if unavailable."""

from __future__ import annotations

from typing import Any


def normalize_device(device: str) -> str:
    """Official SAM3 builder accepts only 'cuda' | 'cpu'."""
    raw = (device or "cpu").strip().lower()
    if raw in {"cuda", "gpu"} or raw.startswith("cuda:"):
        return "cuda"
    if raw.isdigit():
        return "cuda"
    return "cpu"


def gpu_telemetry(device: str = "cuda") -> dict[str, Any]:
    out: dict[str, Any] = {"device": device}
    try:
        import torch

        if not torch.cuda.is_available() or normalize_device(device) != "cuda":
            out["cuda_available"] = False
            return out
        idx = 0
        if ":" in device:
            try:
                idx = int(device.split(":", 1)[1])
            except ValueError:
                idx = 0
        props = torch.cuda.get_device_properties(idx)
        out["cuda_available"] = True
        out["gpu_index"] = idx
        out["gpu_name"] = props.name
        out["allocated_vram_mb"] = round(torch.cuda.memory_allocated(idx) / (1024**2), 1)
        out["reserved_vram_mb"] = round(torch.cuda.memory_reserved(idx) / (1024**2), 1)
        out["total_vram_mb"] = round(props.total_memory / (1024**2), 1)
        try:
            peak = torch.cuda.max_memory_allocated(idx) / (1024**2)
            out["peak_vram_mb"] = round(peak, 1)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        out["telemetry_error"] = str(exc)
    return out


def reset_peak_stats(device: str = "cuda") -> None:
    try:
        import torch

        if torch.cuda.is_available() and normalize_device(device) == "cuda":
            torch.cuda.reset_peak_memory_stats()
    except Exception:  # noqa: BLE001
        return
