"""Broken backlinks on the audit: a page that errors but still has links pointing at it."""

from __future__ import annotations

import urllib.parse as up
from typing import Any, Dict, List, Tuple

from sqlalchemy import desc, select

from app.auditor.checks import issue
from app.crawler.crawler import normalize_url
from app.db.engine import get_session_factory
from app.db.models import BacklinkLink, BacklinkSnapshot, Project


def broken_backlink_targets(domain: str, factory=None) -> Dict[str, Tuple[int, int]]:
    """normalised target URL -> (backlinks, distinct linking domains), from the
    project's latest snapshot. No snapshot, no targets."""
    factory = factory or get_session_factory()
    with factory() as session:
        snap_id = session.scalar(
            select(BacklinkSnapshot.id).join(Project, Project.id == BacklinkSnapshot.project_id)
            .where(Project.domain == domain, BacklinkSnapshot.source == "snapshot")
            .order_by(desc(BacklinkSnapshot.taken_at), desc(BacklinkSnapshot.id)).limit(1))
        if snap_id is None:
            return {}
        links = session.execute(select(BacklinkLink.url_from, BacklinkLink.url_to).where(
            BacklinkLink.snapshot_id == snap_id, BacklinkLink.kind == "broken")).all()
    counts: Dict[str, List[Any]] = {}
    for url_from, url_to in links:
        entry = counts.setdefault(normalize_url(url_to), [0, set()])
        entry[0] += 1
        entry[1].add((up.urlsplit(url_from).hostname or "").lower())
    return {url: (n, len(domains)) for url, (n, domains) in counts.items()}


def backlink_issues(targets: Dict[str, Tuple[int, int]], results: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
    out: Dict[str, List[Dict[str, str]]] = {}
    if not targets:
        return out
    for url, page in results.items():
        status = getattr(page, "status_code", None)
        match = targets.get(normalize_url(url))
        if status is not None and status >= 400 and match:
            n, d = match
            out[url] = [issue("warning", "BACKLINK_TO_BROKEN_PAGE",
                              f"{n} backlink{'' if n == 1 else 's'} from {d} domain{'' if d == 1 else 's'} point to "
                              f"this broken page. Redirect it to keep their value.")]
    return out
