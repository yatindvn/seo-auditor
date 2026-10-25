"""The crawl loop admits no more fetches than the adaptive limit allows."""

import threading
import time

from requests.structures import CaseInsensitiveDict

from app.crawler.crawler import Crawler, PageResult
from tests.fake_http import FakeResponse

HOME = "https://example.com/"


def _wide_site(width):
    children = [f"https://example.com/c{i}" for i in range(width)]
    return children, {HOME: "".join(f"<a href='{c}'>c</a>" for c in children)}


def test_in_flight_fetches_never_exceed_the_limit():
    children, pages = _wide_site(60)
    crawler = Crawler(HOME, max_pages=100, max_depth=2, respect_robots=False,
                      concurrency=6, max_concurrency=6)
    crawler.sitemap_urls = set()
    lock = threading.Lock()
    state = {"now": 0, "peak": 0}

    def fetch(url):
        with lock:
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
        time.sleep(0.01)
        with lock:
            state["now"] -= 1
        return PageResult(url=url, final_url=url, status_code=200,
                          html=pages.get(url, f"<p>{url}</p>"), headers={})

    crawler._fetch = fetch
    crawler.crawl()

    assert 1 < state["peak"] <= 6


def test_a_crawler_without_max_concurrency_never_exceeds_its_concurrency():
    crawler = Crawler(HOME, max_pages=5, respect_robots=False, concurrency=8)
    assert crawler.max_concurrency == 8


def test_throttling_halves_the_limit_during_a_crawl():
    children, pages = _wide_site(40)
    crawler = Crawler(HOME, max_pages=100, max_depth=2, respect_robots=False,
                      concurrency=16, max_concurrency=16)
    crawler.sitemap_urls = set()

    def fetch(url):
        throttled = url.endswith("c3")
        return PageResult(url=url, final_url=url, status_code=200,
                          html=pages.get(url, f"<p>{url}</p>"), headers={},
                          throttled=throttled, retry_after=None)

    crawler._fetch = fetch
    crawler.crawl()

    assert crawler.limit.limit == 8


def test_a_429_is_retried_after_retry_after_and_marks_the_result_throttled():
    crawler = Crawler(HOME, max_pages=1, respect_robots=False, retries=1)
    responses = [FakeResponse(429, {"Retry-After": "0"}),
                 FakeResponse(200, {"Content-Type": "text/html"}, "<p>ok</p>")]

    class Session:
        def get(self, url, **kwargs):
            return responses.pop(0)

    crawler.session = Session()
    result = crawler._fetch(HOME)

    assert result.status_code == 200
    assert result.throttled is True
    assert result.retry_after == 0.0


def test_crawl_delay_forces_one_request_at_a_time(monkeypatch):
    robots = "User-agent: *\nCrawl-delay: 2\n"

    class Session:
        headers = CaseInsensitiveDict()

        def get(self, url, **kwargs):
            if url.endswith("/robots.txt"):
                return FakeResponse(200, {"Content-Type": "text/plain"}, robots)
            return FakeResponse(404, {})

        def mount(self, *args):
            pass

    monkeypatch.setattr("app.crawler.crawler.requests.Session", lambda: Session())
    crawler = Crawler(HOME, respect_robots=True, concurrency=32, max_concurrency=64)

    assert crawler.concurrency == 1
    assert crawler.max_concurrency == 1
    assert crawler.delay >= 2


def test_the_connection_pool_matches_the_maximum_concurrency():
    crawler = Crawler(HOME, respect_robots=False, concurrency=32, max_concurrency=64)
    adapter = crawler.session.get_adapter("https://example.com/")
    assert adapter._pool_maxsize == 64
