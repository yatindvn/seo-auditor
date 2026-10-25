"""Explore a seed keyword: ideas, volume, difficulty, a traffic estimate, and
optional clusters of keywords whose search results overlap."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from app.providers import registry
from app.providers.dry_run import DryRunProvider
from app.providers.keywords import normalize_keyword
from app.providers.serp import ProviderSkipped, SerpQuery, SerpResult

logger = logging.getLogger("seo_auditor")

# Share of a keyword's searches that the #1 organic result receives, as a round
# figure from published CTR studies. The traffic figure is an *estimate* from
# this constant, not measured traffic -- and is labelled so.
CTR_TOP1 = 0.28
MAX_IDEAS = 50
MAX_CLUSTER = 20
MIN_SHARED_URLS = 3


@dataclass
class ExploreResult:
    seed: str
    country: str
    language: str
    dry_run: bool
    keywords: List[Dict] = field(default_factory=list)
    clusters: List[List[str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def _resolve_serp(data):
    """Dry-run data previews with dry-run SERPs; live data uses a live SERP
    provider if one exists, else none (no PAA, no clustering)."""
    if not registry.is_live(data):
        return DryRunProvider()
    try:
        serp = registry.get_serp_provider()
    except ProviderSkipped:
        return None
    return serp if registry.is_live(serp) else None


def cluster_keywords(keywords: List[str], serp, country: str, language: str,
                     prefetched: Optional[Dict[str, SerpResult]] = None) -> Tuple[List[List[str]], List[str]]:
    prefetched = prefetched or {}
    tops: Dict[str, set] = {}
    notes: List[str] = []
    for keyword in keywords[:MAX_CLUSTER]:
        try:
            result = prefetched.get(keyword) or serp.search(SerpQuery(keyword, country, language, depth=10))
        except ProviderSkipped as exc:
            notes.append(f"{keyword!r} not clustered: {exc}")
            continue
        except Exception as exc:
            notes.append(f"{keyword!r} not clustered: {type(exc).__name__}")
            continue
        tops[keyword] = {item.url for item in result.items[:10]}

    parent = {k: k for k in tops}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    checked = list(tops)
    for i, a in enumerate(checked):
        for b in checked[i + 1:]:
            if len(tops[a] & tops[b]) >= MIN_SHARED_URLS:
                parent[find(a)] = find(b)

    groups: Dict[str, List[str]] = {}
    for k in checked:
        groups.setdefault(find(k), []).append(k)
    order = {k: i for i, k in enumerate(keywords)}   # callers pass keywords volume-sorted
    clusters = [sorted(g, key=order.get) for g in groups.values()]
    return sorted(clusters, key=lambda g: order[g[0]]), notes


def explore(seed: str, country: str = "US", language: str = "en", cluster: bool = False,
            serp=None, data=None) -> ExploreResult:
    from app.seo import keyword_suggestions   # looked up at call time: tests replace it

    seed = normalize_keyword(seed)
    if not seed:
        raise ValueError("seed keyword is empty")
    data = data or registry.get_keyword_provider()
    if serp is None:
        serp = _resolve_serp(data)
    result = ExploreResult(seed=seed, country=country.upper(), language=language.lower(),
                           dry_run=not registry.is_live(data))

    sources: Dict[str, str] = {}

    def add(phrase, source):
        keyword = normalize_keyword(phrase)
        if keyword and keyword != seed and keyword not in sources:
            sources[keyword] = source

    for phrase in keyword_suggestions._autocomplete_suggestions(seed):
        add(phrase, "autocomplete")

    prefetched: Dict[str, SerpResult] = {}
    if serp is not None:
        try:
            prefetched[seed] = serp.search(SerpQuery(seed, result.country, result.language, depth=10))
            for question in prefetched[seed].questions:
                add(question, "people_also_ask")
        except ProviderSkipped as exc:
            result.notes.append(f"People Also Ask skipped: {exc}")
        except Exception as exc:
            result.notes.append(f"People Also Ask failed: {type(exc).__name__}")

    ideas = list(sources)[:MAX_IDEAS]
    keywords = [seed] + ideas

    metrics, difficulty = {}, {}
    try:
        metrics = data.metrics(keywords, result.country, result.language)
        difficulty = data.difficulty(keywords, result.country, result.language)
    except ProviderSkipped:
        raise
    except Exception as exc:
        logger.error("Keyword metrics failed for %r: %s", seed, type(exc).__name__)
        result.notes.append(f"keyword metrics unavailable: {type(exc).__name__}")

    rows = []
    for keyword in keywords:
        m = metrics.get(keyword)
        volume = m.search_volume if m else None
        rows.append({
            "keyword": keyword,
            "source": "seed" if keyword == seed else sources[keyword],
            "search_volume": volume,
            "cpc": m.cpc if m else None,
            "competition": m.competition if m else None,
            "difficulty": difficulty.get(keyword),
            "traffic_potential_estimate": round(volume * CTR_TOP1) if volume is not None else None,
        })
    rows.sort(key=lambda r: (r["search_volume"] is None, -(r["search_volume"] or 0), r["keyword"]))
    result.keywords = rows

    if cluster:
        if serp is None:
            result.notes.append("clustering needs a live SERP provider")
        else:
            result.clusters, notes = cluster_keywords([r["keyword"] for r in rows], serp,
                                                      result.country, result.language, prefetched)
            result.notes.extend(notes)
    return result
