"""Explorer and content gap over HTTP, in dry run (no keys configured)."""

import pytest
from fastapi.testclient import TestClient

from app.keywords import explorer, gap
from app.main import app
from app.providers.serp import ProviderError, ProviderSkipped
from app.seo import keyword_suggestions


@pytest.fixture(autouse=True)
def no_real_autocomplete(monkeypatch):
    monkeypatch.setattr(keyword_suggestions, "_autocomplete_suggestions",
                        lambda seed: [f"{seed} price", f"best {seed}"])


@pytest.fixture
def client():
    return TestClient(app)


def test_explore_returns_a_labelled_dry_run(client):
    body = client.post("/api/keywords/explore", json={"seed": "Espresso Machine"}).json()
    assert body["dry_run"] is True and body["seed"] == "espresso machine"
    assert {k["source"] for k in body["keywords"]} == {"seed", "autocomplete"}
    assert all("traffic_potential_estimate" in k for k in body["keywords"])


def test_explore_csv_is_labelled_and_complete(client):
    response = client.get("/api/keywords/explore.csv", params={"seed": "espresso"})
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.splitlines()
    assert lines[0] == "# DRY RUN — made-up data"
    assert lines[1].split(",")[:3] == ["keyword", "source", "search_volume"]
    assert len(lines) == 2 + 3


def test_explore_validation_and_cap(client, monkeypatch):
    assert client.post("/api/keywords/explore", json={"seed": "  "}).status_code == 400

    def capped(*a, **k):
        raise ProviderSkipped("daily cap of 20 dataforseo_labs calls reached")

    monkeypatch.setattr(explorer, "explore", capped)
    response = client.post("/api/keywords/explore", json={"seed": "x"})
    assert response.status_code == 429 and "cap" in response.json()["detail"]


@pytest.fixture
def project(client):
    pid = client.post("/api/projects", json={"domain": "example.com"}).json()["id"]
    client.post(f"/api/projects/{pid}/competitors", json={"domain": "rival.org"})
    return pid


def test_content_gap_defaults_to_project_competitors(client, project):
    body = client.post(f"/api/projects/{project}/content-gap", json={}).json()
    assert body["dry_run"] is True and body["competitors"] == ["rival.org"]
    assert body["rows"] and body["total_gaps"] == len(body["rows"])


def test_content_gap_csv(client, project):
    response = client.get(f"/api/projects/{project}/content-gap.csv")
    lines = response.text.splitlines()
    assert lines[0] == "# DRY RUN — made-up data"
    assert lines[1] == "keyword,search_volume,difficulty,opportunity,best_competitor_position,rival.org position,rival.org url"


def test_content_gap_errors(client, monkeypatch):
    bare = client.post("/api/projects", json={"domain": "bare.com"}).json()["id"]
    assert client.post(f"/api/projects/{bare}/content-gap", json={}).status_code == 400
    six = [f"c{i}.com" for i in range(6)]
    assert client.post(f"/api/projects/{bare}/content-gap", json={"competitors": six}).status_code == 400
    assert client.post("/api/projects/999999/content-gap", json={}).status_code == 404

    def failing(*a, **k):
        raise ProviderError("DataForSEO 40200: Payment required.")

    monkeypatch.setattr(gap, "content_gap", failing)
    response = client.post(f"/api/projects/{bare}/content-gap", json={"competitors": ["rival.org"]})
    assert response.status_code == 502 and "40200" in response.json()["detail"]
