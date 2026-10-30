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
