"""Core Web Vitals rows in the central DB, and issues added to a page after
its row was written."""

from sqlalchemy import select

from app.db.audit_store import record_audit
from app.db.engine import get_session_factory
from app.db.models import Audit, WebVital
from app.models.session_db import SessionDB
from app.vitals.model import VitalsResult


def test_add_issues_appends_and_counts(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": [
        {"severity": "info", "code": "X", "message": "x"}]}])
    db.add_issues("https://a.com/", [{"severity": "warning", "code": "CWV_LCP_POOR", "message": "slow"}])
    db.add_issues("https://a.com/", [])
    codes = sorted(i["code"] for batch in db.iter_issues(100) for i in batch)
    assert codes == ["CWV_LCP_POOR", "X"]
    assert db.get_page("https://a.com/")["issue_count"] == 2


def test_record_audit_stores_vitals_rows_and_status(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": []}])
    rows = [VitalsResult(url="https://a.com/", source="psi", data_kind="field", lcp_ms=2300,
                         inp_ms=180, cls=0.05, rating="good").to_dict(),
            VitalsResult(url="https://a.com/b", source="not_measured", error="timeout").to_dict()]
    result = {"executive_summary": {"health_score": {"score": 80}}, "pages": [],
              "web_vitals": rows, "web_vitals_status": "measured"}
    factory = get_session_factory()
    audit_id, _ = record_audit(factory, db, result, session_id="s1", start_url="https://a.com/")
    with factory() as session:
        stored = session.scalars(select(WebVital).where(WebVital.audit_id == audit_id).order_by(WebVital.id)).all()
        audit = session.get(Audit, audit_id)
        assert [(v.url, v.source, v.lcp_ms, v.rating, v.error) for v in stored] == [
            ("https://a.com/", "psi", 2300.0, "good", None),
            ("https://a.com/b", "not_measured", None, None, "timeout")]
        assert stored[0].measured_at is not None
        assert audit.summary_json["web_vitals_status"] == "measured"
