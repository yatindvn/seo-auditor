"""Skipped URLs are stored and reported, not silently dropped."""

import sqlite3

from app.crawler.crawler import Crawler, PageResult
from app.models.session_db import SessionDB
from app.services import audit_service

HOME = "https://example.com/"


def _page(url, html, final_url=None):
    return PageResult(url=url, final_url=final_url or url, status_code=200,
                      html=html, headers={}, content_type="text/html")


def _crawler():
    body = "<html><head><title>X</title></head><body><h1>X</h1><p>same words</p></body></html>"
    site = {
        HOME: "<html><head><title>Home</title></head><body>"
              "<a href='/x'>1</a><a href='/x/'>2</a><a href='/old'>3</a></body></html>",
        "https://example.com/x": body,
        "https://example.com/x/": body,
    }
    redirects = {"https://example.com/old": HOME}
    crawler = Crawler(HOME, max_pages=10, max_depth=2, respect_robots=False)
    crawler.sitemap_urls = {"https://example.com/orphan"}

    def fetch(url):
        final = redirects.get(url, url)
        page = _page(url, site.get(final, "<p>orphan page</p>"), final_url=final)
        if final != url:
            page.redirect_chain = [{"from": url, "to": final, "status": 301}]
        return page

    crawler._fetch = fetch
    return crawler


def _run(crawler, session_id):
    return audit_service._build_audit_result(
        HOME, crawler, progress_callback=None, event_callback=None, session_id=session_id,
    )


def test_skipped_urls_are_written_as_rows_with_their_reason(isolated_session_dir):
    _run(_crawler(), "sess_dedup")

    db = isolated_session_dir.open_session("sess_dedup")
    rows, total = db.get_pages(limit=50)
    by_url = {row["url"]: row for row in rows}

    assert by_url["https://example.com/old"]["alias_of"] == HOME
    dup = [r for r in rows if r["duplicate_of"]]
    assert len(dup) == 1
    assert by_url["https://example.com/orphan"]["found_via"] == "sitemap"
    assert total == 5


def test_summary_reports_the_dedup_counts():
    result = _run(_crawler(), "sess_counts")

    assert result["dedup"] == {"aliases": 1, "duplicates": 1, "sitemap_only": 1}


def test_an_exact_duplicate_still_appears_in_the_duplicate_content_report():
    result = _run(_crawler(), "sess_groups")

    groups = list(result["duplicates"]["duplicate_content"].values())
    assert any({"https://example.com/x", "https://example.com/x/"} <= set(g) for g in groups)


def test_an_alias_redirect_still_appears_in_the_redirect_report():
    result = _run(_crawler(), "sess_redirects")

    assert result["redirects"]["total_redirecting_urls"] == 1


def test_an_older_session_db_without_the_new_columns_still_opens(tmp_path):
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
          meta_json TEXT
        );
        INSERT INTO pages (url, depth, status, issue_count, meta_json)
        VALUES ('https://example.com/', 0, 200, 0, '{}');
    """)
    conn.commit()
    conn.close()

    db = SessionDB(path)
    rows, total = db.get_pages()

    assert total == 1
    assert rows[0]["alias_of"] is None
