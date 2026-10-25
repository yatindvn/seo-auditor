"""One page, one fetch-and-analysis, whichever spelling reached it.

Fixtures set content_type="text/html" explicitly: the body-hash layer applies
only to real HTML responses, which is what the live fetcher always reports.
"""

import threading
import time

from app.crawler.crawler import Crawler, PageResult

HOME = "https://example.com/"


def _page(url, html, final_url=None, status=200, content_type="text/html"):
    return PageResult(url=url, final_url=final_url or url, status_code=status,
                      html=html, headers={}, content_type=content_type)


def _crawler(site, redirects=None, max_pages=50, max_depth=5):
    """`site` maps URL -> HTML; `redirects` maps URL -> final URL."""
    redirects = redirects or {}
    fetched = []
    lock = threading.Lock()

    def fetch(url):
        with lock:
            fetched.append(url)
        final = redirects.get(url, url)
        return _page(url, site.get(final, ""), final_url=final)

    crawler = Crawler(HOME, max_pages=max_pages, max_depth=max_depth, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler._fetch = fetch
    return crawler, fetched


def _unique(n):
    return f"<html><body>page {n}</body></html>"


def test_target_linked_after_its_redirect_is_never_fetched_on_its_own():
    site = {
        HOME: "<a href='/a'>a</a>",
        "https://example.com/a-target": "<a href='/a-target'>self</a>" + _unique(1),
    }
    crawler, fetched = _crawler(site, redirects={"https://example.com/a": "https://example.com/a-target"})
    analysed = []

    crawler.crawl(on_page=lambda r: analysed.append(r.url))

    assert "https://example.com/a-target" not in fetched
    assert analysed == [HOME, "https://example.com/a"]


def test_redirect_landing_on_an_already_crawled_page_is_an_alias():
    site = {
        HOME: "<a href='/b'>b</a><a href='/old'>old</a>",
        "https://example.com/b": _unique(1),
    }
    crawler, _ = _crawler(site, redirects={"https://example.com/old": "https://example.com/b"},
                          max_depth=1)
    # /b and /old are siblings; make /b complete first so /old is the alias.
    original = crawler._fetch

    def ordered(url):
        if url == "https://example.com/old":
            time.sleep(0.05)
        return original(url)

    crawler._fetch = ordered
    analysed = []

    results = crawler.crawl(on_page=lambda r: analysed.append(r.url))

    assert "https://example.com/old" not in results
    assert crawler.skipped["https://example.com/old"].alias_of == "https://example.com/b"
    assert crawler.aliases["https://example.com/old"] == "https://example.com/b"
    assert "https://example.com/old" not in analysed


def test_two_redirects_to_one_target_produce_one_analysis():
    site = {
        HOME: "<a href='/x'>x</a><a href='/y'>y</a>",
        "https://example.com/t": _unique(1),
    }
    crawler, _ = _crawler(site, redirects={
        "https://example.com/x": "https://example.com/t",
        "https://example.com/y": "https://example.com/t",
    })
    analysed = []

    crawler.crawl(on_page=lambda r: analysed.append(r.url))

    assert len([u for u in analysed if u != HOME]) == 1
    assert len(crawler.skipped) == 1


def test_identical_html_under_two_paths_is_analysed_once():
    body = _unique(7)
    site = {HOME: "<a href='/x'>1</a><a href='/x/'>2</a>",
            "https://example.com/x": body, "https://example.com/x/": body}
    crawler, _ = _crawler(site)
    analysed = []

    crawler.crawl(on_page=lambda r: analysed.append(r.url))

    skipped = list(crawler.skipped.values())
    assert len(skipped) == 1
    assert skipped[0].duplicate_of in {"https://example.com/x", "https://example.com/x/"}
    assert skipped[0].url not in analysed


def test_html_differing_by_one_byte_is_analysed_twice():
    site = {HOME: "<a href='/x'>1</a><a href='/y'>2</a>",
            "https://example.com/x": "<p>a</p>", "https://example.com/y": "<p>b</p>"}
    crawler, _ = _crawler(site)

    crawler.crawl()

    assert crawler.skipped == {}
    assert len(crawler.results) == 3


def test_non_html_responses_are_never_hashed():
    crawler = Crawler(HOME, max_pages=10, max_depth=2, respect_robots=False)
    crawler.sitemap_urls = set()
    links = "<a href='/a.txt'>a</a><a href='/b.txt'>b</a>"
    crawler._fetch = lambda url: (
        _page(url, links) if url == HOME else _page(url, "same", content_type="text/plain")
    )

    crawler.crawl()

    assert crawler.skipped == {}


def test_cap_counts_unique_pages_so_duplicates_do_not_use_it_up():
    """10 unique pages, each also served byte-identically under a trailing slash."""
    links = "".join(f"<a href='/p{i}'>p</a><a href='/p{i}/'>d</a>" for i in range(10))
    site = {HOME: links}
    for i in range(10):
        site[f"https://example.com/p{i}"] = _unique(i)
        site[f"https://example.com/p{i}/"] = _unique(i)
    crawler, _ = _crawler(site, max_pages=11)

    results = crawler.crawl()

    assert len(results) == 11  # home + all 10 unique pages
    for i in range(10):
        spellings = {f"https://example.com/p{i}", f"https://example.com/p{i}/"}
        assert len(spellings & set(results)) == 1


def test_a_site_of_endless_aliases_stops_at_the_fetch_ceiling():
    """100 links that all redirect to one page: every one after the first is an
    alias and hands its slot back, so only the ceiling ends the crawl."""
    target = "https://example.com/target"
    links = "".join(f"<a href='/r{i}'>r</a>" for i in range(100))
    redirects = {f"https://example.com/r{i}": target for i in range(100)}
    crawler, fetched = _crawler({HOME: links, target: _unique(1)}, redirects=redirects,
                                max_pages=5)

    crawler.crawl()

    assert crawler.fetch_ceiling == 10
    assert len(fetched) == 10
    assert len(crawler.results) == 2  # home + the one URL that claimed the target


def test_links_to_a_known_alias_resolve_to_the_page_it_represents():
    """/old redirects to /b and is crawled first, so /old represents /b. A page
    found later linking straight to /b gets an edge to /old, and /b is never
    fetched on its own."""
    site = {
        HOME: "<a href='/old'>old</a>",
        "https://example.com/b": "<a href='/c'>c</a>" + _unique(1),
        "https://example.com/c": "<a href='/b'>back</a>" + _unique(2),
    }
    crawler, fetched = _crawler(site, redirects={"https://example.com/old": "https://example.com/b"})

    crawler.crawl()

    assert crawler.link_graph["https://example.com/c"] == {"https://example.com/old"}
    assert "https://example.com/b" not in fetched
