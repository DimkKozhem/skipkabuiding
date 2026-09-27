from __future__ import annotations

import json
import time
from pathlib import Path

from sitewatch.settings import get_settings


class MetricsCollector:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (get_settings().data_dir / "observations" / "metrics.jsonl")
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, **payload) -> None:
        line = {"kind": kind, **payload, "t": time.time()}
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")

    def timed(self, kind: str, **payload):
        start = time.perf_counter()

        def finish(**extra):
            elapsed_ms = (time.perf_counter() - start) * 1000
            self.record(kind, latency_ms=round(elapsed_ms, 2), **payload, **extra)
            return elapsed_ms

        return finish
