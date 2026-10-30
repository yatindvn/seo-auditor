"""Competitor link gap: domains that link to competitors but not to you."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import Competitor, Project

MAX_COMPETITORS = 5


class GapError(ValueError):
    pass


def link_gap(project_id: int, competitors: Optional[List[str]], provider, factory=None) -> Dict[str, Any]:
    """ProviderSkipped / ProviderError propagate to the caller."""
    factory = factory or get_session_factory()
    with factory() as session:
        project = session.get(Project, project_id)
        mine = project.domain
        if competitors is None:
            competitors = list(session.scalars(select(Competitor.domain).where(
                Competitor.project_id == project_id).order_by(Competitor.id)))
    chosen: List[str] = []
    for c in competitors:
        domain = (c or "").strip().lower()
        if domain and domain != mine and domain not in chosen:
            chosen.append(domain)
    if not 1 <= len(chosen) <= MAX_COMPETITORS:
        raise GapError(f"pick 1 to {MAX_COMPETITORS} competitors")
    rows = [{"domain": r.domain, "rank": r.rank, "linked_count": len(r.linked_competitors),
             "backlinks_by_competitor": dict(r.linked_competitors)}
            for r in provider.intersection(chosen, mine, 100)]
    rows.sort(key=lambda r: (-r["linked_count"], -(r["rank"] or 0), r["domain"]))
    return {"my_domain": mine, "competitors": chosen, "dry_run": provider.dry_run, "rows": rows[:100]}
