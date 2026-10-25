"""The keyword data interface: metrics, difficulty, and what a domain ranks for."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Protocol, Tuple

MAX_KEYWORD_CHARS = 80   # DataForSEO search volume limit per keyword


@dataclass(frozen=True)
class KeywordMetrics:
    keyword: str
    search_volume: Optional[int]
    cpc: Optional[float]
    competition: Optional[str]


@dataclass(frozen=True)
class RankedKeyword:
    keyword: str
    position: int
    url: str
    search_volume: Optional[int]
    difficulty: Optional[int]


class KeywordDataProvider(Protocol):
    name: str

    def metrics(self, keywords: List[str], country: str, language: str) -> Dict[str, KeywordMetrics]: ...

    def difficulty(self, keywords: List[str], country: str, language: str) -> Dict[str, int]: ...

    def ranked_keywords(self, domain: str, country: str, language: str, limit: int) -> List[RankedKeyword]: ...


def normalize_keyword(phrase: str) -> str:
    return " ".join(phrase.lower().split())


def clean_keywords(keywords: List[str]) -> Tuple[List[str], List[str]]:
    kept, dropped, seen = [], [], set()
    for raw in keywords:
        keyword = normalize_keyword(raw)
        if not keyword or keyword in seen:
            continue
        seen.add(keyword)
        (dropped if len(keyword) > MAX_KEYWORD_CHARS else kept).append(keyword)
    return kept, dropped
