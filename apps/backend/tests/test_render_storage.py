"""Raw-vs-rendered comparisons in the central DB."""

from sqlalchemy import select

from app.db.audit_store import record_audit
from app.db.engine import get_session_factory
from app.db.models import Audit, RenderedPage
from app.models.session_db import SessionDB
from app.rendering.model import RenderComparison


def test_record_audit_stores_comparisons_and_status(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": []}])
    rows = [RenderComparison(url="https://a.com/", render_ms=900, raw_word_count=40, rendered_word_count=900,
                             changes={"title": {"raw": "Loading", "rendered": "Shop"}},
                             js_only_links=["https://a.com/x"], js_only_links_count=1).to_dict(),
            RenderComparison(url="https://a.com/b", status="failed", error="Timeout").to_dict()]
    result = {"executive_summary": {"health_score": {"score": 70}}, "pages": [],
              "rendering": rows, "render_status": "rendered"}
    factory = get_session_factory()
    audit_id, _ = record_audit(factory, db, result, session_id="s1", start_url="https://a.com/")
    with factory() as session:
        stored = session.scalars(select(RenderedPage).where(RenderedPage.audit_id == audit_id)
                                 .order_by(RenderedPage.id)).all()
        assert [(r.url, r.status, r.rendered_word_count, r.changes_json, r.js_only_links_count, r.error) for r in stored] == [
            ("https://a.com/", "rendered", 900, {"title": {"raw": "Loading", "rendered": "Shop"}}, 1, None),
            ("https://a.com/b", "failed", None, {}, 0, "Timeout")]
        assert stored[0].js_only_links_json == ["https://a.com/x"]
        assert session.get(Audit, audit_id).summary_json["render_status"] == "rendered"
