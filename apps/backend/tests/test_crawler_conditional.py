"""Conditional requests: ask the server whether a page changed, and treat a
304 as the cached page with today's headers."""

import hashlib

from app.crawler.crawler import Crawler, Validators
from tests.fake_http import FakeSite

HOME = "https://example.com/"
CHILD = "https://example.com/child"


def _sha(html):
    return hashlib.sha256(html.encode("utf-8")).hexdigest()


def _crawler(site, max_pages=10):
    crawler = Crawler(HOME, max_pages=max_pages, max_depth=3, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler.session = site.session
    return crawler


def test_validators_turn_into_conditional_headers_only_for_known_urls():
    site = FakeSite({HOME: "<p>home</p>", CHILD: "<p>child</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag='"x"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT")}

    crawler._fetch(HOME)
    crawler._fetch(CHILD)

    sent = dict(site.calls)
    assert sent[HOME] == {"If-None-Match": '"x"', "If-Modified-Since": "Mon, 01 Jan 2026 00:00:00 GMT"}
    assert sent[CHILD] == {}


def test_a_304_becomes_the_cached_page_with_merged_headers():
    html = "<p>home</p>"
    site = FakeSite({HOME: html})
    site.not_modified_headers = {"Cache-Control": "max-age=60"}
    crawler = _crawler(site)
    stored = {"content-type": "text/html", "Content-Security-Policy": "default-src 'self'",
              "ETag": '"stale"'}
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME), body_hash=_sha(html), headers=stored)}

    result = crawler._fetch(HOME)

    assert result.status_code == 200
    assert result.html == ""
    assert result.cache_status == "not_modified"
    assert result.body_hash == _sha(html)
    lower = {k.lower(): v for k, v in result.headers.items()}
    assert lower["content-security-policy"] == "default-src 'self'"  # kept from the store
    assert lower["cache-control"] == "max-age=60"                     # added by the 304
    assert lower["etag"] == site.etag_of(HOME)                        # updated by the 304
    assert len([k for k in result.headers if k.lower() == "etag"]) == 1
    assert "text/html" in result.content_type


def test_an_unchanged_body_without_validators_is_recognised_by_its_hash():
    html = "<p>home</p>"
    site = FakeSite({HOME: html}, etags=False)
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(body_hash=_sha(html))}

    result = crawler._fetch(HOME)

    assert result.html == html
    assert result.cache_status == "same_hash"


def test_a_changed_body_is_not_marked_reusable():
    site = FakeSite({HOME: "<p>new</p>"}, etags=False)
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(body_hash=_sha("<p>old</p>"))}

    result = crawler._fetch(HOME)

    assert result.cache_status is None
    assert result.body_hash == _sha("<p>new</p>")


def test_fetch_unconditional_sends_no_validators():
    site = FakeSite({HOME: "<p>home</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME))}

    result = crawler.fetch_unconditional(HOME)

    assert site.calls == [(HOME, {})]
    assert result.html == "<p>home</p>"


def test_a_304_pages_cached_links_still_drive_the_crawl():
    site = FakeSite({HOME: f"<a href='{CHILD}'>c</a>", CHILD: "<p>child</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME))}
    crawler.cached_links = lambda url: ([CHILD], ["https://other.com/"]) if url == HOME else None

    results = crawler.crawl()

    assert results[HOME].cache_status == "not_modified"
    assert CHILD in results
    assert "https://other.com/" in crawler.external_links


def test_a_304_with_nothing_cached_is_fetched_again_in_full():
    site = FakeSite({HOME: "<p>home</p>"})
    crawler = _crawler(site)
    crawler.validators = {HOME: Validators(etag=site.etag_of(HOME))}
    crawler.cached_links = lambda url: None
    seen = []

    crawler.crawl(on_page=lambda r: seen.append((r.cache_status, r.html)))

    assert seen == [(None, "<p>home</p>")]


def test_two_304s_with_the_same_stored_body_are_duplicates():
    """Part A's body-hash dedup must still work when neither body was sent."""
    same = "<p>same</p>"
    site = FakeSite({HOME: f"<a href='{CHILD}'>c</a>", CHILD: same, "https://example.com/copy": same})
    crawler = _crawler(site)
    links = {HOME: ([CHILD, "https://example.com/copy"], [])}
    crawler.validators = {
        url: Validators(etag=site.etag_of(url), body_hash=_sha(site.pages[url]),
                        headers={"Content-Type": "text/html"})
        for url in site.pages
    }
    crawler.cached_links = lambda url: links.get(url, ([], []))

    crawler.crawl()

    assert len(crawler.skipped) == 1
    assert next(iter(crawler.skipped.values())).duplicate_of is not None
