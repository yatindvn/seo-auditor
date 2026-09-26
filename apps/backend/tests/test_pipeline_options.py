"""Options the CLI needs from the shared audit pipeline.

The CLI used to own a second copy of the pipeline, so its flags could reach
settings `_build_audit_result` hardcodes: how many external links to status-check,
and whether to call the PageSpeed Insights API. Deleting that copy means the
shared function has to expose them, or the flags silently stop working.

Every option defaults to today's behaviour, so the API is unaffected.
"""

from unittest.mock import patch

from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler


class SpyCrawler(FakeCrawler):
    """FakeCrawler that records how it was asked to check external links."""

    def __init__(self):
        super().__init__()
        self.external_checks = []

    def check_external_links(self, max_check=25):
        self.external_checks.append(max_check)


def _run(crawler, **kwargs):
    return audit_service._build_audit_result(
        "https://example.com/", crawler, progress_callback=None, event_callback=None, **kwargs,
    )


def test_external_link_check_defaults_to_twenty_five():
    """The API's current behaviour, pinned so the new parameter cannot change it."""
    crawler = SpyCrawler()

    _run(crawler)

    assert crawler.external_checks == [25]


def test_external_link_check_limit_is_forwarded():
    crawler = SpyCrawler()

    _run(crawler, external_link_check_limit=100)

    assert crawler.external_checks == [100]


def test_external_link_check_limit_of_zero_skips_the_check_entirely():
    """--skip-external-links. Zero means "do not make these requests", not
    "make zero-length requests"."""
    crawler = SpyCrawler()

    _run(crawler, external_link_check_limit=0)

    assert crawler.external_checks == []


def test_psi_is_never_called_without_a_key():
    """PageSpeed Insights is a quota'd Google API. With no key configured it
    must not be reached at all -- the same discipline the CSE rank checker has."""
    crawler = SpyCrawler()

    with patch.object(audit_service.performance, "fetch_psi_metrics") as mock_psi:
        result = _run(crawler)

    mock_psi.assert_not_called()
    assert result["psi_metrics"] == {}


def test_psi_runs_for_successful_pages_when_a_key_is_given():
    crawler = SpyCrawler()

    with patch.object(
        audit_service.performance, "fetch_psi_metrics", return_value={"lcp": 1.2}
    ) as mock_psi:
        result = _run(crawler, psi_key="test-key", psi_strategy="desktop")

    mock_psi.assert_called_once_with(
        "https://example.com/", "test-key", strategy="desktop",
    )
    assert result["psi_metrics"]["https://example.com/"] == {"lcp": 1.2}


# --- Duplicate-detection mode ----------------------------------------------


def test_result_reports_which_duplicate_path_ran():
    """The two paths do not produce identical similarity numbers, so the client
    is told which one produced these."""
    result = _run(SpyCrawler())

    assert result["near_duplicate_mode"] == "exact"


def test_signatures_are_not_computed_for_a_small_crawl():
    """Signing costs real CPU per page. A crawl that will use the exact path
    must not pay for signatures it will never read."""
    crawler = SpyCrawler()
    crawler.max_pages = 100
    captured = []

    real_analyze = audit_service.page_pipeline.analyze_page
    with patch.object(audit_service.page_pipeline, "analyze_page",
                      side_effect=lambda payload: captured.append(payload) or real_analyze(payload)):
        _run(crawler)

    assert captured, "analyze_page should have been called"
    assert all(p.compute_signature is False for p in captured)


def test_signatures_are_computed_when_the_cap_exceeds_the_exact_path():
    """The decision has to be made per page during the crawl, before the final
    page count is known, so it keys off the cap rather than the realised count."""
    crawler = SpyCrawler()
    crawler.max_pages = 5000
    captured = []

    real_analyze = audit_service.page_pipeline.analyze_page
    with patch.object(audit_service.page_pipeline, "analyze_page",
                      side_effect=lambda payload: captured.append(payload) or real_analyze(payload)):
        _run(crawler)

    assert captured
    assert all(p.compute_signature is True for p in captured)
