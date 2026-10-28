"""Raw-vs-rendered comparisons over HTTP."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import Audit, Project, RenderedPage
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _audit(session, project_id, n, summary):
    t = datetime(2026, 10, 28, tzinfo=timezone.utc)
    audit = Audit(project_id=project_id, session_id=f"s{n}", start_url="https://a.com/", status="completed",
                  trigger="manual", started_at=t, finished_at=t, page_count=1, summary_json=summary)
    session.add(audit); session.flush()
    return audit.id


def test_lists_rows_with_status(client):
    with get_session_factory().begin() as s:
        project = Project(name="a.com", domain="a.com"); s.add(project); s.flush()
        rendered = _audit(s, project.id, 1, {"render_status": "rendered"})
        s.add(RenderedPage(audit_id=rendered, url="https://a.com/", status="rendered", render_ms=900,
                           raw_word_count=40, rendered_word_count=900,
                           changes_json={"title": {"raw": "Loading", "rendered": "Shop"}},
                           js_only_links_json=["https://a.com/x"], js_only_links_count=1))
        unavailable = _audit(s, project.id, 2, {"render_status": "unavailable",
                                                "render_unavailable_reason": "Playwright is not installed"})
        old = _audit(s, project.id, 3, {})
    body = client.get(f"/api/audits/{rendered}/rendering").json()
    assert body["status"] == "rendered" and body["reason"] is None
    assert body["items"] == [{"url": "https://a.com/", "status": "rendered", "error": None, "render_ms": 900.0,
                              "raw_word_count": 40, "rendered_word_count": 900,
                              "changes": {"title": {"raw": "Loading", "rendered": "Shop"}},
                              "js_only_links": ["https://a.com/x"], "js_only_links_count": 1}]
    assert client.get(f"/api/audits/{unavailable}/rendering").json() == {
        "audit_id": unavailable, "status": "unavailable", "reason": "Playwright is not installed", "items": []}
    assert client.get(f"/api/audits/{old}/rendering").json()["status"] == "disabled"
    assert client.get("/api/audits/99999/rendering").status_code == 404
