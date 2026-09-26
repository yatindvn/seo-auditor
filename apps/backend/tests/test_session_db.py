"""Per-session SQLite: the store that lets a 5000-page audit exist at all.

Holding every page in a dict cost ~500 MB of retained HTML plus the assembled
result, and the whole thing was returned by one endpoint. Pages now land on disk
as they are analysed and are read back a page at a time.
"""

import pytest

from app.models.session_db import SessionDB


@pytest.fixture
def db(tmp_path):
    database = SessionDB(tmp_path / "sess_test.db")
    yield database
    database.close()


def _page_row(url, **overrides):
    row = {
        "url": url, "final_url": url, "depth": 1, "status": 200,
        "response_time_ms": 12.5, "content_type": "text/html",
        "title": "T", "meta_description": "D", "h1": "H", "canonical": url,
        "word_count": 100, "char_count": 500,
        "internal_links_count": 3, "external_links_count": 1,
        "images_count": 2, "missing_alt_count": 0,
        "meta_robots": None, "lang": "en", "error": None,
        "meta": {"open_graph": {"og:title": "T"}},
        "issues": [],
    }
    row.update(overrides)
    return row


def test_pages_round_trip_with_meta_deserialised(db):
    db.add_pages([_page_row("https://example.com/")])

    rows, total = db.get_pages()

    assert total == 1
    assert rows[0]["url"] == "https://example.com/"
    assert rows[0]["meta"]["open_graph"] == {"og:title": "T"}, (
        "meta must come back as a dict, not the JSON string it is stored as"
    )


def test_pagination_returns_the_slice_and_the_unpaginated_total(db):
    db.add_pages([_page_row(f"https://example.com/{i}", depth=i) for i in range(10)])

    rows, total = db.get_pages(offset=4, limit=3, sort="depth")

    assert total == 10, "total counts every matching row, not just this page"
    assert [r["depth"] for r in rows] == [4, 5, 6]


def test_offset_past_the_end_returns_empty_not_an_error(db):
    db.add_pages([_page_row("https://example.com/")])

    rows, total = db.get_pages(offset=500, limit=50)

    assert rows == []
    assert total == 1


def test_filtering_narrows_the_total_as_well_as_the_rows(db):
    """A total that ignored the filter would make the client paginate through
    pages that are not there."""
    db.add_pages([_page_row(f"https://example.com/blog/{i}") for i in range(3)])
    db.add_pages([_page_row(f"https://example.com/shop/{i}") for i in range(7)])

    rows, total = db.get_pages(filter_text="/blog/", limit=50)

    assert total == 3
    assert len(rows) == 3


def test_issues_are_stored_per_page_and_filterable_by_severity(db):
    db.add_pages([
        _page_row("https://example.com/a", issues=[
            {"severity": "critical", "code": "MISSING_TITLE", "message": "m"},
            {"severity": "warning", "code": "THIN_CONTENT", "message": "m"},
        ]),
    ])

    critical, total = db.get_issues(severity="critical")

    assert total == 1
    assert critical[0]["code"] == "MISSING_TITLE"


def test_issue_count_is_stored_on_the_page_row(db):
    """So the pages table can sort and filter by it without joining."""
    db.add_pages([
        _page_row("https://example.com/a", issues=[
            {"severity": "critical", "code": "X", "message": "m"},
            {"severity": "warning", "code": "Y", "message": "m"},
        ]),
        _page_row("https://example.com/b"),
    ])

    with_issues, total = db.get_pages(has_issues=True)

    assert total == 1
    assert with_issues[0]["url"] == "https://example.com/a"
    assert with_issues[0]["issue_count"] == 2


def test_summary_round_trips(db):
    db.set_summary({"health_score": {"score": 81.5}})

    assert db.get_summary()["health_score"]["score"] == 81.5


def test_summary_is_replaced_not_appended(db):
    """One audit has one summary. A second write is a correction, not a second
    row -- get_summary has no way to choose between two."""
    db.set_summary({"health_score": {"score": 1}})
    db.set_summary({"health_score": {"score": 2}})

    assert db.get_summary()["health_score"]["score"] == 2


def test_missing_summary_is_none_not_an_error(db):
    """The dashboard polls while the crawl is still running."""
    assert db.get_summary() is None


def test_links_and_signatures_round_trip(db):
    db.add_links([
        ("https://example.com/", "https://example.com/a", True),
        ("https://example.com/", "https://other.example/x", False),
    ])
    db.add_signature("https://example.com/", b"\x00" * 512)

    assert db.get_links() == [("https://example.com/", "https://example.com/a")], (
        "get_links feeds PageRank, which is a graph of internal links only"
    )
    assert db.get_signatures()["https://example.com/"] == b"\x00" * 512


def test_get_page_returns_one_row_by_url(db):
    db.add_pages([_page_row("https://example.com/a"), _page_row("https://example.com/b")])

    assert db.get_page("https://example.com/b")["url"] == "https://example.com/b"
    assert db.get_page("https://example.com/missing") is None


def test_re_adding_a_url_replaces_its_row(db):
    """A retried page must not produce two rows; url is the primary key."""
    db.add_pages([_page_row("https://example.com/", title="First")])
    db.add_pages([_page_row("https://example.com/", title="Second")])

    rows, total = db.get_pages()

    assert total == 1
    assert rows[0]["title"] == "Second"


def test_sort_column_is_whitelisted_not_interpolated(db):
    """The sort key reaches SQL. It must be validated against a fixed set, or it
    is an injection point on a public endpoint."""
    db.add_pages([_page_row("https://example.com/")])

    with pytest.raises(ValueError):
        db.get_pages(sort="url; DROP TABLE pages")


def test_a_reopened_database_still_has_its_rows(tmp_path):
    """The point of moving to disk: a restart no longer erases the audit."""
    path = tmp_path / "sess_reopen.db"
    first = SessionDB(path)
    first.add_pages([_page_row("https://example.com/")])
    first.set_summary({"health_score": {"score": 50}})
    first.close()

    second = SessionDB(path)
    try:
        rows, total = second.get_pages()
        assert total == 1
        assert second.get_summary()["health_score"]["score"] == 50
    finally:
        second.close()
