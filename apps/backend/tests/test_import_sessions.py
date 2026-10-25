"""Existing audits are imported once, under their projects."""

from sqlalchemy import func, select

from app.db.engine import get_session_factory
from app.db.import_sessions import import_all
from app.db.models import Audit
from app.models.session_db import SessionDB


def _saved_session(directory, session_id, url, saved_at):
    db = SessionDB(directory / f"{session_id}.db")
    db.add_pages([{"url": url, "status": 200, "issues": [], "meta": {}}])
    db.set_summary({"url": url, "saved_at": saved_at,
                    "auditResult": {"executive_summary": {"health_score": {"score": 80}},
                                    "partial": False, "pages": []}})
    db.close()


def test_sessions_are_imported_once(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    _saved_session(sessions, "sess_1", "https://example.com/", 1_790_000_000_000_000_000)
    _saved_session(sessions, "sess_2", "https://other.org/", 1_790_000_100_000_000_000)
    (sessions / "page_cache").mkdir()          # not a session: must be ignored
    (sessions / "central").mkdir()             # the central DB's directory: ignored too
    factory = get_session_factory()

    assert import_all(sessions, factory) == {"imported": 2, "skipped": 0, "failed": 0}
    assert import_all(sessions, factory) == {"imported": 0, "skipped": 2, "failed": 0}

    with factory() as s:
        audits = s.scalars(select(Audit).order_by(Audit.session_id)).all()
        assert [a.trigger for a in audits] == ["import", "import"]
        assert audits[0].started_at.year == 2026
        assert s.scalar(select(func.count()).select_from(Audit)) == 2


def test_an_unfinished_session_is_skipped_not_failed(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    SessionDB(sessions / "sess_running.db").close()       # no summary yet

    assert import_all(sessions, get_session_factory()) == {"imported": 0, "skipped": 1, "failed": 0}
