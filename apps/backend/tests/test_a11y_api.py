"""Accessibility scans over HTTP."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import AccessibilityScan, Audit, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _audit(session, project_id, n, summary):
    t = datetime(2026, 10, 29, tzinfo=timezone.utc)
    audit = Audit(project_id=project_id, session_id=f"s{n}", start_url="https://a.com/", status="completed",
                  trigger="manual", started_at=t, finished_at=t, page_count=1, summary_json=summary)
    session.add(audit); session.flush()
    return audit.id


def test_lists_scans_with_status_and_version(client):
    violation = {"id": "region", "impact": "moderate", "help": "Landmarks", "help_url": None,
                 "wcag": ["wcag2a"], "nodes_count": 1, "targets": ["main"]}
    with get_session_factory().begin() as s:
        project = Project(name="a.com", domain="a.com"); s.add(project); s.flush()
        scanned = _audit(s, project.id, 1, {"accessibility_status": "scanned", "axe_version": "4.14.0"})
        s.add(AccessibilityScan(audit_id=scanned, url="https://a.com/", status="scanned", score=97,
                                critical=0, serious=0, moderate=1, minor=0, violations_json=[violation]))
        unavailable = _audit(s, project.id, 2, {"accessibility_status": "unavailable",
                                                "accessibility_unavailable_reason": "Playwright is not installed"})
        old = _audit(s, project.id, 3, {})
    body = client.get(f"/api/audits/{scanned}/accessibility").json()
    assert body == {"audit_id": scanned, "status": "scanned", "reason": None, "axe_version": "4.14.0", "items": [
        {"url": "https://a.com/", "status": "scanned", "error": None, "score": 97,
         "counts": {"critical": 0, "serious": 0, "moderate": 1, "minor": 0}, "violations": [violation]}]}
    assert client.get(f"/api/audits/{unavailable}/accessibility").json()["reason"] == "Playwright is not installed"
    assert client.get(f"/api/audits/{old}/accessibility").json()["status"] == "disabled"
    assert client.get("/api/audits/99999/accessibility").status_code == 404
