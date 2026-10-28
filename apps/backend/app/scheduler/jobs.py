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
from app.db.models import Keyword, Project, as_utc, utcnow

logger = logging.getLogger("seo_auditor")

INTERVALS = {"daily": timedelta(days=1), "weekly": timedelta(days=7)}


def due_projects(session, now: datetime) -> List[Project]:
    projects = session.scalars(select(Project).where(Project.audit_schedule.in_(INTERVALS))).all()
    return [
        p for p in projects
        if p.last_scheduled_at is None or now - as_utc(p.last_scheduled_at) >= INTERVALS[p.audit_schedule]
    ]


def claim(session, project_id: int, previous: Optional[datetime], now: datetime,
          column=None) -> bool:
    """Atomically mark the project as run at `now` -- only if nobody else has
    since `previous`. `column` is the timestamp being claimed."""
    column = column if column is not None else Project.last_scheduled_at
    condition = column.is_(None) if previous is None else column == previous
    result = session.execute(
        update(Project).where(Project.id == project_id, condition).values({column.key: now})
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
                render_js=bool(options.get("render_js", False)),
                trigger="scheduled",
            )
            started.append(session_id)
        except Exception as exc:
            logger.error("Scheduled audit of %s failed: %s", domain, exc, exc_info=exc)
    return started


def due_rank_projects(session, now: datetime) -> List[Project]:
    has_keyword = select(Keyword.id).where(Keyword.project_id == Project.id,
                                           Keyword.enabled.is_(True)).exists()
    projects = session.scalars(select(Project).where(Project.rank_schedule == "daily", has_keyword)).all()
    return [p for p in projects
            if p.last_rank_checked_at is None or now - as_utc(p.last_rank_checked_at) >= timedelta(days=1)]


def run_due_rank_checks(now: Optional[datetime] = None, runner=None, provider=None,
                        notifiers=None) -> List[int]:
    """Daily rank checks. Only with a live provider: dry-run results are made
    up, and must never become rank history."""
    from app.providers import registry
    from app.providers.serp import ProviderSkipped

    if provider is None:
        try:
            provider = registry.get_serp_provider()
        except ProviderSkipped as exc:
            logger.warning("Scheduled rank checks skipped: %s", exc)
            return []
    if not registry.is_live(provider):
        logger.warning("Scheduled rank checks skipped: no live SERP provider "
                       "(set SERP_PROVIDER, and SERP_DRY_RUN=false for paid providers)")
        return []
    if runner is None:
        from app.rank.tracker import run_project as runner

    now = now or utcnow()
    factory = get_session_factory()
    with factory() as session:
        due = [(p.id, p.last_rank_checked_at) for p in due_rank_projects(session, now)]

    checked: List[int] = []
    for project_id, previous in due:
        with factory() as session:
            if not claim(session, project_id, previous, now, column=Project.last_rank_checked_at):
                continue
        try:
            runner(project_id, now=now, provider=provider, notifiers=notifiers)
            checked.append(project_id)
        except Exception as exc:
            logger.error("Scheduled rank check of project %s failed: %s", project_id, exc, exc_info=exc)
    return checked


def start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_due_audits, "interval", minutes=15, id="run_due_audits",
                      max_instances=1, coalesce=True)
    scheduler.add_job(run_due_rank_checks, "interval", minutes=15, id="run_due_rank_checks",
                      max_instances=1, coalesce=True)
    scheduler.start()
    return scheduler
