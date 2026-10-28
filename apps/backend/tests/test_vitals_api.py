"""Core Web Vitals over HTTP: one audit's pages, and the homepage trend."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import Audit, Project, WebVital
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _seed():
    t0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
    with get_session_factory().begin() as s:
        project = Project(name="a.com", domain="a.com")
        s.add(project); s.flush()
        ids = []
        for i, lcp in enumerate([5000, None, 2000]):
            audit = Audit(project_id=project.id, session_id=f"s{i}", start_url="https://a.com/",
                          status="completed", trigger="manual", started_at=t0 + timedelta(days=i),
                          finished_at=t0 + timedelta(days=i), page_count=1,
                          summary_json={"web_vitals_status": "measured"})
            s.add(audit); s.flush(); ids.append(audit.id)
            if i == 1:
                s.add(WebVital(audit_id=audit.id, url="https://a.com/", strategy="mobile",
                               source="not_measured", error="timeout"))
                continue
            s.add(WebVital(audit_id=audit.id, url="https://a.com/", strategy="mobile", source="psi",
                           data_kind="lab", lcp_ms=lcp, cls=0.05, tbt_ms=100, performance_score=70 + i,
                           rating="poor" if lcp > 4000 else "good"))
            s.add(WebVital(audit_id=audit.id, url="https://a.com/b", strategy="mobile", source="psi",
                           data_kind="lab", lcp_ms=1000, rating="good"))
        return project.id, ids


def test_audit_vitals_lists_rows_with_metric_ratings(client):
    _, ids = _seed()
    body = client.get(f"/api/audits/{ids[0]}/vitals").json()
    assert body["audit_id"] == ids[0] and body["status"] == "measured"
    assert [r["url"] for r in body["items"]] == ["https://a.com/", "https://a.com/b"]
    assert body["items"][0]["metric_ratings"]["lcp_ms"] == "poor"
    assert body["items"][0]["measured_at"].endswith("+00:00")
    assert client.get("/api/audits/99999/vitals").status_code == 404


def test_trend_is_the_homepage_oldest_first_skipping_failures(client):
    project_id, ids = _seed()
    body = client.get(f"/api/projects/{project_id}/vitals/trend").json()
    assert body["url"] == "https://a.com/"
    assert [p["audit_id"] for p in body["points"]] == [ids[0], ids[2]]
    assert [p["lcp_ms"] for p in body["points"]] == [5000.0, 2000.0]
    assert body["points"][1]["metric_ratings"]["lcp_ms"] == "good"
    assert client.get("/api/projects/99999/vitals/trend").status_code == 404


def test_trend_for_a_project_without_measurements(client):
    with get_session_factory().begin() as s:
        project = Project(name="b.com", domain="b.com"); s.add(project); s.flush(); pid = project.id
    assert client.get(f"/api/projects/{pid}/vitals/trend").json() == {"url": None, "points": []}
