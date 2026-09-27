from __future__ import annotations

from datetime import datetime

from sitewatch.domain.contracts import EvidenceRef


def evidence_from_observations(rows: list[dict]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for row in rows:
        ts = row["timestamp"]
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        refs.append(
            EvidenceRef(
                media_path=row.get("media_path", ""),
                timestamp=ts,
                observation_id=row.get("observation_id"),
                media_id=row.get("media_id"),
                detection_ids=list(row.get("detection_ids") or []),
                viz_path=row.get("viz_path"),
                camera_code=row.get("camera_code"),
            )
        )
    return refs
