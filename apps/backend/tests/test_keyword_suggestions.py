from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.seo import keyword_suggestions, rank_checker

FAKE_CONFIG = SimpleNamespace(
    GOOGLE_CSE_API_KEY="test-key",
    GOOGLE_CSE_CX="test-cx",
    GOOGLE_CSE_DAILY_QUOTA=100,
    GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
    GOOGLE_CSE_CACHE_TTL_HOURS=24,
)


@pytest.fixture(autouse=True)
def _reset_state():
    rank_checker._state.reset()
    yield
    rank_checker._state.reset()


def _autocomplete_response(seed, suggestions):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = [seed, suggestions]
    return resp


def test_suggest_keywords_uses_autocomplete_related_searches():
    seed_keywords = [{"phrase": "espresso machine", "score": 5.0, "found_in": ["title"]}]

    with patch(
        "app.seo.keyword_suggestions.requests.get",
        return_value=_autocomplete_response(
            "espresso machine", ["espresso machine reviews", "espresso machine budget"]
        ),
    ):
        result = keyword_suggestions.suggest_keywords(
            seed_keywords, [], FAKE_CONFIG,
            fetch_page=lambda u: None, page_url="https://example.com/page",
        )

    phrases = {r["phrase"] for r in result}
    assert "espresso machine reviews" in phrases
    assert "espresso machine budget" in phrases
    assert all(r["reason"] == "related search" for r in result)


def test_suggest_keywords_autocomplete_failure_returns_empty_list():
    seed_keywords = [{"phrase": "espresso machine", "score": 5.0, "found_in": ["title"]}]

    with patch("app.seo.keyword_suggestions.requests.get", side_effect=TimeoutError("boom")):
        result = keyword_suggestions.suggest_keywords(
            seed_keywords, [], FAKE_CONFIG,
            fetch_page=lambda u: None, page_url="https://example.com/page",
        )

    assert result == []


def test_suggest_keywords_competitor_gap_finds_phrases_missing_on_current_page():
    seed_keywords = [{"phrase": "espresso machine", "score": 5.0, "found_in": ["title"]}]
    rank_results = [
        {
            "keyword": "espresso machine",
            "position": 4,
            "note": None,
            "checked_at": "2026-01-01T00:00:00+00:00",
            "top_urls": ["https://competitor-a.com/", "https://competitor-b.com/"],
        }
    ]

    def fake_fetch(url):
        return SimpleNamespace(html="<html><head><title>Pour Over Guide</title></head><body></body></html>")

    with patch("app.seo.keyword_suggestions.requests.get", side_effect=TimeoutError("autocomplete down")):
        result = keyword_suggestions.suggest_keywords(
            seed_keywords, rank_results, FAKE_CONFIG,
            fetch_page=fake_fetch, page_url="https://example.com/page",
            enable_competitor_gap=True,
        )

    gap = next(r for r in result if r["phrase"] == "pour over")
    assert gap["reason"] == "used by top-ranking competitors but missing on this page"
    assert set(gap["competitor_examples"]) == {"https://competitor-a.com/", "https://competitor-b.com/"}


def test_suggest_keywords_dedup_against_current_phrases_is_case_insensitive():
    # Two seed keywords. Autocomplete for the first seed returns a suggestion
    # that matches the *second* seed's phrase but in different case
    # ("milk frother" vs. "Milk Frother"). This specifically exercises the
    # `current_phrases` lookup — a suggestion equal to its own seed is
    # already filtered out by `_autocomplete_suggestions` itself, so that
    # alone wouldn't catch a non-lowercased `current_phrases` set.
    seed_keywords = [
        {"phrase": "espresso machine", "score": 5.0, "found_in": ["title"]},
        {"phrase": "Milk Frother", "score": 4.0, "found_in": ["h1"]},
    ]

    with patch(
        "app.seo.keyword_suggestions.requests.get",
        return_value=_autocomplete_response(
            "espresso machine", ["milk frother", "single origin"]
        ),
    ):
        result = keyword_suggestions.suggest_keywords(
            seed_keywords, [], FAKE_CONFIG,
            fetch_page=lambda u: None, page_url="https://example.com/page",
        )

    phrases = {r["phrase"] for r in result}
    assert "milk frother" not in phrases
    assert "single origin" in phrases


from unittest.mock import patch

from app.seo import keyword_suggestions


FAKE_CONFIG_S = SimpleNamespace(
    GOOGLE_CSE_API_KEY="k", GOOGLE_CSE_CX="cx",
    GOOGLE_CSE_DAILY_QUOTA=100, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
    GOOGLE_CSE_CACHE_TTL_HOURS=24,
)


def _rank(keyword, status, position=None):
    return {"keyword": keyword, "position": position, "status": status,
            "note": None, "checked_at": "", "top_urls": []}


def test_suggestions_seed_from_not_ranked_keyword():
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]
    ranks = [_rank("espresso machine", "not_ranked")]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["espresso machine reviews"]):
        out = keyword_suggestions.suggest_keywords(
            seeds, ranks, FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert [s["phrase"] for s in out] == ["espresso machine reviews"]
    assert out[0]["replaces"] == "espresso machine"


def test_skipped_status_produces_no_suggestions():
    """Not configured / quota reached / request error mean nothing was measured."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]
    ranks = [_rank("espresso machine", "skipped")]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["anything"]) as mock_ac:
        out = keyword_suggestions.suggest_keywords(
            seeds, ranks, FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert out == []
    mock_ac.assert_not_called()


def test_ranked_keyword_produces_no_suggestions():
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]
    ranks = [_rank("espresso machine", "ranked", position=3)]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["anything"]):
        out = keyword_suggestions.suggest_keywords(
            seeds, ranks, FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert out == []


def test_no_rank_data_falls_back_to_seed_keywords():
    """Backward compatibility: suggestions still work with rank checking off."""
    seeds = [{"phrase": "espresso machine", "score": None, "found_in": []}]

    with patch.object(keyword_suggestions, "_autocomplete_suggestions", return_value=["espresso grinder"]):
        out = keyword_suggestions.suggest_keywords(
            seeds, [], FAKE_CONFIG_S, fetch_page=lambda u: None, page_url="https://example.com/"
        )

    assert [s["phrase"] for s in out] == ["espresso grinder"]
    assert out[0]["replaces"] is None
