"""Shared test fixtures.

The important one keeps the suite from writing into the repository. Audits
persist to SQLite files under `config.SESSION_DIR`, which defaults to
`./sessions`, so any test that runs a real audit through `_build_audit_result`
would leave database files in `apps/backend/` -- untracked clutter that grows
with every run and that a careless `git add -A` would commit.
"""

import pytest

from app.models import session_model


@pytest.fixture(autouse=True)
def isolated_session_dir(tmp_path, monkeypatch):
    """Point the shared session store at a per-test temporary directory.

    Autouse, because the tests that trigger a write are not the ones that look
    like they would: any call into the audit pipeline saves a session at the end.
    """
    store = session_model.SessionStore(session_dir=tmp_path / "sessions")
    monkeypatch.setattr(session_model, "session_store", store)

    # Modules that imported the singleton by name hold their own reference, so
    # rebinding the module attribute alone would not redirect them.
    for module_path in ("app.services.audit_service", "app.api.routes"):
        module = __import__(module_path, fromlist=["session_store"])
        if hasattr(module, "session_store"):
            monkeypatch.setattr(module, "session_store", store)

    return store


import shutil

from app.config import config as app_config
from app.db import engine as db_engine


@pytest.fixture(scope="session")
def _migrated_template(tmp_path_factory):
    """Migrate once per test run; each test gets a copy. Running the migration
    per test would add a minute to the suite."""
    path = tmp_path_factory.mktemp("db") / "template.db"
    db_engine.run_migrations(f"sqlite:///{path.as_posix()}")
    db_engine.dispose_all()
    return path


@pytest.fixture(autouse=True)
def isolated_database(tmp_path, monkeypatch, _migrated_template):
    """Every test gets its own migrated central DB under tmp_path, so nothing
    writes platform.db into the repository."""
    # A subdirectory, as in production: tests that use tmp_path itself as a
    # session dir must not see the central DB as a session.
    path = tmp_path / "central" / "platform.db"
    path.parent.mkdir()
    shutil.copy(_migrated_template, path)
    url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    db_engine.mark_migrated(url)
    yield url
    db_engine.dispose_all()
