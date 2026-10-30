"""AI providers: request shapes, citation parsing, errors, the cap, dry run."""

from unittest.mock import MagicMock

import pytest
import requests

from app.ai_visibility.providers import (ClaudeProvider, DryRunAI, GeminiProvider, OpenAIProvider,
                                         configured_providers, provider_status)
from app.config import config


def resp(status, body):
    r = MagicMock(status_code=status, text=str(body))
    r.json.return_value = body
    return r


class Http:
    def __init__(self, *responses):
        self.calls, self.responses = [], list(responses)

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append((url, headers, json, timeout))
        nxt = self.responses.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


CLAUDE = {"model": "claude-sonnet-5", "content": [
    {"type": "server_tool_use", "name": "web_search"},
    {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://books.toscrape.com/", "title": "Books"}]},
    {"type": "text", "text": "Try Books to Scrape. ", "citations": [{"url": "https://books.toscrape.com/", "title": "Books"}]},
    {"type": "text", "text": "Amazon is bigger.", "citations": [{"url": "https://www.amazon.com/books", "title": "Amazon"}]},
]}


def test_claude_request_and_parsing():
    http = Http(resp(200, CLAUDE))
    a = ClaudeProvider("sk-ant-SECRET", "claude-sonnet-5", http=http).ask("best bookstore")
    url, headers, body, timeout = http.calls[0]
    assert url == "https://api.anthropic.com/v1/messages" and timeout == 60
    assert headers["x-api-key"] == "sk-ant-SECRET" and headers["anthropic-version"] == "2023-06-01"
    assert body["model"] == "claude-sonnet-5" and body["messages"] == [{"role": "user", "content": "best bookstore"}]
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}]
    assert a.text == "Try Books to Scrape. Amazon is bigger." and a.error is None
    assert [c["url"] for c in a.citations] == ["https://books.toscrape.com/", "https://www.amazon.com/books"]


def test_openai_request_and_parsing():
    data = {"output": [{"type": "web_search_call"}, {"type": "message", "content": [{"type": "output_text",
            "text": "Books to Scrape is popular.", "annotations": [
                {"type": "url_citation", "url": "https://books.toscrape.com/", "title": "Books"},
                {"type": "file_citation", "file_id": "x"}]}]}]}
    http = Http(resp(200, data))
    a = OpenAIProvider("sk-SECRET", "gpt-x", http=http).ask("best bookstore")
    url, headers, body, _ = http.calls[0]
    assert url == "https://api.openai.com/v1/responses" and headers["Authorization"] == "Bearer sk-SECRET"
    assert body == {"model": "gpt-x", "input": "best bookstore", "tools": [{"type": "web_search"}]}
    assert a.text == "Books to Scrape is popular." and a.citations == [{"url": "https://books.toscrape.com/", "title": "Books"}]


def test_gemini_request_and_parsing():
    data = {"candidates": [{"content": {"parts": [{"text": "Books to Scrape "}, {"text": "and Amazon."}]},
            "groundingMetadata": {"groundingChunks": [
                {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "books.toscrape.com"}}]}}]}
    http = Http(resp(200, data))
    a = GeminiProvider("AIza-SECRET", "gemini-x", http=http).ask("best bookstore")
    url, headers, body, _ = http.calls[0]
    assert url == "https://generativelanguage.googleapis.com/v1beta/models/gemini-x:generateContent"
    assert headers["x-goog-api-key"] == "AIza-SECRET"
    assert body == {"contents": [{"parts": [{"text": "best bookstore"}]}], "tools": [{"google_search": {}}]}
    assert a.text == "Books to Scrape and Amazon." and a.citations[0]["title"] == "books.toscrape.com"


def test_errors_never_carry_the_key():
    http = Http(resp(401, {"error": {"message": "invalid x-api-key sk-ant-SECRET"}}))
    a = ClaudeProvider("sk-ant-SECRET", "m", http=http).ask("q")
    assert a.error == "claude HTTP 401: invalid x-api-key ***"
    a = OpenAIProvider("sk-SECRET", "m", http=Http(requests.Timeout("https://api.openai.com ?key=sk-SECRET"))).ask("q")
    assert a.error == "openai request failed: Timeout"
    a = GeminiProvider("k", "m", http=Http(resp(200, {"candidates": "nonsense"}))).ask("q")
    assert a.error.startswith("gemini returned an unexpected response")


def test_cap_stops_calls(monkeypatch):
    monkeypatch.setattr(config, "AI_VISIBILITY_DAILY_CAP", 0)
    http = Http()
    a = ClaudeProvider("k", "m", http=http).ask("q")
    assert a.error == "daily cap of 0 ai_visibility calls reached" and http.calls == []


def test_dry_run_is_deterministic_and_uses_the_brands():
    hint = [("Books to Scrape", "books.toscrape.com"), ("Amazon", "amazon.com"), ("Goodreads", "goodreads.com")]
    a1 = DryRunAI("claude").ask("best rare books", brands_hint=hint)
    assert a1 == DryRunAI("claude").ask("best rare books", brands_hint=hint)
    assert a1.citations and DryRunAI("claude").dry_run is True
    texts = [DryRunAI(n).ask(f"prompt {i}", brands_hint=hint).text for n in ("claude", "openai", "gemini") for i in range(6)]
    assert any("Books to Scrape" in t for t in texts) and any("Books to Scrape" not in t for t in texts)


def test_configured_providers_and_status(monkeypatch):
    assert [p.name for p in configured_providers()] == ["claude", "openai", "gemini"]
    assert all(p.dry_run for p in configured_providers())
    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "k1")
    monkeypatch.setattr(config, "OPENAI_API_KEY", "k2")          # no OPENAI_MODEL: skipped
    providers = configured_providers()
    assert [(p.name, p.dry_run) for p in providers] == [("claude", False)]
    status = {s["name"]: s for s in provider_status()}
    assert status["claude"]["configured"] is True and status["claude"]["model"] == "claude-sonnet-5"
    assert status["openai"]["configured"] is False and status["openai"]["hint"] == "set OPENAI_MODEL"
    assert status["gemini"]["hint"] == "set GEMINI_API_KEY and GEMINI_MODEL"
    monkeypatch.setattr(config, "AI_VISIBILITY_DRY_RUN", True)
    assert all(p.dry_run for p in configured_providers())
