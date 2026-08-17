from types import SimpleNamespace
from unittest.mock import patch

from app.services import audit_service
from test_audit_service_crawler_registry import FakeCrawler


def _target(url, keywords):
    return SimpleNamespace(url=url, keywords=keywords)


def test_unnominated_page_returns_none():
    # `_match_rank_target` never calls `check_rankings` itself — that
    # wiring lives at the `_build_audit_result` call site and is covered by
    # the integration tests below (patching `check_rankings` here and
    # asserting it was never called would be vacuous: this function simply
    # has no path that could call it). What this unit test actually proves
    # is `_match_rank_target`'s own contract: an unmatched URL returns None.
    targets = [SimpleNamespace(url="https://example.com/a", keywords=["alpha"])]

    keywords = audit_service._match_rank_target("https://example.com/zzz", targets)

    assert keywords is None


def test_nominated_page_returns_exactly_its_keywords():
    targets = [SimpleNamespace(url="https://example.com/a", keywords=["alpha", "beta"])]
    assert audit_service._match_rank_target("https://example.com/a", targets) == ["alpha", "beta"]


# The tests above exercise `_match_rank_target` in isolation — they never call
# through `_build_audit_result`, so they cannot prove the *gating conditional*
# in the rank-check call site (`if enable_rank_check and nominated_keywords`)
# actually wires the matcher's result into whether `check_rankings` fires. A
# regression there (e.g. `and` silently becoming `or`, or the truthiness check
# being dropped) would resurrect the unconditional-quota-burn bug this task
# exists to prevent, and none of the tests above would catch it. These
# integration-level tests close that gap by calling `_build_audit_result`
# directly and asserting on `rank_checker.check_rankings` itself, following
# the same pattern `test_audit_service_crawler_registry.py` uses to prove the
# analogous `enable_keyword_suggestions` gate end to end.

def test_build_audit_result_rank_targets_none_never_calls_check_rankings():
    crawler = FakeCrawler()

    with patch.object(audit_service.rank_checker, "check_rankings") as mock_check:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_rank_check=True, rank_targets=None,
        )

    mock_check.assert_not_called()


def test_build_audit_result_rank_targets_empty_never_calls_check_rankings():
    crawler = FakeCrawler()

    with patch.object(audit_service.rank_checker, "check_rankings") as mock_check:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_rank_check=True, rank_targets=[],
        )

    mock_check.assert_not_called()


def test_build_audit_result_matching_target_calls_check_rankings_with_its_keywords():
    crawler = FakeCrawler()
    targets = [_target("https://example.com/", ["espresso machine", "espresso reviews"])]
    fake_rank_data = [{
        "keyword": "espresso machine", "position": 1, "status": "ranked",
        "note": None, "checked_at": "", "top_urls": [],
    }]

    with patch.object(audit_service.rank_checker, "check_rankings", return_value=fake_rank_data) as mock_check:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_rank_check=True, rank_targets=targets,
        )

    mock_check.assert_called_once_with(
        "https://example.com/",
        ["espresso machine", "espresso reviews"],
        audit_service.config,
        max_keywords=2,
    )


def test_build_audit_result_unmatched_target_never_calls_check_rankings():
    crawler = FakeCrawler()
    targets = [_target("https://example.com/some-other-page", ["alpha"])]

    with patch.object(audit_service.rank_checker, "check_rankings") as mock_check:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_rank_check=True, rank_targets=targets,
        )

    mock_check.assert_not_called()


def test_build_audit_result_enable_rank_check_false_never_calls_check_rankings():
    """enable_rank_check is still the master switch: a matching nomination
    alone must not be enough to spend a query."""
    crawler = FakeCrawler()
    targets = [_target("https://example.com/", ["alpha"])]

    with patch.object(audit_service.rank_checker, "check_rankings") as mock_check:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_rank_check=False, rank_targets=targets,
        )

    mock_check.assert_not_called()
