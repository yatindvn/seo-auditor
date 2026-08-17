"""
rank_checker.py — Live Google ranking checks via the official Custom Search
JSON API (100 free queries/day). Owns an in-memory cache + daily quota
counter so a multi-page crawl doesn't blow through the quota on day one.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

CSE_ENDPOINT = "https://www.googleapis.com/customsearch/v1"

logger = logging.getLogger("seo_auditor")

_NOTES = {
    "not_configured": "ranking check unavailable — Google CSE not configured",
    "quota_reached": "ranking check skipped — daily Google CSE quota reached",
    "error": "ranking check failed — Google CSE request error",
}


class _RankCheckState:
    """In-memory cache + daily quota counter, mirroring session_model.py's
    SessionStore pattern: no DB, no persistence beyond process lifetime."""

    def __init__(self) -> None:
        self._cache: Dict[Tuple[str, str], Dict] = {}
        self._quota_date = None
        self._quota_used = 0

    def get_cached(self, key: Tuple[str, str], ttl_hours: int) -> Optional[List[str]]:
        entry = self._cache.get(key)
        if not entry:
            return None
        if datetime.now(timezone.utc) - entry["cached_at"] > timedelta(hours=ttl_hours):
            return None
        return entry["urls"]

    def set_cached(self, key: Tuple[str, str], urls: List[str]) -> None:
        self._cache[key] = {"urls": urls, "cached_at": datetime.now(timezone.utc)}

    def _reset_quota_if_new_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self._quota_date != today:
            self._quota_date = today
            self._quota_used = 0

    def can_query(self, daily_quota: int) -> bool:
        self._reset_quota_if_new_day()
        return self._quota_used < daily_quota

    def record_query(self) -> None:
        self._reset_quota_if_new_day()
        self._quota_used += 1

    def reset(self) -> None:
        """Test-only: clear cache and quota usage."""
        self._cache.clear()
        self._quota_date = None
        self._quota_used = 0


_state = _RankCheckState()


def _normalize_url(url: str) -> str:
    url = url.split("#")[0].split("?")[0]
    url = re.sub(r"^https?://", "", url)
    url = re.sub(r"^www\.", "", url)
    return url.rstrip("/")


def _domain(url: str) -> str:
    netloc = (urlparse(url).netloc or url).lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _get_cse_results(keyword: str, target_domain: str, config) -> Tuple[Optional[List[str]], Optional[str]]:
    """Cache-or-live CSE lookup for one keyword.

    Returns (urls, skip_reason): urls is a list on success (possibly empty),
    None on any skip/failure; skip_reason is None on success else one of
    "not_configured" | "quota_reached" | "error".

    This is the single place cache/quota bookkeeping happens — both
    check_rankings() and keyword_suggestions.py's competitor-gap path call
    this directly rather than duplicating the logic.
    """
    if not config.GOOGLE_CSE_API_KEY or not config.GOOGLE_CSE_CX:
        return None, "not_configured"

    cache_key = (keyword, target_domain)
    cached = _state.get_cached(cache_key, config.GOOGLE_CSE_CACHE_TTL_HOURS)
    if cached is not None:
        return cached, None

    if not _state.can_query(config.GOOGLE_CSE_DAILY_QUOTA):
        return None, "quota_reached"

    try:
        resp = requests.get(
            CSE_ENDPOINT,
            params={"key": config.GOOGLE_CSE_API_KEY, "cx": config.GOOGLE_CSE_CX, "q": keyword, "num": 10},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        urls = [item["link"] for item in data.get("items", []) if "link" in item]
    except Exception as exc:
        # Never log `exc` (or exc_info) directly here: requests.raise_for_status()
        # embeds the full request URL — including the `key=<API key>` query
        # param — in its exception message, and that message is the exception's
        # str(). Log only the exception type and, when present, the HTTP status
        # code, neither of which can contain the credential.
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        logger.error(
            "CSE lookup failed for keyword %r: %s (status_code=%s)",
            keyword, type(exc).__name__, status_code,
        )
        return None, "error"

    _state.record_query()
    _state.set_cached(cache_key, urls)
    return urls, None


def check_rankings(
    page_url: str,
    keywords: List[str],
    config,
    deep_rank_check: bool = False,
    max_keywords: Optional[int] = None,
) -> List[Dict]:
    # `deep_rank_check` is reserved for future page-2+ pagination support
    # (each extra page is another quota-consuming query) — accepted here so
    # callers can opt in without a breaking signature change later, but it
    # has no effect yet: only the first page of CSE results is ever checked.
    target_domain = _domain(page_url)
    norm_page = _normalize_url(page_url)
    # The config cap guards *automatic* extraction from spending quota. Keywords a
    # user nominated explicitly must not be silently dropped, so callers with an
    # explicit list pass their own bound.
    limit = max_keywords if max_keywords is not None else config.GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE
    capped = keywords[:limit]

    results = []
    for kw in capped:
        checked_at = datetime.now(timezone.utc).isoformat()
        urls, skip_reason = _get_cse_results(kw, target_domain, config)
        if urls is None:
            results.append({
                "keyword": kw,
                "position": None,
                "status": "skipped",
                "note": _NOTES[skip_reason],
                "checked_at": checked_at,
                "top_urls": [],
            })
            continue

        position = None
        for i, link in enumerate(urls, start=1):
            if _normalize_url(link) == norm_page:
                position = i
                break

        results.append({
            "keyword": kw,
            "position": position,
            "status": "ranked" if position else "not_ranked",
            "note": None if position else "not found in top 10",
            "checked_at": checked_at,
            "top_urls": urls,
        })
    return results
