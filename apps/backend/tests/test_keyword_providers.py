"""Keyword data: DataForSEO parsing, cache before spend, dry run, registry."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.providers import registry, spend
from app.providers.dataforseo_keywords import (
    DIFFICULTY_PATH, RANKED_PATH, VOLUME_PATH, DataForSeoKeywordProvider,
)
from app.providers.dry_run_keywords import DryRunKeywordProvider
from app.providers.keywords import clean_keywords
from app.providers.serp import ProviderError, ProviderSkipped

FIX = Path(__file__).parent / "fixtures"


def _http(name):
    http = MagicMock()
    http.post.return_value.json.return_value = json.loads((FIX / name).read_text())
    return http


def test_clean_keywords_normalises_dedupes_and_drops_long_ones():
    kept, dropped = clean_keywords(["  Espresso  Machine ", "espresso machine", "x" * 81, ""])
    assert kept == ["espresso machine"] and dropped == ["x" * 81]


def test_search_volume_request_and_parsing():
    http = _http("dataforseo_search_volume.json")
    out = DataForSeoKeywordProvider("l", "p", cap=5, http=http).metrics(
        ["Espresso Machine", "espresso grinder", "latte art"], "US", "en")
    assert http.post.call_args.args[0].endswith(VOLUME_PATH)
    assert http.post.call_args.kwargs["json"] == [{
        "keywords": ["espresso machine", "espresso grinder", "latte art"],
        "location_name": "United States", "language_code": "en"}]
    assert out["espresso machine"].search_volume == 74000 and out["espresso machine"].cpc == 1.2
    assert out["espresso machine"].competition == "HIGH"
    assert out["latte art"].search_volume is None


def test_difficulty_parsing():
    http = _http("dataforseo_keyword_difficulty.json")
    out = DataForSeoKeywordProvider("l", "p", cap=5, http=http).difficulty(
        ["espresso machine", "espresso grinder"], "US", "en")
    assert http.post.call_args.args[0].endswith(DIFFICULTY_PATH)
    assert out == {"espresso machine": 62, "espresso grinder": 41}


def test_ranked_keywords_request_and_parsing():
    http = _http("dataforseo_ranked_keywords.json")
    out = DataForSeoKeywordProvider("l", "p", cap=5, http=http).ranked_keywords("rival.org", "US", "en", 5000)
    assert http.post.call_args.args[0].endswith(RANKED_PATH)
    assert http.post.call_args.kwargs["json"] == [{
        "target": "rival.org", "location_name": "United States", "language_code": "en",
        "limit": 1000, "item_types": ["organic"]}]
    assert [(r.keyword, r.position, r.url, r.search_volume, r.difficulty) for r in out] == [
        ("best espresso machine", 3, "https://rival.org/best", 9900, 48),
        ("espresso vs coffee", 15, "https://rival.org/vs", 2400, None),
    ]


def test_a_cache_hit_makes_no_request_and_spends_nothing():
    http = _http("dataforseo_search_volume.json")
    provider = DataForSeoKeywordProvider("l", "p", cap=1, http=http)
    provider.metrics(["espresso machine"], "US", "en")
    provider.metrics(["espresso machine"], "US", "en")       # cached: cap of 1 not exceeded
    assert http.post.call_count == 1
    with pytest.raises(ProviderSkipped):                     # a different request needs budget
        provider.metrics(["espresso grinder"], "US", "en")


def test_labs_budget_is_separate_from_the_serp_budget():
    from datetime import date
    for _ in range(3):
        spend.reserve("dataforseo", cap=3, today=date(2026, 10, 25))
    spend.reserve("dataforseo_labs", cap=3, today=date(2026, 10, 25))


def test_provider_errors_surface():
    http = MagicMock()
    http.post.return_value.json.return_value = {"status_code": 40200, "status_message": "Payment required."}
    with pytest.raises(ProviderError, match="40200"):
        DataForSeoKeywordProvider("l", "p", cap=5, http=http).difficulty(["a"], "US", "en")


def test_dry_run_is_deterministic_labelled_and_varies_by_domain():
    dry = DryRunKeywordProvider()
    assert dry.name == "dry_run"
    assert dry.metrics(["a", "b"], "US", "en") == DryRunKeywordProvider().metrics(["a", "b"], "US", "en")
    mine = {r.keyword for r in dry.ranked_keywords("example.com", "US", "en", 100)}
    theirs = {r.keyword for r in dry.ranked_keywords("rival.org", "US", "en", 100)}
    assert mine != theirs and theirs - mine


def _cfg(**overrides):
    base = dict(SERP_PROVIDER="", SERP_DRY_RUN=True, DATAFORSEO_LOGIN="", DATAFORSEO_PASSWORD="",
                DATAFORSEO_LABS_DAILY_CAP=20)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_registry_keyword_provider_is_dry_run_unless_fully_live():
    assert registry.get_keyword_provider(_cfg()).name == "dry_run"
    assert registry.get_keyword_provider(_cfg(SERP_PROVIDER="dataforseo", DATAFORSEO_LOGIN="l",
                                              DATAFORSEO_PASSWORD="p")).name == "dry_run"
    live = registry.get_keyword_provider(_cfg(SERP_PROVIDER="dataforseo", SERP_DRY_RUN=False,
                                              DATAFORSEO_LOGIN="l", DATAFORSEO_PASSWORD="p"))
    assert live.name == "dataforseo" and live.cap == 20
