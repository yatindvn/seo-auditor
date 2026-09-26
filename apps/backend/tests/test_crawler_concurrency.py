"""The crawl loop: continuous workers, BFS order preserved, cap respected.

The previous loop took a batch of `concurrency` URLs and waited for every one of
them before starting the next, and rebuilt its thread pool each time. A slow
page therefore idled every other worker until it finished.
"""

import time

from app.crawler.crawler import Crawler, PageResult


def _site(width=30, slow_every=None, slow_seconds=0.25):
    """An in-memory site: a home page linking to `width` children.

    `slow_every` makes every Nth child slow. One slow page alone would prove
    nothing -- it costs the same either way -- so they are spread so that the
    old batching put exactly one in each batch, where they cost the sum of their
    delays rather than the maximum.
    """
    home = "https://example.com/"
    children = [f"https://example.com/p{i:03d}" for i in range(width)]
    pages = {home: "".join(f"<a href='{c}'>c</a>" for c in children)}
    pages.update({child: "<html><body>leaf</body></html>" for child in children})
    slow = set()
    if slow_every:
        slow = {children[i] for i in range(0, width, slow_every)}

    def fetch(url):
        if url in slow:
            time.sleep(slow_seconds)
        return PageResult(url=url, final_url=url, status_code=200,
                          html=pages.get(url, ""), headers={})

    return home, children, fetch


def test_crawl_visits_pages_in_breadth_first_order():
    """The frontier changed from a list to a heap; click-depth order is what
    makes crawl depth and the architecture graph meaningful, so it must not."""
    home, children, fetch = _site(width=5)
    grandchild = "https://example.com/deep"
    crawler = Crawler(home, max_pages=50, max_depth=5, respect_robots=False)
    original_fetch = fetch

    def fetch_with_grandchild(url):
        if url == children[0]:
            return PageResult(url=url, final_url=url, status_code=200,
                              html=f"<a href='{grandchild}'>d</a>", headers={})
        return original_fetch(url)

    crawler._fetch = fetch_with_grandchild

    results = crawler.crawl()

    depths = {url: result.depth for url, result in results.items()}
    assert depths[home] == 0
    assert all(depths[child] == 1 for child in children)
    assert depths[grandchild] == 2


def test_slow_pages_do_not_stall_the_other_workers():
    """The regression this task exists for.

    Five slow pages, spread one per batch of eight. Batched, they cost the sum
    of their delays (~1.25s) because each batch waits for its slowest member.
    Running continuously they overlap, and cost about one delay.
    """
    home, _, fetch = _site(width=40, slow_every=8, slow_seconds=0.25)
    crawler = Crawler(home, max_pages=41, max_depth=2, respect_robots=False, concurrency=8)
    crawler._fetch = fetch

    started = time.monotonic()
    crawler.crawl()
    elapsed = time.monotonic() - started

    assert elapsed < 0.8, (
        f"crawl took {elapsed:.2f}s; five 0.25s pages are still being serialised "
        "one per batch instead of overlapping"
    )


def test_max_pages_is_never_exceeded_with_many_workers_in_flight():
    """Pins the cap against the new risk: many concurrent fetches can each pass
    a naive `len(visited) < max_pages` check before any of them records a
    result."""
    home, _, fetch = _site(width=100)
    crawler = Crawler(home, max_pages=25, max_depth=3, respect_robots=False, concurrency=32)
    crawler._fetch = fetch

    results = crawler.crawl()

    assert len(results) <= 25


def test_every_reachable_page_is_still_crawled():
    """A continuous loop can terminate early if it mistakes an empty frontier
    for a finished crawl while work is still in flight."""
    home, children, fetch = _site(width=30)
    crawler = Crawler(home, max_pages=100, max_depth=3, respect_robots=False, concurrency=8)
    crawler._fetch = fetch

    results = crawler.crawl()

    assert set(results) == {home, *children}


def test_on_page_observes_every_page():
    """Stage 2 receives each page through this callback. Its return value is
    ignored: it submits the analysis and does not block the crawl on it."""
    home, children, fetch = _site(width=3)
    crawler = Crawler(home, max_pages=10, max_depth=2, respect_robots=False)
    crawler._fetch = fetch
    seen = []

    crawler.crawl(on_page=lambda result: seen.append(result.url))

    assert set(seen) == {home, *children}


def test_links_are_read_before_the_observer_can_release_the_markup():
    """Stage 2 clears result.html once the page is on its way to a worker. If
    the crawler extracted links after that, it would find an empty string and
    every crawl would stop at the start URL."""
    home, children, fetch = _site(width=3)
    crawler = Crawler(home, max_pages=10, max_depth=2, respect_robots=False)
    crawler._fetch = fetch

    def release_markup(result):
        result.html = ""

    results = crawler.crawl(on_page=release_markup)

    assert set(results) == {home, *children}


def test_without_on_page_the_crawler_still_finds_its_own_links():
    """The CLI and any direct caller pass no callback."""
    home, children, fetch = _site(width=4)
    crawler = Crawler(home, max_pages=10, max_depth=2, respect_robots=False)
    crawler._fetch = fetch

    results = crawler.crawl()

    assert set(results) == {home, *children}


def test_stopping_mid_crawl_ends_promptly():
    home, _, fetch = _site(width=50)
    crawler = Crawler(home, max_pages=50, max_depth=3, respect_robots=False, concurrency=4)
    original = fetch

    def fetch_and_stop(url):
        if len(crawler.visited) >= 3:
            crawler.is_stopped = True
        return original(url)

    crawler._fetch = fetch_and_stop

    results = crawler.crawl()

    assert len(results) < 50, "a stopped crawl must not run to completion"


def test_depth_limit_stops_link_following():
    home, children, fetch = _site(width=3)
    crawler = Crawler(home, max_pages=50, max_depth=0, respect_robots=False)
    crawler._fetch = fetch

    results = crawler.crawl()

    assert set(results) == {home}, "at max_depth 0 only the start URL is fetched"
