"""Every audit lands in the central DB -- and a DB failure never fails the audit."""

from sqlalchemy import select

from app.crawler.crawler import Crawler, PageResult
from app.db import audit_store
from app.db.engine import get_session_factory
from app.db.models import Audit
from app.services import audit_service

HOME = "https://example.com/"


def _crawler():
    pages = {HOME: "<a href='/a'>a</a>", "https://example.com/a": "<p>a</p>"}
    crawler = Crawler(HOME, max_pages=5, max_depth=1, respect_robots=False)
    crawler.sitemap_urls = set()
    crawler._fetch = lambda url: PageResult(url=url, final_url=url, status_code=200,
                                            html=pages[url], headers={})
    return crawler


def _run(**kwargs):
    return audit_service._build_audit_result(
        HOME, _crawler(), progress_callback=None, event_callback=None,
        external_link_check_limit=0, **kwargs,
    )


def test_an_audit_is_stored_and_says_so():
    result = _run(session_id="sess_central")

    assert result["persisted"] is True
    with get_session_factory()() as s:
        audit = s.get(Audit, result["audit_id"])
        assert audit.session_id == "sess_central" and audit.page_count == 2
        assert audit.project_id == result["project_id"]


def test_the_trigger_is_recorded():
    result = _run(session_id="sess_sched", trigger="scheduled")
    with get_session_factory()() as s:
        assert s.get(Audit, result["audit_id"]).trigger == "scheduled"


def test_a_database_failure_does_not_fail_the_audit(monkeypatch):
    def broken(*args, **kwargs):
        raise RuntimeError("database is down")

    monkeypatch.setattr(audit_store, "record_audit", broken)
    result = _run(session_id="sess_down")

    assert result["persisted"] is False
    assert result["audit_id"] is None
    assert len(result["pages"]) == 2


def test_the_saved_session_summary_carries_the_audit_id(isolated_session_dir):
    result = _run(session_id="sess_summary")
    saved = isolated_session_dir.get_session("sess_summary")["auditResult"]
    assert saved["audit_id"] == result["audit_id"]
