"""Backlinks provider: DataForSEO request bodies and parsing, the cap, dry run."""

from datetime import date
from unittest.mock import MagicMock

import pytest

from app.backlinks import provider as bp
from app.backlinks.provider import DataForSeoBacklinks, DryRunBacklinks, get_backlink_provider, months_back
from app.config import config
from app.providers.serp import ProviderError, ProviderSkipped


def ok(result):
    resp = MagicMock(status_code=200)
    resp.json.return_value = {"status_code": 20000, "tasks": [{"status_code": 20000, "result": result}]}
    return resp


class Http:
    def __init__(self, *responses):
        self.calls, self.responses = [], list(responses)

    def post(self, url, json=None, auth=None, timeout=None):
        self.calls.append((url.split("/v3/")[1], json[0]))
        return self.responses.pop(0)


def test_summary():
    http = Http(ok([{"rank": 412, "backlinks": 18230, "referring_domains": 640, "broken_backlinks": 37}]))
    s = DataForSeoBacklinks("l", "p", cap=5, http=http).summary("shop.com")
    assert http.calls == [("backlinks/summary/live", {"target": "shop.com", "include_subdomains": True})]
    assert (s.authority, s.backlinks, s.referring_domains, s.broken_backlinks) == (412, 18230, 640, 37)


def test_referring_domains():
    http = Http(ok([{"items": [{"domain": "news.com", "rank": 700, "backlinks": 12, "first_seen": "2025-01-02 10:00:00 +00:00"}]}]))
    rows = DataForSeoBacklinks("l", "p", cap=5, http=http).referring_domains("shop.com", 100)
    assert http.calls[0] == ("backlinks/referring_domains/live", {"target": "shop.com", "limit": 100, "order_by": ["rank,desc"]})
    assert rows[0].domain == "news.com" and rows[0].rank == 700 and rows[0].backlinks == 12


@pytest.mark.parametrize("kind, filters", [
    ("new", ["first_seen", ">=", "2026-09-30"]),
    ("lost", [["is_lost", "=", True], "and", ["last_seen", ">=", "2026-09-30"]]),
    ("broken", ["is_broken", "=", True]),
])
def test_backlink_filters(kind, filters):
    item = {"url_from": "https://news.com/a", "url_to": "https://shop.com/x", "anchor": "great shop",
            "domain_from_rank": 650, "dofollow": True, "first_seen": "2026-10-01 00:00:00 +00:00",
            "last_seen": "2026-10-20 00:00:00 +00:00", "url_to_status_code": 404}
    http = Http(ok([{"items": [item]}]))
    links = DataForSeoBacklinks("l", "p", cap=5, http=http).backlinks("shop.com", kind, date(2026, 9, 30), 100)
    path, task = http.calls[0]
    assert path == "backlinks/backlinks/live"
    assert task == {"target": "shop.com", "mode": "as_is", "limit": 100, "order_by": ["domain_from_rank,desc"], "filters": filters}
    assert (links[0].url_to, links[0].anchor, links[0].domain_from_rank, links[0].dofollow, links[0].target_status) == (
        "https://shop.com/x", "great shop", 650, True, 404)


def test_history_months():
    http = Http(ok([{"items": [{"date": "2026-08-01 00:00:00 +00:00", "rank": 400, "backlinks": 17000, "referring_domains": 600},
                               {"date": "bad"}]}]))
    pts = DataForSeoBacklinks("l", "p", cap=5, http=http).history("shop.com", 12, today=date(2026, 10, 30))
    assert http.calls[0] == ("backlinks/history/live", {"target": "shop.com", "date_from": "2025-10-01", "date_to": "2026-10-30"})
    assert [(p.month, p.authority, p.referring_domains) for p in pts] == [(date(2026, 8, 1), 400, 600)]
    assert months_back(date(2026, 1, 15), 3) == date(2025, 10, 1)


def test_intersection():
    item = {"domain_intersection": {"1": {"domain": "blog.io", "rank": 500, "backlinks": 3},
                                    "2": {"domain": "blog.io", "rank": 500, "backlinks": 1}}}
    only_one = {"domain_intersection": {"1": {"domain": "news.com", "rank": 600, "backlinks": 2}}}
    http = Http(ok([{"items": [item, only_one]}]))
    rows = DataForSeoBacklinks("l", "p", cap=5, http=http).intersection(["rival.com", "other.com"], "shop.com", 100)
    assert http.calls[0] == ("backlinks/domain_intersection/live", {
        "targets": {"1": "rival.com", "2": "other.com"}, "exclude_targets": ["shop.com"], "limit": 100,
        "order_by": ["1.rank,desc"]})
    assert [(r.domain, r.rank, r.linked_competitors) for r in rows] == [
        ("blog.io", 500, {"rival.com": 3, "other.com": 1}), ("news.com", 600, {"rival.com": 2})]


def test_errors_and_cap(monkeypatch):
    bad = MagicMock(status_code=200)
    bad.json.return_value = {"status_code": 40104, "status_message": "Please visit https://app.dataforseo.com/backlinks-subscription"}
    with pytest.raises(ProviderError) as err:
        DataForSeoBacklinks("l", "p", cap=5, http=Http(bad)).summary("shop.com")
    assert "40104" in str(err.value)
    http = Http()
    with pytest.raises(ProviderSkipped):
        DataForSeoBacklinks("l", "p", cap=0, http=http).summary("shop.com")
    assert http.calls == []


def test_dry_run_is_deterministic_and_complete():
    a, b = DryRunBacklinks(), DryRunBacklinks()
    assert a.summary("shop.com") == b.summary("shop.com") and a.dry_run is True
    assert len(a.referring_domains("shop.com", 100)) >= 10
    broken = a.backlinks("shop.com", "broken", date(2026, 9, 30), 100)
    assert broken and all(l.url_to.startswith("https://shop.com/") and l.target_status == 404 for l in broken)
    assert len(a.history("shop.com", 12, today=date(2026, 10, 30))) == 12
    gap = a.intersection(["rival.com", "other.com"], "shop.com", 100)
    assert gap and max(len(g.linked_competitors) for g in gap) == 2


def test_factory(monkeypatch):
    assert isinstance(get_backlink_provider(), DryRunBacklinks)
    monkeypatch.setattr(config, "SERP_PROVIDER", "dataforseo")
    monkeypatch.setattr(config, "SERP_DRY_RUN", False)
    monkeypatch.setattr(config, "DATAFORSEO_LOGIN", "l")
    monkeypatch.setattr(config, "DATAFORSEO_PASSWORD", "p")
    assert isinstance(get_backlink_provider(), DataForSeoBacklinks)
    monkeypatch.setattr(config, "SERP_DRY_RUN", True)
    assert isinstance(get_backlink_provider(), DryRunBacklinks)
