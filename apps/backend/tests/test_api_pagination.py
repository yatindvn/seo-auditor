"""Endpoint shapes and boundaries.

/api/pages returned a bare array of every row and /api/audit/latest returned the
entire audit. At 5000 pages that is tens of megabytes in one response, more than
the dashboard can store or parse. Both paginate now, and the endpoints read from
the session's database rather than from a dict held in the process.

These are breaking changes for any direct API consumer, which is why the shapes
are pinned here.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import routes
from app.main import app
from app.models.session_model import SessionStore

SESSION_ID = "sess_api_test"
HOME = "https://example.com/"


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = SessionStore(session_dir=tmp_path)
    db = store.open_session(SESSION_ID)

    rows = []
    for index in range(10):
        section = "blog" if index < 4 else "shop"
        rows.append({
            "url": f"{HOME}{section}/{index}",
            "final_url": f"{HOME}{section}/{index}",
            "depth": index % 3,
            "status": 200 if index else 404,
            "title": f"Page {index}",
            "word_count": 100 + index,
            "meta": {"lang": "en"},
            "issues": (
                [{"severity": "critical", "code": "MISSING_TITLE", "message": "m"}]
                if index % 2 == 0 else []
            ),
        })
    db.add_pages(rows)
    db.add_links([(f"{HOME}blog/0", f"{HOME}shop/4", True)])
    db.set_summary({
        "url": HOME,
        "timestamp": "2026-09-26T00:00:00Z",
        "saved_at": 1,
        "auditResult": {
            "executive_summary": {"health_score": {"score": 71.0}, "pages_crawled": 10},
            "recommendations": [{"code": "MISSING_TITLE", "severity": "critical",
                                 "recommendation": "Add a title", "affected_pages": 5}],
            "issue_frequency": [],
            "site_wide_analysis": {"orphan_count": 0},
            "broken_links": [],
            "duplicates": {"duplicate_titles": {}},
            "near_duplicate_content": [
                {"url_a": f"{HOME}blog/{i}", "url_b": f"{HOME}shop/{i + 4}",
                 "similarity": 0.9} for i in range(4)
            ],
            "near_duplicate_mode": "exact",
            "redirects": {"redirect_chains": []},
            "pages": [{"url": f"{HOME}blog/0"}],
            "elapsed_seconds": 12.5,
            "degraded": False,
            "partial": False,
        },
    })

    monkeypatch.setattr(routes, "session_store", store)
    return TestClient(app)


# --- /api/pages -------------------------------------------------------------


def test_pages_returns_a_paginated_envelope(client):
    body = client.get(f"/api/pages?session_id={SESSION_ID}&limit=2").json()

    assert len(body["items"]) == 2
    assert body["total"] == 10
    assert body["offset"] == 0
    assert body["limit"] == 2


def test_the_total_counts_every_matching_row_not_the_page(client):
    """Without this the client cannot size its pagination."""
    body = client.get(f"/api/pages?session_id={SESSION_ID}&limit=3&offset=6").json()

    assert body["total"] == 10
    assert len(body["items"]) == 3


def test_filtering_narrows_both_rows_and_total(client):
    body = client.get(f"/api/pages?session_id={SESSION_ID}&filter=/blog/").json()

    assert body["total"] == 4
    assert all("/blog/" in item["url"] for item in body["items"])


def test_limit_above_the_maximum_is_rejected(client):
    """A limit of 5000 is the whole-payload problem returning by another name."""
    response = client.get(f"/api/pages?session_id={SESSION_ID}&limit=5000")

    assert response.status_code == 422


def test_an_unknown_sort_column_is_rejected_not_ignored(client):
    """The sort key reaches SQL as a column name. Rejecting it at the edge means
    the database layer's guard is a second line, not the only one."""
    response = client.get(f"/api/pages?session_id={SESSION_ID}&sort=url;DROP TABLE pages")

    assert response.status_code == 422


def test_sorting_and_order_are_honoured(client):
    body = client.get(
        f"/api/pages?session_id={SESSION_ID}&sort=word_count&order=desc&limit=1"
    ).json()

    assert body["items"][0]["word_count"] == 109


def test_pages_for_an_unknown_session_is_a_404(client):
    assert client.get("/api/pages?session_id=sess_nope").status_code == 404


# --- /api/issues ------------------------------------------------------------


def test_issues_paginate_and_filter_by_severity(client):
    body = client.get(
        f"/api/issues?session_id={SESSION_ID}&severity=critical&limit=2"
    ).json()

    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert all(item["severity"] == "critical" for item in body["items"])


# --- /api/duplicates --------------------------------------------------------


def test_duplicates_paginate_and_report_the_mode(client):
    """The mode says whether these similarities are exact or estimated, so it
    travels with them."""
    body = client.get(f"/api/duplicates?session_id={SESSION_ID}&limit=2").json()

    assert body["total"] == 4
    assert len(body["items"]) == 2
    assert body["mode"] == "exact"


# --- /api/audit/latest ------------------------------------------------------


def test_latest_returns_a_summary_without_page_rows(client):
    body = client.get(f"/api/audit/latest?session_id={SESSION_ID}").json()

    assert body["executive_summary"]["health_score"]["score"] == 71.0
    assert body["page_count"] == 10
    assert "pages" not in body, "page rows come from /api/pages now"
    assert "page_issues_detail" not in body
    assert "architecture" not in body


def test_latest_still_carries_what_the_dashboard_header_needs(client):
    body = client.get(f"/api/audit/latest?session_id={SESSION_ID}").json()

    assert body["elapsed_seconds"] == 12.5
    assert body["near_duplicate_mode"] == "exact"
    assert body["degraded"] is False
    assert body["partial"] is False
    assert body["recommendations"]


def test_latest_is_a_404_while_the_crawl_is_still_running(client, tmp_path):
    """The dashboard polls this from the moment it starts. A session whose
    database exists but has no summary yet is still in progress."""
    routes.session_store.open_session("sess_in_progress")

    assert client.get("/api/audit/latest?session_id=sess_in_progress").status_code == 404


# --- /api/architecture ------------------------------------------------------


def test_architecture_is_clustered_by_path_segment_by_default(client):
    body = client.get(f"/api/architecture?session_id={SESSION_ID}").json()

    assert body["clustered"] is True
    assert {node["id"] for node in body["nodes"]} == {"/blog", "/shop"}


def test_expanding_a_cluster_returns_its_pages(client):
    body = client.get(f"/api/architecture?session_id={SESSION_ID}&expand=/blog").json()

    assert body["clustered"] is False
    assert len(body["nodes"]) == 4
    assert all("/blog/" in node["url"] for node in body["nodes"])


# --- /api/page/{url} --------------------------------------------------------


def test_a_single_page_is_read_by_its_url(client):
    body = client.get(
        f"/api/page/{HOME}blog/1?session_id={SESSION_ID}"
    ).json()

    assert body["url"] == f"{HOME}blog/1"
    assert body["title"] == "Page 1"
