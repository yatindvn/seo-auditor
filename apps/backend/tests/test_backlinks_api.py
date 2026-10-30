"""Backlinks over HTTP."""

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.backlinks.snapshot import refresh_project
from app.backlinks.provider import DryRunBacklinks
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditPage, BacklinkSnapshot, Competitor, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _project():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com"); s.add(p); s.flush()
        s.add_all([Competitor(project_id=p.id, domain="rival.com"), Competitor(project_id=p.id, domain="other.com")])
        return p.id


def test_empty_then_refreshed_overview(client):
    pid = _project()
    empty = client.get(f"/api/projects/{pid}/backlinks").json()
    assert empty["latest"] is None and empty["history"] == [] and empty["dry_run_provider"] is True
    assert client.post(f"/api/projects/{pid}/backlinks/refresh").json()["status"] == "refreshed"
    refresh_project(pid, DryRunBacklinks(), today=date(2026, 11, 6))
    body = client.get(f"/api/projects/{pid}/backlinks").json()
    assert body["latest"]["dry_run"] is True and body["previous"] is not None
    assert {"taken_at", "authority", "backlinks", "referring_domains", "broken_backlinks"} <= set(body["latest"])
    sources = [h["source"] for h in body["history"]]
    assert sources.count("history") == 12 and sources.count("snapshot") == 2
    assert [h["date"] for h in body["history"]] == sorted(h["date"] for h in body["history"])


def test_lists_and_crawled_status(client):
    pid = _project()
    client.post(f"/api/projects/{pid}/backlinks/refresh")
    domains = client.get(f"/api/projects/{pid}/backlinks/referring-domains?limit=5").json()
    assert domains["total"] == 30 and len(domains["items"]) == 5
    assert domains["items"][0]["rank"] >= domains["items"][1]["rank"]
    t = datetime(2026, 10, 30, tzinfo=timezone.utc)
    with get_session_factory().begin() as s:
        audit = Audit(project_id=pid, session_id="s1", start_url="https://shop.com/", status="completed",
                      trigger="manual", started_at=t, finished_at=t)
        s.add(audit); s.flush()
        s.add(AuditPage(audit_id=audit.id, url="https://shop.com/old-page-0", status=404))
    broken = client.get(f"/api/projects/{pid}/backlinks/links?kind=broken").json()
    assert broken["total"] == 10
    first = [i for i in broken["items"] if i["url_to"] == "https://shop.com/old-page-0"][0]
    assert first["crawled_status"] == 404
    assert client.get(f"/api/projects/{pid}/backlinks/links?kind=bogus").status_code == 422


def test_gap(client):
    pid = _project()
    body = client.post(f"/api/projects/{pid}/backlinks/gap", json={}).json()
    assert body["competitors"] == ["rival.com", "other.com"] and body["rows"] and body["dry_run"] is True
    assert client.post(f"/api/projects/{pid}/backlinks/gap", json={"competitors": []}).status_code == 400


def test_404s(client):
    assert client.get("/api/projects/999/backlinks").status_code == 404
    assert client.post("/api/projects/999/backlinks/refresh").status_code == 404
