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


def _fresh(url):
    with create_engine(url).begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    db_engine.run_migrations(url)


def test_models_match_the_migrations_on_postgres():
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from app.db.models import Base

    _fresh(URL)
    with create_engine(URL).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_full_downgrade_and_upgrade_on_postgres():
    from alembic import command

    _fresh(URL)
    cfg = db_engine._alembic_config(URL)
    command.downgrade(cfg, "base")
    assert "content_searches" not in inspect(create_engine(URL)).get_table_names()
    command.upgrade(cfg, "head")
    assert {"ai_runs", "content_searches"} <= set(inspect(create_engine(URL)).get_table_names())


def test_ai_visibility_and_content_explorer_on_postgres():
    from app.ai_visibility.providers import Answer
    from app.ai_visibility.run import run_project
    from app.content_explorer.explore import explore, recent
    from app.db.models import AiBrandTerm, AiPrompt, AiVisibilityRun, Project
    from app.providers.dry_run import DryRunProvider
    from sqlalchemy import select

    class Fixed:
        name, model, dry_run = "claude", "claude-1", False

        def ask(self, prompt, brands_hint=None):
            return Answer("Try Books to Scrape.", [{"url": "https://books.toscrape.com/", "title": "b"}], self.model)

    class Links:
        dry_run = False

        def bulk_metrics(self, urls):
            return {u: (10, 2) for u in urls}

    _fresh(URL)
    factory = db_engine.get_session_factory(URL)
    with factory.begin() as s:
        p = Project(name="Books to Scrape", domain="books.toscrape.com", audit_options_json={})
        s.add(p); s.flush()
        s.add(AiPrompt(project_id=p.id, text="best rare books"))
        s.add(AiBrandTerm(project_id=p.id, owner="books.toscrape.com", term="BTS"))
        pid = p.id
    result = run_project(pid, providers=[Fixed()], factory=factory)
    assert result["status"] == "ran" and result["mention_rate"] == 1.0
    with factory() as s:
        row = s.scalars(select(AiVisibilityRun)).one()
        assert row.cited and row.position == 1 and row.citations_json[0]["url"] == "https://books.toscrape.com/"

    found = explore("rare books", serp=DryRunProvider(), backlinks=Links(), factory=factory)
    assert found["dry_run"] and len(found["results"]) == 10
    assert recent(factory=factory)[0]["id"] == found["id"]
