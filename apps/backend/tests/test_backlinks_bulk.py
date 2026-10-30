"""Bulk backlink counts for many URLs: two DataForSEO requests, capped."""

from unittest.mock import MagicMock

import pytest

from app.backlinks.provider import DataForSeoBacklinks, DryRunBacklinks
from app.providers.serp import ProviderSkipped


def resp(body):
    r = MagicMock(status_code=200)
    r.json.return_value = body
    return r


def ok(items):
    return resp({"status_code": 20000, "tasks": [{"status_code": 20000, "result": [{"items": items}]}]})


def test_two_requests_cover_every_url_and_match_trailing_slashes():
    http = MagicMock()
    http.post.side_effect = [
        ok([{"target": "https://a.com/x", "backlinks": 120}, {"target": "https://b.com/", "backlinks": 7}]),
        ok([{"target": "https://a.com/x", "referring_domains": 30}, {"target": "https://b.com", "referring_domains": 2}]),
    ]
    p = DataForSeoBacklinks("l", "p", cap=10, http=http)
    out = p.bulk_metrics(["https://a.com/x", "https://b.com/", "https://c.com/"])
    assert out == {"https://a.com/x": (120, 30), "https://b.com/": (7, 2), "https://c.com/": (None, None)}
    paths = [call.args[0] for call in http.post.call_args_list]
    assert paths == ["https://api.dataforseo.com/v3/backlinks/bulk_backlinks/live",
                     "https://api.dataforseo.com/v3/backlinks/bulk_referring_domains/live"]
    assert http.post.call_args_list[0].kwargs["json"] == [{"targets": ["https://a.com/x", "https://b.com/", "https://c.com/"]}]


def test_no_urls_no_call_and_the_cap_stops_it():
    http = MagicMock()
    assert DataForSeoBacklinks("l", "p", cap=10, http=http).bulk_metrics([]) == {}
    with pytest.raises(ProviderSkipped):
        DataForSeoBacklinks("l", "p", cap=0, http=http).bulk_metrics(["https://a.com/"])
    http.post.assert_not_called()


def test_dry_run_is_stable():
    d = DryRunBacklinks()
    first = d.bulk_metrics(["https://a.com/x", "https://b.com/"])
    assert first == d.bulk_metrics(["https://a.com/x", "https://b.com/"])
    assert all(isinstance(b, int) and isinstance(r, int) and b >= r for b, r in first.values())
