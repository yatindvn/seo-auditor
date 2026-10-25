"""Keywords, competitors, history and manual runs over HTTP."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import Keyword, RankCheck, utcnow
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"domain": "example.com"}).json()


def test_bulk_add_keywords_skips_duplicates_and_turns_on_daily_tracking(client, project):
    body = {"keywords": [{"phrase": "espresso"}, {"phrase": "Espresso "},
                         {"phrase": "espresso", "country": "GB", "device": "mobile"}]}
    added = client.post(f"/api/projects/{project['id']}/keywords", json=body).json()
    assert added == {"created": 2, "skipped": 1}
    assert client.get("/api/projects").json()["items"][0]["rank_schedule"] == "daily"

    listed = client.get(f"/api/projects/{project['id']}/keywords").json()["items"]
    assert {(k["phrase"], k["country"], k["device"]) for k in listed} == {
        ("espresso", "US", "desktop"), ("espresso", "GB", "mobile"),
    }


def test_keyword_list_shows_latest_position_and_change(client, project):
    client.post(f"/api/projects/{project['id']}/keywords", json={"keywords": [{"phrase": "espresso"}]})
    with get_session_factory().begin() as s:
        kw = s.query(Keyword).one()
        s.add_all([
            RankCheck(keyword_id=kw.id, checked_at=utcnow() - timedelta(days=1), provider="t",
                      status="ranked", position=4),
            RankCheck(keyword_id=kw.id, checked_at=utcnow(), provider="t", status="ranked",
                      position=9, ranking_url="https://example.com/e"),
        ])
    item = client.get(f"/api/projects/{project['id']}/keywords").json()["items"][0]
    assert item["latest"]["position"] == 9 and item["change"] == -5


def test_history_is_oldest_first_within_the_window(client, project):
    client.post(f"/api/projects/{project['id']}/keywords", json={"keywords": [{"phrase": "espresso"}]})
    with get_session_factory().begin() as s:
        kw = s.query(Keyword).one()
        for days, pos in ((100, 1), (2, 4), (1, 9)):
            s.add(RankCheck(keyword_id=kw.id, checked_at=utcnow() - timedelta(days=days),
                            provider="t", status="ranked", position=pos,
                            competitor_positions_json={"rival.org": 3}))
        kw_id = kw.id
    history = client.get(f"/api/keywords/{kw_id}/history?days=90").json()["items"]
    assert [h["position"] for h in history] == [4, 9]
    assert history[0]["competitor_positions"] == {"rival.org": 3}


def test_disable_and_delete_keyword(client, project):
    client.post(f"/api/projects/{project['id']}/keywords", json={"keywords": [{"phrase": "espresso"}]})
    kw_id = client.get(f"/api/projects/{project['id']}/keywords").json()["items"][0]["id"]
    assert client.patch(f"/api/keywords/{kw_id}", json={"enabled": False}).json()["enabled"] is False
    assert client.delete(f"/api/keywords/{kw_id}").status_code == 204
    assert client.get(f"/api/projects/{project['id']}/keywords").json()["items"] == []


def test_competitors(client, project):
    pid = project["id"]
    created = client.post(f"/api/projects/{pid}/competitors", json={"domain": "https://www.Rival.org/x"})
    assert created.status_code == 201 and created.json()["domain"] == "rival.org"
    assert client.post(f"/api/projects/{pid}/competitors", json={"domain": "rival.org"}).status_code == 409
    listed = client.get(f"/api/projects/{pid}/competitors").json()["items"]
    assert client.delete(f"/api/projects/{pid}/competitors/{listed[0]['id']}").status_code == 204


def test_manual_run_defaults_to_an_unsaved_preview(client, project):
    pid = project["id"]
    client.post(f"/api/projects/{pid}/keywords", json={"keywords": [{"phrase": "espresso"}]})
    preview = client.post(f"/api/projects/{pid}/rank-checks/run").json()
    assert preview["dry_run"] is True and preview["results"][0]["phrase"] == "espresso"
    with get_session_factory()() as s:
        assert s.query(RankCheck).count() == 0


def test_a_live_run_needs_a_live_provider(client, project):
    assert client.post(f"/api/projects/{project['id']}/rank-checks/run?dry_run=false").status_code == 409


def test_alert_settings_and_schedule_via_project_patch(client, project):
    updated = client.patch(f"/api/projects/{project['id']}",
                           json={"rank_schedule": "daily", "alert_settings": {"drop_threshold": 5}}).json()
    assert updated["rank_schedule"] == "daily" and updated["alert_settings"] == {"drop_threshold": 5}
