"""The schema comes from the migration, and the models agree with it."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from app.db import engine as db_engine
from app.db.models import Base
from app.db.projects import get_or_create_project, project_domain

TABLES = {
    "projects", "audits", "audit_pages", "audit_issues", "keywords", "rank_checks",
    "competitors", "backlink_snapshots", "ai_visibility_runs", "web_vitals", "render_comparisons", "accessibility_results", "custom_rules", "gsc_daily", "gsc_pages", "gsc_queries", "gsc_inspections", "backlink_ref_domains", "backlink_links",
}


def test_the_migration_creates_every_table(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    db_engine.run_migrations(url)

    assert TABLES <= set(inspect(create_engine(url)).get_table_names())


def test_the_models_match_the_migration(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm.db').as_posix()}"
    db_engine.run_migrations(url)

    with create_engine(url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diff == []


@pytest.mark.parametrize("url, domain", [
    ("https://example.com/", "example.com"),
    ("https://WWW.Example.com:443/x?y=1", "example.com"),
    ("http://www.example.com:8080/", "example.com"),
    ("https://blog.example.com/a", "blog.example.com"),
    ("example.com/path", "example.com"),
])
def test_project_domain(url, domain):
    assert project_domain(url) == domain


def test_audits_of_one_site_share_a_project():
    factory = db_engine.get_session_factory()
    with factory.begin() as session:
        first = get_or_create_project(session, "https://example.com/")
        second = get_or_create_project(session, "https://www.example.com/about")
        other = get_or_create_project(session, "https://other.org/")
        assert first.id == second.id != other.id
        assert first.name == "example.com"

def test_migration_0002_adds_rank_tracker_schema(tmp_path):
    url = f"sqlite:///{(tmp_path / 'm2.db').as_posix()}"
    db_engine.run_migrations(url)
    insp = inspect(create_engine(url))

    assert {"provider_usage", "alerts"} <= set(insp.get_table_names())
    assert {"language", "enabled", "created_at"} <= {c["name"] for c in insp.get_columns("keywords")}
    assert {"serp_json", "competitor_positions_json"} <= {c["name"] for c in insp.get_columns("rank_checks")}
    assert {"rank_schedule", "last_rank_checked_at", "alert_settings_json"} <= {
        c["name"] for c in insp.get_columns("projects")
    }
