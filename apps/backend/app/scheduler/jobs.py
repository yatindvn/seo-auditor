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
