"""A finished audit is copied, completely and in batches, into the central DB."""

from sqlalchemy import func, select

from app.db import audit_store
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditIssue, AuditPage, Keyword, Project, RankCheck
from app.models.session_db import SessionDB


def _session(tmp_path, pages=3, name="s.db"):
    db = SessionDB(tmp_path / name)
    db.add_pages([
        {"url": f"https://example.com/p{i}", "final_url": f"https://example.com/p{i}",
         "status": 200, "depth": 1, "title": f"P{i}", "word_count": 100,
         "issues": [{"severity": "warning", "code": "MISSING_H1", "message": "no h1"}],
         "meta": {}}
        for i in range(pages)
    ])
    return db


def _result(partial=False, rankings=None):
    page = {"url": "https://example.com/p0",
            "keyword_analysis": {"rankings": rankings or []}}
    return {"executive_summary": {"health_score": {"score": 72.5}},
            "partial": partial, "pages": [page], "duplicates": {}}


def test_an_audit_and_all_its_rows_are_stored(tmp_path):
    factory = get_session_factory()
    audit_id, project_id = audit_store.record_audit(
        factory, _session(tmp_path), _result(), session_id="s1",
        start_url="https://www.example.com/",
    )

    with factory() as s:
        audit = s.get(Audit, audit_id)
        assert audit.status == "completed" and audit.trigger == "manual"
        assert audit.page_count == 3 and audit.health_score == 72.5
        assert audit.summary_json["executive_summary"]["health_score"]["score"] == 72.5
        assert "pages" not in audit.summary_json
        assert s.get(Project, project_id).domain == "example.com"
        assert s.scalar(select(func.count()).select_from(AuditPage)) == 3
        assert s.scalar(select(func.count()).select_from(AuditIssue)) == 3


def test_two_audits_of_one_site_share_its_project(tmp_path):
    factory = get_session_factory()
    _, first = audit_store.record_audit(factory, _session(tmp_path, name="a.db"), _result(),
                                        session_id="a", start_url="https://example.com/")
    _, second = audit_store.record_audit(factory, _session(tmp_path, name="b.db"), _result(),
                                         session_id="b", start_url="https://example.com/x")
    assert first == second


def test_a_partial_audit_is_marked_partial(tmp_path):
    factory = get_session_factory()
    audit_id, _ = audit_store.record_audit(factory, _session(tmp_path), _result(partial=True),
                                           session_id="p", start_url="https://example.com/")
    with factory() as s:
        assert s.get(Audit, audit_id).status == "partial"


def test_large_audits_stream_in_batches(tmp_path, monkeypatch):
    monkeypatch.setattr(audit_store, "BATCH_SIZE", 500)
    db = _session(tmp_path, pages=1200)
    batches = []
    original = db.iter_pages

    def spying(batch):
        for chunk in original(batch):
            batches.append(len(chunk))
            yield chunk

    db.iter_pages = spying
    audit_store.record_audit(get_session_factory(), db, _result(), session_id="big",
                             start_url="https://example.com/")

    assert batches == [500, 500, 200]


def test_rank_results_become_keywords_and_rank_checks(tmp_path):
    factory = get_session_factory()
    rankings = [
        {"keyword": "espresso", "position": 3, "status": "ranked", "note": None,
         "checked_at": "2026-10-25T10:00:00+00:00",
         "top_urls": ["https://a.com/", "https://b.com/", "https://example.com/p0"]},
        {"keyword": "grinder", "position": None, "status": "skipped",
         "note": "quota reached", "checked_at": "2026-10-25T10:00:00+00:00", "top_urls": []},
    ]
    audit_id, _ = audit_store.record_audit(factory, _session(tmp_path), _result(rankings=rankings),
                                           session_id="r", start_url="https://example.com/")
    audit_store.record_audit(factory, _session(tmp_path, name="r2.db"), _result(rankings=rankings),
                             session_id="r2", start_url="https://example.com/")

    with factory() as s:
        assert s.scalar(select(func.count()).select_from(Keyword)) == 2   # reused, not duplicated
        checks = s.scalars(select(RankCheck).where(RankCheck.audit_id == audit_id)).all()
        ranked = next(c for c in checks if c.position == 3)
        assert ranked.ranking_url == "https://example.com/p0"
        assert ranked.provider == "google_cse" and ranked.status == "ranked"
        assert any(c.status == "skipped" and c.note == "quota reached" for c in checks)
