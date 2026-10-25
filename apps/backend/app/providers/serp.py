"""The SERP provider interface: one search in, ranked organic results out."""

from __future__ import annotations

import urllib.parse as up
from dataclasses import dataclass, field
from typing import List, Optional, Protocol


@dataclass(frozen=True)
class SerpQuery:
    keyword: str
    country: str = "US"
    language: str = "en"
    device: str = "desktop"
    depth: int = 100


@dataclass(frozen=True)
class SerpItem:
    position: int
    url: str
    domain: str
    title: str = ""


@dataclass
class SerpResult:
    items: List[SerpItem] = field(default_factory=list)
    provider: str = ""
    note: Optional[str] = None
    questions: List[str] = field(default_factory=list)   # People Also Ask


class SerpProvider(Protocol):
    name: str

    def search(self, query: SerpQuery) -> SerpResult: ...


class ProviderSkipped(Exception):
    """No call was made -- not configured, or the daily cap was reached."""


class ProviderError(Exception):
    """The provider was called and failed."""


def domain_of(url: str) -> str:
    host = (up.urlsplit(url if "://" in url else "https://" + url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host
