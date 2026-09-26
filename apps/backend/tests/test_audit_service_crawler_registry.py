from types import SimpleNamespace
from unittest.mock import patch

from app.crawler.crawler import PageResult
from app.services import audit_service, page_pipeline


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

    def crawl(self, progress_callback=None, event_callback=None, on_page=None):
        self.event_callback = event_callback
        # Mirrors the real crawler's observer contract: stage 2 receives each
        # page through on_page as it completes, not from crawler.results
        # afterwards. A fake that skipped this would leave every page
        # unanalysed while looking like a successful crawl.
        for result in list(self.results.values()):
            if on_page is not None:
                on_page(result)

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


def test_build_audit_result_rank_targets_nominated_page_calls_suggest_keywords():
    """Owner's decision (final-review finding): when rank_targets were
    supplied, suggestions are scoped to pages that matched a rank target."""
    crawler = FakeCrawler()
    targets = [SimpleNamespace(url="https://example.com/", keywords=["espresso machine"])]

    with patch.object(audit_service.keyword_suggestions, "suggest_keywords", return_value=[]) as mock_suggest:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_keyword_suggestions=True, rank_targets=targets,
        )

    mock_suggest.assert_called_once()


def test_build_audit_result_rank_targets_unnominated_page_never_calls_suggest_keywords():
    """The start form sets enable_keyword_suggestions site-wide as soon as one
    rank row is filled in. Without this gate, every un-nominated page would
    fire up to 3 synchronous Google Autocomplete requests each (5s timeout
    apiece) from the no-rank-data fallback -- ~300 requests at the form's
    100-page default -- and would show ungrounded suggestions everywhere
    except the one page the user actually nominated."""
    crawler = FakeCrawler()
    targets = [SimpleNamespace(url="https://example.com/some-other-page", keywords=["alpha"])]

    with patch.object(audit_service.keyword_suggestions, "suggest_keywords") as mock_suggest:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_keyword_suggestions=True, rank_targets=targets,
        )

    mock_suggest.assert_not_called()


def test_build_audit_result_rank_targets_empty_preserves_site_wide_suggestions():
    """rank_targets=[] is falsy, same as omitting it: enable_keyword_suggestions
    alone must still fire suggestions on every page. enable_keyword_suggestions
    is a documented standalone API capability (docs/api.md) independent of
    rank tracking, so direct API callers who never send rank_targets must not
    silently regress."""
    crawler = FakeCrawler()

    with patch.object(audit_service.keyword_suggestions, "suggest_keywords", return_value=[]) as mock_suggest:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_keyword_suggestions=True, rank_targets=[],
        )

    mock_suggest.assert_called_once()


def test_build_audit_result_enable_keyword_suggestions_false_never_calls_even_when_nominated():
    """enable_keyword_suggestions remains the master switch: a matching
    nomination alone must not be enough to fire suggestions."""
    crawler = FakeCrawler()
    targets = [SimpleNamespace(url="https://example.com/", keywords=["espresso machine"])]

    with patch.object(audit_service.keyword_suggestions, "suggest_keywords") as mock_suggest:
        audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None, event_callback=None,
            enable_keyword_suggestions=False, rank_targets=targets,
        )

    mock_suggest.assert_not_called()


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

    result = page_pipeline.resolve_keyword_data(
        target_keywords=None,
        enable_keyword_analysis=False,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert result == []


def test_resolve_keyword_data_enabled_and_no_target_keywords_extracts_keywords():
    page_meta_entry = {"title": "Espresso Machines", "h1": "Best Espresso Machines", "heading_hierarchy": []}
    content_stats = {"text": "espresso machine reviews and buying guide"}

    result = page_pipeline.resolve_keyword_data(
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

    result = page_pipeline.resolve_keyword_data(
        target_keywords=["custom keyword"],
        enable_keyword_analysis=False,
        page_meta_entry=page_meta_entry,
        content_stats=content_stats,
    )

    assert result == [{"phrase": "custom keyword", "score": None, "found_in": []}]
