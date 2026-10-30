"""Which Search Console property a project uses, and the daily sync."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, insert, select

from app.db.engine import get_session_factory
from app.db.models import GscDaily, GscPage, GscQuery, Project, utcnow
from app.db.projects import project_domain
from app.gsc.provider import GscError, SiteEntry

logger = logging.getLogger(__name__)
LAG_DAYS = 2


def match_property(domain: str, sites: List[SiteEntry]) -> Optional[str]:
    usable = [s.site_url for s in sites if s.permission != "siteUnverifiedUser"]
    if f"sc-domain:{domain}" in usable:
        return f"sc-domain:{domain}"
    prefixes = [u for u in usable if not u.startswith("sc-domain:") and project_domain(u) == domain]
    prefixes.sort(key=lambda u: (not u.startswith("https://"), "://www." not in u))
    return prefixes[0] if prefixes else None


def resolve_property(domain: str, provider, factory=None) -> Optional[str]:
    """The project's saved property, else a match from what the service account
    can see (saved onto the project when there is one). Raises GscError."""
    factory = factory or get_session_factory()
    with factory() as session:
        project = session.scalar(select(Project).where(Project.domain == domain))
        if project is not None and project.gsc_property:
            return project.gsc_property
    found = f"sc-domain:{domain}" if provider.dry_run else match_property(domain, provider.sites())
    if found:
        with factory.begin() as session:
            project = session.scalar(select(Project).where(Project.domain == domain))
            if project is not None and not project.gsc_property:
                project.gsc_property = found
    return found


def _stats(row) -> Dict[str, float]:
    return {"clicks": row.clicks, "impressions": row.impressions, "ctr": row.ctr, "position": row.position}


def sync_project(project_id: int, provider, today: Optional[date] = None, factory=None) -> Dict[str, Any]:
    factory = factory or get_session_factory()
    today = today or utcnow().date()
    with factory() as session:
        domain = session.get(Project, project_id).domain
    try:
        prop = resolve_property(domain, provider, factory)
    except GscError as exc:
        return {"status": "error", "property": None, "message": exc.message, "dry_run": provider.dry_run}
    if not prop:
        return {"status": "no_access", "property": None, "client_email": provider.client_email,
                "dry_run": provider.dry_run}
    end = today - timedelta(days=LAG_DAYS)
    try:
        daily = provider.search_analytics(prop, end - timedelta(days=89), end, ["date"], 1000)
        pages = provider.search_analytics(prop, end - timedelta(days=27), end, ["page"], 1000)
        queries = provider.search_analytics(prop, end - timedelta(days=27), end, ["query"], 1000)
    except GscError as exc:
        return {"status": "error", "property": prop, "message": exc.message, "dry_run": provider.dry_run}

    now, dry = utcnow(), provider.dry_run
    with factory.begin() as session:
        project = session.get(Project, project_id)
        project.gsc_property, project.last_gsc_sync_at = prop, now
        by_date = {date.fromisoformat(r.keys[0]): r for r in daily if r.keys}
        existing = {row.date: row for row in session.scalars(select(GscDaily).where(
            GscDaily.project_id == project_id, GscDaily.date.in_(list(by_date))))}
        for day, r in by_date.items():
            if day in existing:
                for key, value in _stats(r).items():
                    setattr(existing[day], key, value)
                existing[day].dry_run = dry
            else:
                session.add(GscDaily(project_id=project_id, date=day, dry_run=dry, **_stats(r)))
        session.execute(delete(GscPage).where(GscPage.project_id == project_id))
        session.execute(delete(GscQuery).where(GscQuery.project_id == project_id))
        if pages:
            session.execute(insert(GscPage), [{"project_id": project_id, "url": r.keys[0], "synced_at": now,
                                               "dry_run": dry, **_stats(r)} for r in pages if r.keys])
        if queries:
            session.execute(insert(GscQuery), [{"project_id": project_id, "query": r.keys[0], "synced_at": now,
                                                "dry_run": dry, **_stats(r)} for r in queries if r.keys])
    return {"status": "synced", "property": prop, "days": len(by_date), "pages": len(pages),
            "queries": len(queries), "dry_run": dry}
