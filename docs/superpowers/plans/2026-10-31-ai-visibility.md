# AI Visibility (Phase 7.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A project's prompts are asked of Claude, OpenAI and Gemini (with
web search) or a dry run. Each answer records:
- whether the brand is mentioned
- its position among the tracked brands
- whether the site is cited, plus the cited domains

The AI Visibility tab shows KPIs, trends, share of voice, top citations and
every answer. Runs are manual or weekly (opt-in), and capped.

**Architecture:**
- `app/ai_visibility/` holds:
  - `providers.py`: three HTTP providers, a dry run, and configuration/status
  - `detect.py`: pure matching, positions, citations, highlights, share of voice
  - `run.py`: brand loading, the parallel run, and storage
- Migration 0010 adds the prompts, brand terms and runs tables, extends
  `ai_visibility_runs`, and adds the project schedule fields.
- An API router, a scheduler job (opt-in, never on all-dry-run), and a tab.

**Tech Stack:** Python, requests, SQLAlchemy/Alembic, APScheduler, FastAPI, pytest; Next.js 14, Recharts, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-30-ai-visibility-design.md`

## Global Constraints

- **Providers:**
  - Claude: `POST https://api.anthropic.com/v1/messages` (headers `x-api-key`, `anthropic-version: 2023-06-01`; tool `{type: ANTHROPIC_WEB_SEARCH_TOOL, name: "web_search", max_uses: 3}`)
  - OpenAI: `POST https://api.openai.com/v1/responses` (Bearer; tool `{type: OPENAI_WEB_SEARCH_TOOL}`)
  - Gemini: `POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent` (`x-goog-api-key`; tool `{google_search: {}}`)
  - All with a 60 s timeout.
- **Config:**
  - `ANTHROPIC_MODEL` defaults to `claude-sonnet-5`. `OPENAI_MODEL` and `GEMINI_MODEL` have no default; a provider without its model is skipped.
  - `ANTHROPIC_WEB_SEARCH_TOOL` defaults to `web_search_20250305`, `OPENAI_WEB_SEARCH_TOOL` to `web_search`.
  - `AI_VISIBILITY_DAILY_CAP` defaults to 30. `AI_VISIBILITY_DRY_RUN`.
- **Calls:** every `ask` first calls `spend.reserve("ai_visibility", cap)`. Keys never appear in errors. A network error reports its type only.
- **Dry run** when `AI_VISIBILITY_DRY_RUN` is set or no key exists: three `DryRunAI` (claude/openai/gemini).
- **Matching:** whole word, case-insensitive: `(?<![\w-])term(?![\w-])`. The domain counts as a term (with or without `www.`).
- **Position** = the 1-based order of the self brand among the mentioned tracked brands.
- **Cited** = a citation domain equal to the self domain or a subdomain of it. For Gemini grounding redirect hosts, the domain comes from the title.
- **Limits:** 25 prompts (409), prompt text 1–300 characters, terms 1–100 characters and ≤ 10 per owner (422). The answer is stored up to 8,000 characters, citations up to 20.
- **Scheduling:** weekly is opt-in (`ai_schedule = "weekly"`). The scheduler skips when every provider is a dry run.
- **UI:**
  - highlights are rendered as text inside `<mark>`, never as HTML
  - citation links are http/https only, with `rel="noopener noreferrer"`
- **Commits:** the full backend suite must exit 0 before each commit.

---

### Task 1: Providers

**Files:**
- Create: `apps/backend/app/ai_visibility/__init__.py`, `apps/backend/app/ai_visibility/providers.py`, `apps/backend/tests/test_ai_providers.py`
- Modify: `apps/backend/app/config/config.py`, `apps/backend/tests/conftest.py`

**Interfaces:**
- Produces:
  - `Answer(text="", citations=[], model="", error=None)`
  - `ClaudeProvider(key, model, http=requests)`, `OpenAIProvider(...)`, `GeminiProvider(...)`, each `.ask(prompt, brands_hint=None) -> Answer`
  - `DryRunAI(name)`
  - `configured_providers(cfg=config) -> list`
  - `provider_status(cfg=config) -> List[dict]`

- [ ] **Step 1: Config and isolation**

Append to `app/config/config.py`:

```python
# AI Visibility (Phase 7.1): prompts asked of AI models with their own web
# search. Each provider runs only with its key (and, for OpenAI and Gemini, a
# model you choose). No keys at all = made-up dry-run answers.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
ANTHROPIC_WEB_SEARCH_TOOL = os.getenv("ANTHROPIC_WEB_SEARCH_TOOL", "web_search_20250305")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")
OPENAI_WEB_SEARCH_TOOL = os.getenv("OPENAI_WEB_SEARCH_TOOL", "web_search")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "")
AI_VISIBILITY_DRY_RUN = os.getenv("AI_VISIBILITY_DRY_RUN", "").strip().lower() in ("1", "true", "yes")
AI_VISIBILITY_DAILY_CAP = int(os.getenv("AI_VISIBILITY_DAILY_CAP", "30"))
```

Append to the `no_live_web_vitals` fixture in `tests/conftest.py`:

```python
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setattr(app_config, name, "")
    monkeypatch.setattr(app_config, "AI_VISIBILITY_DRY_RUN", False)
```

- [ ] **Step 2: Write the failing test**

```python
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
```

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_ai_providers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.ai_visibility'`

- [ ] **Step 4: Implement**

`app/ai_visibility/__init__.py`:

```python
"""AI Visibility (Phase 7.1): does the brand show up when people ask AI assistants?"""
```

`app/ai_visibility/providers.py`:

```python
"""Claude, OpenAI and Gemini behind one interface, each answering with its own
web search, plus a deterministic dry run. Request and response shapes follow
each provider's docs and are confirmed on the owner-approved first live call."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote

import requests

from app.config import config
from app.providers import spend
from app.providers.serp import ProviderSkipped

logger = logging.getLogger(__name__)
BUDGET = "ai_visibility"
TIMEOUT = 60
MAX_CITATIONS = 20


@dataclass
class Answer:
    text: str = ""
    citations: List[Dict[str, str]] = field(default_factory=list)
    model: str = ""
    error: Optional[str] = None


class _Failed(Exception):
    pass


def _dedupe(citations) -> List[Dict[str, str]]:
    seen, out = set(), []
    for c in citations:
        url = (c.get("url") or "").strip()
        if url and url not in seen:
            seen.add(url)
            out.append({"url": url, "title": (c.get("title") or "")[:300]})
    return out[:MAX_CITATIONS]


def _error_message(resp) -> str:
    try:
        body = resp.json()
    except ValueError:
        return (resp.text or "")[:200]
    err = body.get("error") if isinstance(body, dict) else None
    if isinstance(err, dict):
        return str(err.get("message") or "")[:200]
    return str(err or "")[:200]


class _HttpProvider:
    name = ""
    dry_run = False

    def __init__(self, key: str, model: str, http=requests) -> None:
        self._key, self.model, self._http = key, model, http

    def _post(self, url: str, headers: Dict[str, str], body: Dict[str, Any]) -> Dict[str, Any]:
        resp = self._http.post(url, headers=headers, json=body, timeout=TIMEOUT)
        if resp.status_code >= 300:
            raise _Failed(f"{self.name} HTTP {resp.status_code}: {_error_message(resp)}")
        return resp.json()

    def _ask(self, prompt: str) -> Answer:
        raise NotImplementedError

    def ask(self, prompt: str, brands_hint: Optional[Sequence[Tuple[str, str]]] = None) -> Answer:
        try:
            spend.reserve(BUDGET, config.AI_VISIBILITY_DAILY_CAP)
        except ProviderSkipped as exc:
            return Answer(model=self.model, error=str(exc))
        try:
            return self._ask(prompt)
        except _Failed as exc:
            return Answer(model=self.model, error=str(exc).replace(self._key, "***") if self._key else str(exc))
        except requests.RequestException as exc:
            # The type only: messages can carry URLs with keys.
            return Answer(model=self.model, error=f"{self.name} request failed: {type(exc).__name__}")
        except (ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
            return Answer(model=self.model, error=f"{self.name} returned an unexpected response ({type(exc).__name__})")


class ClaudeProvider(_HttpProvider):
    name = "claude"

    def _ask(self, prompt: str) -> Answer:
        data = self._post("https://api.anthropic.com/v1/messages",
                          {"x-api-key": self._key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                          {"model": self.model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}],
                           "tools": [{"type": config.ANTHROPIC_WEB_SEARCH_TOOL, "name": "web_search", "max_uses": 3}]})
        texts, cites = [], []
        for block in data.get("content") or []:
            if block.get("type") == "text":
                texts.append(block.get("text") or "")
                cites += [c for c in (block.get("citations") or []) if isinstance(c, dict)]
            elif block.get("type") == "web_search_tool_result" and isinstance(block.get("content"), list):
                cites += [r for r in block["content"] if isinstance(r, dict)]
        return Answer("".join(texts).strip(), _dedupe(cites), data.get("model") or self.model)


class OpenAIProvider(_HttpProvider):
    name = "openai"

    def _ask(self, prompt: str) -> Answer:
        data = self._post("https://api.openai.com/v1/responses", {"Authorization": f"Bearer {self._key}"},
                          {"model": self.model, "input": prompt, "tools": [{"type": config.OPENAI_WEB_SEARCH_TOOL}]})
        texts, cites = [], []
        for item in data.get("output") or []:
            if item.get("type") != "message":
                continue
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    texts.append(part.get("text") or "")
                    cites += [a for a in (part.get("annotations") or []) if a.get("type") == "url_citation"]
        return Answer("".join(texts).strip(), _dedupe(cites), self.model)


class GeminiProvider(_HttpProvider):
    name = "gemini"

    def _ask(self, prompt: str) -> Answer:
        data = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model, safe='')}:generateContent",
            {"x-goog-api-key": self._key},
            {"contents": [{"parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]})
        candidate = (data.get("candidates") or [{}])[0]
        text = "".join(p.get("text") or "" for p in (candidate.get("content") or {}).get("parts") or [])
        chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
        cites = [{"url": c["web"].get("uri"), "title": c["web"].get("title")} for c in chunks
                 if isinstance(c.get("web"), dict) and c["web"].get("uri")]
        return Answer(text.strip(), _dedupe(cites), self.model)


def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest()[:8], 16)


class DryRunAI:
    """Made-up but stable answers naming some of the tracked brands, so the tab
    can be tried without keys. Rows it produces are stored as dry_run."""

    dry_run = True

    def __init__(self, name: str) -> None:
        self.name = name
        self.model = f"{name}-dry-run"

    def ask(self, prompt: str, brands_hint: Optional[Sequence[Tuple[str, str]]] = None) -> Answer:
        brands = list(brands_hint or [("Example", "example.com")])
        s = _seed(self.name, prompt)
        start = s % len(brands)
        ordered = brands[start:] + brands[:start]
        named = ordered[: 1 + (s // 7) % len(brands)]
        lines = [f"For \"{prompt}\", people often recommend:"]
        lines += [f"{i}. {label} ({domain})" for i, (label, domain) in enumerate(named, start=1)]
        cites = [{"url": f"https://{domain}/", "title": label} for label, domain in named[:2]]
        cites.append({"url": f"https://www.example-reviews.com/{s % 1000}", "title": "Example Reviews"})
        return Answer("\n".join(lines), cites, self.model)


_PROVIDERS = (("claude", ClaudeProvider, "ANTHROPIC"), ("openai", OpenAIProvider, "OPENAI"), ("gemini", GeminiProvider, "GEMINI"))


def configured_providers(cfg=config) -> list:
    if cfg.AI_VISIBILITY_DRY_RUN or not (cfg.ANTHROPIC_API_KEY or cfg.OPENAI_API_KEY or cfg.GEMINI_API_KEY):
        return [DryRunAI(name) for name, _, _ in _PROVIDERS]
    out = []
    for name, cls, prefix in _PROVIDERS:
        key, model = getattr(cfg, f"{prefix}_API_KEY"), getattr(cfg, f"{prefix}_MODEL")
        if key and model:
            out.append(cls(key, model))
    return out


def provider_status(cfg=config) -> List[Dict[str, Any]]:
    """What the UI shows per model: configured, dry run, or what's missing."""
    dry = cfg.AI_VISIBILITY_DRY_RUN or not (cfg.ANTHROPIC_API_KEY or cfg.OPENAI_API_KEY or cfg.GEMINI_API_KEY)
    out = []
    for name, _, prefix in _PROVIDERS:
        key, model = getattr(cfg, f"{prefix}_API_KEY"), getattr(cfg, f"{prefix}_MODEL")
        missing = [n for n, v in ((f"{prefix}_API_KEY", key), (f"{prefix}_MODEL", model)) if not v]
        out.append({"name": name, "model": (f"{name}-dry-run" if dry else model) or None, "dry_run": dry,
                    "configured": dry or not missing, "hint": None if dry or not missing else "set " + " and ".join(missing)})
    return out
```

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_ai_providers.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/ai_visibility apps/backend/app/config/config.py apps/backend/tests/conftest.py apps/backend/tests/test_ai_providers.py
git commit -m "feat(ai-visibility): Claude/OpenAI/Gemini providers with web search, cap, dry run"
```

---

### Task 2: Detection

**Files:**
- Create: `apps/backend/app/ai_visibility/detect.py`, `apps/backend/tests/test_ai_detect.py`

**Interfaces:**
- Produces:
  - `Brand(owner, is_self, terms: Tuple[str, ...], domain)`
  - `spans(text, brand) -> List[Tuple[int, int]]`
  - `first_index(text, brand) -> Optional[int]`
  - `citation_domain(citation) -> Optional[str]`
  - `analyze(text, citations, brands) -> {mentioned, position, brands_mentioned, cited, cited_domains}`
  - `highlights(text, brands) -> List[{start, end, owner}]`

- [ ] **Step 1: Write the failing test**

```python
"""Brand mentions, position and citations in an AI answer."""

from app.ai_visibility.detect import Brand, analyze, citation_domain, first_index, highlights, spans

ME = Brand("books.toscrape.com", True, ("Books to Scrape", "BTS"), "books.toscrape.com")
AMAZON = Brand("amazon.com", False, ("Amazon",), "amazon.com")
READS = Brand("goodreads.com", False, ("Goodreads",), "goodreads.com")


def test_whole_word_case_insensitive_and_domains():
    assert spans("I like books to scrape a lot", ME) == [(7, 22)]
    assert spans("Bookstores and AmazonBasics", AMAZON) == []
    assert spans("non-Amazon sellers", AMAZON) == []              # hyphen counts as part of the word
    assert spans("visit www.amazon.com today", AMAZON) == [(6, 20)]
    assert first_index("BTS, then Books to Scrape", ME) == 0
    assert first_index("nothing here", ME) is None


def test_position_is_order_among_tracked_brands():
    text = "Amazon is biggest. Goodreads has reviews. Books to Scrape is a fun demo."
    result = analyze(text, [], [ME, AMAZON, READS])
    assert result["brands_mentioned"] == ["amazon.com", "goodreads.com", "books.toscrape.com"]
    assert result["mentioned"] is True and result["position"] == 3


def test_absent_brand_has_no_position():
    result = analyze("Amazon only.", [], [ME, AMAZON])
    assert result["mentioned"] is False and result["position"] is None and result["brands_mentioned"] == ["amazon.com"]


def test_citations_count_subdomains_and_gemini_titles():
    assert citation_domain({"url": "https://www.amazon.com/x"}) == "amazon.com"
    gemini = {"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "books.toscrape.com"}
    assert citation_domain(gemini) == "books.toscrape.com"
    assert citation_domain({"url": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/x", "title": "A great page"}) is None
    cites = [{"url": "https://reviews.example.com/a"}, {"url": "https://shop.books.toscrape.com/b"}, gemini,
             {"url": "https://reviews.example.com/c"}]
    result = analyze("no brands", cites, [ME, AMAZON])
    assert result["cited"] is True
    assert result["cited_domains"] == ["reviews.example.com", "shop.books.toscrape.com", "books.toscrape.com"]
    assert analyze("x", [{"url": "https://notbooks.toscrape.com.evil.io/"}], [ME])["cited"] is False


def test_highlights_are_sorted_and_never_overlap():
    text = "Books to Scrape (books.toscrape.com) beats Amazon."
    hl = highlights(text, [ME, AMAZON])
    assert [(text[h["start"]:h["end"]], h["owner"]) for h in hl] == [
        ("Books to Scrape", "books.toscrape.com"), ("books.toscrape.com", "books.toscrape.com"), ("Amazon", "amazon.com")]
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_ai_detect.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: `app/ai_visibility/detect.py`**

```python
"""Finding tracked brands and citations in an AI answer. Pure functions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

_DOMAIN = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+")
_REDIRECT_HOSTS = ("vertexaisearch.cloud.google.com", "googleusercontent.com")


@dataclass(frozen=True)
class Brand:
    owner: str
    is_self: bool
    terms: Tuple[str, ...]
    domain: str


def _patterns(brand: Brand) -> List[re.Pattern]:
    words = {t.strip() for t in brand.terms if t and t.strip()}
    if brand.domain:
        words |= {brand.domain, f"www.{brand.domain}"}
    return [re.compile(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", re.IGNORECASE) for w in sorted(words, key=len, reverse=True)]


def spans(text: str, brand: Brand) -> List[Tuple[int, int]]:
    found = sorted({(m.start(), m.end()) for p in _patterns(brand) for m in p.finditer(text or "")})
    out: List[Tuple[int, int]] = []
    for start, end in found:                 # keep the longest of overlapping matches
        if out and start < out[-1][1]:
            if end - start > out[-1][1] - out[-1][0]:
                out[-1] = (start, end)
            continue
        out.append((start, end))
    return out


def first_index(text: str, brand: Brand) -> Optional[int]:
    found = spans(text, brand)
    return found[0][0] if found else None


def citation_domain(citation: Dict[str, Any]) -> Optional[str]:
    url = citation.get("url") or ""
    host = (urlsplit(url).hostname or "").lower()
    if any(host == h or host.endswith("." + h) for h in _REDIRECT_HOSTS) or "grounding-api-redirect" in url:
        title = (citation.get("title") or "").strip().lower()
        if not _DOMAIN.fullmatch(title):
            return None
        host = title
    if not host:
        return None
    return host[4:] if host.startswith("www.") else host


def analyze(text: str, citations: Sequence[Dict[str, Any]], brands: Sequence[Brand]) -> Dict[str, Any]:
    order = sorted(((first_index(text, b), b) for b in brands if first_index(text, b) is not None), key=lambda x: x[0])
    mentioned_owners = [b.owner for _, b in order]
    me = next((b for b in brands if b.is_self), None)
    position = mentioned_owners.index(me.owner) + 1 if me and me.owner in mentioned_owners else None
    domains: List[str] = []
    for c in citations:
        d = citation_domain(c)
        if d and d not in domains:
            domains.append(d)
    cited = bool(me) and any(d == me.domain or d.endswith("." + me.domain) for d in domains)
    return {"mentioned": position is not None, "position": position, "brands_mentioned": mentioned_owners,
            "cited": cited, "cited_domains": domains}


def highlights(text: str, brands: Sequence[Brand]) -> List[Dict[str, Any]]:
    marks = sorted((s, e, b.owner) for b in brands for s, e in spans(text, b))
    out: List[Dict[str, Any]] = []
    for start, end, owner in marks:
        if out and start < out[-1]["end"]:
            continue
        out.append({"start": start, "end": end, "owner": owner})
    return out
```

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_ai_detect.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/ai_visibility/detect.py apps/backend/tests/test_ai_detect.py
git commit -m "feat(ai-visibility): whole-word brand detection, position, citations, highlights"
```

---

### Task 3: Storage and the opt-in schedule

**Files:**
- Create: `apps/backend/alembic/versions/0010_ai_visibility.py`, `apps/backend/tests/test_ai_storage.py`
- Modify: `apps/backend/app/db/models.py`, `apps/backend/app/api/projects.py`, `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Produces:
  - models `AiPrompt`, `AiBrandTerm`, `AiRun`
  - `AiVisibilityRun` gains `run_id, prompt_id, model, answer, mentioned, position, brands_json, cited, citations_json, error, dry_run`
  - `Project.ai_schedule`, `Project.last_ai_run_at`
  - project JSON and `PATCH` support `ai_schedule`

- [ ] **Step 1: Write the failing test**

```python
"""AI Visibility tables and the opt-in weekly schedule."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.db.engine import get_session_factory
from app.db.models import AiBrandTerm, Project
from app.main import app


def test_schedule_opt_in():
    client = TestClient(app)
    p = client.post("/api/projects", json={"domain": "shop.com"}).json()
    assert p["ai_schedule"] is None and p["last_ai_run_at"] is None
    assert client.patch(f"/api/projects/{p['id']}", json={"ai_schedule": "weekly"}).json()["ai_schedule"] == "weekly"
    assert client.patch(f"/api/projects/{p['id']}", json={"ai_schedule": "daily"}).status_code == 422


def test_brand_terms_are_unique_per_owner():
    with get_session_factory().begin() as s:
        p = Project(name="shop.com", domain="shop.com"); s.add(p); s.flush()
        s.add(AiBrandTerm(project_id=p.id, owner="shop.com", term="Shop"))
    with pytest.raises(IntegrityError):
        with get_session_factory().begin() as s:
            s.add(AiBrandTerm(project_id=p.id, owner="shop.com", term="Shop"))
```

Add `"ai_prompts", "ai_brand_terms", "ai_runs"` to `TABLES` in `tests/test_db_schema.py`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_ai_storage.py tests/test_db_schema.py -q`
Expected: FAIL.

- [ ] **Step 3: Models**

In `class Project`, after `last_backlink_refresh_at`:

```python
    ai_schedule: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_ai_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
```

In `class AiVisibilityRun`, after `result_json`:

```python
    run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ai_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    prompt_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="", server_default="")
    answer: Mapped[str] = mapped_column(Text, default="", server_default="")
    mentioned: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    position: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    brands_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    cited: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    citations_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
```

Append:

```python
class AiPrompt(Base):
    """A question tracked for AI Visibility (Phase 7.1)."""
    __tablename__ = "ai_prompts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiBrandTerm(Base):
    """A name or alias a brand (the project's or a competitor's) is matched by."""
    __tablename__ = "ai_brand_terms"
    __table_args__ = (UniqueConstraint("project_id", "owner", "term", name="uq_ai_brand_terms_owner_term"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    owner: Mapped[str] = mapped_column(String(255))
    term: Mapped[str] = mapped_column(String(100))


class AiRun(Base):
    """One AI Visibility run: every enabled prompt asked of every model."""
    __tablename__ = "ai_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    trigger: Mapped[str] = mapped_column(String(16))
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
```

`AiVisibilityRun` references `ai_runs`, which is defined after it. A string
FK is fine for SQLAlchemy.

- [ ] **Step 4: Migration `alembic/versions/0010_ai_visibility.py`**

```python
"""ai visibility

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-31 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.add_column(sa.Column('ai_schedule', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('last_ai_run_at', sa.DateTime(timezone=True), nullable=True))

    op.create_table('ai_prompts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default=sa.true(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_prompts_project_id'), 'ai_prompts', ['project_id'], unique=False)

    op.create_table('ai_brand_terms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('owner', sa.String(length=255), nullable=False),
    sa.Column('term', sa.String(length=100), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'owner', 'term', name='uq_ai_brand_terms_owner_term')
    )
    op.create_index(op.f('ix_ai_brand_terms_project_id'), 'ai_brand_terms', ['project_id'], unique=False)

    op.create_table('ai_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('trigger', sa.String(length=16), nullable=False),
    sa.Column('dry_run', sa.Boolean(), nullable=False),
    sa.Column('calls', sa.Integer(), nullable=False),
    sa.Column('errors', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_ai_runs_project_id'), 'ai_runs', ['project_id'], unique=False)

    with op.batch_alter_table('ai_visibility_runs') as batch_op:
        batch_op.add_column(sa.Column('run_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('prompt_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('model', sa.String(length=64), server_default='', nullable=False))
        batch_op.add_column(sa.Column('answer', sa.Text(), server_default='', nullable=False))
        batch_op.add_column(sa.Column('mentioned', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('brands_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('cited', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('citations_json', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('error', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('dry_run', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.create_index(batch_op.f('ix_ai_visibility_runs_run_id'), ['run_id'], unique=False)
        batch_op.create_foreign_key('fk_ai_visibility_runs_run_id', 'ai_runs', ['run_id'], ['id'], ondelete='CASCADE')


def downgrade() -> None:
    with op.batch_alter_table('ai_visibility_runs') as batch_op:
        batch_op.drop_constraint('fk_ai_visibility_runs_run_id', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_ai_visibility_runs_run_id'))
        for column in ('dry_run', 'error', 'citations_json', 'cited', 'brands_json', 'position', 'mentioned',
                       'answer', 'model', 'prompt_id', 'run_id'):
            batch_op.drop_column(column)
    for table in ('ai_runs', 'ai_brand_terms', 'ai_prompts'):
        op.drop_index(op.f(f'ix_{table}_project_id'), table_name=table)
        op.drop_table(table)
    with op.batch_alter_table('projects') as batch_op:
        batch_op.drop_column('last_ai_run_at')
        batch_op.drop_column('ai_schedule')
```

`brands_json` and `citations_json` are nullable in the migration (old rows),
so declare them `nullable=True` in the model too: `mapped_column(JSON,
default=list, nullable=True)`. The models-vs-migration test enforces this.
Name the FK in the model to match: `ForeignKey("ai_runs.id",
ondelete="CASCADE", name="fk_ai_visibility_runs_run_id")`.

- [ ] **Step 5: Project API**

`app/api/projects.py`:
- Add `ai_schedule: Optional[Literal["weekly"]] = None` to `ProjectUpdate`.
- In `update_project`, add `if "ai_schedule" in fields: project.ai_schedule = fields["ai_schedule"]`.
- In `_project_json`, add `"ai_schedule": project.ai_schedule` and `"last_ai_run_at": as_utc(project.last_ai_run_at).isoformat() if project.last_ai_run_at else None`.

- [ ] **Step 6: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_ai_storage.py tests/test_db_schema.py tests/test_projects_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/db/models.py apps/backend/alembic/versions/0010_ai_visibility.py apps/backend/app/api/projects.py apps/backend/tests/test_ai_storage.py apps/backend/tests/test_db_schema.py
git commit -m "feat(ai-visibility): prompts, brand terms, runs tables (migration 0010) and opt-in schedule"
```

---

### Task 4: Running prompts, and the weekly job

**Files:**
- Create: `apps/backend/app/ai_visibility/run.py`, `apps/backend/tests/test_ai_run.py`
- Modify: `apps/backend/app/scheduler/jobs.py`

**Interfaces:**
- Produces:
  - `load_brands(session, project) -> List[Brand]`
  - `run_project(project_id, providers=None, trigger="manual", factory=None) -> dict`
  - `jobs.run_due_ai_visibility(now=None, providers=None) -> List[int]`

- [ ] **Step 1: Write the failing test**

```python
"""AI Visibility runs: every prompt x model, stored and analysed; failures
isolated; the opt-in weekly job never runs on dry run."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.ai_visibility.providers import Answer, DryRunAI
from app.ai_visibility.run import load_brands, run_project
from app.db.engine import get_session_factory
from app.db.models import AiBrandTerm, AiPrompt, AiRun, AiVisibilityRun, Competitor, Project
from app.scheduler import jobs


def _project(prompts=("best rare books",), schedule=None, last=None):
    with get_session_factory().begin() as s:
        p = Project(name="Books to Scrape", domain="books.toscrape.com", ai_schedule=schedule, last_ai_run_at=last)
        s.add(p); s.flush()
        s.add(Competitor(project_id=p.id, domain="amazon.com"))
        s.add(AiBrandTerm(project_id=p.id, owner="amazon.com", term="Amazon"))
        s.add(AiBrandTerm(project_id=p.id, owner="books.toscrape.com", term="BTS"))
        for text in prompts:
            s.add(AiPrompt(project_id=p.id, text=text))
        return p.id


class Fixed:
    dry_run = False

    def __init__(self, name, text="", error=None, raises=None):
        self.name, self.model, self.text, self.error, self.raises, self.prompts = name, f"{name}-1", text, error, raises, []

    def ask(self, prompt, brands_hint=None):
        self.prompts.append(prompt)
        if self.raises:
            raise self.raises
        return Answer(self.text, [{"url": "https://books.toscrape.com/x", "title": "x"}], self.model, self.error)


def test_brands_include_project_name_and_competitor_terms():
    pid = _project()
    with get_session_factory()() as s:
        brands = load_brands(s, s.get(Project, pid))
    me = brands[0]
    assert me.is_self and me.domain == "books.toscrape.com" and set(me.terms) == {"BTS", "Books to Scrape"}
    assert brands[1].owner == "amazon.com" and brands[1].terms == ("Amazon",)


def test_every_prompt_by_every_model_is_stored_and_analysed():
    pid = _project(prompts=("q1", "q2"))
    a = Fixed("claude", text="Amazon first, then Books to Scrape.")
    b = Fixed("openai", error="openai HTTP 500: boom")
    c = Fixed("gemini", raises=RuntimeError("bad"))
    result = run_project(pid, providers=[a, b, c])
    assert result["status"] == "ran" and result["calls"] == 6 and result["errors"] == 4 and result["mention_rate"] == 1.0
    assert sorted(a.prompts) == ["q1", "q2"]
    with get_session_factory()() as s:
        rows = s.scalars(select(AiVisibilityRun).where(AiVisibilityRun.run_id == result["run_id"])).all()
        ok = [r for r in rows if r.provider == "claude"]
        assert len(rows) == 6 and all(r.mentioned and r.position == 2 and r.cited for r in ok)
        assert ok[0].brands_json == ["amazon.com", "books.toscrape.com"]
        assert {r.error for r in rows if r.provider == "gemini"} == {"unexpected error (RuntimeError)"}
        run = s.get(AiRun, result["run_id"])
        assert (run.calls, run.errors, run.finished_at is not None) == (6, 4, True)
        assert s.get(Project, pid).last_ai_run_at is not None


def test_long_answers_are_trimmed_and_no_prompts_is_reported():
    pid = _project()
    run_project(pid, providers=[Fixed("claude", text="x" * 9000)])
    with get_session_factory()() as s:
        assert len(s.scalar(select(AiVisibilityRun.answer))) == 8000
    empty = _project(prompts=())
    assert run_project(empty, providers=[Fixed("claude")]) == {"status": "no_prompts"}


def test_dry_run_flags_the_run():
    pid = _project()
    result = run_project(pid, providers=[DryRunAI("claude"), DryRunAI("openai")])
    assert result["dry_run"] is True and result["calls"] == 2


def test_weekly_job_is_opt_in_and_never_dry_run():
    now = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)
    due = _project(schedule="weekly")
    with get_session_factory().begin() as s:
        p = Project(name="fresh.com", domain="fresh.com", ai_schedule="weekly", last_ai_run_at=now - timedelta(days=1))
        s.add(p); s.flush(); s.add(AiPrompt(project_id=p.id, text="q"))
    assert jobs.run_due_ai_visibility(now=now, providers=[DryRunAI("claude")]) == []
    assert jobs.run_due_ai_visibility(now=now, providers=[Fixed("claude", text="BTS")]) == [due]
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_ai_run.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: `app/ai_visibility/run.py`**

```python
"""Asking every enabled prompt of every model, analysing and storing each answer."""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from sqlalchemy import insert, select

from app.ai_visibility.detect import Brand, analyze
from app.ai_visibility.providers import Answer, configured_providers
from app.db.engine import get_session_factory
from app.db.models import AiBrandTerm, AiPrompt, AiRun, AiVisibilityRun, Competitor, Project, utcnow

logger = logging.getLogger(__name__)
MAX_ANSWER = 8000
WORKERS = 3


def load_brands(session, project: Project) -> List[Brand]:
    by_owner: Dict[str, List[str]] = defaultdict(list)
    for term in session.scalars(select(AiBrandTerm).where(AiBrandTerm.project_id == project.id).order_by(AiBrandTerm.id)):
        by_owner[term.owner].append(term.term)
    own = list(by_owner.get(project.domain, []))
    if project.name and project.name != project.domain and project.name not in own:
        own.append(project.name)
    brands = [Brand(project.domain, True, tuple(own), project.domain)]
    for domain in session.scalars(select(Competitor.domain).where(Competitor.project_id == project.id).order_by(Competitor.id)):
        brands.append(Brand(domain, False, tuple(by_owner.get(domain, [])), domain))
    return brands


def run_project(project_id: int, providers=None, trigger: str = "manual", factory=None) -> Dict[str, Any]:
    factory = factory or get_session_factory()
    providers = providers if providers is not None else configured_providers()
    with factory() as session:
        project = session.get(Project, project_id)
        prompts = [(p.id, p.text) for p in session.scalars(select(AiPrompt).where(
            AiPrompt.project_id == project_id, AiPrompt.enabled.is_(True)).order_by(AiPrompt.id))]
        brands = load_brands(session, project)
    if not prompts:
        return {"status": "no_prompts"}
    if not providers:
        return {"status": "not_configured"}
    dry = any(p.dry_run for p in providers)
    with factory.begin() as session:
        run = AiRun(project_id=project_id, started_at=utcnow(), trigger=trigger, dry_run=dry, calls=0, errors=0)
        session.add(run)
        session.flush()
        run_id = run.id

    hint = [((b.terms[0] if b.terms else b.domain), b.domain) for b in brands]
    jobs = [(prompt_id, text, provider) for prompt_id, text in prompts for provider in providers]

    def call(job):
        _, text, provider = job
        try:
            return provider.ask(text, brands_hint=hint)
        except Exception as exc:
            logger.error("%s failed on a prompt: %s", provider.name, exc, exc_info=exc)
            return Answer(model=provider.model, error=f"unexpected error ({type(exc).__name__})")

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        answers = list(pool.map(call, jobs))

    now, rows, errors, ok, mentions = utcnow(), [], 0, 0, 0
    for (prompt_id, text, provider), answer in zip(jobs, answers):
        if answer.error:
            errors += 1
            facts = {"mentioned": False, "position": None, "brands_mentioned": [], "cited": False}
        else:
            facts = analyze(answer.text, answer.citations, brands)
            ok += 1
            mentions += int(facts["mentioned"])
        rows.append({"run_id": run_id, "project_id": project_id, "ran_at": now, "provider": provider.name,
                     "model": (answer.model or provider.model or "")[:64], "prompt": text, "prompt_id": prompt_id,
                     "answer": (answer.text or "")[:MAX_ANSWER], "mentioned": facts["mentioned"],
                     "position": facts["position"], "brands_json": facts["brands_mentioned"], "cited": facts["cited"],
                     "citations_json": answer.citations[:20], "error": answer.error, "dry_run": provider.dry_run,
                     "result_json": {}})
    with factory.begin() as session:
        session.execute(insert(AiVisibilityRun), rows)
        run = session.get(AiRun, run_id)
        run.finished_at, run.calls, run.errors = now, len(rows), errors
        session.get(Project, project_id).last_ai_run_at = now
    return {"status": "ran", "run_id": run_id, "calls": len(rows), "errors": errors, "dry_run": dry,
            "mention_rate": round(mentions / ok, 3) if ok else None}
```

- [ ] **Step 4: The weekly job** (`app/scheduler/jobs.py`)

Add after `run_due_backlink_refreshes`:

```python
def run_due_ai_visibility(now: Optional[datetime] = None, providers=None) -> List[int]:
    """Weekly AI Visibility runs for projects that opted in. Never when every
    model is a dry run: made-up answers must not pile up on a schedule."""
    from app.ai_visibility.providers import configured_providers
    from app.ai_visibility.run import run_project

    providers = providers if providers is not None else configured_providers()
    if not providers or all(p.dry_run for p in providers):
        logger.warning("Scheduled AI Visibility runs skipped: no live AI provider")
        return []
    now = now or utcnow()
    factory = get_session_factory()
    with factory() as session:
        due = [(p.id, p.last_ai_run_at) for p in session.scalars(select(Project).where(Project.ai_schedule == "weekly")).all()
               if p.last_ai_run_at is None or now - as_utc(p.last_ai_run_at) >= timedelta(days=7)]
    ran: List[int] = []
    for project_id, previous in due:
        with factory() as session:
            if not claim(session, project_id, previous, now, column=Project.last_ai_run_at):
                continue
        try:
            result = run_project(project_id, providers=providers, trigger="scheduled")
            if result["status"] == "ran":
                ran.append(project_id)
        except Exception as exc:
            logger.error("AI Visibility run of project %s failed: %s", project_id, exc, exc_info=exc)
    return ran
```

In `start_scheduler`, add `scheduler.add_job(run_due_ai_visibility, "interval", hours=6, id="run_due_ai_visibility", max_instances=1, coalesce=True)`.

- [ ] **Step 5: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_ai_run.py tests/test_scheduler.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/ai_visibility/run.py apps/backend/app/scheduler/jobs.py apps/backend/tests/test_ai_run.py
git commit -m "feat(ai-visibility): run every prompt x model in parallel, store analysed answers; opt-in weekly job"
```

---

### Task 5: API

**Files:**
- Create: `apps/backend/app/api/ai_visibility.py`, `apps/backend/tests/test_ai_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces:
  - `GET /api/projects/{id}/ai-visibility`
  - `GET/POST /api/projects/{id}/ai-visibility/prompts`
  - `PATCH/DELETE /api/ai-prompts/{id}`
  - `GET/PUT /api/projects/{id}/ai-visibility/brands`
  - `POST /api/projects/{id}/ai-visibility/run`
  - `GET /api/projects/{id}/ai-visibility/answers`
  - `rates(rows) -> {mention_rate, avg_position, cited_rate}`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_ai_api.py -q`
Expected: FAIL.

- [ ] **Step 3: `app/api/ai_visibility.py`**

```python
"""AI Visibility (Phase 7.1): prompts, brand terms, runs, results."""

from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Response
from sqlalchemy import delete, desc, func, select

from app.ai_visibility.detect import citation_domain, highlights
from app.ai_visibility.providers import provider_status
from app.ai_visibility.run import load_brands, run_project
from app.api.projects import _factory
from app.db.models import AiBrandTerm, AiPrompt, AiRun, AiVisibilityRun, Competitor, Project, as_utc

router = APIRouter()
MAX_PROMPTS = 25
MAX_TERMS = 10


def _project(session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def rates(rows) -> Dict[str, Optional[float]]:
    ok = [r for r in rows if not r.error]
    positions = [r.position for r in ok if r.position]
    return {"mention_rate": round(sum(r.mentioned for r in ok) / len(ok), 3) if ok else None,
            "avg_position": round(sum(positions) / len(positions), 2) if positions else None,
            "cited_rate": round(sum(r.cited for r in ok) / len(ok), 3) if ok else None}


def _run_summary(run: AiRun, rows) -> Dict[str, Any]:
    providers = sorted({r.provider for r in rows})
    return {"run_id": run.id, "started_at": as_utc(run.started_at).isoformat(), "dry_run": run.dry_run,
            "calls": run.calls, "errors": run.errors, **rates(rows),
            "by_provider": {p: rates([r for r in rows if r.provider == p]) for p in providers}}


def _prompt_json(p: AiPrompt) -> Dict[str, Any]:
    return {"id": p.id, "text": p.text, "enabled": p.enabled}


@router.get("/projects/{project_id}/ai-visibility")
def overview(project_id: int):
    status = provider_status()
    with _factory()() as session:
        project = _project(session, project_id)
        runs = session.scalars(select(AiRun).where(AiRun.project_id == project_id, AiRun.finished_at.is_not(None))
                               .order_by(desc(AiRun.started_at), desc(AiRun.id)).limit(20)).all()
        rows_by_run = {run.id: session.scalars(select(AiVisibilityRun).where(AiVisibilityRun.run_id == run.id)).all()
                       for run in runs}
        latest = _run_summary(runs[0], rows_by_run[runs[0].id]) if runs else None
        previous = _run_summary(runs[1], rows_by_run[runs[1].id]) if len(runs) > 1 else None
        trend = [{"run_id": r.id, "started_at": as_utc(r.started_at).isoformat(),
                  "mention_rate": rates(rows_by_run[r.id])["mention_rate"],
                  "by_provider": {p: rates([x for x in rows_by_run[r.id] if x.provider == p])["mention_rate"]
                                  for p in sorted({x.provider for x in rows_by_run[r.id]})}} for r in reversed(runs)]
        share, cited = [], []
        if runs:
            ok = [r for r in rows_by_run[runs[0].id] if not r.error]
            brands = load_brands(session, project)
            share = sorted(({"owner": b.owner, "is_self": b.is_self,
                             "rate": round(sum(b.owner in (r.brands_json or []) for r in ok) / len(ok), 3) if ok else 0.0}
                            for b in brands), key=lambda s: (-s["rate"], not s["is_self"], s["owner"]))
            counts = Counter(d for r in ok for d in {citation_domain(c) for c in (r.citations_json or [])} if d)
            cited = [{"domain": d, "count": n, "is_self": d == project.domain or d.endswith("." + project.domain)}
                     for d, n in counts.most_common(10)]
        return {"providers": status, "dry_run": any(s["dry_run"] for s in status) or bool(latest and latest["dry_run"]),
                "schedule": project.ai_schedule,
                "last_run_at": as_utc(project.last_ai_run_at).isoformat() if project.last_ai_run_at else None,
                "latest": latest, "previous": previous, "trend": trend, "share_of_voice": share, "top_cited": cited}


@router.get("/projects/{project_id}/ai-visibility/prompts")
def list_prompts(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
        return {"items": [_prompt_json(p) for p in session.scalars(
            select(AiPrompt).where(AiPrompt.project_id == project_id).order_by(AiPrompt.id))]}


def _clean_text(value: Any) -> str:
    text = (value or "").strip() if isinstance(value, str) else ""
    if not 1 <= len(text) <= 300:
        raise HTTPException(status_code=422, detail="prompt text must be 1-300 characters")
    return text


@router.post("/projects/{project_id}/ai-visibility/prompts", status_code=201)
def add_prompt(project_id: int, body: Dict[str, Any] = Body(...)):
    text = _clean_text(body.get("text"))
    with _factory().begin() as session:
        _project(session, project_id)
        count = session.scalar(select(func.count()).select_from(AiPrompt).where(AiPrompt.project_id == project_id))
        if count >= MAX_PROMPTS:
            raise HTTPException(status_code=409, detail=f"a project can have at most {MAX_PROMPTS} prompts")
        prompt = AiPrompt(project_id=project_id, text=text)
        session.add(prompt)
        session.flush()
        return _prompt_json(prompt)


@router.patch("/ai-prompts/{prompt_id}")
def update_prompt(prompt_id: int, body: Dict[str, Any] = Body(...)):
    with _factory().begin() as session:
        prompt = session.get(AiPrompt, prompt_id)
        if prompt is None:
            raise HTTPException(status_code=404, detail="prompt not found")
        if "text" in body:
            prompt.text = _clean_text(body["text"])
        if "enabled" in body:
            prompt.enabled = bool(body["enabled"])
        session.flush()
        return _prompt_json(prompt)


@router.delete("/ai-prompts/{prompt_id}", status_code=204)
def delete_prompt(prompt_id: int):
    with _factory().begin() as session:
        prompt = session.get(AiPrompt, prompt_id)
        if prompt is None:
            raise HTTPException(status_code=404, detail="prompt not found")
        session.delete(prompt)
    return Response(status_code=204)


def _brands_json(session, project: Project) -> Dict[str, Any]:
    terms: Dict[str, List[str]] = {}
    for t in session.scalars(select(AiBrandTerm).where(AiBrandTerm.project_id == project.id).order_by(AiBrandTerm.id)):
        terms.setdefault(t.owner, []).append(t.term)
    competitors = session.scalars(select(Competitor.domain).where(Competitor.project_id == project.id).order_by(Competitor.id)).all()
    return {"self": {"domain": project.domain, "terms": terms.get(project.domain, [])},
            "competitors": [{"domain": d, "terms": terms.get(d, [])} for d in competitors]}


def _clean_terms(values: Any) -> List[str]:
    if not isinstance(values, list):
        raise HTTPException(status_code=422, detail="terms must be a list")
    out: List[str] = []
    for value in values:
        term = (value or "").strip() if isinstance(value, str) else ""
        if not 1 <= len(term) <= 100:
            raise HTTPException(status_code=422, detail="each term must be 1-100 characters")
        if term.lower() not in (t.lower() for t in out):
            out.append(term)
    if len(out) > MAX_TERMS:
        raise HTTPException(status_code=422, detail=f"at most {MAX_TERMS} terms per brand")
    return out


@router.get("/projects/{project_id}/ai-visibility/brands")
def get_brands(project_id: int):
    with _factory()() as session:
        return _brands_json(session, _project(session, project_id))


@router.put("/projects/{project_id}/ai-visibility/brands")
def put_brands(project_id: int, body: Dict[str, Any] = Body(...)):
    with _factory().begin() as session:
        project = _project(session, project_id)
        competitors = set(session.scalars(select(Competitor.domain).where(Competitor.project_id == project_id)))
        updates: Dict[str, List[str]] = {}
        if "self" in body:
            updates[project.domain] = _clean_terms(body["self"])
        for domain, values in (body.get("competitors") or {}).items():
            if domain not in competitors:
                raise HTTPException(status_code=400, detail=f"{domain} is not a competitor of this project")
            updates[domain] = _clean_terms(values)
        for owner, terms in updates.items():
            session.execute(delete(AiBrandTerm).where(AiBrandTerm.project_id == project_id, AiBrandTerm.owner == owner))
            session.add_all(AiBrandTerm(project_id=project_id, owner=owner, term=t) for t in terms)
        session.flush()
        return _brands_json(session, project)


@router.post("/projects/{project_id}/ai-visibility/run")
def run_now(project_id: int):
    with _factory()() as session:
        _project(session, project_id)
    return run_project(project_id)


@router.get("/projects/{project_id}/ai-visibility/answers")
def answers(project_id: int, run_id: Optional[int] = None, provider: Optional[str] = None,
            prompt_id: Optional[int] = None, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    with _factory()() as session:
        project = _project(session, project_id)
        if run_id is None:
            run_id = session.scalar(select(AiRun.id).where(AiRun.project_id == project_id, AiRun.finished_at.is_not(None))
                                    .order_by(desc(AiRun.started_at), desc(AiRun.id)).limit(1))
        if run_id is None:
            return {"run_id": None, "total": 0, "items": []}
        query = select(AiVisibilityRun).where(AiVisibilityRun.run_id == run_id, AiVisibilityRun.project_id == project_id)
        if provider:
            query = query.where(AiVisibilityRun.provider == provider)
        if prompt_id is not None:
            query = query.where(AiVisibilityRun.prompt_id == prompt_id)
        rows = session.scalars(query.order_by(AiVisibilityRun.prompt_id, AiVisibilityRun.provider, AiVisibilityRun.id)).all()
        brands = load_brands(session, project)
        items = [{"id": r.id, "prompt": r.prompt, "provider": r.provider, "model": r.model, "mentioned": r.mentioned,
                  "position": r.position, "brands": r.brands_json or [], "cited": r.cited,
                  "citations": r.citations_json or [], "error": r.error, "answer": r.answer,
                  "highlights": highlights(r.answer, brands) if not r.error else []}
                 for r in rows[offset:offset + limit]]
        return {"run_id": run_id, "total": len(rows), "items": items}
```

In `app/main.py`, after the backlinks router lines:

```python
from app.api.ai_visibility import router as ai_visibility_router  # noqa: E402
app.include_router(ai_visibility_router, prefix="/api")
```

- [ ] **Step 4: Run and pass, gated full suite, then commit**

```bash
python -m pytest tests/test_ai_api.py -q
python -m pytest -q > /tmp/t.txt 2>&1; echo "exit=$?"; tail -1 /tmp/t.txt
git add apps/backend/app/api/ai_visibility.py apps/backend/app/main.py apps/backend/tests/test_ai_api.py
git commit -m "feat(ai-visibility): API (overview math, prompts, brand terms, run, answers with highlights)"
```

---

### Task 6: Frontend

**Files:**
- Modify: `packages/shared/src/types/platform.ts`, `apps/frontend/services/platform.ts`, `components/platform/project-tabs.tsx`
- Create:
  - `apps/frontend/lib/ai-visibility.ts` (+ `lib/__tests__/ai-visibility.test.ts`)
  - `apps/frontend/components/platform/ai-charts.tsx`
  - `apps/frontend/components/platform/ai-answers.tsx`
  - `apps/frontend/components/platform/ai-setup.tsx`
  - `apps/frontend/app/projects/[id]/ai-visibility/page.tsx`
  - `components/__tests__/ai-visibility-page.test.tsx`

**Interfaces:**
- Produces:
  - Types `AiProviderStatus, AiRates, AiRunSummary, AiOverview, AiPrompt, AiBrands, AiAnswer, AiRunResult`
  - `Platform.aiOverview, aiPrompts, addAiPrompt, updateAiPrompt, deleteAiPrompt, aiBrands, saveAiBrands, runAi, aiAnswers`
  - `segments(text, highlights)`, `ordinal(n)`, `pct(rate)`, `estimate(prompts, providers)`

- [ ] **Step 1: Types, service, helpers**

Append to `packages/shared/src/types/platform.ts`:

```ts
// AI Visibility (backend Phase 7.1).
export interface AiProviderStatus { name: string; model: string | null; dry_run: boolean; configured: boolean; hint: string | null }
export interface AiRates { mention_rate: number | null; avg_position: number | null; cited_rate: number | null }
export interface AiRunSummary extends AiRates {
  run_id: number; started_at: string; dry_run: boolean; calls: number; errors: number; by_provider: Record<string, AiRates>;
}
export interface AiOverview {
  providers: AiProviderStatus[]; dry_run: boolean; schedule: "weekly" | null; last_run_at: string | null;
  latest: AiRunSummary | null; previous: AiRunSummary | null;
  trend: { run_id: number; started_at: string; mention_rate: number | null; by_provider: Record<string, number | null> }[];
  share_of_voice: { owner: string; is_self: boolean; rate: number }[];
  top_cited: { domain: string; count: number; is_self: boolean }[];
}
export interface AiPrompt { id: number; text: string; enabled: boolean }
export interface AiBrands { self: { domain: string; terms: string[] }; competitors: { domain: string; terms: string[] }[] }
export interface AiAnswer {
  id: number; prompt: string; provider: string; model: string; mentioned: boolean; position: number | null; brands: string[];
  cited: boolean; citations: { url: string; title: string }[]; error: string | null; answer: string;
  highlights: { start: number; end: number; owner: string }[];
}
export interface AiRunResult { status: "ran" | "no_prompts" | "not_configured"; run_id?: number; calls?: number; errors?: number; dry_run?: boolean; mention_rate?: number | null }
```

In `ProjectSummary`, add `ai_schedule?: "weekly" | null; last_ai_run_at?: string | null;`.

In `services/platform.ts`:
- Import the types.
- Widen `updateProject`'s body with `ai_schedule: "weekly" | null`.
- Add:

```ts
  aiOverview: (id: number) => request<AiOverview>(`/projects/${id}/ai-visibility`),
  aiPrompts: (id: number) => request<{ items: AiPrompt[] }>(`/projects/${id}/ai-visibility/prompts`),
  addAiPrompt: (id: number, text: string) => request<AiPrompt>(`/projects/${id}/ai-visibility/prompts`, post({ text })),
  updateAiPrompt: (promptId: number, body: { text?: string; enabled?: boolean }) => request<AiPrompt>(`/ai-prompts/${promptId}`, patch(body)),
  deleteAiPrompt: (promptId: number) => request<void>(`/ai-prompts/${promptId}`, { method: "DELETE" }),
  aiBrands: (id: number) => request<AiBrands>(`/projects/${id}/ai-visibility/brands`),
  saveAiBrands: (id: number, body: { self?: string[]; competitors?: Record<string, string[]> }) =>
    request<AiBrands>(`/projects/${id}/ai-visibility/brands`, { method: "PUT", body: JSON.stringify(body) }),
  runAi: (id: number) => request<AiRunResult>(`/projects/${id}/ai-visibility/run`, post()),
  aiAnswers: (id: number, runId?: number) => request<{ run_id: number | null; total: number; items: AiAnswer[] }>(
    `/projects/${id}/ai-visibility/answers${runId != null ? `?run_id=${runId}` : ""}`),
```

`apps/frontend/lib/ai-visibility.ts`:

```ts
export interface Segment { text: string; owner?: string }

/** Split an answer at the server's highlight ranges, for rendering as text inside <mark>, never as HTML. */
export function segments(text: string, highlights: { start: number; end: number; owner: string }[]): Segment[] {
  const out: Segment[] = [];
  let at = 0;
  for (const h of [...highlights].sort((a, b) => a.start - b.start)) {
    if (h.start < at || h.end > text.length || h.end <= h.start) continue;
    if (h.start > at) out.push({ text: text.slice(at, h.start) });
    out.push({ text: text.slice(h.start, h.end), owner: h.owner });
    at = h.end;
  }
  if (at < text.length) out.push({ text: text.slice(at) });
  return out;
}

export function ordinal(n: number): string {
  const rem100 = n % 100;
  if (rem100 >= 11 && rem100 <= 13) return `${n}th`;
  return `${n}${({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[n % 10] ?? "th"}`;
}

export const pct = (rate: number | null | undefined) => (rate == null ? "—" : `${Math.round(rate * 100)}%`);

/** Rough cost of one run: about $0.03 per prompt per model with web search. */
export const estimate = (prompts: number, providers: number) => `≈ $${(prompts * providers * 0.03).toFixed(2)}`;

export const safeUrl = (url: string) => /^https?:\/\//i.test(url) ? url : null;
```

`lib/__tests__/ai-visibility.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { estimate, ordinal, pct, safeUrl, segments } from "@/lib/ai-visibility";

describe("ai-visibility helpers", () => {
  it("splits text at highlights, ignoring bad ranges", () => {
    expect(segments("Amazon then BTS!", [{ start: 12, end: 15, owner: "me" }, { start: 0, end: 6, owner: "amz" }, { start: 3, end: 5, owner: "x" }]))
      .toEqual([{ text: "Amazon", owner: "amz" }, { text: " then " }, { text: "BTS", owner: "me" }, { text: "!" }]);
    expect(segments("abc", [{ start: 1, end: 9, owner: "x" }])).toEqual([{ text: "abc" }]);
  });
  it("formats", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 22].map(ordinal)).toEqual(["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd"]);
    expect(pct(0.756)).toBe("76%");
    expect(estimate(2, 3)).toBe("≈ $0.18");
    expect(safeUrl("javascript:alert(1)")).toBeNull();
    expect(safeUrl("https://a.com/")).toBe("https://a.com/");
  });
});
```

Rebuild shared: `cd packages/shared && npx tsc`.

- [ ] **Step 2: Write the failing page test** (`components/__tests__/ai-visibility-page.test.tsx`)

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import AiVisibilityPage from "@/app/projects/[id]/ai-visibility/page";
import { Platform } from "@/services/platform";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }), usePathname: () => "/projects/7/ai-visibility" }));

const rates = (m: number, p: number | null, c: number) => ({ mention_rate: m, avg_position: p, cited_rate: c });
const summary = (id: number, m: number, p: number | null, c: number) => ({
  run_id: id, started_at: `2026-10-2${id}T10:00:00+00:00`, dry_run: false, calls: 6, errors: 0, ...rates(m, p, c),
  by_provider: { claude: rates(m, p, c), openai: rates(m, p, c) } });
const providers = [{ name: "claude", model: "claude-sonnet-5", dry_run: false, configured: true, hint: null },
                   { name: "openai", model: "gpt-x", dry_run: false, configured: true, hint: null },
                   { name: "gemini", model: null, dry_run: false, configured: false, hint: "set GEMINI_API_KEY and GEMINI_MODEL" }];
const overview = (over: object = {}) => ({
  providers, dry_run: false, schedule: null, last_run_at: null,
  latest: summary(2, 0.6, 1.5, 0.4), previous: summary(1, 0.4, 2, 0.4),
  trend: [{ run_id: 1, started_at: "2026-10-21T10:00:00+00:00", mention_rate: 0.4, by_provider: { claude: 0.5, openai: 0.3 } },
          { run_id: 2, started_at: "2026-10-22T10:00:00+00:00", mention_rate: 0.6, by_provider: { claude: 0.7, openai: 0.5 } }],
  share_of_voice: [{ owner: "books.toscrape.com", is_self: true, rate: 0.6 }, { owner: "amazon.com", is_self: false, rate: 0.5 }],
  top_cited: [{ domain: "books.toscrape.com", count: 3, is_self: true }],
  ...over,
});
const answer = { id: 1, prompt: "best rare books", provider: "claude", model: "claude-sonnet-5", mentioned: true, position: 2,
  brands: ["amazon.com", "books.toscrape.com"], cited: true, error: null, answer: "Amazon then Books to Scrape.",
  citations: [{ url: "https://books.toscrape.com/", title: "Books" }, { url: "javascript:alert(1)", title: "evil" }],
  highlights: [{ start: 0, end: 6, owner: "amazon.com" }, { start: 12, end: 27, owner: "books.toscrape.com" }] };

beforeEach(() => {
  vi.restoreAllMocks();
  vi.spyOn(Platform, "aiPrompts").mockResolvedValue({ items: [{ id: 1, text: "best rare books", enabled: true }, { id: 2, text: "cheap books", enabled: true }] });
  vi.spyOn(Platform, "aiBrands").mockResolvedValue({ self: { domain: "books.toscrape.com", terms: ["BTS"] },
    competitors: [{ domain: "amazon.com", terms: ["Amazon"] }] });
  vi.spyOn(Platform, "aiAnswers").mockResolvedValue({ run_id: 2, total: 1, items: [answer] });
});

describe("AI Visibility tab", () => {
  it("shows KPIs with changes (position: lower is better)", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText("60%")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 20 pts")).toBeInTheDocument();
    expect(screen.getByLabelText("improved by 0.5")).toBeInTheDocument();
    expect(screen.getByText(/set GEMINI_API_KEY and GEMINI_MODEL/)).toBeInTheDocument();
  });

  it("shows an empty state before the first run, and the preview banner on dry run", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview({ latest: null, previous: null, trend: [], share_of_voice: [], top_cited: [], dry_run: true }) as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText(/No runs yet/)).toBeInTheDocument();
    expect(screen.getAllByRole("note").length).toBeGreaterThan(0);
  });

  it("runs now with a cost estimate, and toggles weekly", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    const run = vi.spyOn(Platform, "runAi").mockResolvedValue({ status: "ran", run_id: 3, calls: 4, errors: 1, dry_run: false, mention_rate: 0.5 });
    const update = vi.spyOn(Platform, "updateProject").mockResolvedValue({} as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText(/≈ \$0\.12/)).toBeInTheDocument();          // 2 prompts × 2 configured models
    await userEvent.click(screen.getByRole("button", { name: /run now/i }));
    expect(run).toHaveBeenCalledWith(7);
    expect(await screen.findByText(/Ran 4 calls \(1 failed\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("switch", { name: /weekly/i }));
    expect(update).toHaveBeenCalledWith(7, { ai_schedule: "weekly" });
  });

  it("adds prompts and brand aliases", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    const add = vi.spyOn(Platform, "addAiPrompt").mockResolvedValue({ id: 3, text: "rare first editions", enabled: true });
    const save = vi.spyOn(Platform, "saveAiBrands").mockResolvedValue({ self: { domain: "books.toscrape.com", terms: ["BTS", "Books to Scrape"] }, competitors: [] });
    render(<AiVisibilityPage params={{ id: "7" }} />);
    await userEvent.type(await screen.findByLabelText(/new prompt/i), "rare first editions");
    await userEvent.click(screen.getByRole("button", { name: /add prompt/i }));
    expect(add).toHaveBeenCalledWith(7, "rare first editions");
    await userEvent.type(screen.getByLabelText(/alias for books.toscrape.com/i), "Books to Scrape");
    await userEvent.click(screen.getByRole("button", { name: /add alias for books.toscrape.com/i }));
    await waitFor(() => expect(save).toHaveBeenCalledWith(7, { self: ["BTS", "Books to Scrape"] }));
  });

  it("expands an answer with marked brands and only safe links", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    expect(await screen.findByText("2nd of 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show answer: best rare books \(claude\)/i }));
    const marks = document.querySelectorAll("mark");
    expect([...marks].map((m) => m.textContent)).toEqual(["Amazon", "Books to Scrape"]);
    const link = screen.getByRole("link", { name: "Books" });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "evil" })).toBeNull();
  });

  it("charts have table views", async () => {
    vi.spyOn(Platform, "aiOverview").mockResolvedValue(overview() as any);
    render(<AiVisibilityPage params={{ id: "7" }} />);
    const toggles = await screen.findAllByRole("button", { name: /show as table/i });
    await userEvent.click(toggles[1]);
    expect(screen.getByRole("cell", { name: "amazon.com" })).toBeInTheDocument();
  });
});
```

`brands` lists the owners mentioned. With 2 brands mentioned and position 2,
the label reads "2nd of 2".

- [ ] **Step 3: Run and watch it fail**

Run: `cd apps/frontend && npx vitest run lib/__tests__/ai-visibility.test.ts components/__tests__/ai-visibility-page.test.tsx`
Expected: FAIL.

- [ ] **Step 4: Components**

`components/platform/ai-charts.tsx` (trend: one line per model with a legend, never dual axis; share of voice: bars):

```tsx
"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { AiOverview } from "@seo-auditor/shared";

import { pct } from "@/lib/ai-visibility";
import { SERIES_LIGHT } from "@/lib/platform-charts";

function Frame({ title, asTable, onToggle, children }: { title: string; asTable: boolean; onToggle: () => void; children: React.ReactNode }) {
  return (
    <section className="min-w-0 rounded-[18px] border bg-card p-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-semibold tracking-tight">{title}</h2>
        <button type="button" onClick={onToggle} className="rounded-full border px-3 py-1 text-xs active:scale-95">{asTable ? "Show as chart" : "Show as table"}</button>
      </div>
      {children}
    </section>
  );
}

export function MentionTrend({ trend }: { trend: AiOverview["trend"] }) {
  const [asTable, setAsTable] = useState(false);
  const models = Array.from(new Set(trend.flatMap((t) => Object.keys(t.by_provider))));
  const data = trend.map((t) => ({ label: new Date(t.started_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    ...Object.fromEntries(models.map((m) => [m, t.by_provider[m] != null ? Math.round((t.by_provider[m] as number) * 100) : null])) }));
  return (
    <Frame title="Mention rate per run" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Run</th>{models.map((m) => <th key={m} className="py-1">{m}</th>)}</tr></thead>
          <tbody>{trend.map((t, i) => <tr key={t.run_id}><td className="py-1">{data[i].label}</td>{models.map((m) => <td key={m} className="py-1 tabular-nums">{pct(t.by_provider[m])}</td>)}</tr>)}</tbody></table>
      ) : (
        <div className="h-56 w-full" role="img" aria-label="Mention rate per run by model">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} unit="%" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Legend itemSorter={null} wrapperStyle={{ fontSize: 12 }} />
              {models.map((m, i) => <Line key={m} type="monotone" dataKey={m} stroke={SERIES_LIGHT[i % SERIES_LIGHT.length]} strokeWidth={2} dot={{ r: 3 }} connectNulls={false} />)}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </Frame>
  );
}

export function ShareOfVoice({ share }: { share: AiOverview["share_of_voice"] }) {
  const [asTable, setAsTable] = useState(false);
  const data = share.map((s) => ({ owner: s.owner, value: Math.round(s.rate * 100), isSelf: s.is_self }));
  return (
    <Frame title="Share of voice (latest run)" asTable={asTable} onToggle={() => setAsTable((v) => !v)}>
      {asTable ? (
        <table className="w-full text-[13px]"><thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Brand</th><th className="py-1">Answers mentioning it</th></tr></thead>
          <tbody>{share.map((s) => <tr key={s.owner}><td className="py-1">{s.owner}</td><td className="py-1 tabular-nums">{pct(s.rate)}{s.is_self ? " (you)" : ""}</td></tr>)}</tbody></table>
      ) : (
        <div className="w-full" style={{ height: Math.max(120, data.length * 36) }} role="img" aria-label="Share of voice by brand">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 8 }}>
              <XAxis type="number" domain={[0, 100]} unit="%" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <YAxis type="category" dataKey="owner" width={140} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
              <Bar dataKey="value" name="Mentioned in" radius={[0, 4, 4, 0]}>
                {data.map((d) => <Cell key={d.owner} fill={d.isSelf ? SERIES_LIGHT[0] : "hsl(var(--muted-foreground))"} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </Frame>
  );
}
```

`components/platform/ai-answers.tsx`:

```tsx
"use client";

import { Fragment, useState } from "react";
import { CheckCircle2, Link2, MinusCircle } from "lucide-react";
import type { AiAnswer } from "@seo-auditor/shared";

import { ordinal, safeUrl, segments } from "@/lib/ai-visibility";

function Pill({ on, yes, no }: { on: boolean; yes: string; no: string }) {
  return on ? (
    <span className="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2 py-0.5 text-[11px] font-medium text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400"><CheckCircle2 className="h-3 w-3" aria-hidden />{yes}</span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] font-medium text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400"><MinusCircle className="h-3 w-3" aria-hidden />{no}</span>
  );
}

export function AiAnswers({ items }: { items: AiAnswer[] }) {
  const [open, setOpen] = useState<number | null>(null);
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No answers in this run.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground"><tr className="border-b">
          <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Prompt</th><th className="py-2 pr-4 font-medium">Model</th>
          <th className="py-2 pr-4 font-medium">Mentioned</th><th className="py-2 pr-4 font-medium">Position</th><th className="py-2 font-medium">Cited</th></tr></thead>
        <tbody className="divide-y">
          {items.map((a) => {
            const isOpen = open === a.id;
            return (
              <Fragment key={a.id}>
                <tr className="align-top">
                  <td className="sticky left-0 max-w-[180px] bg-card py-2 pr-4 sm:max-w-[320px]">
                    <button type="button" onClick={() => setOpen(isOpen ? null : a.id)} aria-expanded={isOpen}
                            aria-label={`Show answer: ${a.prompt} (${a.provider})`} className="text-left hover:text-primary">{a.prompt}</button>
                  </td>
                  <td className="py-2 pr-4 text-muted-foreground">{a.provider}</td>
                  {a.error ? <td colSpan={3} className="py-2 text-muted-foreground">Failed: {a.error}</td> : (
                    <>
                      <td className="py-2 pr-4"><Pill on={a.mentioned} yes="Mentioned" no="Not mentioned" /></td>
                      <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{a.position ? `${ordinal(a.position)} of ${a.brands.length}` : "—"}</td>
                      <td className="py-2"><Pill on={a.cited} yes="Cited" no="Not cited" /></td>
                    </>
                  )}
                </tr>
                {isOpen && !a.error && (
                  <tr><td colSpan={5} className="bg-muted/30 px-3 py-3">
                    <p className="whitespace-pre-wrap text-sm leading-relaxed">
                      {segments(a.answer, a.highlights).map((s, i) => s.owner
                        ? <mark key={i} className="rounded bg-amber-100 px-0.5 text-foreground dark:bg-amber-900/50">{s.text}</mark>
                        : <Fragment key={i}>{s.text}</Fragment>)}
                    </p>
                    {a.citations.length > 0 && (
                      <ul className="mt-3 space-y-1 text-xs">
                        {a.citations.map((c, i) => {
                          const href = safeUrl(c.url);
                          return href ? (
                            <li key={i} className="flex items-center gap-1 break-all"><Link2 className="h-3 w-3 shrink-0" aria-hidden />
                              <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{c.title || href}</a></li>
                          ) : null;
                        })}
                      </ul>
                    )}
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

`components/platform/ai-setup.tsx`:

```tsx
"use client";

import { useState } from "react";
import { X } from "lucide-react";
import type { AiBrands, AiPrompt } from "@seo-auditor/shared";

import { ApiError, Platform } from "@/services/platform";

function TermsRow({ owner, terms, onSave }: { owner: string; terms: string[]; onSave: (terms: string[]) => Promise<void> }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="min-w-[140px] text-sm font-medium">{owner}</span>
      {terms.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">{t}
          <button type="button" aria-label={`Remove ${t}`} onClick={() => onSave(terms.filter((x) => x !== t))}><X className="h-3 w-3" aria-hidden /></button></span>
      ))}
      <input aria-label={`Alias for ${owner}`} value={value} maxLength={100} onChange={(e) => setValue(e.target.value)}
             className="h-8 w-40 rounded-full border bg-background px-3 text-xs" placeholder="Add a name…" />
      <button type="button" aria-label={`Add alias for ${owner}`} disabled={!value.trim()}
              onClick={async () => { await onSave([...terms, value.trim()]); setValue(""); }}
              className="h-8 rounded-full border px-3 text-xs active:scale-95 disabled:opacity-50">Add</button>
    </div>
  );
}

export function BrandTerms({ projectId, brands, onChanged }: { projectId: number; brands: AiBrands; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const save = async (body: { self?: string[]; competitors?: Record<string, string[]> }) => {
    setError(null);
    try { await Platform.saveAiBrands(projectId, body); onChanged(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Could not save"); }
  };
  return (
    <section className="min-w-0 space-y-3 rounded-[18px] border bg-card p-5">
      <h2 className="font-semibold tracking-tight">Brand names</h2>
      <p className="text-xs text-muted-foreground">Matched as whole words, case-insensitive. Domains always count.</p>
      <TermsRow owner={brands.self.domain} terms={brands.self.terms} onSave={(terms) => save({ self: terms })} />
      {brands.competitors.map((c) => (
        <TermsRow key={c.domain} owner={c.domain} terms={c.terms} onSave={(terms) => save({ competitors: { [c.domain]: terms } })} />
      ))}
      {brands.competitors.length === 0 && <p className="text-xs text-muted-foreground">Add competitors in the Rank Tracker tab to compare against them.</p>}
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
    </section>
  );
}

export function Prompts({ projectId, prompts, onChanged }: { projectId: number; prompts: AiPrompt[]; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); onChanged(); } catch (e) { setError(e instanceof ApiError ? e.detail : "Something went wrong"); }
  };
  return (
    <section className="min-w-0 space-y-3 rounded-[18px] border bg-card p-5">
      <h2 className="font-semibold tracking-tight">Prompts <span className="text-xs font-normal text-muted-foreground">({prompts.length}/25)</span></h2>
      <ul className="divide-y text-sm">
        {prompts.map((p) => (
          <li key={p.id} className="flex items-center gap-3 py-2">
            <input type="checkbox" aria-label={`Enable ${p.text}`} checked={p.enabled}
                   onChange={(e) => act(() => Platform.updateAiPrompt(p.id, { enabled: e.target.checked }))} />
            <span className={`min-w-0 flex-1 break-words ${p.enabled ? "" : "text-muted-foreground line-through"}`}>{p.text}</span>
            <button type="button" aria-label={`Delete ${p.text}`} onClick={() => act(() => Platform.deleteAiPrompt(p.id))}
                    className="rounded-full border px-2 py-0.5 text-xs active:scale-95">Delete</button>
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); act(async () => { await Platform.addAiPrompt(projectId, text.trim()); setText(""); }); }}>
        <input aria-label="New prompt" value={text} maxLength={300} onChange={(e) => setText(e.target.value)}
               placeholder="e.g. best online bookstore for rare books" className="h-9 min-w-0 flex-1 rounded-full border bg-background px-3 text-sm" />
        <button type="submit" disabled={!text.trim() || prompts.length >= 25} aria-label="Add prompt"
                className="h-9 rounded-full border px-4 text-sm active:scale-95 disabled:opacity-50">Add</button>
      </form>
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
    </section>
  );
}
```

`app/projects/[id]/ai-visibility/page.tsx`:

```tsx
"use client";

import { useState } from "react";

import { AiAnswers } from "@/components/platform/ai-answers";
import { MentionTrend, ShareOfVoice } from "@/components/platform/ai-charts";
import { BrandTerms, Prompts } from "@/components/platform/ai-setup";
import { AsyncState } from "@/components/platform/async-state";
import { DeltaBadge } from "@/components/platform/delta-badge";
import { DryRunBanner } from "@/components/platform/dry-run-banner";
import { KpiTile } from "@/components/platform/kpi-tile";
import { PageHeader } from "@/components/platform/page-header";
import { estimate, pct } from "@/lib/ai-visibility";
import { change } from "@/lib/gsc";
import { useApi } from "@/lib/use-api";
import { ApiError, Platform } from "@/services/platform";

export default function AiVisibilityPage({ params }: { params: { id: string } }) {
  const projectId = Number(params.id);
  const overview = useApi(() => Platform.aiOverview(projectId), [projectId]);
  const prompts = useApi(() => Platform.aiPrompts(projectId), [projectId]);
  const brands = useApi(() => Platform.aiBrands(projectId), [projectId]);
  const answers = useApi(() => Platform.aiAnswers(projectId), [projectId, overview.data?.latest?.run_id]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const runNow = async () => {
    setBusy(true); setMessage(null);
    try {
      const r = await Platform.runAi(projectId);
      setMessage(r.status === "ran" ? `Ran ${r.calls} calls${r.errors ? ` (${r.errors} failed)` : ""}.`
        : r.status === "no_prompts" ? "Add a prompt first." : "No AI model is configured.");
      overview.reload();
    } catch (e) {
      setMessage(e instanceof ApiError ? e.detail : "Run failed");
    } finally {
      setBusy(false);
    }
  };

  const toggleWeekly = async (on: boolean) => {
    await Platform.updateProject(projectId, { ai_schedule: on ? "weekly" : null });
    overview.reload();
  };

  return (
    <div className="space-y-6">
      <PageHeader title="AI Visibility" description="Do AI assistants mention and cite this site when people ask? Answers come from each model's own web search." />
      <AsyncState state={overview}>
        {(o) => {
          const configured = o.providers.filter((p) => p.configured);
          const enabledPrompts = (prompts.data?.items ?? []).filter((p) => p.enabled).length;
          const l = o.latest, p = o.previous;
          return (
            <div className="space-y-6">
              <DryRunBanner show={o.dry_run} message="Preview data. No AI keys are set, so these answers are made up." />
              <div className="grid gap-4 xl:grid-cols-2">
                {brands.data && <BrandTerms projectId={projectId} brands={brands.data} onChanged={brands.reload} />}
                {prompts.data && <Prompts projectId={projectId} prompts={prompts.data.items} onChanged={prompts.reload} />}
              </div>
              <section className="flex flex-wrap items-center gap-4 rounded-[18px] border bg-card p-5 text-sm">
                <button type="button" onClick={runNow} disabled={busy} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">
                  {busy ? "Running…" : "Run now"}
                </button>
                <span className="text-xs text-muted-foreground">{estimate(enabledPrompts, configured.length)}: {enabledPrompts} prompts × {configured.length} models × ~$0.03</span>
                <div className="flex flex-wrap gap-2">
                  {o.providers.map((pr) => (
                    <span key={pr.name} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                      {pr.name}{pr.configured ? `: ${pr.model}${pr.dry_run ? " (dry run)" : ""}` : `: not configured (${pr.hint})`}
                    </span>
                  ))}
                </div>
                <label className="ml-auto flex items-center gap-2">
                  <button type="button" role="switch" aria-checked={o.schedule === "weekly"} aria-label="Weekly runs" onClick={() => toggleWeekly(o.schedule !== "weekly")}
                          className={`relative h-6 w-11 rounded-full transition-colors ${o.schedule === "weekly" ? "bg-primary" : "bg-muted"}`}>
                    <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-background transition-all ${o.schedule === "weekly" ? "left-[22px]" : "left-0.5"}`} />
                  </button>
                  Weekly
                </label>
                {message && <p className="w-full text-muted-foreground">{message}</p>}
              </section>
              {!l ? (
                <p className="rounded-[18px] border bg-card p-5 text-sm text-muted-foreground">No runs yet. Add prompts and press <strong>Run now</strong>.</p>
              ) : (
                <>
                  <div className="grid gap-4 sm:grid-cols-3">
                    <KpiTile label="Mention rate" value={pct(l.mention_rate)} hint="answers that name you"
                             delta={<DeltaBadge value={change(l.mention_rate != null ? l.mention_rate * 100 : null, p?.mention_rate != null ? p.mention_rate * 100 : null)} suffix=" pts" />} />
                    <KpiTile label="Avg. position" value={l.avg_position ?? "—"} hint="among tracked brands, when named"
                             delta={<DeltaBadge value={change(l.avg_position, p?.avg_position, 1)} lowerIsBetter />} />
                    <KpiTile label="Cited rate" value={pct(l.cited_rate)} hint="answers that cite your site"
                             delta={<DeltaBadge value={change(l.cited_rate != null ? l.cited_rate * 100 : null, p?.cited_rate != null ? p.cited_rate * 100 : null)} suffix=" pts" />} />
                  </div>
                  <div className="grid gap-4 lg:grid-cols-2">
                    <MentionTrend trend={o.trend} />
                    <ShareOfVoice share={o.share_of_voice} />
                  </div>
                  <section className="min-w-0 rounded-[18px] border bg-card p-5">
                    <h2 className="mb-3 font-semibold tracking-tight">Top cited domains <span className="text-xs font-normal text-muted-foreground">(latest run)</span></h2>
                    <ul className="divide-y text-[13px]">{o.top_cited.map((c) => (
                      <li key={c.domain} className="flex justify-between gap-3 py-1.5"><span className="min-w-0 break-all">{c.domain}{c.is_self && <strong className="ml-2 text-xs text-primary">you</strong>}</span>
                        <span className="tabular-nums text-muted-foreground">{c.count}</span></li>))}</ul>
                  </section>
                  <section className="min-w-0 rounded-[18px] border bg-card p-5">
                    <h2 className="mb-3 font-semibold tracking-tight">Answers <span className="text-xs font-normal text-muted-foreground">(latest run)</span></h2>
                    <AsyncState state={answers}>{(a) => <AiAnswers items={a.items} />}</AsyncState>
                  </section>
                </>
              )}
            </div>
          );
        }}
      </AsyncState>
    </div>
  );
}
```

Check `change(...)` in `lib/gsc.ts` (`change(now, before, digits = 0)`, rounding to integers by default). For mention 60 vs 40 it gives 20, labelled "improved by 20 pts" through the suffix. For position (1.5 − 2, 1 digit) it gives −0.5 with `lowerIsBetter`, labelled "improved by 0.5".

`components/platform/project-tabs.tsx`: add `{ suffix: "/ai-visibility", label: "AI Visibility" },` after Backlinks.

- [ ] **Step 5: Run and pass, gated, then commit**

```bash
npx vitest run > /tmp/fe.txt 2>&1; echo "vitest exit=$?"; grep -E "Tests " /tmp/fe.txt
npx tsc --noEmit; echo "tsc exit=$?"
(cd ../backend && python -m pytest -q > /tmp/t.txt 2>&1; echo "pytest exit=$?")
git add packages/shared/src apps/frontend
git commit -m "feat(frontend): AI Visibility tab (setup, run, KPIs, trend, share of voice, citations, answers)"
```

---

### Task 7: Docs and the dry-run live check

- [ ] **Step 1: Env, compose, docs**

`apps/backend/.env.example`, after the GSC block:

```
# AI Visibility: prompts asked of AI models with their own web search
# (about $0.02-0.05 per prompt per model). Each provider needs its key; OpenAI
# and Gemini also need the model you want. No keys = made-up dry-run answers.
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-sonnet-5
OPENAI_API_KEY=
OPENAI_MODEL=
GEMINI_API_KEY=
GEMINI_MODEL=
# Web-search tool names, in case a provider versions them.
ANTHROPIC_WEB_SEARCH_TOOL=web_search_20250305
OPENAI_WEB_SEARCH_TOOL=web_search
AI_VISIBILITY_DRY_RUN=false
# Hard daily cap on AI calls (each prompt x model is one call).
AI_VISIBILITY_DAILY_CAP=30
```

- `deploy/oracle/docker-compose.yml`: the same variables in the backend env, with `${VAR:-default}`.
- `docs/env.md`: rows for each.
- `docs/api.md`: an "AI Visibility" section covering:
  - how answers are produced (web search per provider) and the cost
  - mention, position and citation rules, and share of voice
  - every endpoint, with examples from Task 5's test
  - the opt-in weekly schedule (never on dry run)
  - keys never logged
- `README.md`: an "AI Visibility (Phase 7.1)" section with a **How to verify (no money spent)** block:

```bash
cd apps/backend
python -m pytest tests/test_ai_providers.py tests/test_ai_detect.py tests/test_ai_storage.py tests/test_ai_run.py tests/test_ai_api.py -q
export SESSION_DIR=/tmp/seo-ai          # no AI keys = dry run
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links   # creates project 1
python -m uvicorn app.main:app --port 5000 &
curl -s -X POST -H 'Content-Type: application/json' -d '{"text":"best online bookstore for rare books"}' localhost:5000/api/projects/1/ai-visibility/prompts
curl -s -X PUT -H 'Content-Type: application/json' -d '{"self":["Books to Scrape"]}' localhost:5000/api/projects/1/ai-visibility/brands
curl -s -X POST localhost:5000/api/projects/1/ai-visibility/run
curl -s localhost:5000/api/projects/1/ai-visibility | python -c "import sys,json; d=json.load(sys.stdin); print(d['dry_run'], d['latest'])"
```

Commit the docs (suite gated).

- [ ] **Step 2: Live check (dry run)**

1. Run the README block. Expect `ran` with 3 calls, and `latest` with rates and dry_run true.
2. Add a competitor (`amazon.com`) with an alias, plus a second prompt, and run again. Expect share of voice to list both, and the trend to have 2 points.
3. UI at 1440 and 390 px (Playwright):
   - setup forms
   - Run now (with the estimate and message)
   - weekly switch
   - KPIs and their changes
   - both charts and their table views
   - top cited
   - an expanded answer showing `<mark>` highlights and only safe links
   - no sideways scroll
4. Fix anything found (with a test when it's behaviour), commit, and stop the servers.
5. Report: real calls need each key (and the OpenAI/Gemini model names), plus the owner's go-ahead for the first call per provider.
