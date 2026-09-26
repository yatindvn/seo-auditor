"""Audit rows land in SQLite as the crawl runs.

This is what makes the paginated endpoints possible: the dashboard can read a
page of results without the server assembling every row into one response.

Deliberately additive for now. `_build_audit_result` still returns the whole
audit dict, because the CLI builds its five report files from it and the API
still serves it. The endpoints switch to reading from here in the task that
changes their shapes; doing both at once would leave everything in between
broken.
"""

from unittest.mock import patch

from app.crawler.crawler import Crawler, PageResult
from app.models.session_model import SessionStore
from app.services import audit_service

HTML = (
    "<html><head><title>T</title></head><body><h1>H</h1>"
    "<p>words here plenty of them for the content checks to chew on</p>"
    "<a href='https://other.example/x'>ext</a></body></html>"
)


def _crawler(page_count=4, max_pages=None):
    home = "https://example.com/"
    children = [f"https://example.com/p{i}" for i in range(page_count - 1)]
    links = "".join(f"<a href='{c}'>x</a>" for c in children)
    pages = {home: f"<html><head><title>Home</title></head><body>{links}</body></html>"}
    pages.update({child: HTML for child in children})
    crawler = Crawler(home, max_pages=max_pages or page_count, max_depth=2,
                      respect_robots=False)
    crawler._fetch = lambda url: PageResult(
        url=url, final_url=url, status_code=200, html=pages.get(url, HTML), headers={},
    )
    return crawler


def _run(store, crawler, session_id="sess_persist", **kwargs):
    with patch.object(audit_service, "session_store", store):
        return audit_service._build_audit_result(
            "https://example.com/", crawler, progress_callback=None,
            event_callback=None, session_id=session_id, **kwargs,
        )


def test_every_page_is_written_to_the_session_database(tmp_path):
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    rows, total = store.get("sess_persist").get_pages()
    assert total == 4
    assert {row["url"] for row in rows} == {
        "https://example.com/",
        "https://example.com/p0",
        "https://example.com/p1",
        "https://example.com/p2",
    }


def test_written_rows_carry_the_pages_metadata(tmp_path):
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    row = store.get("sess_persist").get_page("https://example.com/p0")
    assert row["title"] == "T"
    assert row["h1"] == "H"
    assert row["status"] == 200
    assert row["word_count"] > 0
    assert row["meta"]["open_graph"] == {}


def test_issues_are_written_and_countable(tmp_path):
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    db = store.get("sess_persist")
    _, total = db.get_issues()
    assert total > 0
    critical, _ = db.get_issues(severity="critical")
    assert all(issue["severity"] == "critical" for issue in critical)


def test_links_are_written_with_internal_and_external_distinguished(tmp_path):
    """get_links feeds PageRank, which scores the site's own graph, so an
    external edge leaking in would distort every score."""
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    internal_edges = store.get("sess_persist").get_links()
    assert internal_edges, "the home page links to its children"
    assert all("other.example" not in dst for _, dst in internal_edges)


def test_signatures_are_written_when_the_crawl_computes_them(tmp_path):
    store = SessionStore(session_dir=tmp_path)
    crawler = _crawler(max_pages=5000)

    _run(store, crawler)

    signatures = store.get("sess_persist").get_signatures()
    assert signatures, "a crawl above the exact-path threshold signs its pages"
    assert all(len(sig) == 512 for sig in signatures.values())


def test_no_signatures_are_written_for_a_small_crawl(tmp_path):
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    assert store.get("sess_persist").get_signatures() == {}


def test_the_summary_is_stored_alongside_the_rows(tmp_path):
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    summary = store.get("sess_persist").get_summary()
    assert summary["auditResult"]["executive_summary"]["health_score"]["score"] >= 0
    assert summary["url"] == "https://example.com/"


def test_the_history_listing_still_sees_the_audit(tmp_path):
    """Phase B's contract: historical-comparison-panel.tsx restores a past audit
    from this shape. Writing rows must not bypass it."""
    store = SessionStore(session_dir=tmp_path)

    _run(store, _crawler())

    listed = store.get_all_sessions()
    assert [s["id"] for s in listed] == ["sess_persist"]
    assert listed[0]["auditResult"]["pages"]


def test_the_returned_payload_is_unchanged_for_now(tmp_path):
    """Pins the transitional contract: the CLI writes its five report files from
    this dict, and the API still serves it."""
    store = SessionStore(session_dir=tmp_path)

    result = _run(store, _crawler())

    assert len(result["pages"]) == 4
    assert result["executive_summary"]
    assert result["recommendations"] is not None


def test_a_failed_page_is_still_written_as_a_row(tmp_path):
    """A page that could not be audited must appear in the table saying so, not
    go missing from the report."""
    store = SessionStore(session_dir=tmp_path)
    real_analyze = audit_service.page_pipeline.analyze_page

    def fail_one(payload):
        if payload.url.endswith("/p1"):
            raise AttributeError("boom")
        return real_analyze(payload)

    with patch.object(audit_service.page_pipeline, "analyze_page", side_effect=fail_one):
        _run(store, _crawler())

    db = store.get("sess_persist")
    assert db.get_page("https://example.com/p1") is not None
    issues, _ = db.get_issues(code="AUDIT_ERROR")
    assert [i["url"] for i in issues] == ["https://example.com/p1"]


def test_run_full_audit_passes_its_session_id_through(tmp_path):
    """The API generates the session id when it accepts the request and hands it
    back to the client. If the audit wrote its rows under a different id, every
    endpoint would look in the wrong database."""
    with patch.object(audit_service, "Crawler"), \
         patch.object(audit_service, "_build_audit_result", return_value={}) as mock_build:
        audit_service.run_full_audit("https://example.com/", "sess_from_api")

    assert mock_build.call_args.kwargs["session_id"] == "sess_from_api"
