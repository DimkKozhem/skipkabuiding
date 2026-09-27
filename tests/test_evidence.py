from pathlib import Path

from sitewatch.pipeline.seed import seed_demo
from sitewatch.services.queries import get_alert, get_evidence, list_alerts
from sitewatch.storage.db import get_session
from sitewatch.storage.models import ActualStateRecord, DetectionRecord, MediaAsset, Observation


def test_alert_evidence_chain_reaches_source():
    seed_demo()
    alerts = list_alerts()
    assert alerts
    for row in alerts:
        detail = get_alert(row["id"])
        assert detail["deviation"], "alert must explain expected vs observed"
        assert detail["deviation"].get("expected") is not None
        assert detail["deviation"].get("observed") is not None
        assert detail["deviation"].get("rationale")
        assert detail["evidence"], f"{row['type']} must attach evidence"
        for ev in detail["evidence"]:
            assert ev["observation_id"]
            assert ev["media_path"]
            source = Path(ev["media_path"])
            assert source.exists(), source
            assert "source" in source.parts
            if ev.get("viz_path"):
                viz = Path(ev["viz_path"])
                if viz.exists():
                    assert viz.resolve() != source.resolve()
            chain = get_evidence(ev["id"])
            assert chain["alert_id"] == detail["id"]
            assert chain["observation_id"] == ev["observation_id"]
            assert chain["observation"]
            with get_session() as session:
                obs = session.get(Observation, chain["observation_id"])
                assert obs is not None
                media = session.get(MediaAsset, obs.media_id)
                assert media is not None
                assert Path(media.path).exists()
                assert session.query(DetectionRecord).filter_by(observation_id=obs.id).count() >= 1
                assert session.query(ActualStateRecord).filter_by(observation_id=obs.id).count() == 1


def test_no_alert_without_source_image():
    seed_demo()
    missing = next(item for item in list_alerts() if item["type"] == "missing_equipment")
    detail = get_alert(missing["id"])
    assert Path(detail["evidence"][0]["media_path"]).exists()
    assert detail["evidence"][0]["detections"]
