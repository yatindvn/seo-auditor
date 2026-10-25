"""The migration and an audit round-trip on real Postgres. Opt-in:

    docker run -d --name pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine
    PG_TEST_URL=postgresql+psycopg://postgres:test@127.0.0.1:55432/postgres python -m pytest tests/test_postgres_optional.py
"""

import os

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db import engine as db_engine
from app.db.diff import diff_audits

URL = os.getenv("PG_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set PG_TEST_URL to run against Postgres")


def test_migration_and_diff_on_postgres(tmp_path):
    with create_engine(URL).begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    db_engine.run_migrations(URL)
    assert "audit_issues" in inspect(create_engine(URL)).get_table_names()

    from tests.test_audit_diff import _audit
    from app.db.models import Project

    factory = db_engine.get_session_factory(URL)
    with factory.begin() as s:
        project = Project(name="pg.com", domain="pg.com", audit_options_json={})
        s.add(project)
        s.flush()
        old = _audit(s, project, "pg-old", {"/a": 200}, [("/a", "X")], 50.0, 0)
        new = _audit(s, project, "pg-new", {"/a": 404}, [("/a", "Y")], 40.0, 5)
    with factory() as s:
        diff = diff_audits(s, old, new)
    assert diff["issues"]["new_count"] == 1 and diff["issues"]["fixed_count"] == 1
    assert diff["pages"]["status_changed"] == [{"url": "/a", "old_status": 200, "new_status": 404}]
