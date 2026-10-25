"""Sitemap-listed pages are crawled, after everything links reach."""

import time

from app.crawler.crawler import Crawler, PageResult

HOME = "https://example.com/"


def _crawler(site, sitemap, max_pages=50, max_depth=3, delay=0.0, concurrency=8):
    crawler = Crawler(HOME, max_pages=max_pages, max_depth=max_depth,
                      respect_robots=False, delay=delay, concurrency=concurrency)
    crawler.sitemap_urls = set(sitemap)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=site.get(url, f"<p>{url}</p>"), headers={},
    )
    return crawler


def test_a_page_only_in_the_sitemap_is_crawled_and_marked():
    orphan = "https://example.com/orphan"
    crawler = _crawler({HOME: "<p>no links</p>"}, sitemap=[orphan])

    results = crawler.crawl()

    assert orphan in results
    assert results[orphan].found_via == "sitemap"
    assert results[orphan].depth == crawler.max_depth + 1


def test_a_sitemap_page_also_reachable_by_link_gets_its_link_depth():
    linked = "https://example.com/linked"
    crawler = _crawler({HOME: f"<a href='{linked}'>l</a>"}, sitemap=[linked])

    results = crawler.crawl()

    assert results[linked].depth == 1
    assert results[linked].found_via == "link"


def test_link_reachable_pages_are_crawled_before_sitemap_only_ones():
    children = [f"https://example.com/c{i}" for i in range(5)]
    orphan = "https://example.com/orphan"
    crawler = _crawler({HOME: "".join(f"<a href='{c}'>c</a>" for c in children)},
                       sitemap=[orphan], max_pages=6)

    results = crawler.crawl()

    assert orphan not in results  # cap filled by link-reachable pages first
    assert set(children) <= set(results)


def test_off_domain_sitemap_entries_are_ignored():
    crawler = _crawler({HOME: "<p>x</p>"}, sitemap=["https://other.com/x"])

    results = crawler.crawl()

    assert "https://other.com/x" not in results


def test_sitemap_only_pages_are_not_expanded():
    orphan = "https://example.com/orphan"
    beyond = "https://example.com/beyond"
    crawler = _crawler({HOME: "<p>x</p>", orphan: f"<a href='{beyond}'>b</a>"}, sitemap=[orphan])

    results = crawler.crawl()

    assert beyond not in results


def test_delay_paces_each_worker_not_the_whole_crawl():
    """8 pages, 8 workers, 0.2s delay: paced per worker this takes ~0.2s plus
    the home page; paced on the main loop it took 8 x 0.2s."""
    children = [f"https://example.com/c{i}" for i in range(8)]
    crawler = _crawler({HOME: "".join(f"<a href='{c}'>c</a>" for c in children)},
                       sitemap=[], delay=0.2, concurrency=8)

    started = time.monotonic()
    crawler.crawl()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0
