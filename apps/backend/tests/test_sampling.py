"""Choosing which crawled pages get expensive treatment (Core Web Vitals,
JavaScript rendering)."""

from types import SimpleNamespace as Page

from app.analysis.sampling import select_pages


def _results():
    return {
        "https://a.com/": Page(status_code=200, depth=0, content_type="text/html"),
        "https://a.com/shop": Page(status_code=200, depth=1, content_type="text/html; charset=utf-8"),
        "https://a.com/blog": Page(status_code=200, depth=1, content_type=""),
        "https://a.com/gone": Page(status_code=404, depth=1, content_type="text/html"),
        "https://a.com/file.pdf": Page(status_code=200, depth=1, content_type="application/pdf"),
        "https://a.com/deep": Page(status_code=200, depth=3, content_type="text/html"),
    }


def test_start_url_first_then_pagerank_order():
    top = [{"url": "https://a.com/deep", "score": 0.3}, {"url": "https://a.com/", "score": 0.2},
           {"url": "https://a.com/gone", "score": 0.1}, {"url": "https://a.com/shop", "score": 0.05}]
    assert select_pages("https://a.com/", top, _results(), 3) == [
        "https://a.com/", "https://a.com/deep", "https://a.com/shop"]


def test_priority_pages_come_right_after_the_start_url():
    top = [{"url": "https://a.com/shop", "score": 0.3}]
    assert select_pages("https://a.com/", top, _results(), 3, priority=["https://a.com/deep", "https://a.com/gone"]) == [
        "https://a.com/", "https://a.com/deep", "https://a.com/shop"]


def test_without_pagerank_the_shallowest_pages_fill_in():
    assert select_pages("https://a.com/", [], _results(), 10) == [
        "https://a.com/", "https://a.com/shop", "https://a.com/blog", "https://a.com/deep"]


def test_a_failed_start_url_is_skipped_and_limit_zero_selects_nothing():
    results = _results()
    results["https://a.com/"].status_code = 500
    assert select_pages("https://a.com/", [], results, 1) == ["https://a.com/shop"]
    assert select_pages("https://a.com/", [], _results(), 0) == []
