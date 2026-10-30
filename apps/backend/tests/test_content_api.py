"""Content Explorer over HTTP (dry-run SERP and backlinks)."""

import pytest
from fastapi.testclient import TestClient

from app.config import config
from app.content_explorer import explore as explore_mod
from app.main import app
from app.providers.serp import ProviderError, ProviderSkipped


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "SERP_PROVIDER", "")
    monkeypatch.setattr(config, "GOOGLE_CSE_API_KEY", "")
    return TestClient(app)


def test_search_reopen_recent_and_csv(client):
    r = client.post("/api/content-explorer", json={"topic": "Rare Books"})
    assert r.status_code == 200
    body = r.json()
    assert body["topic"] == "rare books" and body["dry_run"] is True and len(body["results"]) == 10
    assert body["summary"]["median_words"] is not None
    again = client.get(f"/api/content-explorer/{body['id']}").json()
    assert again["cached"] is True and again["results"] == body["results"]
    assert client.get("/api/content-explorer/recent").json()["items"][0]["id"] == body["id"]
    csv = client.get(f"/api/content-explorer/{body['id']}/csv")
    lines = csv.text.splitlines()
    assert csv.headers["content-type"].startswith("text/csv") and lines[0].startswith("# DRY RUN")
    assert lines[1].startswith("position,url,domain,title") and len(lines) == 12
    assert client.get("/api/content-explorer/9999").status_code == 404
    assert client.get("/api/content-explorer/9999/csv").status_code == 404


def test_errors(client, monkeypatch):
    assert client.post("/api/content-explorer", json={"topic": "x"}).status_code == 422
    assert client.post("/api/content-explorer", json={"topic": "ok topic", "country": "USA"}).status_code == 422

    class Raiser:
        name = "dataforseo"

        def __init__(self, exc):
            self.exc = exc

        def search(self, query):
            raise self.exc

    monkeypatch.setattr(explore_mod.registry, "get_serp_provider", lambda: Raiser(ProviderSkipped("daily cap of 50 reached")))
    r = client.post("/api/content-explorer", json={"topic": "rare books"})
    assert r.status_code == 429 and "daily cap" in r.json()["detail"]
    monkeypatch.setattr(explore_mod.registry, "get_serp_provider", lambda: Raiser(ProviderError("DataForSEO 500")))
    assert client.post("/api/content-explorer", json={"topic": "rare books"}).status_code == 502
    assert client.get("/api/content-explorer/recent").json()["items"] == []
