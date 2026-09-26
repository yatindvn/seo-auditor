"""SessionStore indexes session files instead of holding audit results in RAM.

Keeping 50 full results in a list was viable only while audits were small. At
5000 pages one result is tens of megabytes, and every one of them was resident
for the life of the process and lost on restart.

The public contract is unchanged on purpose: routes.py and the dashboard's
historical-comparison panel read these exact shapes, and they are not part of
this change.
"""

import pytest

from app.models.session_model import SessionStore


def _audit_result(score=90.0, recommendations=None):
    return {
        "executive_summary": {
            "audit_date": "2026-09-26T00:00:00Z",
            "health_score": {"score": score},
        },
        "recommendations": recommendations if recommendations is not None else [],
        "pages": [{"url": "https://example.com/"}],
    }


@pytest.fixture
def store(tmp_path):
    return SessionStore(session_dir=tmp_path)


def _save(store, session_id, url="https://example.com/", **kwargs):
    store.save_session({
        "id": session_id,
        "url": url,
        "timestamp": "2026-09-26T00:00:00Z",
        "auditResult": _audit_result(**kwargs),
    })


def test_saving_a_session_creates_its_database_file(store, tmp_path):
    _save(store, "sess_1")

    assert (tmp_path / "sess_1.db").exists()


def test_sessions_survive_a_new_store_over_the_same_directory(store, tmp_path):
    """The point of moving to disk: a redeploy no longer erases history."""
    _save(store, "sess_1")

    reopened = SessionStore(session_dir=tmp_path)

    assert [s["id"] for s in reopened.get_all_sessions()] == ["sess_1"]


def test_listed_sessions_keep_the_shape_the_dashboard_reads(store):
    """historical-comparison-panel.tsx restores a past audit by reading
    session.auditResult directly. Dropping it would make clicking a past session
    silently do nothing."""
    _save(store, "sess_1", score=77.5)

    listed = store.get_all_sessions()[0]

    assert listed["id"] == "sess_1"
    assert listed["url"] == "https://example.com/"
    assert listed["timestamp"] == "2026-09-26T00:00:00Z"
    assert listed["auditResult"]["executive_summary"]["health_score"]["score"] == 77.5


def test_sessions_are_listed_newest_first(store):
    _save(store, "sess_1")
    _save(store, "sess_2")
    _save(store, "sess_3")

    assert [s["id"] for s in store.get_all_sessions()] == ["sess_3", "sess_2", "sess_1"]


def test_retention_keeps_the_newest_twenty_and_deletes_the_rest(store, tmp_path):
    for index in range(25):
        _save(store, f"sess_{index:03d}")

    remaining = sorted(path.stem for path in tmp_path.glob("*.db"))

    assert len(remaining) == 20
    assert remaining[0] == "sess_005", "the five oldest go, the newest stay"


def test_deleting_a_session_removes_its_file(store, tmp_path):
    _save(store, "sess_1")

    assert store.delete_session("sess_1") is True
    assert not (tmp_path / "sess_1.db").exists()
    assert store.delete_session("sess_1") is False


def test_history_comparison_reports_the_delta_against_the_previous_audit(store):
    _save(store, "sess_old", score=70.0, recommendations=[{"code": "NO_HTTPS"}])
    current = _audit_result(score=85.0, recommendations=[{"code": "MISSING_TITLE"}])
    _save(store, "sess_new", score=85.0, recommendations=[{"code": "MISSING_TITLE"}])

    comparison = store.get_history_comparison(current)

    assert comparison["previousScore"] == 70.0
    assert comparison["currentScore"] == 85.0
    assert comparison["scoreChange"] == 15.0
    assert comparison["newIssues"] == ["MISSING_TITLE"]
    assert comparison["resolvedIssues"] == ["NO_HTTPS"]


def test_history_comparison_is_none_with_nothing_to_compare_against(store):
    _save(store, "sess_only")

    assert store.get_history_comparison(_audit_result()) is None


def test_open_session_hands_back_a_writable_database(store):
    """What the pipeline will use once it writes rows as it crawls."""
    db = store.open_session("sess_live")
    db.add_pages([{"url": "https://example.com/", "issues": [], "meta": {}}])

    rows, total = store.get("sess_live").get_pages()

    assert total == 1
    assert rows[0]["url"] == "https://example.com/"


def test_get_returns_none_for_a_session_that_never_existed(store):
    assert store.get("sess_nope") is None
