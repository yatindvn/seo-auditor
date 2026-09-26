"""Crawl and checks run concurrently, and a failure in either degrades rather
than destroys the audit.

The checks used to be a phase appended to the crawl: fetch everything, then
analyse everything. At 5000 pages that second phase is minutes of CPU on top of
the crawl, with every page's HTML retained until it ran.
"""

from concurrent.futures.process import BrokenProcessPool
from unittest.mock import patch

from app.crawler.crawler import Crawler, PageResult
from app.services import audit_service

HTML = (
    "<html><head><title>T</title></head><body><h1>H</h1>"
    "<p>words here plenty of them for the content checks to chew on</p></body></html>"
)


def _crawler(page_count=5, max_pages=None):
    home = "https://example.com/"
    children = [f"https://example.com/p{i}" for i in range(page_count - 1)]
    links = "".join(f"<a href='{c}'>x</a>" for c in children)
    pages = {home: f"<html><head><title>Home</title></head><body>{links}</body></html>"}
    pages.update({child: HTML for child in children})
    crawler = Crawler(home, max_pages=max_pages or page_count, max_depth=2,
                      respect_robots=False)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=pages.get(url, HTML), headers={},
    )
    return crawler


def _run(crawler, **kwargs):
    return audit_service._build_audit_result(
        "https://example.com/", crawler, progress_callback=None, event_callback=None,
        **kwargs,
    )


def test_every_crawled_page_is_analysed():
    result = _run(_crawler())

    assert len(result["pages"]) == 5
    assert all(row["title"] for row in result["pages"])


def test_html_is_released_once_a_page_is_analysed():
    """Retaining HTML for every page is ~500 MB at 5000 pages. This assertion
    is what keeps resident memory flat as the crawl grows."""
    crawler = _crawler()

    _run(crawler)

    assert all(not page.html for page in crawler.results.values()), (
        "PageResult.html must be cleared once its analysis has been submitted"
    )


def test_analysis_runs_in_a_process_pool_for_a_large_crawl():
    """Spawning processes for an eight-page audit is pure overhead, so the pool
    is used only where it pays. This pins that it *is* used above the
    threshold."""
    crawler = _crawler(page_count=3, max_pages=audit_service.POOL_MIN_PAGES + 1)

    with patch.object(audit_service, "_submit_analysis",
                      side_effect=audit_service._submit_analysis) as spy:
        _run(crawler)

    assert spy.called
    assert any(call.args[0] is not None for call in spy.call_args_list), (
        "a pool should have been created and passed"
    )


def test_small_crawls_skip_the_pool_entirely():
    crawler = _crawler(page_count=3, max_pages=4)

    with patch.object(audit_service, "_submit_analysis",
                      side_effect=audit_service._submit_analysis) as spy:
        result = _run(crawler)

    assert len(result["pages"]) == 3
    assert all(call.args[0] is None for call in spy.call_args_list), (
        "no pool for a crawl too small to pay for one"
    )


def test_a_dead_process_pool_falls_back_in_process_and_reports_degraded():
    """Slow beats failed: if the pool cannot run, the audit still completes."""
    crawler = _crawler(max_pages=audit_service.POOL_MIN_PAGES + 1)

    with patch.object(audit_service, "_submit_analysis",
                      side_effect=BrokenProcessPool("pool died")):
        result = _run(crawler)

    assert len(result["pages"]) == 5, "every page is still analysed"
    assert result["degraded"] is True


def test_one_pages_analysis_failing_does_not_destroy_the_audit():
    crawler = _crawler()
    real_analyze = audit_service.page_pipeline.analyze_page

    def fail_one(payload):
        if payload.url.endswith("/p1"):
            raise AttributeError("'NoneType' object has no attribute 'get_text'")
        return real_analyze(payload)

    with patch.object(audit_service.page_pipeline, "analyze_page", side_effect=fail_one):
        result = _run(crawler)

    assert len(result["pages"]) == 5
    broken = result["page_issues_detail"]["https://example.com/p1"]
    assert [i for i in broken if i["code"] == "AUDIT_ERROR"]


def test_stopping_mid_crawl_still_produces_a_summary_marked_partial():
    crawler = _crawler(page_count=50, max_pages=50)
    original_fetch = crawler._fetch

    def stop_after_three(url):
        if len(crawler.visited) >= 3:
            crawler.is_stopped = True
        return original_fetch(url)

    crawler._fetch = stop_after_three

    result = _run(crawler)

    assert result["partial"] is True
    assert result["executive_summary"], "a stopped crawl still renders a dashboard"


def test_a_completed_crawl_is_not_marked_partial():
    result = _run(_crawler())

    assert result["partial"] is False
    assert result["degraded"] is False
