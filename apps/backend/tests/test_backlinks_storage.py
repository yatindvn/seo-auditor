"""Backlink tables and the opt-in weekly schedule."""

from fastapi.testclient import TestClient

from app.main import app


def test_schedule_is_off_by_default_and_opt_in():
    client = TestClient(app)
    project = client.post("/api/projects", json={"domain": "shop.com"}).json()
    assert project["backlink_schedule"] is None and project["last_backlink_refresh_at"] is None
    on = client.patch(f"/api/projects/{project['id']}", json={"backlink_schedule": "weekly"}).json()
    assert on["backlink_schedule"] == "weekly"
    assert client.patch(f"/api/projects/{project['id']}", json={"backlink_schedule": None}).json()["backlink_schedule"] is None
    assert client.patch(f"/api/projects/{project['id']}", json={"backlink_schedule": "hourly"}).status_code == 422
