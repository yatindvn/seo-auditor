"""Check a project's keywords: one SERP per keyword gives my position, the URL
that ranks, and every competitor's position."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Sequence, Tuple

from sqlalchemy import select

from app.alerts import rules
from app.alerts.delivery import deliver
from app.alerts.notifiers import configured_notifiers
from app.config import config
from app.db.engine import get_session_factory
from app.db.models import Competitor, Keyword, Project, RankCheck, utcnow
from app.providers.serp import ProviderSkipped, SerpItem, SerpQuery

logger = logging.getLogger("seo_auditor")
SERP_SNAPSHOT_LIMIT = 100


def _matches(domain: str, target: str) -> bool:
    return domain == target or domain.endswith("." + target)


def position_for(items: Sequence[SerpItem], domain: str) -> Tuple[Optional[int], Optional[str]]:
    for item in items:
        if _matches(item.domain, domain):
            return item.position, item.url
    return None, None


def check_keyword(session, provider, keyword: Keyword, project_domain: str,
                  competitor_domains: List[str], depth: int) -> RankCheck:
    query = SerpQuery(keyword.phrase, country=keyword.country or "US",
                      language=keyword.language or "en", device=keyword.device or "desktop",
                      depth=depth)
    check = RankCheck(keyword_id=keyword.id, audit_id=None, checked_at=utcnow(),
                      provider=provider.name, status="skipped")
    try:
        result = provider.search(query)
    except ProviderSkipped as exc:
        check.note = str(exc)
    except Exception as exc:
        # Type only: provider exceptions may carry request details.
        logger.error("Rank check failed for %r: %s", keyword.phrase, type(exc).__name__)
        check.note = f"provider error: {type(exc).__name__}"
    else:
        position, url = position_for(result.items, project_domain)
        check.status = "ranked" if position else "not_ranked"
        check.position, check.ranking_url, check.note = position, url, result.note
        check.competitor_positions_json = {d: position_for(result.items, d)[0] for d in competitor_domains}
        check.serp_json = [{"position": i.position, "url": i.url, "domain": i.domain}
                           for i in result.items[:SERP_SNAPSHOT_LIMIT]]
    session.add(check)
    session.flush()
    return check


def previous_real_check(session, keyword_id: int, before_id: int) -> Optional[RankCheck]:
    return session.scalar(
        select(RankCheck).where(RankCheck.keyword_id == keyword_id, RankCheck.id < before_id,
                                RankCheck.status != "skipped")
        .order_by(RankCheck.id.desc()).limit(1)
    )


@dataclass
class RunReport:
    checked: int = 0
    skipped: int = 0
    changes: List = field(default_factory=list)


def run_project(project_id: int, now: Optional[datetime] = None, provider=None,
                notifiers=None, factory=None) -> RunReport:
    if provider is None:
        from app.providers.registry import get_serp_provider
        provider = get_serp_provider()
    factory = factory or get_session_factory()
    report = RunReport()

    with factory.begin() as session:
        project = session.get(Project, project_id)
        if project is None:
            return report
        competitors = list(session.scalars(
            select(Competitor.domain).where(Competitor.project_id == project_id)).all())
        keywords = session.scalars(
            select(Keyword).where(Keyword.project_id == project_id, Keyword.enabled.is_(True))
            .order_by(Keyword.id)).all()
        settings = project.alert_settings_json
        domain = project.domain
        for keyword in keywords:
            check = check_keyword(session, provider, keyword, project.domain, competitors, config.RANK_DEPTH)
            report.checked += 1
            if check.status == "skipped":
                report.skipped += 1
                continue
            previous = previous_real_check(session, keyword.id, check.id)
            report.changes.extend(rules.evaluate(previous, check, keyword, settings))

    if report.changes:
        if notifiers is None:
            notifiers = configured_notifiers()
        deliver(factory, project_id, domain, report.changes, notifiers, now or utcnow())
    return report
