"""Search Console over HTTP."""

from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import gsc as gsc_api
from app.config import config
from app.db.engine import get_session_factory
from app.db.models import Audit, AuditPage, GscDaily, GscInspection, GscPage, GscQuery, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _seed():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com", gsc_property="sc-domain:shop.com"); s.add(p); s.flush()
        start = date(2026, 9, 1)
        for i in range(56):   # previous 28 days, then the latest 28
            clicks = 10 if i < 28 else 20
            s.add(GscDaily(project_id=p.id, date=start + timedelta(days=i), clicks=clicks, impressions=100,
                           ctr=clicks / 100, position=10 if i < 28 else 5))
        t = datetime(2026, 10, 28, tzinfo=timezone.utc)
        for n, (url, clicks, impr) in enumerate([("https://shop.com/", 50, 900), ("https://shop.com/a", 9, 300),
                                                  ("https://shop.com/hidden", 2, 120)]):
            s.add(GscPage(project_id=p.id, url=url, clicks=clicks, impressions=impr, ctr=clicks / impr,
                          position=3 + n, synced_at=t))
        s.add(GscQuery(project_id=p.id, query="buy books", clicks=30, impressions=500, ctr=0.06, position=4, synced_at=t))
        audit = Audit(project_id=p.id, session_id="s1", start_url="https://shop.com/", status="completed",
                      trigger="manual", started_at=t, finished_at=t, page_count=2,
                      summary_json={"gsc_status": "inspected", "gsc_property": "sc-domain:shop.com", "gsc_dry_run": False})
        s.add(audit); s.flush()
        s.add_all([AuditPage(audit_id=audit.id, url="https://shop.com/", status=200),
                   AuditPage(audit_id=audit.id, url="https://shop.com/a", status=200),
                   GscInspection(audit_id=audit.id, url="https://shop.com/a", verdict="NEUTRAL",
                                 coverage_state="Crawled - currently not indexed")])
        return p.id, audit.id


def test_overview_kpis_compare_the_last_28_days(client, monkeypatch):
    monkeypatch.setattr(config, "GSC_DRY_RUN", True)
    pid, _ = _seed()
    body = client.get(f"/api/projects/{pid}/gsc").json()
    assert body["configured"] is True and body["property"] == "sc-domain:shop.com"
    assert body["kpis"] == {"clicks": 560, "impressions": 2800, "ctr": 0.2, "position": 5.0}
    assert body["previous_kpis"] == {"clicks": 280, "impressions": 2800, "ctr": 0.1, "position": 10.0}
    assert len(body["daily"]) == 56 and body["daily"][0]["date"] == "2026-09-01"


def test_overview_when_not_configured(client):
    pid, _ = _seed()
    body = client.get(f"/api/projects/{pid}/gsc").json()
    assert body["configured"] is False


def test_pages_and_queries_sort_and_page(client):
    pid, _ = _seed()
    pages = client.get(f"/api/projects/{pid}/gsc/pages?sort=impressions&limit=2").json()
    assert pages["total"] == 3 and [r["key"] for r in pages["items"]] == ["https://shop.com/", "https://shop.com/a"]
    by_position = client.get(f"/api/projects/{pid}/gsc/pages?sort=position").json()["items"]
    assert by_position[0]["position"] == 3       # best (lowest) position first
    assert client.get(f"/api/projects/{pid}/gsc/queries").json()["items"][0]["key"] == "buy books"
    assert client.get(f"/api/projects/{pid}/gsc/pages?sort=evil").status_code == 422


def test_audit_join(client):
    _, audit_id = _seed()
    body = client.get(f"/api/audits/{audit_id}/gsc").json()
    assert body["status"] == "inspected" and body["inspections"][0]["verdict"] == "NEUTRAL"
    assert [(p["url"], p["clicks"], p["inspection_verdict"]) for p in body["pages"]] == [
        ("https://shop.com/", 50, None), ("https://shop.com/a", 9, "NEUTRAL")]
    assert [p["url"] for p in body["not_crawled"]] == ["https://shop.com/hidden"]
    assert client.get("/api/audits/9999/gsc").status_code == 404


def test_sync_and_sites(client, monkeypatch):
    pid, _ = _seed()
    assert client.post(f"/api/projects/{pid}/gsc/sync").status_code == 409
    assert client.get("/api/gsc/sites").json() == {"configured": False, "dry_run": False, "client_email": None, "sites": []}
    monkeypatch.setattr(config, "GSC_DRY_RUN", True)
    result = client.post(f"/api/projects/{pid}/gsc/sync").json()
    assert result["status"] == "synced" and result["dry_run"] is True
    assert client.get("/api/gsc/sites").json()["dry_run"] is True
