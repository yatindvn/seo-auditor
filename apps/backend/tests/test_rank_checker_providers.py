"""Audits share the provider layer's budget -- and never use dry-run data."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.providers import spend
from app.providers.google_cse import GoogleCseProvider
from app.providers.serp import SerpItem, SerpQuery, SerpResult
from app.seo import rank_checker

CSE = SimpleNamespace(GOOGLE_CSE_API_KEY="k", GOOGLE_CSE_CX="c", GOOGLE_CSE_DAILY_QUOTA=2,
                      GOOGLE_CSE_MAX_KEYWORDS_PER_PAGE=3, GOOGLE_CSE_CACHE_TTL_HOURS=24)


def _resp(links):
    r = MagicMock()
    r.json.return_value = {"items": [{"link": u} for u in links]}
    return r


def setup_function():
    rank_checker._state.reset()


def test_the_cse_quota_survives_a_restart():
    """Counted in the DB now: clearing the in-process state (a restart) no
    longer resets today's spend."""
    with patch("app.seo.rank_checker.requests.get", return_value=_resp(["https://a.com/"])) as get:
        rank_checker.check_rankings("https://example.com/", ["one", "two"], CSE)
        rank_checker._state.reset()
        result = rank_checker.check_rankings("https://example.com/", ["three"], CSE)
    assert get.call_count == 2
    assert result[0]["status"] == "skipped"


def test_google_cse_provider_uses_the_same_request():
    with patch("app.seo.rank_checker.requests.get",
               return_value=_resp(["https://www.a.com/x", "https://b.org/"])) as get:
        result = GoogleCseProvider(CSE).search(SerpQuery("espresso", country="GB", device="mobile", depth=100))
    assert get.call_args.kwargs["params"]["gl"] == "gb"
    assert get.call_args.kwargs["params"]["num"] == 10
    assert [(i.position, i.domain) for i in result.items] == [(1, "a.com"), (2, "b.org")]
    assert "device" in result.note and "10" in result.note


def test_audits_use_a_live_dataforseo_provider():
    cfg = SimpleNamespace(**{**CSE.__dict__, "SERP_PROVIDER": "dataforseo"})
    live = MagicMock(name="live")
    live.name = "dataforseo"
    live.search.return_value = SerpResult(items=[
        SerpItem(position=1, url="https://rival.com/", domain="rival.com"),
        SerpItem(position=2, url="https://example.com/page", domain="example.com"),
    ], provider="dataforseo")
    with patch("app.seo.rank_checker.registry.get_serp_provider", return_value=live):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], cfg)
    assert result[0]["position"] == 2
    assert live.search.call_args.args[0].depth == 10


def test_registry_picks_google_cse_when_its_key_is_set():
    from app.providers import registry
    cfg = SimpleNamespace(**{**CSE.__dict__, "SERP_PROVIDER": "", "SERP_DRY_RUN": True,
                             "SERP_DAILY_CAP": 50, "DATAFORSEO_LOGIN": "", "DATAFORSEO_PASSWORD": ""})
    assert registry.get_serp_provider(cfg).name == "google_cse"


def test_audits_never_use_dry_run_positions():
    cfg = SimpleNamespace(**{**CSE.__dict__, "SERP_PROVIDER": "dataforseo"})
    from app.providers.dry_run import DryRunProvider
    with patch("app.seo.rank_checker.registry.get_serp_provider", return_value=DryRunProvider()):
        result = rank_checker.check_rankings("https://example.com/page", ["espresso"], cfg)
    assert result[0]["status"] == "skipped" and result[0]["position"] is None
