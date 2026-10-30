"""AI Visibility over HTTP."""

import pytest
from fastapi.testclient import TestClient

from app.api import ai_visibility as api
from app.ai_visibility.providers import Answer
from app.ai_visibility.run import run_project
from app.db.engine import get_session_factory
from app.db.models import Competitor, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _project():
    with get_session_factory().begin() as s:
        p = Project(name="books.toscrape.com", domain="books.toscrape.com"); s.add(p); s.flush()
        s.add(Competitor(project_id=p.id, domain="amazon.com"))
        return p.id


class Scripted:
    dry_run = False

    def __init__(self, name, texts):
        self.name, self.model, self.texts = name, f"{name}-1", list(texts)

    def ask(self, prompt, brands_hint=None):
        text = self.texts.pop(0)
        return Answer(text, [{"url": "https://www.books.toscrape.com/a", "title": "a"}] if "BTS" in text else [], self.model)


def test_prompts_crud_and_cap(client, monkeypatch):
    pid = _project()
    created = client.post(f"/api/projects/{pid}/ai-visibility/prompts", json={"text": "  best rare books  "})
    assert created.status_code == 201 and created.json()["text"] == "best rare books"
    assert client.post(f"/api/projects/{pid}/ai-visibility/prompts", json={"text": ""}).status_code == 422
    prompt_id = created.json()["id"]
    assert client.patch(f"/api/ai-prompts/{prompt_id}", json={"enabled": False}).json()["enabled"] is False
    monkeypatch.setattr(api, "MAX_PROMPTS", 1)
    assert client.post(f"/api/projects/{pid}/ai-visibility/prompts", json={"text": "x"}).status_code == 409
    assert client.delete(f"/api/ai-prompts/{prompt_id}").status_code == 204
    assert client.get(f"/api/projects/{pid}/ai-visibility/prompts").json()["items"] == []


def test_brands_get_and_put(client):
    pid = _project()
    body = client.put(f"/api/projects/{pid}/ai-visibility/brands",
                      json={"self": ["BTS", " Books to Scrape "], "competitors": {"amazon.com": ["Amazon", "AMZN"]}}).json()
    assert body["self"] == {"domain": "books.toscrape.com", "terms": ["BTS", "Books to Scrape"]}
    assert body["competitors"] == [{"domain": "amazon.com", "terms": ["Amazon", "AMZN"]}]
    assert client.put(f"/api/projects/{pid}/ai-visibility/brands", json={"competitors": {"nope.com": ["x"]}}).status_code == 400
    assert client.put(f"/api/projects/{pid}/ai-visibility/brands", json={"self": ["x" * 101]}).status_code == 422
    assert client.put(f"/api/projects/{pid}/ai-visibility/brands", json={"self": [f"t{i}" for i in range(11)]}).status_code == 422


def test_overview_math_answers_and_highlights(client):
    pid = _project()
    client.put(f"/api/projects/{pid}/ai-visibility/brands", json={"self": ["BTS"], "competitors": {"amazon.com": ["Amazon"]}})
    for text in ("q1", "q2"):
        client.post(f"/api/projects/{pid}/ai-visibility/prompts", json={"text": text})
    run_project(pid, providers=[Scripted("claude", ["Amazon then BTS", "nothing"]), Scripted("openai", ["BTS!", "Amazon only"])])
    run_project(pid, providers=[Scripted("claude", ["BTS", "BTS"]), Scripted("openai", ["BTS", "nothing"])])
    o = client.get(f"/api/projects/{pid}/ai-visibility").json()
    assert o["latest"]["mention_rate"] == 0.75 and o["previous"]["mention_rate"] == 0.5
    assert o["previous"]["avg_position"] == 1.5 and o["previous"]["cited_rate"] == 0.5
    assert o["latest"]["by_provider"]["claude"]["mention_rate"] == 1.0
    assert [t["mention_rate"] for t in o["trend"]] == [0.5, 0.75]
    assert o["share_of_voice"][0] == {"owner": "books.toscrape.com", "is_self": True, "rate": 0.75}
    assert o["top_cited"][0] == {"domain": "books.toscrape.com", "count": 3, "is_self": True}
    assert [p["name"] for p in o["providers"]] == ["claude", "openai", "gemini"]
    answers = client.get(f"/api/projects/{pid}/ai-visibility/answers?run_id={o['previous']['run_id']}&provider=claude").json()
    first = [a for a in answers["items"] if a["answer"] == "Amazon then BTS"][0]
    assert first["position"] == 2 and first["brands"] == ["amazon.com", "books.toscrape.com"]
    assert [(h["start"], h["end"], h["owner"]) for h in first["highlights"]] == [(0, 6, "amazon.com"), (12, 15, "books.toscrape.com")]


def test_run_endpoint_uses_dry_run_without_keys(client):
    pid = _project()
    assert client.post(f"/api/projects/{pid}/ai-visibility/run").json() == {"status": "no_prompts"}
    client.post(f"/api/projects/{pid}/ai-visibility/prompts", json={"text": "best rare books"})
    result = client.post(f"/api/projects/{pid}/ai-visibility/run").json()
    assert result["status"] == "ran" and result["dry_run"] is True and result["calls"] == 3
    assert client.get("/api/projects/999/ai-visibility").status_code == 404
