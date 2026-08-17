"""
keyword_suggestions.py — Combines Google Autocomplete (free, unofficial) with
a competitor keyword-gap comparison to suggest keywords a page should target.

Google Autocomplete is an undocumented endpoint: it may change shape or
disappear without notice. Every call to it is wrapped so a failure here
never breaks the audit — it just means fewer suggestions.
"""

from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Tuple

import requests

from .. import checks
from . import keyword_extraction, rank_checker

AUTOCOMPLETE_ENDPOINT = "https://suggestqueries.google.com/complete/search"
MAX_SUGGESTIONS = 10
MAX_COMPETITORS = 3

logger = logging.getLogger("seo_auditor")


def _autocomplete_suggestions(seed: str) -> List[str]:
    try:
        resp = requests.get(
            AUTOCOMPLETE_ENDPOINT,
            params={"client": "firefox", "q": seed},
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()
        return [s for s in data[1] if isinstance(s, str) and s.lower() != seed.lower()]
    except Exception as exc:
        # Autocomplete is an unofficial, undocumented endpoint — failures here
        # are expected/normal, not actionable, so this is debug-level only.
        logger.debug("Autocomplete lookup failed for %r: %s", seed, exc)
        return []


def _extract_competitor_meta(page) -> Tuple[Dict, Dict]:
    _, title = checks.check_title(page)
    _, h1 = checks.check_headings(page)
    _, meta_description = checks.check_meta_description(page)
    soup = checks._soup(page.html)
    for tag in (soup(["script", "style", "noscript"]) if soup else []):
        tag.decompose()
    text = soup.get_text(" ", strip=True) if soup else ""
    page_meta = {"title": title, "h1": h1, "meta_description": meta_description, "heading_hierarchy": []}
    content_stats = {"word_count": len(text.split()), "text": text[:20000]}
    return page_meta, content_stats


def _competitor_gap(
    seed_keyword: str,
    page_domain: str,
    current_phrases: set,
    rank_results: List[Dict],
    config,
    fetch_page: Callable,
) -> List[Dict]:
    top_urls: Optional[List[str]] = None
    for r in rank_results:
        if r["keyword"] == seed_keyword and r.get("top_urls"):
            top_urls = r["top_urls"]
            break

    if top_urls is None:
        top_urls, _ = rank_checker._get_cse_results(seed_keyword, page_domain, config)
        top_urls = top_urls or []

    competitor_urls = [u for u in top_urls if rank_checker._domain(u) != page_domain][:MAX_COMPETITORS]

    phrase_hits: Dict[str, List[str]] = {}
    for url in competitor_urls:
        try:
            page = fetch_page(url)
        except Exception:
            continue
        if not page or not getattr(page, "html", None):
            continue
        comp_meta, comp_stats = _extract_competitor_meta(page)
        for kw in keyword_extraction.extract_keywords(comp_meta, comp_stats, top_n=15):
            if kw["phrase"] not in current_phrases:
                phrase_hits.setdefault(kw["phrase"], []).append(url)

    return [
        {
            "phrase": phrase,
            "reason": "used by top-ranking competitors but missing on this page",
            "competitor_examples": urls,
        }
        for phrase, urls in phrase_hits.items()
        if len(urls) >= 2
    ]


def suggest_keywords(
    seed_keywords: List[Dict],
    rank_results: List[Dict],
    config,
    fetch_page: Callable,
    page_url: str,
    enable_competitor_gap: bool = False,
) -> List[Dict]:
    current_phrases = {k["phrase"].lower() for k in seed_keywords}
    suggestions: List[Dict] = []
    seen = set()

    # Only "not_ranked" is evidence of underperformance. "skipped" means the check
    # never ran (no credentials, quota exhausted, or request error) — seeding from
    # it would invent replacements for keywords nobody measured.
    underperforming = [r["keyword"] for r in rank_results if r.get("status") == "not_ranked"]
    # Non-empty rank_results means rank checking ran for this page — seed only
    # from what genuinely didn't rank, even if that list is empty (all "ranked"
    # or "skipped"). Only fall back to seed keywords when rank checking never
    # ran at all (empty rank_results), preserving pre-rank-checking behaviour.
    has_rank_data = bool(rank_results)

    if has_rank_data:
        seed_phrases = [(kw, kw) for kw in underperforming[:3]]
    else:
        seed_phrases = [(s["phrase"], None) for s in seed_keywords[:3]]

    for seed_phrase, replaces in seed_phrases:
        for phrase in _autocomplete_suggestions(seed_phrase):
            key = phrase.lower()
            if key in seen or key in current_phrases:
                continue
            seen.add(key)
            suggestions.append({
                "phrase": phrase,
                "reason": "related search",
                "competitor_examples": None,
                "replaces": replaces,
            })

    if enable_competitor_gap and seed_keywords:
        # Same rule as the primary loop above: once rank checking has run for
        # this page (has_rank_data), only a genuinely-unranked keyword may
        # seed a competitor-gap query. Falling back to a plain seed keyword
        # here would fire a live competitor fetch from a keyword nobody
        # measured — e.g. every result "skipped" from a transient request
        # error, which (unlike not_configured/quota_reached) has no other
        # backstop inside _competitor_gap. Only fall back to seed_keywords
        # when rank checking never ran at all (empty rank_results).
        if has_rank_data:
            gap_seed = underperforming[0] if underperforming else None
        else:
            gap_seed = seed_keywords[0]["phrase"]

        if gap_seed is not None:
            page_domain = rank_checker._domain(page_url)
            for gap in _competitor_gap(
                gap_seed, page_domain, current_phrases, rank_results, config, fetch_page
            ):
                key = gap["phrase"].lower()
                if key in seen or key in current_phrases:
                    continue
                seen.add(key)
                gap["replaces"] = gap_seed if underperforming else None
                suggestions.append(gap)

    return suggestions[:MAX_SUGGESTIONS]
