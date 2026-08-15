from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.seo import rank_checker

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


def _canned_response(items):
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"items": items}
    return resp


def test_check_rankings_parses_position_from_cse_response():
    items = [{"link": f"https://competitor{i}.com/"} for i in range(4)]
    items.insert(2, {"link": "https://www.example.com/page/?utm=1"})

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings("https://example.com/page", ["espresso machine"], FAKE_CONFIG)

    assert result[0]["keyword"] == "espresso machine"
    assert result[0]["position"] == 3
    mock_get.assert_called_once()


def test_check_rankings_not_found_in_top_10():
    items = [{"link": f"https://competitor{i}.com/"} for i in range(10)]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso machine"], FAKE_CONFIG)

    assert result[0]["position"] is None
    assert result[0]["note"] == "not found in top 10"


def test_check_rankings_cache_hit_avoids_second_request():
    items = [{"link": "https://example.com/page"}]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        rank_checker.check_rankings("https://example.com/page", ["espresso machine"], FAKE_CONFIG)
        rank_checker.check_rankings("https://example.com/page", ["espresso machine"], FAKE_CONFIG)

    assert mock_get.call_count == 1


def test_check_rankings_quota_exhaustion_produces_skipped_note():
    quota_config = SimpleNamespace(**{**FAKE_CONFIG.__dict__, "GOOGLE_CSE_DAILY_QUOTA": 1})
    items = [{"link": "https://competitor.com/"}]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings(
            "https://example.com/page", ["espresso machine", "pour over"], quota_config
        )

    assert mock_get.call_count == 1
    assert result[1]["note"] == "ranking check skipped — daily Google CSE quota reached"
    assert result[1]["position"] is None


def test_check_rankings_deep_rank_check_flag_is_accepted_as_a_noop():
    items = [{"link": f"https://competitor{i}.com/"} for i in range(10)]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings(
            "https://example.com/page", ["espresso machine"], FAKE_CONFIG, deep_rank_check=True
        )

    # Pagination isn't implemented yet — passing the flag must not change
    # behavior or issue a second (page-2) request.
    assert mock_get.call_count == 1
    assert result[0]["position"] is None
    assert result[0]["note"] == "not found in top 10"


def test_check_rankings_without_credentials_skips_cleanly():
    unconfigured = SimpleNamespace(
        GOOGLE_CSE_API_KEY="",
        GOOGLE_CSE_CX="",
        GOOGLE_CSE_DAILY_QUOTA=100,
        GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
        GOOGLE_CSE_CACHE_TTL_HOURS=24,
    )

    with patch("app.seo.rank_checker.requests.get") as mock_get:
        result = rank_checker.check_rankings("https://example.com/page", ["espresso machine"], unconfigured)

    mock_get.assert_not_called()
    assert result[0]["position"] is None
    assert result[0]["note"] == "ranking check unavailable — Google CSE not configured"


def test_status_is_ranked_when_position_found():
    items = [{"link": "https://example.com/page"}]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert result[0]["status"] == "ranked"
    assert result[0]["position"] == 1


def test_status_is_not_ranked_when_absent_from_top_10():
    items = [{"link": f"https://competitor{i}.com/"} for i in range(10)]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert result[0]["status"] == "not_ranked"
    assert result[0]["position"] is None


def test_status_is_skipped_when_not_configured():
    unconfigured = SimpleNamespace(
        GOOGLE_CSE_API_KEY="", GOOGLE_CSE_CX="",
        GOOGLE_CSE_DAILY_QUOTA=100, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
        GOOGLE_CSE_CACHE_TTL_HOURS=24,
    )
    result = rank_checker.check_rankings("https://example.com/page", ["espresso"], unconfigured)

    assert result[0]["status"] == "skipped"
    assert result[0]["position"] is None


def test_status_is_skipped_when_quota_reached():
    exhausted = SimpleNamespace(
        GOOGLE_CSE_API_KEY="k", GOOGLE_CSE_CX="cx",
        GOOGLE_CSE_DAILY_QUOTA=0, GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3,
        GOOGLE_CSE_CACHE_TTL_HOURS=24,
    )
    result = rank_checker.check_rankings("https://example.com/page", ["espresso"], exhausted)

    assert result[0]["status"] == "skipped"


def test_status_is_skipped_on_request_error():
    with patch("app.seo.rank_checker.requests.get", side_effect=RuntimeError("boom")):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], FAKE_CONFIG)

    assert result[0]["status"] == "skipped"
    assert result[0]["note"] == "ranking check failed — Google CSE request error"


def test_config_cap_applies_when_max_keywords_not_given():
    items = [{"link": "https://other.com/"}]
    keywords = ["one", "two", "three", "four", "five"]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings("https://example.com/page", keywords, FAKE_CONFIG)

    assert len(result) == 3
    assert mock_get.call_count == 3


def test_max_keywords_overrides_config_cap():
    items = [{"link": "https://other.com/"}]
    keywords = ["one", "two", "three", "four", "five"]

    with patch("app.seo.rank_checker.requests.get", return_value=_canned_response(items)) as mock_get:
        result = rank_checker.check_rankings(
            "https://example.com/page", keywords, FAKE_CONFIG, max_keywords=5
        )

    assert len(result) == 5
    assert mock_get.call_count == 5
