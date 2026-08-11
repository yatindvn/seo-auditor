"""
keyword_suggestions.py — Combines Google Autocomplete (free, unofficial) with
a competitor keyword-gap comparison to suggest keywords a page should target.

Google Autocomplete is an undocumented endpoint: it may change shape or
disappear without notice. Every call to it is wrapped so a failure here
never breaks the audit — it just means fewer suggestions.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

import requests

from .. import checks
from . import keyword_extraction, rank_checker

AUTOCOMPLETE_ENDPOINT = "https://suggestqueries.google.com/complete/search"
MAX_SUGGESTIONS = 10
MAX_COMPETITORS = 3


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
    except Exception:
        return []


def _extract_competitor_meta(page) -> Tuple[Dict, Dict]:
    _, title = checks.check_title(page)
    _, h1 = checks.check_headings(page)
    _, meta_description = checks.check_meta_description(page)
    soup = checks._soup(page.html)
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
    page_meta: Dict,
    rank_results: List[Dict],
    config,
    fetch_page: Callable,
    page_url: str,
    enable_competitor_gap: bool = False,
) -> List[Dict]:
    current_phrases = {k["phrase"].lower() for k in seed_keywords}
    suggestions: List[Dict] = []
    seen = set()

    for seed in seed_keywords[:3]:
        for phrase in _autocomplete_suggestions(seed["phrase"]):
            key = phrase.lower()
            if key in seen or key in current_phrases:
                continue
            seen.add(key)
            suggestions.append({"phrase": phrase, "reason": "related search", "competitor_examples": None})

    if enable_competitor_gap and seed_keywords:
        page_domain = rank_checker._domain(page_url)
        for gap in _competitor_gap(
            seed_keywords[0]["phrase"], page_domain, current_phrases, rank_results, config, fetch_page
        ):
            key = gap["phrase"].lower()
            if key in seen or key in current_phrases:
                continue
            seen.add(key)
            suggestions.append(gap)

    return suggestions[:MAX_SUGGESTIONS]
