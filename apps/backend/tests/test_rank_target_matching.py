from types import SimpleNamespace

from app.services import audit_service


def _target(url, keywords):
    return SimpleNamespace(url=url, keywords=keywords)


def test_matches_ignoring_scheme_www_and_trailing_slash():
    targets = [_target("example.com/services", ["cloud"])]
    assert audit_service._match_rank_target("https://www.example.com/services/", targets) == ["cloud"]


def test_matches_ignoring_query_string_and_fragment():
    targets = [_target("https://example.com/services", ["cloud"])]
    assert audit_service._match_rank_target("https://example.com/services?utm=1#top", targets) == ["cloud"]


def test_returns_none_for_unnominated_page():
    targets = [_target("https://example.com/services", ["cloud"])]
    assert audit_service._match_rank_target("https://example.com/about", targets) is None


def test_returns_none_when_no_targets_supplied():
    assert audit_service._match_rank_target("https://example.com/", None) is None
    assert audit_service._match_rank_target("https://example.com/", []) is None


def test_distinct_pages_get_their_own_keywords():
    targets = [
        _target("https://example.com/a", ["alpha"]),
        _target("https://example.com/b", ["beta", "gamma"]),
    ]
    assert audit_service._match_rank_target("https://example.com/a", targets) == ["alpha"]
    assert audit_service._match_rank_target("https://example.com/b", targets) == ["beta", "gamma"]
