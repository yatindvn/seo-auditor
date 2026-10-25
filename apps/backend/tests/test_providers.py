"""SERP providers: DataForSEO parsing, dry run, the spend guard, the registry."""

import json
import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.providers import registry, spend
from app.providers.dataforseo import DataForSeoProvider
from app.providers.dry_run import DryRunProvider
from app.providers.serp import ProviderError, ProviderSkipped, SerpItem, SerpQuery

FIXTURE = Path(__file__).parent / "fixtures" / "dataforseo_live_advanced.json"


def _http(payload):
    http = MagicMock()
    http.post.return_value.json.return_value = payload
    http.post.return_value.status_code = 200
    return http


def test_dataforseo_request_follows_the_documented_shape():
    http = _http(json.loads(FIXTURE.read_text()))
    DataForSeoProvider("login", "pw", http=http).search(
        SerpQuery("espresso machine", country="GB", language="en", device="mobile", depth=500)
    )
    url = http.post.call_args.args[0]
    kwargs = http.post.call_args.kwargs
    assert url == "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
    assert kwargs["auth"] == ("login", "pw")
    assert kwargs["json"] == [{"keyword": "espresso machine", "location_name": "United Kingdom",
                               "language_code": "en", "device": "mobile", "depth": 200}]


def test_dataforseo_parses_organic_items_only():
    http = _http(json.loads(FIXTURE.read_text()))
    result = DataForSeoProvider("l", "p", http=http).search(SerpQuery("espresso machine"))
    assert [(i.position, i.domain) for i in result.items] == [
        (1, "coffee.com"), (2, "shop.example.com"), (3, "rival.org"),
    ]
    assert result.provider == "dataforseo"


@pytest.mark.parametrize("payload", [
    {"status_code": 40100, "status_message": "You are not authorized to access this resource.", "tasks": []},
    {"status_code": 20000, "status_message": "Ok.",
     "tasks": [{"status_code": 40501, "status_message": "Invalid Field.", "result": None}]},
])
def test_dataforseo_errors_raise_provider_error(payload):
    with pytest.raises(ProviderError, match="40"):
        DataForSeoProvider("l", "p", http=_http(payload)).search(SerpQuery("x"))


def test_dataforseo_rejects_an_unknown_country():
    with pytest.raises(ValueError):
        DataForSeoProvider("l", "p", http=MagicMock()).search(SerpQuery("x", country="ZZ"))


def test_dry_run_is_deterministic_and_offline(monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: pytest.fail("network"))
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("network"))
    first = DryRunProvider().search(SerpQuery("espresso"))
    assert first.items == DryRunProvider().search(SerpQuery("espresso")).items
    assert first.note == "dry run" and len(first.items) == 10


def test_dry_run_returns_injected_items():
    items = [SerpItem(position=1, url="https://a.com/", domain="a.com")]
    assert DryRunProvider(items=items).search(SerpQuery("x")).items == items


def test_spend_guard_allows_exactly_the_cap_per_day():
    for _ in range(3):
        spend.reserve("dataforseo", cap=3, today=date(2026, 10, 25))
    with pytest.raises(ProviderSkipped, match="cap of 3"):
        spend.reserve("dataforseo", cap=3, today=date(2026, 10, 25))
    spend.reserve("dataforseo", cap=3, today=date(2026, 10, 26))      # a new day
    spend.reserve("google_cse", cap=3, today=date(2026, 10, 25))      # separate budget


def test_spend_guard_holds_under_concurrency():
    allowed = []

    def worker():
        try:
            spend.reserve("dataforseo", cap=5, today=date(2026, 10, 25))
            allowed.append(1)
        except ProviderSkipped:
            pass

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(allowed) == 5


def test_spend_guard_wraps_a_provider():
    inner = DryRunProvider()
    guarded = spend.SpendGuard(inner, cap=1)
    assert guarded.name == "dry_run"
    guarded.search(SerpQuery("a"))
    with pytest.raises(ProviderSkipped):
        guarded.search(SerpQuery("b"))


def _cfg(**overrides):
    base = dict(SERP_PROVIDER="", SERP_DRY_RUN=True, SERP_DAILY_CAP=50,
                DATAFORSEO_LOGIN="", DATAFORSEO_PASSWORD="",
                GOOGLE_CSE_API_KEY="", GOOGLE_CSE_CX="", GOOGLE_CSE_DAILY_QUOTA=100)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_registry_keeps_dataforseo_in_dry_run_until_told_otherwise():
    provider = registry.get_serp_provider(_cfg(SERP_PROVIDER="dataforseo",
                                               DATAFORSEO_LOGIN="l", DATAFORSEO_PASSWORD="p"))
    assert provider.name == "dry_run" and not registry.is_live(provider)


def test_registry_goes_live_only_with_dry_run_off_and_credentials():
    live = registry.get_serp_provider(_cfg(SERP_PROVIDER="dataforseo", SERP_DRY_RUN=False,
                                           DATAFORSEO_LOGIN="l", DATAFORSEO_PASSWORD="p"))
    assert live.name == "dataforseo" and isinstance(live, spend.SpendGuard)
    with pytest.raises(ProviderSkipped, match="not configured"):
        registry.get_serp_provider(_cfg(SERP_PROVIDER="dataforseo", SERP_DRY_RUN=False))


def test_registry_defaults_to_dry_run_without_any_provider():
    assert registry.get_serp_provider(_cfg()).name == "dry_run"
