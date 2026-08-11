from unittest.mock import patch

from app.crawler.crawler import PageResult
from app.services import audit_service


class FakeCrawler:
    """Minimal stand-in for `Crawler` exposing only what
    `_build_audit_result` touches, so these tests can exercise the real
    keyword-gating wiring without a real (network-hitting) crawl."""

    def __init__(self):
        page_html = (
            "<html><head><title>Espresso Machines</title></head>"
            "<body><h1>Best Espresso Machines</h1>"
            "<p>espresso machine reviews and buying guide with plenty of words "
            "to satisfy word count checks in this audit pipeline test fixture.</p>"
            "</body></html>"
        )
        page_url = "https://example.com/"
        self.start_url = page_url
        self.results = {
            page_url: PageResult(
                url=page_url,
                final_url=page_url,
                status_code=200,
                html=page_html,
                headers={},
                depth=0,
            )
        }
        self.link_graph = {page_url: set()}
        self.inbound_links = {page_url: set()}
        self.external_links_checked = {}
        self.robots_txt_content = None
        self.sitemaps_found = []
        self.sitemap_urls = set()
        self.event_callback = None
        self.fetch_calls = []

    def crawl(self, progress_callback=None, event_callback=None):
        self.event_callback = event_callback

    def check_external_links(self, max_check=25):
        pass

    def _fetch(self, url):
        self.fetch_calls.append(url)
        raise AssertionError(f"crawler._fetch should not be called for {url} in this test")


def test_build_audit_result_default_params_never_calls_suggest_keywords():
    """Regression test for the critical final-review finding: with default
    params (no flags overridden — matching what a bare POST /api/audit sends),
    `keyword_suggestions.suggest_keywords` — and therefore the Google
    Autocomplete network call it makes — must never run. Before this fix,
    `suggest_keywords` was gated by `enable_keyword_analysis` (default True),
    so it fired unconditionally on every page of every audit."""
    crawler = FakeCrawler()

    with patch.object(audit_service.keyword_suggestions, "suggest_keywords") as mock_suggest:
        result = audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
        )

    mock_suggest.assert_not_called()
    # Extraction (the actually-free part) must still run by default.
    keyword_analysis = result["pages"][0]["keyword_analysis"] if result["pages"] else None
    assert keyword_analysis is not None
    assert len(keyword_analysis["top_keywords"]) > 0


def test_build_audit_result_enable_keyword_suggestions_true_calls_suggest_keywords():
    """Sanity-check the flip side: explicitly opting in still wires through."""
    crawler = FakeCrawler()

    with patch.object(audit_service.keyword_suggestions, "suggest_keywords", return_value=[]) as mock_suggest:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_keyword_suggestions=True,
        )

    mock_suggest.assert_called_once()


def test_get_crawler_returns_none_for_unknown_session():
    assert audit_service.get_crawler("unknown_session") is None


def test_registered_crawler_is_scoped_to_its_session():
    crawler_a = object()
    crawler_b = object()

    audit_service.register_crawler("session_a", crawler_a)
    audit_service.register_crawler("session_b", crawler_b)

    try:
        assert audit_service.get_crawler("session_a") is crawler_a
        assert audit_service.get_crawler("session_b") is crawler_b
    finally:
        audit_service.unregister_crawler("session_a")
        audit_service.unregister_crawler("session_b")


def test_unregister_crawler_removes_only_its_own_session():
    audit_service.register_crawler("session_a", object())
    audit_service.register_crawler("session_b", object())

    audit_service.unregister_crawler("session_a")

    assert audit_service.get_crawler("session_a") is None
    assert audit_service.get_crawler("session_b") is not None

    audit_service.unregister_crawler("session_b")


def test_resolve_keyword_data_disabled_and_no_target_keywords_returns_empty():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = audit_service._resolve_keyword_data(
        target_keywords=None,
        enable_keyword_analysis=False,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert result == []


def test_resolve_keyword_data_enabled_and_no_target_keywords_extracts_keywords():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = audit_service._resolve_keyword_data(
        target_keywords=None,
        enable_keyword_analysis=True,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert len(result) > 0
    assert any("espresso" in kw["phrase"] for kw in result)


def test_resolve_keyword_data_target_keywords_override_wins_even_when_disabled():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = audit_service._resolve_keyword_data(
        target_keywords=["custom keyword"],
        enable_keyword_analysis=False,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert result == [{"phrase": "custom keyword", "score": None, "found_in": []}]
