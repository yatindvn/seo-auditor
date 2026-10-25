# Phase 1: Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A central, project-scoped database records every finished audit (pages, issues, rank checks), two audits of a project can be diffed, and audits can run on a schedule via APScheduler or a secret-protected cron endpoint.

**Architecture:** SQLAlchemy 2 models plus one Alembic migration in `app/db/`. The crawl keeps writing its per-session SQLite file. At the end of `_build_audit_result`, `record_audit` streams that file into the central DB inside one transaction, and a DB failure only marks the result `persisted: false`. A projects router serves listing, audit history and SQL-side diffs. The scheduler claims due projects atomically and runs `run_full_audit`.

**Tech Stack:** SQLAlchemy 2.1, Alembic 1.20, APScheduler 3.11, psycopg 3.3 (Postgres), SQLite (default), FastAPI, pytest.

**Spec:** `docs/superpowers/specs/2026-10-25-foundation-design.md`

## Global Constraints

- Branch `feat/foundation`. Baseline: backend 342 passed, frontend 57 passed.
- `DATABASE_URL` defaults to `sqlite:///<SESSION_DIR>/platform.db`. Postgres URLs use `postgresql+psycopg://`.
- The schema comes **only** from the Alembic migration. Tests build DBs from it, and a test asserts models and migration agree.
- No test writes outside `tmp_path`. An autouse fixture points `DATABASE_URL` at a per-test copy of a migrated template DB.
- A central-DB failure never fails an audit (`persisted: false`).
- `/api/cron/run` returns 404 when `CRON_SECRET` is unset and 401 on a bad token. Tokens are compared with `hmac.compare_digest`.
- The scheduler is off unless `SCHEDULER_ENABLED=true`.
- No secrets in git. `.env.example` holds placeholders only.
- Run the full backend suite (`cd apps/backend && python -m pytest -q`) before every commit.
- Commit messages end with: `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`

---

### Task 1: Engine, models, migration, test fixture

**Files:**
- Modify: `apps/backend/requirements.txt`, `apps/backend/app/config/config.py`
- Create: `apps/backend/app/db/__init__.py`, `app/db/engine.py`, `app/db/models.py`, `app/db/projects.py`
- Create: `apps/backend/alembic.ini`, `apps/backend/alembic/env.py`, `apps/backend/alembic/script.py.mako`, `apps/backend/alembic/versions/0001_initial.py`
- Modify: `apps/backend/tests/conftest.py` (autouse DB fixture)
- Test: `apps/backend/tests/test_db_schema.py`

**Interfaces (produced):**
- `config.DATABASE_URL: str`, `config.CRON_SECRET: str` (`""` = unset), `config.SCHEDULER_ENABLED: bool`
- `engine.get_session_factory(url: Optional[str] = None) -> sessionmaker`. Cached per URL. It runs migrations the first time a URL is used, unless `mark_migrated(url)` was called.
- `engine.run_migrations(url: str) -> None`, `engine.mark_migrated(url)`, `engine.dispose_all()`
- `models.Base`, `Project`, `Audit`, `AuditPage`, `AuditIssue`, `Keyword`, `RankCheck`, `Competitor`, `BacklinkSnapshot`, `AiVisibilityRun`, `models.utcnow() -> datetime`, `models.as_utc(dt) -> Optional[datetime]`
- `projects.project_domain(url: str) -> str`, `projects.get_or_create_project(session, url: str) -> Project`

- [ ] **Step 1: Dependencies and config**

Append to `apps/backend/requirements.txt`:

```
# Central database (Phase 1). SQLite by default; Postgres through psycopg 3.
sqlalchemy>=2.0
alembic>=1.13
psycopg[binary]>=3.1
# Scheduled audits in-process (SCHEDULER_ENABLED); 4.x is a different API.
apscheduler>=3.10,<4
```

In `apps/backend/app/config/config.py`, after `PAGE_CACHE_MAX_AGE_DAYS`:

```python
# The central database: projects, audits, rank checks. SQLite on the sessions
# volume unless pointed at Postgres (postgresql+psycopg://user:pass@host/db).
DATABASE_URL = os.getenv("DATABASE_URL") or f"sqlite:///{(SESSION_DIR / 'platform.db').as_posix()}"
# POST /api/cron/run requires this as a bearer token; unset disables the route.
CRON_SECRET = os.getenv("CRON_SECRET", "")
# Run due scheduled audits from inside the API process every 15 minutes.
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "").lower() in ("1", "true", "yes")
```

- [ ] **Step 2: Write the failing tests**

Create `apps/backend/tests/test_db_schema.py`:

```python
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
    "competitors", "backlink_snapshots", "ai_visibility_runs",
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_db_schema.py -q`
Expected: FAIL with `ModuleNotFoundError: app.db`.

- [ ] **Step 4: Implement models and helpers**

`apps/backend/app/db/__init__.py`: one line, `"""Central database: projects, audits, rank checks."""`

`apps/backend/app/db/models.py`:

```python
"""Central database models. The schema itself is owned by the Alembic
migration in apps/backend/alembic; tests assert the two agree."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """SQLite returns naive datetimes even for timezone=True columns; every
    value stored here is UTC, so a naive one is UTC too."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    domain: Mapped[str] = mapped_column(String(255), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    audit_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    audit_options_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    last_scheduled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    audits = relationship("Audit", back_populates="project")


class Audit(Base):
    __tablename__ = "audits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True)
    start_url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    trigger: Mapped[str] = mapped_column(String(16))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    health_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    summary_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)

    project = relationship("Project", back_populates="audits")


class AuditPage(Base):
    __tablename__ = "audit_pages"
    __table_args__ = (UniqueConstraint("audit_id", "url", name="uq_audit_pages_audit_url"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    depth: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    issue_count: Mapped[int] = mapped_column(Integer, default=0)
    alias_of: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duplicate_of: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cache_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)


class AuditIssue(Base):
    __tablename__ = "audit_issues"
    __table_args__ = (
        Index("ix_audit_issues_audit_code", "audit_id", "code"),
        Index("ix_audit_issues_audit_url", "audit_id", "url"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"))
    url: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)


class Keyword(Base):
    __tablename__ = "keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "phrase", "country", "device", name="uq_keywords_identity"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    phrase: Mapped[str] = mapped_column(String(255))
    country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    device: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    target_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class RankCheck(Base):
    __tablename__ = "rank_checks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    keyword_id: Mapped[int] = mapped_column(ForeignKey("keywords.id"), index=True)
    audit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("audits.id", ondelete="SET NULL"), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ranking_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("project_id", "domain", name="uq_competitors_project_domain"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"))
    domain: Mapped[str] = mapped_column(String(255))


class BacklinkSnapshot(Base):
    __tablename__ = "backlink_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    metrics_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)


class AiVisibilityRun(Base):
    __tablename__ = "ai_visibility_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    provider: Mapped[str] = mapped_column(String(32))
    prompt: Mapped[str] = mapped_column(Text)
    result_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
```

`apps/backend/app/db/projects.py`:

```python
"""Projects are per domain: auditing a site files the audit under its project."""

from __future__ import annotations

import urllib.parse as up

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Project


def project_domain(url: str) -> str:
    """The lowercased host without `www.` or a port. Other subdomains are
    separate projects: blog.example.com is not example.com."""
    if "://" not in url:
        url = "https://" + url
    host = (up.urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def get_or_create_project(session: Session, url: str) -> Project:
    domain = project_domain(url)
    project = session.scalar(select(Project).where(Project.domain == domain))
    if project is None:
        project = Project(name=domain, domain=domain, audit_options_json={})
        session.add(project)
        session.flush()
    return project
```

- [ ] **Step 5: Engine and Alembic**

`apps/backend/app/db/engine.py`:

```python
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
```

`apps/backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
# Set at runtime from DATABASE_URL by app.db.engine; never a real URL here.
sqlalchemy.url =

[loggers]
keys = root

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
formatter = generic

[formatter_generic]
format = %(levelname)s [%(name)s] %(message)s
```

`apps/backend/alembic/env.py`:

```python
from alembic import context
from sqlalchemy import create_engine

from app.db.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url")
    connectable = create_engine(url)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=url.startswith("sqlite"),
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


run_migrations_online()
```

`apps/backend/alembic/script.py.mako`: Alembic's standard template:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`apps/backend/alembic/versions/0001_initial.py`: write it by **autogenerating against an empty DB, then reviewing it**:

```bash
cd apps/backend
python -c "from alembic import command; from app.db.engine import _alembic_config; command.revision(_alembic_config('sqlite:///./_gen.db'), message='initial schema', autogenerate=True, rev_id='0001')"
```

Rename the generated file to `alembic/versions/0001_initial.py`. Check that it creates all nine tables, the three unique constraints, both `audit_issues` indexes and the `index=True` columns, with `ondelete` on the three foreign keys. Then delete `_gen.db`. Do not hand-edit types: `test_the_models_match_the_migration` is the check.

- [ ] **Step 6: Autouse DB fixture**

Append to `apps/backend/tests/conftest.py`:

```python
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
    path = tmp_path / "platform.db"
    shutil.copy(_migrated_template, path)
    url = f"sqlite:///{path.as_posix()}"
    monkeypatch.setattr(app_config, "DATABASE_URL", url)
    db_engine.mark_migrated(url)
    yield url
    db_engine.dispose_all()
```

- [ ] **Step 7: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_db_schema.py -v && python -m pytest -q`
Expected: all PASS (342 + 9). Check that `git status` shows no `platform.db` or `_gen.db` anywhere.

```bash
git add apps/backend/requirements.txt apps/backend/app/config/config.py apps/backend/app/db apps/backend/alembic.ini apps/backend/alembic apps/backend/tests/conftest.py apps/backend/tests/test_db_schema.py
git commit -m "feat: central database models, initial migration and engine"
```

---

### Task 2: Record finished audits

**Files:**
- Create: `apps/backend/app/services/summary_fields.py`, `apps/backend/app/db/audit_store.py`
- Modify: `apps/backend/app/models/session_db.py` (`iter_pages`, `iter_issues`)
- Modify: `apps/backend/app/api/routes.py` (import `SUMMARY_FIELDS`)
- Test: `apps/backend/tests/test_audit_store.py`

**Interfaces:**
- Consumes: Task 1 models and `get_or_create_project`.
- Produces:
  - `summary_fields.SUMMARY_FIELDS: Tuple[str, ...]` (the current routes tuple plus `"audit_id"`, `"project_id"`, `"persisted"`)
  - `SessionDB.iter_pages(batch: int) -> Iterator[List[Dict]]` with keys `url, final_url, status, depth, title, word_count, issue_count, alias_of, duplicate_of, cache_status`
  - `SessionDB.iter_issues(batch: int) -> Iterator[List[Dict]]` with keys `url, severity, code, message`
  - `audit_store.BATCH_SIZE = 500`
  - `audit_store.record_audit(factory, session_db, result, *, session_id, start_url, trigger="manual", started_at=None) -> Tuple[int, int]` returns `(audit_id, project_id)` and raises on failure (the caller decides)

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_audit_store.py`:

```python
"""A finished audit is copied, completely and in batches, into the central DB."""

from sqlalchemy import func, select

from app.db import audit_store
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditIssue, AuditPage, Keyword, Project, RankCheck
from app.models.session_db import SessionDB


def _session(tmp_path, pages=3, name="s.db"):
    db = SessionDB(tmp_path / name)
    db.add_pages([
        {"url": f"https://example.com/p{i}", "final_url": f"https://example.com/p{i}",
         "status": 200, "depth": 1, "title": f"P{i}", "word_count": 100,
         "issues": [{"severity": "warning", "code": "MISSING_H1", "message": "no h1"}],
         "meta": {}}
        for i in range(pages)
    ])
    return db


def _result(partial=False, rankings=None):
    page = {"url": "https://example.com/p0",
            "keyword_analysis": {"rankings": rankings or []}}
    return {"executive_summary": {"health_score": {"score": 72.5}},
            "partial": partial, "pages": [page], "duplicates": {}}


def test_an_audit_and_all_its_rows_are_stored(tmp_path):
    factory = get_session_factory()
    audit_id, project_id = audit_store.record_audit(
        factory, _session(tmp_path), _result(), session_id="s1",
        start_url="https://www.example.com/",
    )

    with factory() as s:
        audit = s.get(Audit, audit_id)
        assert audit.status == "completed" and audit.trigger == "manual"
        assert audit.page_count == 3 and audit.health_score == 72.5
        assert audit.summary_json["executive_summary"]["health_score"]["score"] == 72.5
        assert "pages" not in audit.summary_json
        assert s.get(Project, project_id).domain == "example.com"
        assert s.scalar(select(func.count()).select_from(AuditPage)) == 3
        assert s.scalar(select(func.count()).select_from(AuditIssue)) == 3


def test_two_audits_of_one_site_share_its_project(tmp_path):
    factory = get_session_factory()
    _, first = audit_store.record_audit(factory, _session(tmp_path, name="a.db"), _result(),
                                        session_id="a", start_url="https://example.com/")
    _, second = audit_store.record_audit(factory, _session(tmp_path, name="b.db"), _result(),
                                         session_id="b", start_url="https://example.com/x")
    assert first == second


def test_a_partial_audit_is_marked_partial(tmp_path):
    factory = get_session_factory()
    audit_id, _ = audit_store.record_audit(factory, _session(tmp_path), _result(partial=True),
                                           session_id="p", start_url="https://example.com/")
    with factory() as s:
        assert s.get(Audit, audit_id).status == "partial"


def test_large_audits_stream_in_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "BATCH_SIZE", 500)
    db = _session(tmp_path, pages=1200)
    batches = []
    original = db.iter_pages

    def spying(batch):
        for chunk in original(batch):
            batches.append(len(chunk))
            yield chunk

    db.iter_pages = spying
    audit_store.record_audit(get_session_factory(), db, _result(), session_id="big",
                             start_url="https://example.com/")

    assert batches == [500, 500, 200]


def test_rank_results_become_keywords_and_rank_checks(tmp_path):
    factory = get_session_factory()
    rankings = [
        {"keyword": "espresso", "position": 3, "status": "ranked", "note": None,
         "checked_at": "2026-10-25T10:00:00+00:00",
         "top_urls": ["https://a.com/", "https://b.com/", "https://example.com/p0"]},
        {"keyword": "grinder", "position": None, "status": "skipped",
         "note": "quota reached", "checked_at": "2026-10-25T10:00:00+00:00", "top_urls": []},
    ]
    audit_id, _ = audit_store.record_audit(factory, _session(tmp_path), _result(rankings=rankings),
                                           session_id="r", start_url="https://example.com/")
    audit_store.record_audit(factory, _session(tmp_path, name="r2.db"), _result(rankings=rankings),
                             session_id="r2", start_url="https://example.com/")

    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Keyword)) == 2   # reused, not duplicated
        checks = s.scalars(select(RankCheck).where(RankCheck.audit_id == audit_id)).all()
        ranked = next(c for c in checks if c.position == 3)
        assert ranked.ranking_url == "https://example.com/p0"
        assert ranked.provider == "google_cse" and ranked.status == "ranked"
        assert any(c.status == "skipped" and c.note == "quota reached" for c in checks)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_audit_store.py -q`
Expected: FAIL with `ImportError` on `audit_store`.

- [ ] **Step 3: Implement**

1. Create `apps/backend/app/services/summary_fields.py`, moving the tuple out of `routes.py`:

```python
"""The audit fields that make up its summary: what /api/audit/latest serves and
what the central DB stores per audit. Page rows, issue detail and the graph are
never in it -- they have their own endpoints and tables."""

SUMMARY_FIELDS = (
    "executive_summary", "site_wide_analysis", "recommendations",
    "issue_frequency", "duplicates", "redirects", "rank_targets",
    "near_duplicate_mode", "elapsed_seconds", "degraded", "partial", "dedup", "reuse",
    "robots_txt", "sitemaps_found", "psi_metrics", "note",
    "audit_id", "project_id", "persisted",
)
```

   In `routes.py`, delete the `SUMMARY_FIELDS = (...)` block (and keep its comment as context above the import), and add `from app.services.summary_fields import SUMMARY_FIELDS`.

2. In `apps/backend/app/models/session_db.py`, add after `get_links`:

```python
    _ITER_PAGE_COLUMNS = (
        "url, final_url, status, depth, title, word_count, issue_count, "
        "alias_of, duplicate_of, cache_status"
    )

    def iter_pages(self, batch: int) -> Iterator[List[Dict[str, Any]]]:
        """Every page row, `batch` at a time, for copying out without holding a
        5000-page audit in memory."""
        cursor = self._conn.execute(f"SELECT {self._ITER_PAGE_COLUMNS} FROM pages ORDER BY rowid")
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                return
            yield [dict(row) for row in rows]

    def iter_issues(self, batch: int) -> Iterator[List[Dict[str, Any]]]:
        cursor = self._conn.execute("SELECT url, severity, code, message FROM issues ORDER BY rowid")
        while True:
            rows = cursor.fetchmany(batch)
            if not rows:
                return
            yield [dict(row) for row in rows]
```

   Add `Iterator` to the `typing` import.

3. Create `apps/backend/app/db/audit_store.py`:

```python
"""Copy a finished audit from its session file into the central database."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import insert, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Audit, AuditIssue, AuditPage, Keyword, RankCheck, utcnow
from app.db.projects import get_or_create_project
from app.services.summary_fields import SUMMARY_FIELDS

BATCH_SIZE = 500
RANK_PROVIDER = "google_cse"


def _summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return {field: result[field] for field in SUMMARY_FIELDS if field in result}


def _parse_time(value: Optional[str]) -> datetime:
    try:
        return datetime.fromisoformat(value) if value else utcnow()
    except ValueError:
        return utcnow()


def _keyword(session: Session, project_id: int, phrase: str, target_url: str) -> Keyword:
    # Looked up explicitly: country and device are NULL here, and SQL unique
    # constraints treat NULLs as distinct, so the constraint alone would not
    # stop a second "espresso" row.
    keyword = session.scalar(select(Keyword).where(
        Keyword.project_id == project_id, Keyword.phrase == phrase,
        Keyword.country.is_(None), Keyword.device.is_(None),
    ))
    if keyword is None:
        keyword = Keyword(project_id=project_id, phrase=phrase, target_url=target_url)
        session.add(keyword)
        session.flush()
    return keyword


def _record_rankings(session: Session, project_id: int, audit_id: int, pages: List[Dict]) -> None:
    for page in pages:
        rankings = ((page.get("keyword_analysis") or {}).get("rankings")) or []
        for ranking in rankings:
            keyword = _keyword(session, project_id, ranking["keyword"], page.get("url"))
            position = ranking.get("position")
            top = ranking.get("top_urls") or []
            session.add(RankCheck(
                keyword_id=keyword.id, audit_id=audit_id,
                checked_at=_parse_time(ranking.get("checked_at")),
                provider=RANK_PROVIDER, status=ranking.get("status") or "skipped",
                position=position,
                ranking_url=top[position - 1] if position and len(top) >= position else None,
                note=ranking.get("note"),
            ))


def record_audit(
    factory: sessionmaker,
    session_db,
    result: Dict[str, Any],
    *,
    session_id: str,
    start_url: str,
    trigger: str = "manual",
    started_at: Optional[datetime] = None,
) -> Tuple[int, int]:
    """Store one audit; return (audit_id, project_id). One transaction: a
    failure stores nothing. Raises -- the caller decides what failure means."""
    with factory.begin() as session:
        project = get_or_create_project(session, start_url)
        health = ((result.get("executive_summary") or {}).get("health_score") or {}).get("score")
        audit = Audit(
            project_id=project.id, session_id=session_id, start_url=start_url,
            status="partial" if result.get("partial") else "completed",
            trigger=trigger, started_at=started_at or utcnow(), finished_at=utcnow(),
            page_count=0, health_score=health, summary_json=_summary(result),
        )
        session.add(audit)
        session.flush()

        page_count = 0
        for batch in session_db.iter_pages(BATCH_SIZE):
            session.execute(insert(AuditPage), [{**row, "audit_id": audit.id} for row in batch])
            page_count += len(batch)
        for batch in session_db.iter_issues(BATCH_SIZE):
            session.execute(insert(AuditIssue), [{**row, "audit_id": audit.id} for row in batch])

        audit.page_count = page_count
        _record_rankings(session, project.id, audit.id, result.get("pages") or [])
        return audit.id, project.id
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_audit_store.py -v && python -m pytest -q`
Expected: all PASS.

```bash
git add apps/backend/app/services/summary_fields.py apps/backend/app/db/audit_store.py apps/backend/app/models/session_db.py apps/backend/app/api/routes.py apps/backend/tests/test_audit_store.py
git commit -m "feat: copy finished audits, pages, issues and rank checks into the central DB"
```

---

### Task 3: Persist every audit from the pipeline

**Files:**
- Modify: `apps/backend/app/services/audit_service.py` (`run_full_audit`, `_build_audit_result`)
- Test: `apps/backend/tests/test_audit_persistence_central.py`

**Interfaces:**
- Consumes: `record_audit`, `get_session_factory` (Tasks 1–2).
- Produces: the audit result gains `audit_id: Optional[int]`, `project_id: Optional[int]` and `persisted: bool`. `_build_audit_result(..., trigger: str = "manual")` and `run_full_audit(..., trigger: str = "manual")`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_audit_persistence_central.py`:

```python
"""Every audit lands in the central DB -- and a DB failure never fails the audit."""

from sqlalchemy import select

from app.crawler.crawler import Crawler, PageResult
from app.db import audit_store
from app.db.engine import get_session_factory
from app.db.models import Audit
from app.services import audit_service

HOME = "https://example.com/"


def _crawler():
    pages = {HOME: "<a href='/a'>a</a>", "https://example.com/a": "<p>a</p>"}
    crawler = Crawler(HOME, max_pages=5, max_depth=1, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler._fetch = lambda url: PageResult(url=url, final_url=url, status_code=200,
                                            html=pages[url], headers={})
    return crawler


def _run(**kwargs):
    return audit_service._build_audit_result(
        HOME, _crawler(), progress_callback=None, event_callback=None,
        external_link_check_limit=0, **kwargs,
    )


def test_an_audit_is_stored_and_says_so():
    result = _run(session_id="sess_central")

    assert result["persisted"] is True
    with get_session_factory()() as s:
        audit = s.get(Audit, result["audit_id"])
        assert audit.session_id == "sess_central" and audit.page_count == 2
        assert audit.project_id == result["project_id"]


def test_the_trigger_is_recorded():
    result = _run(session_id="sess_sched", trigger="scheduled")
    with get_session_factory()() as s:
        assert s.get(Audit, result["audit_id"]).trigger == "scheduled"


def test_a_database_failure_does_not_fail_the_audit(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(audit_store, "record_audit", broken)
    result = _run(session_id="sess_down")

    assert result["persisted"] is False
    assert result["audit_id"] is None
    assert len(result["pages"]) == 2


def test_the_saved_session_summary_carries_the_audit_id(isolated_session_dir):
    result = _run(session_id="sess_summary")
    saved = isolated_session_dir.get_session("sess_summary")["auditResult"]
    assert saved["audit_id"] == result["audit_id"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_audit_persistence_central.py -q`
Expected: FAIL with `KeyError: 'persisted'` and an unexpected keyword `trigger`.

- [ ] **Step 3: Implement**

In `apps/backend/app/services/audit_service.py`:

1. Imports: `from app.db import audit_store` and `from app.db.engine import get_session_factory`.

2. `run_full_audit`: add the parameter `trigger: str = "manual"` after `fresh`, and pass `trigger=trigger` to `_build_audit_result`.

3. `_build_audit_result`: add `trigger: str = "manual"` after `fresh`. Directly after `started_at = time.monotonic()`, add `started_wall = datetime.now(timezone.utc)` with `from datetime import datetime, timezone` imported.

4. Immediately **before** the `db.set_summary({...})` call, add:

```python
    # The central DB is the durable, project-scoped record. It must never cost
    # the audit: on any failure the audit stands, marked as not persisted.
    try:
        audit_id, project_id = audit_store.record_audit(
            get_session_factory(), db, result_data,
            session_id=session_id, start_url=url, trigger=trigger,
            started_at=started_wall,
        )
        result_data.update(audit_id=audit_id, project_id=project_id, persisted=True)
    except Exception as exc:
        logger.error("Audit %s not recorded in the central DB: %s", session_id, exc, exc_info=exc)
        result_data.update(audit_id=None, project_id=None, persisted=False)
```

   `record_audit` only reads `result_data` before these keys exist, so the stored `summary_json` lacks `audit_id`. That's fine: the audit row's own id is that.

- [ ] **Step 4: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_audit_persistence_central.py -v && python -m pytest -q`
Expected: all PASS. The existing pipeline tests now also persist into their per-test DB.

```bash
git add apps/backend/app/services/audit_service.py apps/backend/tests/test_audit_persistence_central.py
git commit -m "feat: persist every finished audit centrally, never at the audit's expense"
```

---

### Task 4: Diff two audits

**Files:**
- Create: `apps/backend/app/db/diff.py`
- Test: `apps/backend/tests/test_audit_diff.py`

**Interfaces:**
- Produces: `diff.diff_audits(session, old_id: int, new_id: int, limit: int = 500) -> Dict` with:
  - `old_audit_id`, `new_audit_id`, `health_score_change` (float or None)
  - `issues`: `{new: [...], fixed: [...], new_count, fixed_count, persisting_count}`, each item `{url, code, severity, message}`
  - `pages`: `{added: [url], removed: [url], status_changed: [{url, old_status, new_status}], added_count, removed_count, status_changed_count}`

  Lists are truncated at `limit`; the counts are always exact. Raises `ValueError` when the audits belong to different projects, and `LookupError` when an id doesn't exist.
- `diff.previous_audit_id(session, audit_id) -> Optional[int]`: the latest earlier audit (by `finished_at`, then id) of the same project.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_audit_diff.py`:

```python
"""Comparing two runs of a project: what broke, what got fixed, what moved."""

from datetime import timedelta

import pytest

from app.db.diff import diff_audits, previous_audit_id
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditIssue, AuditPage, Project, utcnow


def _audit(s, project, session_id, pages, issues, score, minutes):
    audit = Audit(project_id=project.id, session_id=session_id, start_url="https://example.com/",
                  status="completed", trigger="manual",
                  started_at=utcnow() + timedelta(minutes=minutes),
                  finished_at=utcnow() + timedelta(minutes=minutes),
                  page_count=len(pages), health_score=score, summary_json={})
    s.add(audit)
    s.flush()
    for url, status in pages.items():
        s.add(AuditPage(audit_id=audit.id, url=url, status=status, issue_count=0))
    for url, code in issues:
        s.add(AuditIssue(audit_id=audit.id, url=url, code=code, severity="warning", message=code))
    s.flush()
    return audit.id


@pytest.fixture
def two_runs():
    factory = get_session_factory()
    with factory.begin() as s:
        project = Project(name="example.com", domain="example.com", audit_options_json={})
        other = Project(name="other.org", domain="other.org", audit_options_json={})
        s.add_all([project, other])
        s.flush()
        old = _audit(s, project, "old",
                     {"/a": 200, "/b": 200, "/gone": 200},
                     [("/a", "MISSING_H1"), ("/b", "THIN_CONTENT"), ("/b", "MISSING_ALT")],
                     score=60.0, minutes=0)
        new = _audit(s, project, "new",
                     {"/a": 200, "/b": 404, "/fresh": 200},
                     [("/a", "MISSING_H1"), ("/b", "STATUS_404"), ("/fresh", "MISSING_ALT")],
                     score=55.5, minutes=10)
        foreign = _audit(s, other, "foreign", {"/x": 200}, [], score=90.0, minutes=5)
    return factory, old, new, foreign


def test_new_fixed_and_persisting_issues(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        diff = diff_audits(s, old, new)

    assert {(i["url"], i["code"]) for i in diff["issues"]["new"]} == {("/b", "STATUS_404"), ("/fresh", "MISSING_ALT")}
    assert {(i["url"], i["code"]) for i in diff["issues"]["fixed"]} == {("/b", "THIN_CONTENT"), ("/b", "MISSING_ALT")}
    assert diff["issues"]["persisting_count"] == 1
    assert diff["health_score_change"] == pytest.approx(-4.5)


def test_page_changes(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        pages = diff_audits(s, old, new)["pages"]

    assert pages["added"] == ["/fresh"]
    assert pages["removed"] == ["/gone"]
    assert pages["status_changed"] == [{"url": "/b", "old_status": 200, "new_status": 404}]


def test_lists_truncate_but_counts_stay_exact(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        diff = diff_audits(s, old, new, limit=1)

    assert len(diff["issues"]["new"]) == 1 and diff["issues"]["new_count"] == 2


def test_audits_of_different_projects_cannot_be_diffed(two_runs):
    factory, old, _, foreign = two_runs
    with factory() as s, pytest.raises(ValueError):
        diff_audits(s, old, foreign)


def test_unknown_audit_is_a_lookup_error(two_runs):
    factory, old, _, _ = two_runs
    with factory() as s, pytest.raises(LookupError):
        diff_audits(s, old, 999_999)


def test_previous_audit_is_the_latest_earlier_one_in_the_project(two_runs):
    factory, old, new, _ = two_runs
    with factory() as s:
        assert previous_audit_id(s, new) == old
        assert previous_audit_id(s, old) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_audit_diff.py -q`
Expected: FAIL with `ModuleNotFoundError: app.db.diff`.

- [ ] **Step 3: Implement**

Create `apps/backend/app/db/diff.py`:

```python
"""Diff two audits of one project in SQL -- anti-joins on indexed columns --
rather than loading 5000-page audits into Python."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session, aliased

from app.db.models import Audit, AuditIssue, AuditPage


def _issues_only_in(session: Session, keep_id: int, other_id: int, limit: int):
    other = aliased(AuditIssue)
    missing = ~exists().where(and_(
        other.audit_id == other_id, other.url == AuditIssue.url, other.code == AuditIssue.code,
    ))
    where = and_(AuditIssue.audit_id == keep_id, missing)
    count = session.scalar(
        select(func.count()).select_from(
            select(AuditIssue.url, AuditIssue.code).where(where).distinct().subquery()
        )
    )
    rows = session.execute(
        select(AuditIssue.url, AuditIssue.code, func.min(AuditIssue.severity), func.min(AuditIssue.message))
        .where(where).group_by(AuditIssue.url, AuditIssue.code)
        .order_by(AuditIssue.url, AuditIssue.code).limit(limit)
    ).all()
    items = [{"url": u, "code": c, "severity": s, "message": m} for u, c, s, m in rows]
    return items, count


def _persisting(session: Session, old_id: int, new_id: int) -> int:
    other = aliased(AuditIssue)
    present = exists().where(and_(
        other.audit_id == old_id, other.url == AuditIssue.url, other.code == AuditIssue.code,
    ))
    return session.scalar(
        select(func.count()).select_from(
            select(AuditIssue.url, AuditIssue.code)
            .where(AuditIssue.audit_id == new_id, present).distinct().subquery()
        )
    )


def _pages_only_in(session: Session, keep_id: int, other_id: int, limit: int):
    other = aliased(AuditPage)
    where = and_(AuditPage.audit_id == keep_id, ~exists().where(and_(
        other.audit_id == other_id, other.url == AuditPage.url,
    )))
    count = session.scalar(select(func.count()).select_from(AuditPage).where(where))
    urls = session.scalars(select(AuditPage.url).where(where).order_by(AuditPage.url).limit(limit)).all()
    return list(urls), count


def _status_changed(session: Session, old_id: int, new_id: int, limit: int):
    old, new = aliased(AuditPage), aliased(AuditPage)
    where = and_(old.audit_id == old_id, new.audit_id == new_id, old.url == new.url,
                 old.status.is_distinct_from(new.status))
    joined = select(old.url, old.status, new.status).join(new, old.url == new.url).where(where)
    count = session.scalar(select(func.count()).select_from(joined.subquery()))
    rows = session.execute(joined.order_by(old.url).limit(limit)).all()
    return [{"url": u, "old_status": o, "new_status": n} for u, o, n in rows], count


def diff_audits(session: Session, old_id: int, new_id: int, limit: int = 500) -> Dict[str, Any]:
    old, new = session.get(Audit, old_id), session.get(Audit, new_id)
    if old is None or new is None:
        raise LookupError(f"no audit {old_id if old is None else new_id}")
    if old.project_id != new.project_id:
        raise ValueError("audits belong to different projects")

    new_issues, new_count = _issues_only_in(session, new_id, old_id, limit)
    fixed, fixed_count = _issues_only_in(session, old_id, new_id, limit)
    added, added_count = _pages_only_in(session, new_id, old_id, limit)
    removed, removed_count = _pages_only_in(session, old_id, new_id, limit)
    changed, changed_count = _status_changed(session, old_id, new_id, limit)

    score_change = None
    if old.health_score is not None and new.health_score is not None:
        score_change = round(new.health_score - old.health_score, 2)

    return {
        "old_audit_id": old_id, "new_audit_id": new_id,
        "health_score_change": score_change,
        "issues": {"new": new_issues, "fixed": fixed, "new_count": new_count,
                   "fixed_count": fixed_count, "persisting_count": _persisting(session, old_id, new_id)},
        "pages": {"added": added, "removed": removed, "status_changed": changed,
                  "added_count": added_count, "removed_count": removed_count,
                  "status_changed_count": changed_count},
    }


def previous_audit_id(session: Session, audit_id: int) -> Optional[int]:
    audit = session.get(Audit, audit_id)
    if audit is None:
        return None
    return session.scalar(
        select(Audit.id).where(
            Audit.project_id == audit.project_id,
            (Audit.finished_at < audit.finished_at)
            | (and_(Audit.finished_at == audit.finished_at, Audit.id < audit.id)),
        ).order_by(Audit.finished_at.desc(), Audit.id.desc()).limit(1)
    )
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_audit_diff.py -v && python -m pytest -q`
Expected: all PASS.

```bash
git add apps/backend/app/db/diff.py apps/backend/tests/test_audit_diff.py
git commit -m "feat: diff two audits of a project in SQL (new/fixed issues, page changes)"
```

---

### Task 5: Projects API

**Files:**
- Create: `apps/backend/app/api/projects.py`
- Modify: `apps/backend/app/main.py` (mount the router)
- Test: `apps/backend/tests/test_projects_api.py`

**Interfaces:**
- Produces these routes under `/api`:
  - `GET /projects`
  - `POST /projects`
  - `PATCH /projects/{id}`
  - `GET /projects/{id}/audits`
  - `GET /audits/{id}/diff`

  A DB failure answers 503 (`{"detail": "central database unavailable"}`).

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_projects_api.py`:

```python
"""Projects, their audit history, and diffs over HTTP."""

import pytest
from fastapi.testclient import TestClient

from app.db import engine as db_engine
from app.main import app
from tests.test_audit_diff import two_runs  # noqa: F401  (fixture)


@pytest.fixture
def client():
    return TestClient(app)


def test_create_list_and_update_projects(client):
    created = client.post("/api/projects", json={"domain": "https://www.Shop.com/",
                                                  "audit_schedule": "weekly",
                                                  "audit_options": {"max_pages": 50}})
    assert created.status_code == 201
    project = created.json()
    assert project["domain"] == "shop.com" and project["audit_schedule"] == "weekly"

    assert client.post("/api/projects", json={"domain": "shop.com"}).status_code == 409

    renamed = client.patch(f"/api/projects/{project['id']}", json={"name": "My shop"})
    assert renamed.json()["name"] == "My shop"

    listed = client.get("/api/projects").json()
    assert [p["domain"] for p in listed["items"]] == ["shop.com"]
    assert listed["items"][0]["audit_count"] == 0 and listed["items"][0]["latest_audit"] is None


def test_a_bad_schedule_is_rejected(client):
    assert client.post("/api/projects", json={"domain": "a.com", "audit_schedule": "hourly"}).status_code == 422


def test_project_audits_newest_first(client, two_runs):  # noqa: F811
    _, old, new, _ = two_runs
    project_id = client.get("/api/projects").json()["items"][0]["id"]

    audits = client.get(f"/api/projects/{project_id}/audits").json()
    assert [a["id"] for a in audits["items"]] == [new, old]
    assert audits["total"] == 2


def test_diff_defaults_to_the_previous_audit(client, two_runs):  # noqa: F811
    _, old, new, _ = two_runs
    diff = client.get(f"/api/audits/{new}/diff").json()
    assert diff["old_audit_id"] == old and diff["issues"]["new_count"] == 2


def test_diff_errors(client, two_runs):  # noqa: F811
    _, old, new, foreign = two_runs
    assert client.get(f"/api/audits/{old}/diff").status_code == 404           # no earlier audit
    assert client.get(f"/api/audits/{new}/diff?against={foreign}").status_code == 400
    assert client.get("/api/audits/999999/diff").status_code == 404


def test_a_database_outage_is_a_503(client, monkeypatch):
    def down(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(db_engine, "get_session_factory", down)
    assert client.get("/api/projects").status_code == 503
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_projects_api.py -q`
Expected: FAIL with 404s (routes don't exist).

- [ ] **Step 3: Implement**

Create `apps/backend/app/api/projects.py`:

```python
"""Projects, audit history and diffs, read from the central database."""

from __future__ import annotations

import logging
from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import engine as db_engine
from app.db.diff import diff_audits, previous_audit_id
from app.db.models import Audit, Project
from app.db.projects import project_domain

router = APIRouter()
logger = logging.getLogger("seo_auditor")

Schedule = Optional[Literal["daily", "weekly"]]


class ProjectCreate(BaseModel):
    domain: str
    name: Optional[str] = None
    audit_schedule: Schedule = None
    audit_options: Dict[str, Any] = {}


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    audit_schedule: Schedule = None
    audit_options: Optional[Dict[str, Any]] = None


def _factory():
    try:
        return db_engine.get_session_factory()
    except Exception as exc:
        logger.error("Central database unavailable: %s", exc, exc_info=exc)
        raise HTTPException(status_code=503, detail="central database unavailable")


def _audit_json(audit: Audit) -> Dict[str, Any]:
    return {
        "id": audit.id, "session_id": audit.session_id, "status": audit.status,
        "trigger": audit.trigger, "start_url": audit.start_url,
        "started_at": audit.started_at.isoformat(), "finished_at": audit.finished_at.isoformat(),
        "page_count": audit.page_count, "health_score": audit.health_score,
    }


def _project_json(session, project: Project) -> Dict[str, Any]:
    latest = session.scalar(select(Audit).where(Audit.project_id == project.id)
                            .order_by(Audit.finished_at.desc(), Audit.id.desc()).limit(1))
    count = session.scalar(select(func.count()).select_from(Audit).where(Audit.project_id == project.id))
    return {
        "id": project.id, "name": project.name, "domain": project.domain,
        "audit_schedule": project.audit_schedule, "audit_options": project.audit_options_json,
        "audit_count": count,
        "latest_audit": None if latest is None else {
            "id": latest.id, "finished_at": latest.finished_at.isoformat(),
            "health_score": latest.health_score,
        },
    }


@router.get("/projects")
def list_projects():
    with _factory()() as session:
        projects = session.scalars(select(Project).order_by(Project.domain)).all()
        return {"items": [_project_json(session, p) for p in projects]}


@router.post("/projects", status_code=201)
def create_project(body: ProjectCreate):
    domain = project_domain(body.domain)
    try:
        with _factory().begin() as session:
            project = Project(name=body.name or domain, domain=domain,
                              audit_schedule=body.audit_schedule,
                              audit_options_json=body.audit_options)
            session.add(project)
            session.flush()
            return _project_json(session, project)
    except IntegrityError:
        raise HTTPException(status_code=409, detail=f"a project for {domain} already exists")


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: ProjectUpdate):
    with _factory().begin() as session:
        project = session.get(Project, project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="no such project")
        fields = body.model_dump(exclude_unset=True)
        if "name" in fields:
            project.name = fields["name"]
        if "audit_schedule" in fields:
            project.audit_schedule = fields["audit_schedule"]
        if fields.get("audit_options") is not None:
            project.audit_options_json = fields["audit_options"]
        session.flush()
        return _project_json(session, project)


@router.get("/projects/{project_id}/audits")
def list_project_audits(project_id: int, offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=200)):
    with _factory()() as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail="no such project")
        where = Audit.project_id == project_id
        total = session.scalar(select(func.count()).select_from(Audit).where(where))
        audits = session.scalars(select(Audit).where(where)
                                 .order_by(Audit.finished_at.desc(), Audit.id.desc())
                                 .offset(offset).limit(limit)).all()
        return {"items": [_audit_json(a) for a in audits], "total": total,
                "offset": offset, "limit": limit}


@router.get("/audits/{audit_id}/diff")
def audit_diff(audit_id: int, against: Optional[int] = None, limit: int = Query(500, ge=1, le=5000)):
    with _factory()() as session:
        if session.get(Audit, audit_id) is None:
            raise HTTPException(status_code=404, detail="no such audit")
        old_id = against if against is not None else previous_audit_id(session, audit_id)
        if old_id is None:
            raise HTTPException(status_code=404, detail="no earlier audit of this project to compare with")
        try:
            return diff_audits(session, old_id, audit_id, limit=limit)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
```

In `app/main.py`, after `app.include_router(api_router, prefix="/api")`:

```python
from app.api.projects import router as projects_router  # noqa: E402
app.include_router(projects_router, prefix="/api")
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_projects_api.py -v && python -m pytest -q`
Expected: all PASS.

```bash
git add apps/backend/app/api/projects.py apps/backend/app/main.py apps/backend/tests/test_projects_api.py
git commit -m "feat: projects API with audit history and diffs"
```

---

### Task 6: Backfill existing session files

**Files:**
- Create: `apps/backend/app/db/import_sessions.py`
- Test: `apps/backend/tests/test_import_sessions.py`

**Interfaces:**
- Produces: `import_sessions.import_all(session_dir: Path, factory) -> Dict[str, int]` returns `{"imported": n, "skipped": m, "failed": k}`. CLI: `python -m app.db.import_sessions [--session-dir DIR]`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_import_sessions.py`:

```python
"""Existing audits are imported once, under their projects."""

from sqlalchemy import func, select

from app.db.engine import get_session_factory
from app.db.import_sessions import import_all
from app.db.models import Audit
from app.models.session_db import SessionDB


def _saved_session(directory, session_id, url, saved_at):
    db = SessionDB(directory / f"{session_id}.db")
    db.add_pages([{"url": url, "status": 200, "issues": [], "meta": {}}])
    db.set_summary({"url": url, "saved_at": saved_at,
                    "auditResult": {"executive_summary": {"health_score": {"score": 80}},
                                    "partial": False, "pages": []}})
    db.close()


def test_sessions_are_imported_once(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _saved_session(sessions, "sess_1", "https://example.com/", 1_790_000_000_000_000_000)
    _saved_session(sessions, "sess_2", "https://other.org/", 1_790_000_100_000_000_000)
    (sessions / "page_cache").mkdir()          # not a session: must be ignored
    (sessions / "platform.db").write_bytes(b"")  # the central DB itself: never imported
    factory = get_session_factory()

    assert import_all(sessions, factory) == {"imported": 2, "skipped": 0, "failed": 0}
    assert import_all(sessions, factory) == {"imported": 0, "skipped": 2, "failed": 0}

    with factory() as s:
        audits = s.scalars(select(Audit).order_by(Audit.session_id)).all()
        assert [a.trigger for a in audits] == ["import", "import"]
        assert audits[0].started_at.year == 2026
        assert s.scalar(select(func.count()).select_from(Audit)) == 2


def test_an_unfinished_session_is_skipped_not_failed(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    SessionDB(sessions / "sess_running.db").close()       # no summary yet

    assert import_all(sessions, get_session_factory()) == {"imported": 0, "skipped": 1, "failed": 0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_import_sessions.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

Create `apps/backend/app/db/import_sessions.py`:

```python
"""Import audits saved before the central DB existed. Safe to re-run: any
session already imported is skipped.

    cd apps/backend
    python -m app.db.import_sessions [--session-dir DIR]
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from sqlalchemy import select

from app.config import config
from app.db import audit_store
from app.db.engine import get_session_factory
from app.db.models import Audit
from app.models.session_db import SessionDB

logger = logging.getLogger("seo_auditor")


def import_all(session_dir: Path, factory) -> Dict[str, int]:
    counts = {"imported": 0, "skipped": 0, "failed": 0}
    with factory() as session:
        known = set(session.scalars(select(Audit.session_id)).all())

    # platform.db (the central DB) lives in the same directory and matches the
    # glob; opening it as a SessionDB would create session tables inside it.
    for path in sorted(p for p in Path(session_dir).glob("*.db") if p.name != "platform.db"):
        session_id = path.stem
        if session_id in known:
            counts["skipped"] += 1
            continue
        db = SessionDB(path)
        try:
            summary = db.get_summary() or {}
            result = summary.get("auditResult")
            if not result or not summary.get("url"):
                counts["skipped"] += 1      # a crawl that never finished
                continue
            saved_ns = int(summary.get("saved_at") or 0)
            started = datetime.fromtimestamp(saved_ns / 1e9, tz=timezone.utc) if saved_ns else None
            audit_store.record_audit(factory, db, result, session_id=session_id,
                                     start_url=summary["url"], trigger="import", started_at=started)
            counts["imported"] += 1
        except Exception as exc:
            logger.error("Could not import %s: %s", path.name, exc, exc_info=exc)
            counts["failed"] += 1
        finally:
            db.close()
    return counts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", default=str(config.SESSION_DIR))
    args = parser.parse_args(argv)
    counts = import_all(Path(args.session_dir), get_session_factory())
    print(f"imported {counts['imported']}, skipped {counts['skipped']}, failed {counts['failed']}")
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_import_sessions.py -v && python -m pytest -q`
Expected: all PASS.

```bash
git add apps/backend/app/db/import_sessions.py apps/backend/tests/test_import_sessions.py
git commit -m "feat: one-off, re-runnable import of existing audits into the central DB"
```

---

### Task 7: Scheduler and cron endpoint

**Files:**
- Create: `apps/backend/app/scheduler/__init__.py`, `app/scheduler/jobs.py`, `app/api/cron.py`
- Modify: `apps/backend/app/main.py` (mount the cron router; start APScheduler on startup when enabled)
- Test: `apps/backend/tests/test_scheduler.py`

**Interfaces:**
- Produces:
  - `jobs.due_projects(session, now) -> List[Project]`
  - `jobs.claim(session, project_id, previous: Optional[datetime], now) -> bool`
  - `jobs.run_due_audits(now: Optional[datetime] = None, runner=None) -> List[str]`, which returns the started session ids. `runner` defaults to `audit_service.run_full_audit`.
  - `jobs.start_scheduler() -> BackgroundScheduler`
  - Route `POST /api/cron/run` → 202 `{"status": "accepted"}`. The audits run in a background task, so their session ids aren't known yet when it answers. This refines the spec's `{"started": [...]}`.

- [ ] **Step 1: Write the failing tests**

Create `apps/backend/tests/test_scheduler.py`:

```python
"""Scheduled audits: due projects run once, from either trigger."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import config
from app.db.engine import get_session_factory
from app.db.models import Project, utcnow
from app.main import app
from app.scheduler import jobs


def _project(domain, schedule, last=None, options=None):
    with get_session_factory().begin() as s:
        p = Project(name=domain, domain=domain, audit_schedule=schedule,
                    audit_options_json=options or {}, last_scheduled_at=last)
        s.add(p)
        s.flush()
        return p.id


def _runner(calls):
    def run(**kwargs):
        calls.append(kwargs)
        return {}
    return run


def test_only_due_projects_run():
    now = utcnow()
    _project("daily-due.com", "daily", last=now - timedelta(hours=25))
    _project("daily-fresh.com", "daily", last=now - timedelta(hours=2))
    _project("weekly-due.com", "weekly", last=now - timedelta(days=8))
    _project("weekly-fresh.com", "weekly", last=now - timedelta(days=3))
    _project("never.com", "daily")
    _project("unscheduled.com", None)
    calls = []

    jobs.run_due_audits(now=now, runner=_runner(calls))

    assert sorted(c["url"] for c in calls) == [
        "https://daily-due.com/", "https://never.com/", "https://weekly-due.com/",
    ]
    assert all(c["trigger"] == "scheduled" for c in calls)


def test_project_options_are_passed_to_the_audit():
    _project("opts.com", "daily", options={"max_pages": 40, "max_depth": 3, "ignore_robots": True})
    calls = []

    jobs.run_due_audits(runner=_runner(calls))

    assert calls[0]["max_pages"] == 40 and calls[0]["max_depth"] == 3 and calls[0]["ignore_robots"] is True


def test_a_project_is_claimed_once():
    project_id = _project("race.com", "daily")
    now = utcnow()
    with get_session_factory()() as s:
        assert jobs.claim(s, project_id, None, now) is True
    with get_session_factory()() as s:
        assert jobs.claim(s, project_id, None, now) is False      # the other trigger lost


def test_one_failing_audit_does_not_stop_the_rest():
    _project("a-fails.com", "daily")
    _project("b-works.com", "daily")
    calls = []

    def runner(**kwargs):
        if "a-fails" in kwargs["url"]:
            raise RuntimeError("boom")
        calls.append(kwargs)
        return {}

    started = jobs.run_due_audits(runner=runner)

    assert [c["url"] for c in calls] == ["https://b-works.com/"]
    assert len(started) == 1


@pytest.fixture
def client():
    return TestClient(app)


def test_cron_route_is_absent_without_a_secret(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "")
    assert client.post("/api/cron/run").status_code == 404


def test_cron_route_rejects_a_wrong_token(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    assert client.post("/api/cron/run").status_code == 401
    assert client.post("/api/cron/run", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_cron_route_runs_due_audits(client, monkeypatch):
    monkeypatch.setattr(config, "CRON_SECRET", "s3cret")
    ran = []
    monkeypatch.setattr(jobs, "run_due_audits", lambda: ran.append(True) or [])

    response = client.post("/api/cron/run", headers={"Authorization": "Bearer s3cret"})

    assert response.status_code == 202
    assert ran == [True]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd apps/backend && python -m pytest tests/test_scheduler.py -q`
Expected: FAIL with `ModuleNotFoundError: app.scheduler`.

- [ ] **Step 3: Implement**

`apps/backend/app/scheduler/__init__.py`: `"""Scheduled audits."""`

`apps/backend/app/scheduler/jobs.py`:

```python
"""Run audits for projects whose schedule is due.

Two triggers call run_due_audits: APScheduler inside the API process
(SCHEDULER_ENABLED) and POST /api/cron/run for an external cron. A project is
claimed with a conditional UPDATE before its audit starts, so the two can
never start the same audit twice.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select, update

from app.db.engine import get_session_factory
from app.db.models import Project, as_utc, utcnow

logger = logging.getLogger("seo_auditor")

INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def due_projects(session, now: datetime) -> List[Project]:
    projects = session.scalars(select(Project).where(Project.audit_schedule.in_(INTERVALS))).all()
    return [
        p for p in projects
        if p.last_scheduled_at is None or now - as_utc(p.last_scheduled_at) >= INTERVALS[p.audit_schedule]
    ]


def claim(session, project_id: int, previous: Optional[datetime], now: datetime) -> bool:
    """Atomically mark the project as scheduled at `now` -- only if nobody else
    has since `previous`. Returns whether this caller won."""
    condition = (Project.last_scheduled_at.is_(None) if previous is None
                 else Project.last_scheduled_at == previous)
    result = session.execute(
        update(Project).where(Project.id == project_id, condition).values(last_scheduled_at=now)
    )
    session.commit()
    return result.rowcount == 1


def run_due_audits(now: Optional[datetime] = None, runner=None) -> List[str]:
    if runner is None:
        from app.services.audit_service import run_full_audit as runner
    now = now or utcnow()
    factory = get_session_factory()
    started: List[str] = []

    with factory() as session:
        due = [(p.id, p.domain, p.last_scheduled_at, dict(p.audit_options_json or {}))
               for p in due_projects(session, now)]

    for project_id, domain, previous, options in due:
        with factory() as session:
            if not claim(session, project_id, previous, now):
                continue
        session_id = f"sess_{int(time.time() * 1000)}_{project_id}"
        try:
            runner(
                url=f"https://{domain}/", session_id=session_id,
                max_pages=options.get("max_pages", 100),
                max_depth=options.get("max_depth", 3),
                ignore_robots=bool(options.get("ignore_robots", False)),
                trigger="scheduled",
            )
            started.append(session_id)
        except Exception as exc:
            logger.error("Scheduled audit of %s failed: %s", domain, exc, exc_info=exc)
    return started


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_due_audits, "interval", minutes=15, id="run_due_audits",
                      max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler
```

`apps/backend/app/api/cron.py`:

```python
"""POST /api/cron/run -- lets an external cron service trigger due audits.

Absent (404) until CRON_SECRET is set, so an unconfigured deployment exposes
nothing; otherwise the bearer token must match, compared in constant time.
"""

from __future__ import annotations

import hmac
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from app.config import config
from app.scheduler import jobs

router = APIRouter()


@router.post("/cron/run", status_code=202)
def cron_run(background_tasks: BackgroundTasks, authorization: Optional[str] = Header(default=None)):
    if not config.CRON_SECRET:
        raise HTTPException(status_code=404, detail="Not Found")
    expected = f"Bearer {config.CRON_SECRET}"
    if not authorization or not hmac.compare_digest(authorization.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid cron token")
    background_tasks.add_task(jobs.run_due_audits)
    return {"status": "accepted"}
```

   The test monkeypatches `jobs.run_due_audits`. `add_task(jobs.run_due_audits)` looks the attribute up at request time, so the patch applies. `TestClient` runs background tasks before returning.

In `app/main.py`, after the projects router:

```python
from app.api.cron import router as cron_router  # noqa: E402
app.include_router(cron_router, prefix="/api")


@app.on_event("startup")
def _start_scheduler():
    if config.SCHEDULER_ENABLED:
        from app.scheduler.jobs import start_scheduler
        app.state.scheduler = start_scheduler()
```

- [ ] **Step 4: Verify and commit**

Run: `cd apps/backend && python -m pytest tests/test_scheduler.py -v && python -m pytest -q`
Expected: all PASS.

```bash
git add apps/backend/app/scheduler apps/backend/app/api/cron.py apps/backend/app/main.py apps/backend/tests/test_scheduler.py
git commit -m "feat: scheduled audits via APScheduler or a secret-protected cron endpoint"
```

---

### Task 8: Postgres check, deploy, docs, verification

**Files:**
- Test: `apps/backend/tests/test_postgres_optional.py` (opt-in)
- Modify: `deploy/oracle/docker-compose.yml`, `apps/backend/.env.example`, `docs/env.md`, `docs/api.md`, `README.md`

- [ ] **Step 1: Opt-in Postgres test**

Create `apps/backend/tests/test_postgres_optional.py`:

```python
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
```

Run: `docker run -d --name pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine`, wait until `docker exec pg-test pg_isready` succeeds, then run the test with `PG_TEST_URL` set as in the docstring. Expected: PASS. Then `docker rm -f pg-test`. Without `PG_TEST_URL` the suite skips it.

- [ ] **Step 2: Deploy and env**

`deploy/oracle/docker-compose.yml`:
- In the `backend` environment, add `DATABASE_URL: ${DATABASE_URL:-}`, `CRON_SECRET: ${CRON_SECRET:-}` and `SCHEDULER_ENABLED: ${SCHEDULER_ENABLED:-false}`.
- Add a service:

```yaml
  # Optional. Set DATABASE_URL=postgresql+psycopg://seo:${POSTGRES_PASSWORD}@postgres/seo
  # to use it; without DATABASE_URL the backend uses SQLite on the sessions volume.
  postgres:
    image: postgres:16-alpine
    restart: unless-stopped
    profiles: ["postgres"]
    environment:
      POSTGRES_USER: seo
      POSTGRES_DB: seo
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD}
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U seo"]
      interval: 10s
      retries: 5
```

  Add `pgdata:` under `volumes:`. Because of `profiles: ["postgres"]`, it only starts with `docker compose --profile postgres up -d`.

`apps/backend/.env.example`: append

```
# Central database. Unset = SQLite at $SESSION_DIR/platform.db.
DATABASE_URL=
# Bearer token for POST /api/cron/run. Unset = route disabled.
CRON_SECRET=
# Run due scheduled audits in-process every 15 minutes.
SCHEDULER_ENABLED=false
```

- [ ] **Step 3: Docs**

- `docs/env.md`: add `DATABASE_URL`, `CRON_SECRET`, `SCHEDULER_ENABLED` and `PAGE_CACHE_MAX_AGE_DAYS`, with defaults and what each does.
- `docs/api.md`: document the five project/diff routes and `POST /api/cron/run`, with request/response examples taken from the tests.
- `README.md`: add a "Projects & history (Phase 1)" section covering the backfill command and the note that crawls run on the always-on VM (Oracle). Vercel serverless can't run them. An external cron only needs `curl -X POST -H "Authorization: Bearer $CRON_SECRET" https://<backend>/api/cron/run`. Add a **How to verify** list that matches Step 4.

- [ ] **Step 4: End-to-end verification**

In a scratch `SESSION_DIR`, from `apps/backend`:

1. `python -m app.cli https://books.toscrape.com/ --max-pages 20 --max-depth 2 --skip-external-links --json` twice. Each result must contain `"persisted": true` and an `audit_id`.
2. Start the API (`uvicorn app.main:app --port 5055`) with the same `SESSION_DIR`, then:
   - `GET /api/projects` → `books.toscrape.com` with `audit_count: 2`.
   - `GET /api/projects/{id}/audits` → two audits, newest first.
   - `GET /api/audits/{newest}/diff` → a diff against the older audit (likely 0 new, 0 fixed, since the site is static).
3. `CRON_SECRET=x`, `PATCH` the project to `audit_schedule: "daily"`, then `POST /api/cron/run` with `Authorization: Bearer x` → 202, and a third audit with `trigger: "scheduled"` appears.

Record the outputs in the commit message.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/tests/test_postgres_optional.py deploy/oracle/docker-compose.yml apps/backend/.env.example docs/env.md docs/api.md README.md
git commit -m "docs: Phase 1 deploy, env, API docs and verification; opt-in Postgres test"
```
