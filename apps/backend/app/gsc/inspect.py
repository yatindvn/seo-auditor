"""URL Inspection of an audit's most important pages, and the issues it raises."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.analysis.sampling import select_pages
from app.auditor.checks import issue
from app.crawler.crawler import normalize_url
from app.db.projects import project_domain
from app.gsc.provider import GscError, Inspection, build_gsc_provider
from app.gsc.sync import resolve_property

logger = logging.getLogger(__name__)


def gsc_issues(insp: Inspection, meta_robots: Optional[str], x_robots: Optional[str]) -> List[Dict[str, str]]:
    if insp.error:
        return []
    out = []
    deliberate = "noindex" in (meta_robots or "").lower() or "noindex" in (x_robots or "").lower()
    if insp.verdict in ("FAIL", "NEUTRAL") and not deliberate:
        out.append(issue("warning", "GSC_NOT_INDEXED", f"Not indexed by Google: {insp.coverage_state or insp.verdict}"))
    g, u = insp.google_canonical, insp.user_canonical
    if g and u and normalize_url(g) != normalize_url(u):
        out.append(issue("info", "GSC_CANONICAL_MISMATCH", f"Google chose {g} over your canonical {u}"))
    return out


def inspect_for_audit(audit_url: str, start_page: str, top_pages: List[Dict[str, Any]], results: Dict[str, Any],
                      limit: int, provider=None) -> Tuple[str, Optional[str], bool, List[Inspection]]:
    provider = provider if provider is not None else build_gsc_provider()
    if provider is None:
        return "not_configured", None, False, []
    try:
        prop = resolve_property(project_domain(audit_url), provider)
    except GscError as exc:
        logger.warning("Search Console property lookup failed: %s", exc.message)
        return "error", None, provider.dry_run, []
    if not prop:
        return "no_property", None, provider.dry_run, []
    return "inspected", prop, provider.dry_run, [provider.inspect(prop, url)
                                                for url in select_pages(start_page, top_pages, results, limit)]
