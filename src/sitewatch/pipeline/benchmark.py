"""Perception real-image benchmark (presence / count MAE / latency)."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sitewatch.domain.enums import EntityVisibility, PerceptionMode
from sitewatch.perception.pipeline import PerceptionPipeline
from sitewatch.temporal.state_engine import TemporalStateEngine


@dataclass
class CaseMetrics:
    case_id: str
    presence_tp: int = 0
    presence_fp: int = 0
    presence_fn: int = 0
    count_abs_err: float = 0.0
    count_n: int = 0
    unknown_n: int = 0
    latency_ms: float = 0.0
    error: str | None = None


def _load_cases(root: Path) -> list[dict]:
    manifest = root / "manifest.json"
    if manifest.is_file():
        data = json.loads(manifest.read_text(encoding="utf-8"))
        raw = data.get("cases") if isinstance(data, dict) else data
        if not isinstance(raw, list):
            raw = []
        cases: list[dict] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            payload = dict(item)
            payload.setdefault("id", payload.get("id") or "case")
            image = Path(str(payload.get("image") or ""))
            if not image.is_file():
                candidate = root / image
                if candidate.is_file():
                    payload["image"] = str(candidate)
                else:
                    payload["image"] = str(root / "cases" / payload["id"] / "image.jpg")
            cases.append(payload)
        return cases
    cases = []
    for meta in sorted((root / "cases").glob("*/expected.json") if (root / "cases").is_dir() else root.glob("*/expected.json")):
        payload = json.loads(meta.read_text(encoding="utf-8"))
        payload.setdefault("id", meta.parent.name)
        payload.setdefault("image", str(meta.parent / "image.jpg"))
        cases.append(payload)
    return cases


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def build_run_manifest(
    *,
    root: Path,
    cases: list[dict],
    mode: str,
    summary: dict,
    out_dir: Path,
) -> dict:
    """Reproducible record of one benchmark run. Does not claim model quality by itself."""
    from sitewatch.perception.ontology import ontology_version, perception_config
    from sitewatch.settings import project_root

    cfg = perception_config()
    config_dir = project_root() / "config"
    config_hashes = {
        path.name: file_sha256(path)
        for path in sorted(config_dir.glob("*.yaml"))
        if path.is_file()
    }
    frames = []
    for case in cases:
        image = Path(str(case.get("image") or ""))
        if not image.is_file():
            continue
        frames.append(
            {
                "id": case.get("id"),
                "role": case.get("role") or "unspecified",
                "episode": case.get("episode"),
                "object_id": case.get("object_id"),
                "camera_id": case.get("camera_id"),
                "captured_at": case.get("captured_at"),
                "sha256": file_sha256(image),
                "image": str(image),
            }
        )
    manifest = {
        "created_at": datetime.utcnow().isoformat(),
        "mode": mode,
        "pipeline_version": cfg.get("pipeline_version"),
        "ontology_version": ontology_version(),
        "prompt_version": cfg.get("prompt_version"),
        "config_sha256": config_hashes,
        "frames": frames,
        "summary": {k: v for k, v in summary.items() if k != "cases"},
        "artifacts": str(out_dir),
        "limitations": [
            "annotation mode does not measure real detector quality",
            "holdout days listed in validation/equipment_v1/domain_split.json stay sealed",
        ],
    }
    (out_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def run_benchmark(root: Path, *, out_dir: Path | None = None, mode: PerceptionMode | None = None) -> dict:
    root = Path(root)
    out_dir = out_dir or (root / "predictions")
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = mode or PerceptionMode.REAL
    pipe = PerceptionPipeline(mode=mode)
    temporal = TemporalStateEngine()
    metrics: list[CaseMetrics] = []

    for case in _load_cases(root):
        case_id = str(case.get("id") or "case")
        image = Path(case.get("image") or "")
        if not image.is_file():
            image = root / "cases" / case_id / "image.jpg"
        if not image.is_file():
            image = root / case_id / "image.jpg"
        m = CaseMetrics(case_id=case_id)
        # Skip placeholder cases without a local JPEG
        if not image.is_file():
            if "placeholder" in case_id:
                continue
            m.error = f"missing_image:{image}"
            metrics.append(m)
            continue
        try:
            observed = pipe.run(
                image,
                object_id=str(case.get("object_id") or "bench"),
                zone_id=str(case.get("zone_id") or "bench"),
                camera_id=str(case.get("camera_id") or "cam"),
                captured_at=datetime.utcnow(),
                artifact_dir=out_dir / case_id,
            )
            _ = temporal.update(None, observed)
            m.latency_ms = float(observed.pipeline_run.total_latency_ms or 0) if observed.pipeline_run else 0.0

            expected_classes = set(case.get("expected_visible_classes") or [])
            predicted_visible = {
                k
                for k, v in {**observed.structures, **observed.equipment}.items()
                if v.status in {EntityVisibility.VISIBLE, EntityVisibility.PARTIALLY_VISIBLE}
            }
            m.presence_tp = len(expected_classes & predicted_visible)
            m.presence_fp = len(predicted_visible - expected_classes)
            m.presence_fn = len(expected_classes - predicted_visible)

            expected_counts = dict(case.get("expected_counts") or {})
            for label, exp in expected_counts.items():
                obs = observed.structures.get(label) or observed.equipment.get(label)
                pred = obs.count_visible if obs else None
                if pred is None:
                    m.unknown_n += 1
                    continue
                m.count_abs_err += abs(float(pred) - float(exp))
                m.count_n += 1

            (out_dir / case_id / "observed_state.json").write_text(
                observed.model_dump_json(indent=2), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            m.error = str(exc)
        metrics.append(m)

    tp = sum(x.presence_tp for x in metrics)
    fp = sum(x.presence_fp for x in metrics)
    fn = sum(x.presence_fn for x in metrics)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    count_n = sum(x.count_n for x in metrics)
    mae = (sum(x.count_abs_err for x in metrics) / count_n) if count_n else None
    latencies = [x.latency_ms for x in metrics if not x.error]
    summary = {
        "n_cases": len(metrics),
        "presence_precision": round(precision, 4),
        "presence_recall": round(recall, 4),
        "count_mae": round(mae, 4) if mae is not None else None,
        "unknown_rate": round(sum(x.unknown_n for x in metrics) / max(count_n, 1), 4),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "cases": [x.__dict__ for x in metrics],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    build_run_manifest(
        root=root,
        cases=_load_cases(root),
        mode=mode.value,
        summary=summary,
        out_dir=out_dir,
    )
    summary["run_manifest"] = str(out_dir / "run_manifest.json")
    return summary
