"""A cached provider response is returned without calling (or paying) again."""

from datetime import timedelta

from app.db.models import utcnow
from app.providers import cache


def _counting(value):
    calls = []

    def fetch():
        calls.append(1)
        return value
    return fetch, calls


def test_a_fresh_entry_is_served_without_fetching():
    fetch, calls = _counting([{"keyword": "a", "search_volume": 10}])
    first = cache.cached_call("p", "/vol", {"k": ["a"]}, timedelta(days=30), fetch)
    second = cache.cached_call("p", "/vol", {"k": ["a"]}, timedelta(days=30), fetch)
    assert first == second == [{"keyword": "a", "search_volume": 10}]
    assert len(calls) == 1


def test_key_order_does_not_matter():
    assert cache.request_hash({"a": 1, "b": [1, 2]}) == cache.request_hash({"b": [1, 2], "a": 1})
    assert cache.request_hash({"a": 1}) != cache.request_hash({"a": 2})


def test_an_expired_entry_is_fetched_again_and_replaced():
    fetch_old, _ = _counting("old")
    cache.cached_call("p", "/r", {"t": "x"}, timedelta(days=7), fetch_old, now=utcnow() - timedelta(days=8))
    fetch_new, calls = _counting("new")
    assert cache.cached_call("p", "/r", {"t": "x"}, timedelta(days=7), fetch_new) == "new"
    assert len(calls) == 1
    assert cache.cached_call("p", "/r", {"t": "x"}, timedelta(days=7), fetch_new) == "new"
    assert len(calls) == 1


def test_a_failed_fetch_stores_nothing():
    def boom():
        raise RuntimeError("provider down")

    try:
        cache.cached_call("p", "/x", {"q": 1}, timedelta(days=1), boom)
    except RuntimeError:
        pass
    fetch, calls = _counting("ok")
    assert cache.cached_call("p", "/x", {"q": 1}, timedelta(days=1), fetch) == "ok"
    assert len(calls) == 1
