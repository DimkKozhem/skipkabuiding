from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_db(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "sitewatch.db"
    monkeypatch.setenv("SITEWATCH_DB_PATH", str(db_path))
    monkeypatch.setenv("SITEWATCH_CAPTURE_LOOP", "0")
    monkeypatch.setenv("SITEWATCH_PERCEPTION_MODE", "annotation")
    from sitewatch.settings import get_settings
    from sitewatch.storage import db as dbmod

    get_settings.cache_clear()
    dbmod._engine = None
    dbmod.SessionLocal = None
    try:
        from sitewatch.perception import ontology as ont

        ont.raw_ontology.cache_clear()
        ont.perception_config.cache_clear()
        ont.entity_index.cache_clear()
    except Exception:
        pass
    yield db_path
    get_settings.cache_clear()
    dbmod._engine = None
    dbmod.SessionLocal = None
