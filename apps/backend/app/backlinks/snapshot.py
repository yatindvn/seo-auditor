"""One backlink snapshot for a project: every call first, then one write."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import insert, select

from app.db.engine import get_session_factory
from app.db.models import BacklinkLink, BacklinkRefDomain, BacklinkSnapshot, Project, utcnow
from app.providers.serp import ProviderError, ProviderSkipped

WINDOW_DAYS = 30
TOP = 100
HISTORY_MONTHS = 12


def refresh_project(project_id: int, provider, today: Optional[date] = None, factory=None) -> Dict[str, Any]:
    factory = factory or get_session_factory()
    today = today or utcnow().date()
    with factory() as session:
        domain = session.get(Project, project_id).domain
        first = session.scalar(select(BacklinkSnapshot.id).where(
            BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "snapshot").limit(1)) is None
        known = set(session.scalars(select(BacklinkSnapshot.period).where(
            BacklinkSnapshot.project_id == project_id, BacklinkSnapshot.source == "history")))
    since = today - timedelta(days=WINDOW_DAYS)
    try:
        summary = provider.summary(domain)
        domains = provider.referring_domains(domain, TOP)
        links = {kind: provider.backlinks(domain, kind, since, TOP) for kind in ("new", "lost", "broken")}
        history = provider.history(domain, HISTORY_MONTHS) if first else []
    except ProviderSkipped as exc:
        return {"status": "capped", "message": str(exc), "dry_run": provider.dry_run}
    except ProviderError as exc:
        return {"status": "error", "message": str(exc), "dry_run": provider.dry_run}

    now, dry = utcnow(), provider.dry_run
    with factory.begin() as session:
        snap = BacklinkSnapshot(project_id=project_id, taken_at=now, provider=provider.name, metrics_json={},
                                source="snapshot", dry_run=dry, authority=summary.authority,
                                backlinks=summary.backlinks, referring_domains=summary.referring_domains,
                                broken_backlinks=summary.broken_backlinks)
        session.add(snap)
        session.flush()
        if domains:
            session.execute(insert(BacklinkRefDomain), [
                {"snapshot_id": snap.id, "domain": d.domain[:255], "rank": d.rank, "backlinks": d.backlinks,
                 "first_seen": (d.first_seen or None) and d.first_seen[:40]} for d in domains])
        link_rows = [{"snapshot_id": snap.id, "kind": kind, "url_from": l.url_from, "url_to": l.url_to,
                      "anchor": l.anchor, "domain_from_rank": l.domain_from_rank, "dofollow": l.dofollow,
                      "first_seen": (l.first_seen or None) and l.first_seen[:40],
                      "last_seen": (l.last_seen or None) and l.last_seen[:40], "target_status": l.target_status}
                     for kind, rows in links.items() for l in rows]
        if link_rows:
            session.execute(insert(BacklinkLink), link_rows)
        added = 0
        for point in history:
            if point.month in known:
                continue
            session.add(BacklinkSnapshot(
                project_id=project_id, provider=provider.name, metrics_json={}, source="history", dry_run=dry,
                period=point.month, taken_at=datetime(point.month.year, point.month.month, 1, tzinfo=timezone.utc),
                authority=point.authority, backlinks=point.backlinks, referring_domains=point.referring_domains))
            added += 1
        session.get(Project, project_id).last_backlink_refresh_at = now
        snapshot_id = snap.id
    return {"status": "refreshed", "snapshot_id": snapshot_id, "dry_run": dry, "history_months": added}
