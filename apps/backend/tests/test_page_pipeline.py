"""Stage 2 of the pipeline: everything that happens to one page's HTML.

Extracted from audit_service's per-page loop so it can run in a process pool
while the crawl continues. Purity is the requirement that makes that possible --
no config, no network, no module-level state, and nothing reaching back into the
crawler -- so it is asserted here rather than assumed.
"""

import pickle

from app.services.page_pipeline import PagePayload, analyze_page

HTML = (
    "<html lang='en'><head><title>Espresso Machines</title>"
    "<meta name='description' content='Reviews of espresso machines'>"
    "<meta property='og:title' content='Espresso'></head>"
    "<body><h1>Best Espresso Machines</h1>"
    "<h2>Reviews</h2>"
    "<p>espresso machine reviews and buying guide with plenty of words to "
    "satisfy the word count checks in this pipeline test fixture.</p>"
    "<img src='/a.png'><img src='/b.png' alt='b'>"
    "<a href='/grinders'>Grinders</a>"
    "<a href='/grinders'>Grinders again</a>"
    "<a href='https://other.example/x'>Off site</a>"
    "</body></html>"
)


def _payload(**overrides):
    base = dict(
        url="https://example.com/", final_url="https://example.com/", status_code=200,
        headers={}, html=HTML, depth=0, redirect_chain=[], response_time_ms=10.0,
        content_type="text/html", error=None,
    )
    base.update(overrides)
    return PagePayload(**base)


def test_analyze_page_returns_the_pages_metadata():
    result = analyze_page(_payload())

    assert result.meta["title"] == "Espresso Machines"
    assert result.meta["meta_description"] == "Reviews of espresso machines"
    assert result.meta["h1"] == "Best Espresso Machines"
    assert result.meta["lang"] == "en"
    assert result.meta["h2_count"] == 1
    assert result.meta["images_count"] == 2
    assert result.meta["missing_alt_count"] == 1
    assert result.meta["word_count"] > 0
    assert result.meta["open_graph"] == {"og:title": "Espresso"}


def test_analyze_page_returns_issues():
    result = analyze_page(_payload())

    codes = {issue["code"] for issue in result.issues}
    assert "MISSING_ALT" in codes
    assert all({"severity", "code", "message"} == set(issue) for issue in result.issues)


def test_analyze_page_separates_internal_from_external_links():
    result = analyze_page(_payload())

    assert "https://example.com/grinders" in result.internal_links
    assert "https://other.example/x" in result.external_links
    assert "https://other.example/x" not in result.internal_links


def test_link_counts_are_deduplicated():
    """The page links to /grinders twice. The old implementation read this from
    the crawler's link_graph, which is a set, so the count must stay deduped."""
    result = analyze_page(_payload())

    assert result.meta["internal_links_count"] == 1


def test_external_link_count_reflects_the_pages_actual_external_links():
    """Regression: this was always 0.

    audit_service computed it as the external URLs whose `inbound_links` entry
    contained this page -- but the crawler only ever populates inbound_links for
    internal pages it fetched, so the intersection was empty by construction and
    every page reported 0 external links. Proven against a real crawl before the
    move.
    """
    result = analyze_page(_payload())

    assert result.meta["external_links_count"] == 1


def test_analyze_page_is_picklable_in_both_directions():
    """The process pool sends a payload and receives an analysis. Anything
    unpicklable in either -- a BeautifulSoup node, a compiled regex, a lambda --
    fails at the pool boundary, where the error is far from its cause."""
    payload = _payload()

    assert pickle.loads(pickle.dumps(payload)).url == payload.url
    assert pickle.loads(pickle.dumps(analyze_page(payload))).meta["title"] == "Espresso Machines"


def test_keyword_extraction_runs_by_default():
    result = analyze_page(_payload())

    assert result.keyword_data, "extraction is the free, local part and is on by default"


def test_keyword_extraction_is_skipped_when_disabled():
    result = analyze_page(_payload(enable_keyword_analysis=False))

    assert result.keyword_data == []


def test_target_keywords_override_extraction():
    result = analyze_page(_payload(target_keywords=["espresso machine"]))

    assert [k["phrase"] for k in result.keyword_data] == ["espresso machine"]


def test_signature_is_only_computed_when_asked():
    """Signing costs real CPU, and only crawls above the exact-path threshold
    need it."""
    assert analyze_page(_payload()).signature is None

    signed = analyze_page(_payload(compute_signature=True))
    assert signed.signature is not None
    assert len(signed.signature) == 512


def test_a_page_with_no_html_still_produces_a_usable_result():
    """A fetch error yields a PageResult with empty html; it must still get a
    row and its status issues, not blow up the worker."""
    result = analyze_page(_payload(html="", status_code=None, error="timeout"))

    assert result.url == "https://example.com/"
    assert result.internal_links == []
    assert result.signature is None
    assert result.issues, "a page that could not be fetched is itself an issue"


def test_dupe_row_carries_what_duplicate_detection_needs():
    result = analyze_page(_payload())

    assert result.dupe_row["url"] == "https://example.com/"
    assert result.dupe_row["title"] == "Espresso Machines"
    assert result.dupe_row["content_hash"]
    assert result.dupe_row["text"]
