"""Live crawl events must stay proportionate to the crawl.

One event per internal link means a few hundred thousand WebSocket messages on a
5000-page site -- the browser stalls long before the crawl finishes. Links are
reported as a running count instead, flushed at most once a second.
"""

import time

from app.crawler.crawler import Crawler, PageResult


def _crawler_with(html, **kwargs):
    home = "https://example.com/"
    options = dict(max_pages=1, max_depth=1, respect_robots=False)
    options.update(kwargs)
    crawler = Crawler(home, **options)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=html, headers={},
    )
    return crawler


def _collect(crawler):
    events = []
    crawler.crawl(event_callback=lambda kind, payload: events.append((kind, payload)))
    return events


def test_links_are_reported_as_an_aggregate_not_one_event_each():
    links = "".join(f"<a href='https://example.com/p{i}'>x</a>" for i in range(200))

    events = _collect(_crawler_with(links))

    assert not [e for e in events if e[0] in ("internal_link", "external_link")], (
        "per-link events are exactly what this removes"
    )
    progress = [payload for kind, payload in events if kind == "link_progress"]
    assert progress, "the aggregate must still be reported"
    assert progress[-1]["internal_total"] == 200


def test_external_links_are_counted_separately():
    html = (
        "<a href='https://example.com/one'>i</a>"
        "<a href='https://other.example/a'>e</a>"
        "<a href='https://third.example/b'>e</a>"
    )

    events = _collect(_crawler_with(html))

    final = [payload for kind, payload in events if kind == "link_progress"][-1]
    assert final["internal_total"] == 1
    assert final["external_total"] == 2


def test_page_crawled_events_are_still_per_page():
    """Only the per-link firehose is aggregated. One event per page is
    proportionate -- it is what drives the live feed."""
    links = "".join(f"<a href='https://example.com/p{i}'>x</a>" for i in range(30))

    events = _collect(_crawler_with(links, max_pages=5, max_depth=2))

    assert len([e for e in events if e[0] == "page_crawled"]) == 5


def test_the_running_total_is_flushed_at_most_once_a_second():
    """Throttled, or the aggregate becomes its own firehose on a fast crawl."""
    links = "".join(f"<a href='https://example.com/p{i}'>x</a>" for i in range(40))
    crawler = _crawler_with(links, max_pages=20, max_depth=3)

    started = time.monotonic()
    events = _collect(crawler)
    elapsed = time.monotonic() - started

    flushes = len([e for e in events if e[0] == "link_progress"])
    assert flushes <= int(elapsed) + 2, (
        f"{flushes} link_progress events in {elapsed:.2f}s is not throttled"
    )


def test_a_final_flush_reports_the_true_total():
    """Throttling must not lose the last increments: a crawl finishing inside
    the flush window would otherwise report a stale count, or none at all."""
    links = "".join(f"<a href='https://example.com/p{i}'>x</a>" for i in range(7))

    events = _collect(_crawler_with(links))

    final = [payload for kind, payload in events if kind == "link_progress"][-1]
    assert final["internal_total"] == 7
