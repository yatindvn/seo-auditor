"""Projects, their audit history, and diffs over HTTP."""

import pytest
from fastapi.testclient import TestClient

from app.db import engine as db_engine
from app.main import app
from tests.test_audit_diff import two_runs  # noqa: F401  (fixture)


@pytest.fixture
def client():
    return TestClient(app)


def test_create_list_and_update_projects(client):
    created = client.post("/api/projects", json={"domain": "https://www.Shop.com/",
                                                  "audit_schedule": "weekly",
                                                  "audit_options": {"max_pages": 50}})
    assert created.status_code == 201
    project = created.json()
    assert project["domain"] == "shop.com" and project["audit_schedule"] == "weekly"

    assert client.post("/api/projects", json={"domain": "shop.com"}).status_code == 409

    renamed = client.patch(f"/api/projects/{project['id']}", json={"name": "My shop"})
    assert renamed.json()["name"] == "My shop"

    listed = client.get("/api/projects").json()
    assert [p["domain"] for p in listed["items"]] == ["shop.com"]
    assert listed["items"][0]["audit_count"] == 0 and listed["items"][0]["latest_audit"] is None


def test_a_bad_schedule_is_rejected(client):
    assert client.post("/api/projects", json={"domain": "a.com", "audit_schedule": "hourly"}).status_code == 422


def test_project_audits_newest_first(client, two_runs):  # noqa: F811
    _, old, new, _ = two_runs
    project_id = client.get("/api/projects").json()["items"][0]["id"]

    audits = client.get(f"/api/projects/{project_id}/audits").json()
    assert [a["id"] for a in audits["items"]] == [new, old]
    assert audits["total"] == 2


def test_diff_defaults_to_the_previous_audit(client, two_runs):  # noqa: F811
    _, old, new, _ = two_runs
    diff = client.get(f"/api/audits/{new}/diff").json()
    assert diff["old_audit_id"] == old and diff["issues"]["new_count"] == 2


def test_diff_errors(client, two_runs):  # noqa: F811
    _, old, new, foreign = two_runs
    assert client.get(f"/api/audits/{old}/diff").status_code == 404           # no earlier audit
    assert client.get(f"/api/audits/{new}/diff?against={foreign}").status_code == 400
    assert client.get("/api/audits/999999/diff").status_code == 404


def test_a_database_outage_is_a_503(client, monkeypatch):
    def down(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(db_engine, "get_session_factory", down)
    assert client.get("/api/projects").status_code == 503


def test_timestamps_are_explicitly_utc(client, two_runs):  # noqa: F811
    """SQLite hands back naive datetimes; a client reading one as local time
    would place every audit hours off."""
    project = client.get("/api/projects").json()["items"][0]
    audits = client.get(f"/api/projects/{project['id']}/audits").json()["items"]

    assert project["latest_audit"]["finished_at"].endswith("+00:00")
    assert all(a["started_at"].endswith("+00:00") and a["finished_at"].endswith("+00:00") for a in audits)
