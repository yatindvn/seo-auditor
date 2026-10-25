"""Which pages an audit measures, and measuring them a few at a time."""

import threading
from types import SimpleNamespace as Page

from app.vitals.model import VitalsResult
from app.vitals.runner import measure_pages, select_vitals_pages


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
    assert select_vitals_pages("https://a.com/", top, _results(), 3) == [
        "https://a.com/", "https://a.com/deep", "https://a.com/shop"]


def test_without_pagerank_the_shallowest_pages_fill_in():
    assert select_vitals_pages("https://a.com/", [], _results(), 10) == [
        "https://a.com/", "https://a.com/shop", "https://a.com/blog", "https://a.com/deep"]


def test_a_failed_start_url_is_skipped_and_limit_zero_measures_nothing():
    results = _results()
    results["https://a.com/"].status_code = 500
    assert select_vitals_pages("https://a.com/", [], results, 1) == ["https://a.com/shop"]
    assert select_vitals_pages("https://a.com/", [], _results(), 0) == []


class _Provider:
    name = "stub"

    def __init__(self):
        self.lock, self.active, self.peak = threading.Lock(), 0, 0

    def measure(self, url, strategy="mobile"):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if url.endswith("boom"):
                raise RuntimeError("boom")
            return VitalsResult(url=url, source="psi", data_kind="lab", lcp_ms=1000)
        finally:
            with self.lock:
                self.active -= 1


def test_measure_keeps_order_reports_progress_and_contains_errors():
    urls = [f"https://a.com/{i}" for i in range(5)] + ["https://a.com/boom"]
    seen = []
    provider = _Provider()
    results = measure_pages(provider, urls, on_progress=lambda d, t, u: seen.append((d, t)))
    assert [r.url for r in results] == urls
    assert results[-1].source == "not_measured" and results[-1].error == "unexpected error (RuntimeError)"
    assert sorted(seen) == [(i, 6) for i in range(1, 7)]
    assert provider.peak <= 3
