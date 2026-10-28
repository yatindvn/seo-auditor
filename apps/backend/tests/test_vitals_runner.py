"""Measuring Core Web Vitals a few pages at a time."""

import threading

from app.vitals.model import VitalsResult
from app.vitals.runner import measure_pages


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
