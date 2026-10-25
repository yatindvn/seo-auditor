"""A re-audit reuses the HTML analysis of unchanged pages and redoes the rest."""

import sqlite3

import pytest

from app.crawler.crawler import Crawler
from app.models.page_cache import cache_file_name
from app.models.session_db import SessionDB
from app.services import audit_service, page_pipeline
from tests.fake_http import FakeSite

HOME = "https://example.com/"


def _site(**kwargs):
    body = "<p>{} has enough words here for the content checks to be satisfied fully</p>"
    pages = {HOME: "<html><head><title>Home</title></head><body>"
                   "<a href='/a'>a</a><a href='/b'>b</a>" + body.format("home") + "</body></html>"}
    for name in ("a", "b"):
        pages[f"https://example.com/{name}"] = (
            f"<html><head><title>Page {name}</title></head><body><h1>{name}</h1>"
            + body.format(name) + "</body></html>"
        )
    return FakeSite(pages, **kwargs)


def _audit(site, session_id, **kwargs):
    crawler = Crawler(HOME, max_pages=10, max_depth=2, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler.session = site.session
    return audit_service._build_audit_result(
        HOME, crawler, progress_callback=None, event_callback=None,
        external_link_check_limit=0, session_id=session_id, **kwargs,
    )


def _issue_codes(result):
    return {url: sorted(i["code"] for i in issues)
            for url, issues in result["page_issues_detail"].items()}


def test_the_first_audit_analyses_every_page():
    result = _audit(_site(), "s1")

    assert result["reuse"] == {"not_modified": 0, "same_hash": 0, "analysed": 3}


def test_a_re_audit_of_an_unchanged_site_analyses_nothing(monkeypatch):
    site = _site()
    first = _audit(site, "s1")

    def no_html_analysis(payload):
        raise AssertionError(f"re-analysed {payload.url}")

    monkeypatch.setattr(page_pipeline, "analyze_html", no_html_analysis)
    second = _audit(site, "s2")

    assert second["reuse"] == {"not_modified": 3, "same_hash": 0, "analysed": 0}
    assert _issue_codes(second) == _issue_codes(first)
    assert set(site.conditional_calls()) == set(site.pages)


def test_a_changed_page_is_analysed_again_and_the_rest_reused():
    site = _site()
    _audit(site, "s1")
    site.pages["https://example.com/a"] = site.pages["https://example.com/a"].replace(
        "<title>Page a</title>", "<title>Page a, rewritten</title>"
    )

    second = _audit(site, "s2")

    assert second["reuse"] == {"not_modified": 2, "same_hash": 0, "analysed": 1}
    assert second["executive_summary"]["pages_crawled"] == 3


def test_without_validators_an_identical_body_is_reused_by_hash():
    site = _site(etags=False)
    _audit(site, "s1")

    second = _audit(site, "s2")

    assert second["reuse"] == {"not_modified": 0, "same_hash": 3, "analysed": 0}


def test_response_checks_run_fresh_on_a_304():
    """The 304 adds Cache-Control the first audit lacked: NO_CACHE_HEADER must
    clear, while the CSP stored from the first audit must not be reported
    missing just because the 304 did not repeat it."""
    site = _site()
    first = _audit(site, "s1")
    assert all("NO_CACHE_HEADER" in codes for codes in _issue_codes(first).values())

    site.not_modified_headers = {"Cache-Control": "max-age=60"}
    second = _audit(site, "s2")

    for codes in _issue_codes(second).values():
        assert "NO_CACHE_HEADER" not in codes
        assert "MISSING_HEADER_CONTENT_SECURITY_POLICY" not in codes


def test_fresh_re_checks_everything_and_sends_no_validators():
    site = _site()
    _audit(site, "s1")
    site.calls.clear()

    second = _audit(site, "s2", fresh=True)

    assert second["reuse"]["analysed"] == 3
    assert site.conditional_calls() == []


def test_changing_the_audit_options_invalidates_the_cache():
    site = _site()
    _audit(site, "s1")

    second = _audit(site, "s2", enable_keyword_analysis=False)

    assert second["reuse"]["analysed"] == 3


def test_a_corrupt_cache_does_not_fail_the_audit(isolated_session_dir):
    site = _site()
    _audit(site, "s1")
    path = isolated_session_dir.page_cache_dir / cache_file_name(HOME)
    path.write_bytes(b"corrupt" * 1000)
    for suffix in ("-wal", "-shm"):
        (path.parent / (path.name + suffix)).unlink(missing_ok=True)

    second = _audit(site, "s2")

    assert second["reuse"]["analysed"] == 3


def test_reused_pages_are_marked_in_the_stored_rows(isolated_session_dir):
    site = _site()
    _audit(site, "s1")
    _audit(site, "s2")

    rows, _ = isolated_session_dir.open_session("s2").get_pages(limit=10)

    assert {row["cache_status"] for row in rows} == {"not_modified"}


def test_a_session_db_without_cache_status_still_opens(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE pages (
          url TEXT PRIMARY KEY, final_url TEXT, depth INTEGER, status INTEGER,
          response_time_ms REAL, content_type TEXT, title TEXT, meta_description TEXT,
          h1 TEXT, canonical TEXT, word_count INTEGER, char_count INTEGER,
          internal_links_count INTEGER, external_links_count INTEGER,
          images_count INTEGER, missing_alt_count INTEGER,
          meta_robots TEXT, lang TEXT, error TEXT, issue_count INTEGER DEFAULT 0,
          meta_json TEXT, alias_of TEXT, duplicate_of TEXT, found_via TEXT
        );
        INSERT INTO pages (url, depth, status, issue_count, meta_json)
        VALUES ('https://example.com/', 0, 200, 0, '{}');
    """)
    conn.commit()
    conn.close()

    rows, total = SessionDB(path).get_pages()

    assert total == 1
    assert rows[0]["cache_status"] is None
