"""Accessibility scans in the central DB."""

from sqlalchemy import select

from app.accessibility.model import A11yResult
from app.accessibility.scoring import summarize
from app.db.audit_store import record_audit
from app.db.engine import get_session_factory
from app.db.models import AccessibilityScan, Audit
from app.models.session_db import SessionDB


def test_record_audit_stores_scans_and_status(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": []}])
    scanned = summarize("https://a.com/", {"violations": [{"id": "region", "impact": "moderate", "help": "Landmarks",
                                                           "tags": ["wcag2a"], "nodes": [{"target": ["main"]}]}]})
    result = {"executive_summary": {"health_score": {"score": 70}}, "pages": [],
              "accessibility": [scanned.to_dict(), A11yResult(url="https://a.com/b", status="failed", error="boom").to_dict()],
              "accessibility_status": "scanned", "axe_version": "4.14.0"}
    factory = get_session_factory()
    audit_id, _ = record_audit(factory, db, result, session_id="s1", start_url="https://a.com/")
    with factory() as session:
        rows = session.scalars(select(AccessibilityScan).where(AccessibilityScan.audit_id == audit_id)
                               .order_by(AccessibilityScan.id)).all()
        assert [(r.url, r.status, r.score, r.moderate, r.critical, r.error) for r in rows] == [
            ("https://a.com/", "scanned", 97, 1, 0, None), ("https://a.com/b", "failed", None, 0, 0, "boom")]
        assert rows[0].violations_json[0]["id"] == "region"
        summary = session.get(Audit, audit_id).summary_json
        assert summary["accessibility_status"] == "scanned" and summary["axe_version"] == "4.14.0"
