from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from sitewatch.settings import get_settings
from sitewatch.storage.models import Base

_engine = None
SessionLocal = None


def get_engine():
    global _engine, SessionLocal
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            echo=False,
            future=True,
            connect_args={"check_same_thread": False, "timeout": 30},
        )

        from sqlalchemy import event

        @event.listens_for(_engine, "connect")
        def _sqlite_on_connect(dbapi_conn, _connection_record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
        SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    _ensure_sqlite_columns(engine)


def _ensure_sqlite_columns(engine) -> None:
    """Add columns on an existing SQLite file. create_all does not ALTER."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    tables = inspector.get_table_names()
    patches = {
        "alerts": {
            "fingerprint": "VARCHAR(64) DEFAULT ''",
            "decision_reason": "VARCHAR(64) DEFAULT ''",
            "decision_note": "TEXT DEFAULT ''",
            "decided_at": "DATETIME",
            "decided_by": "VARCHAR(128) DEFAULT ''",
        },
        "cameras": {
            "uri": "VARCHAR(1024) DEFAULT ''",
            "enabled": "INTEGER DEFAULT 1",
            "interval_minutes": "INTEGER DEFAULT 30",
            "last_captured_at": "DATETIME",
            "last_error": "TEXT DEFAULT ''",
        },
        "zones": {
            "description": "TEXT DEFAULT ''",
            "construction_type_id": "VARCHAR(64)",
        },
    }
    with engine.begin() as conn:
        for table, additions in patches.items():
            if table not in tables:
                continue
            names = {col["name"] for col in inspector.get_columns(table)}
            for column, ddl in additions.items():
                if column not in names:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


@contextmanager
def get_session() -> Iterator[Session]:
    get_engine()
    assert SessionLocal is not None
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
