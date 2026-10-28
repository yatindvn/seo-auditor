"""Custom rules over HTTP."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.api import rules as rules_api
from app.crawler.crawler import PageResult
from app.db.engine import get_session_factory
from app.db.models import Audit, Project
from app.main import app

TITLE = {"type": "field", "field": "title", "op": "contains", "value": "| Brand"}


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project_id():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com"); s.add(p); s.flush()
        return p.id


def test_crud(client, project_id):
    created = client.post(f"/api/projects/{project_id}/rules", json={"name": "Brand in title", "check": TITLE,
                                                                     "url_pattern": "/blog/*"})
    assert created.status_code == 201
    rule = created.json()
    assert rule["description"] == "Title contains '| Brand'" and rule["enabled"] is True and rule["severity"] == "warning"
    assert client.get(f"/api/projects/{project_id}/rules").json()["items"][0]["id"] == rule["id"]

    patched = client.patch(f"/api/rules/{rule['id']}", json={"enabled": False, "severity": "critical"}).json()
    assert patched["enabled"] is False and patched["severity"] == "critical" and patched["check"] == TITLE

    assert client.patch(f"/api/rules/{rule['id']}", json={"check": {"type": "selector", "selector": "div[", "op": "exists"}}).status_code == 422
    assert client.delete(f"/api/rules/{rule['id']}").status_code == 204
    assert client.get(f"/api/projects/{project_id}/rules").json()["items"] == []


def test_validation_errors_are_readable(client, project_id):
    bad = client.post(f"/api/projects/{project_id}/rules",
                      json={"name": "x", "check": {"type": "field", "field": "word_count", "op": "contains", "value": "a"}})
    assert bad.status_code == 422 and "not valid for word_count" in bad.json()["detail"]


def test_limits_and_404s(client, project_id, monkeypatch):
    monkeypatch.setattr(rules_api, "MAX_RULES", 1)
    assert client.post(f"/api/projects/{project_id}/rules", json={"name": "a", "check": TITLE}).status_code == 201
    assert client.post(f"/api/projects/{project_id}/rules", json={"name": "b", "check": TITLE}).status_code == 409
    assert client.post("/api/projects/9999/rules", json={"name": "a", "check": TITLE}).status_code == 404
    assert client.patch("/api/rules/9999", json={"enabled": False}).status_code == 404
    assert client.delete("/api/rules/9999").status_code == 404


def _page(html, status=200):
    return PageResult(url="https://shop.com/p", final_url="https://shop.com/p", status_code=status,
                      html=html, headers={"Content-Type": "text/html"}, content_type="text/html", response_time_ms=120)


def test_rule_test_endpoint(client, project_id, monkeypatch):
    monkeypatch.setattr(rules_api, "fetch_page", lambda url: _page("<html><head><title>Shop</title></head><body></body></html>"))
    body = client.post(f"/api/projects/{project_id}/rules/test",
                       json={"url": "https://www.shop.com/p", "rule": {"name": "Brand", "check": TITLE}}).json()
    assert body["applies"] is True and body["passed"] is False and body["observed"] == "Shop"
    assert body["issue"]["message"] == "Brand: Title contains '| Brand'"

    scoped = client.post(f"/api/projects/{project_id}/rules/test",
                         json={"url": "https://shop.com/p", "rule": {"name": "B", "check": TITLE, "url_pattern": "/blog/*"}}).json()
    assert scoped["applies"] is False and scoped["passed"] is None


def test_rule_test_guards(client, project_id, monkeypatch):
    rule = {"name": "Brand", "check": TITLE}
    assert client.post(f"/api/projects/{project_id}/rules/test", json={"url": "https://evil.com/", "rule": rule}).status_code == 400
    monkeypatch.setattr(rules_api, "fetch_page", lambda url: PageResult(url=url, final_url=url, status_code=None, error="timeout"))
    failed = client.post(f"/api/projects/{project_id}/rules/test", json={"url": "https://shop.com/", "rule": rule})
    assert failed.status_code == 502 and "timeout" in failed.json()["detail"]


def test_audit_custom_rules_summary(client, project_id):
    t = datetime(2026, 10, 29, tzinfo=timezone.utc)
    summary = [{"rule_id": 1, "name": "r", "severity": "warning", "description": "Has h1",
                "pages_checked": 3, "pages_failed": 1, "example_urls": ["https://shop.com/x"]}]
    with get_session_factory().begin() as s:
        with_rules = Audit(project_id=project_id, session_id="s1", start_url="https://shop.com/", status="completed",
                           trigger="manual", started_at=t, finished_at=t, summary_json={"custom_rules": summary})
        old = Audit(project_id=project_id, session_id="s2", start_url="https://shop.com/", status="completed",
                    trigger="manual", started_at=t, finished_at=t, summary_json={})
        s.add_all([with_rules, old]); s.flush()
        ids = with_rules.id, old.id
    assert client.get(f"/api/audits/{ids[0]}/custom-rules").json() == {"audit_id": ids[0], "items": summary}
    assert client.get(f"/api/audits/{ids[1]}/custom-rules").json()["items"] == []
    assert client.get("/api/audits/9999/custom-rules").status_code == 404
