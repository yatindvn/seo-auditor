"""One engine and session factory per database URL, migrated on first use."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.config import config

BACKEND_DIR = Path(__file__).resolve().parents[2]

_lock = threading.Lock()
_engines: Dict[str, Engine] = {}
_factories: Dict[str, sessionmaker] = {}
_migrated: set = set()


def _alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def run_migrations(url: str) -> None:
    if url.startswith("sqlite:///"):
        Path(url[len("sqlite:///"):]).parent.mkdir(parents=True, exist_ok=True)
    command.upgrade(_alembic_config(url), "head")
    _migrated.add(url)


def mark_migrated(url: str) -> None:
    """For a database already at head (tests copy a migrated template)."""
    _migrated.add(url)


def _make_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_conn, _record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        return engine
    return create_engine(url, pool_pre_ping=True)


def get_session_factory(url: Optional[str] = None) -> sessionmaker:
    url = url or config.DATABASE_URL
    with _lock:
        if url not in _factories:
            if url not in _migrated:
                run_migrations(url)
            _engines[url] = _make_engine(url)
            _factories[url] = sessionmaker(bind=_engines[url], expire_on_commit=False)
        return _factories[url]


def dispose_all() -> None:
    with _lock:
        for engine in _engines.values():
            engine.dispose()
        _engines.clear()
        _factories.clear()
