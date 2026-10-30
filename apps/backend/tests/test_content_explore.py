"""Content Explorer: SERP -> pages -> backlinks -> summary, cached 7 days."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from app.content_explorer.explore import explore, get_search, normalize, recent, summarize
from app.crawler.crawler import PageResult
from app.db.engine import get_session_factory
from app.db.models import ContentSearch
from app.providers.dry_run import DryRunProvider
from app.providers.serp import ProviderError, ProviderSkipped, SerpItem, SerpResult

NOW = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
PAGE = "<html><head><title>{t}</title></head><body><h1>{t}</h1><h2>Best rare books</h2><h2>Rare first editions</h2><p>" + "word " * 300 + "</p></body></html>"


class LiveSerp:
    name = "dataforseo"

    def __init__(self, exc=None):
        self.calls, self.exc = 0, exc

    def search(self, query):
        self.calls += 1
        if self.exc:
            raise self.exc
        return SerpResult([SerpItem(i, f"https://s{i}.com/p", f"s{i}.com", f"S{i}") for i in range(1, 13)], self.name)


class Links:
    dry_run = False

    def __init__(self, exc=None):
        self.exc = exc

    def bulk_metrics(self, urls):
        if self.exc:
            raise self.exc
        return {u: (100 * n, 10 * n) for n, u in enumerate(urls, start=1)}


def fetch(url):
    return PageResult(url=url, final_url=url, status_code=200, html=PAGE.format(t=url))


def count():
    with get_session_factory()() as s:
        return s.scalar(select(func.count()).select_from(ContentSearch))


def test_normalize():
    assert normalize("  Rare   BOOKS ", "us", "EN") == ("rare books", "US", "en")
    for bad in (("a", "US", "en"), ("x" * 81, "US", "en"), ("ok topic", "USA", "en"), ("ok topic", "US", "e1")):
        with pytest.raises(ValueError):
            normalize(*bad)


def test_summary_math():
    rows = [{"word_count": 100, "schema_types": ["Article", "FAQPage"], "referring_domains": 5,
             "outline": [{"level": 2, "text": "Best rare books"}, {"level": 2, "text": "Rare rare"}, {"level": 3, "text": "Shipping"}]},
            {"word_count": 300, "schema_types": ["Article"], "referring_domains": None, "outline": [{"level": 2, "text": "Rare prices"}]},
            {"word_count": 900, "schema_types": [], "referring_domains": 15, "outline": []},
            {"word_count": None, "schema_types": [], "referring_domains": 25, "outline": [{"level": 2, "text": "ignored"}]}]
    s = summarize(rows)
    assert s["median_words"] == 300 and s["median_referring_domains"] == 15
    assert s["schema_counts"] == {"Article": 2, "FAQPage": 1}
    assert s["common_h2_terms"][0] == {"term": "rare", "count": 2}
    assert {"term": "shipping", "count": 1} not in s["common_h2_terms"]
    assert summarize([])["median_words"] is None


def test_live_search_is_analysed_saved_and_cached():
    serp = LiveSerp()
    first = explore("Rare Books", serp=serp, backlinks=Links(), fetch=fetch, now=NOW)
    assert first["cached"] is False and first["dry_run"] is False and len(first["results"]) == 10
    assert first["results"][0]["h1"] == "https://s1.com/p" and first["results"][2]["referring_domains"] == 30
    assert first["summary"]["median_words"] > 300 and {"term": "rare", "count": 10} in first["summary"]["common_h2_terms"]
    again = explore("rare books", serp=serp, backlinks=Links(), fetch=fetch, now=NOW + timedelta(days=6))
    assert again["cached"] is True and again["id"] == first["id"] and serp.calls == 1
    fresh = explore("rare books", refresh=True, serp=serp, backlinks=Links(), fetch=fetch, now=NOW + timedelta(days=6))
    assert fresh["cached"] is False and serp.calls == 2
    stale = explore("rare books", serp=serp, backlinks=Links(), fetch=fetch, now=NOW + timedelta(days=14))
    assert stale["cached"] is False and serp.calls == 3


def test_dry_run_is_saved_but_never_served_from_cache():
    a = explore("rare books", serp=DryRunProvider(), backlinks=Links(), now=NOW)
    b = explore("rare books", serp=DryRunProvider(), backlinks=Links(), now=NOW)
    assert a["dry_run"] and b["dry_run"] and not b["cached"] and a["id"] != b["id"]
    assert get_search(a["id"])["cached"] is True and get_search(9999) is None
    assert [r["id"] for r in recent()] == [b["id"], a["id"]]


def test_serp_failures_save_nothing_and_backlink_failures_only_note():
    with pytest.raises(ProviderSkipped):
        explore("rare books", serp=LiveSerp(ProviderSkipped("daily cap")), backlinks=Links(), fetch=fetch, now=NOW)
    with pytest.raises(ProviderError):
        explore("rare books", serp=LiveSerp(RuntimeError("boom")), backlinks=Links(), fetch=fetch, now=NOW)
    assert count() == 0
    r = explore("rare books", serp=LiveSerp(), backlinks=Links(ProviderSkipped("daily cap of 0")), fetch=fetch, now=NOW)
    assert r["notes"] == ["Backlinks skipped: daily cap of 0"] and r["results"][0]["word_count"] > 0
    assert r["results"][0]["backlinks"] is None
