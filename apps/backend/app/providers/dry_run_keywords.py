"""Made-up keyword data for previews. Never cached, never real."""

from __future__ import annotations

import hashlib
from typing import Dict, List

from app.providers.keywords import KeywordMetrics, RankedKeyword, clean_keywords

TOPICS = ["guide", "best", "review", "price", "how to", "vs", "near me", "cheap", "tips",
          "ideas", "examples", "online", "free", "template", "course", "near", "2026", "list"]


def _h(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest(), 16)


class DryRunKeywordProvider:
    name = "dry_run"

    def metrics(self, keywords: List[str], country: str, language: str) -> Dict[str, KeywordMetrics]:
        kept, _ = clean_keywords(keywords)
        return {k: KeywordMetrics(k, (_h(k) % 500) * 10, round((_h(k) % 300) / 100, 2),
                                  ["LOW", "MEDIUM", "HIGH"][_h(k) % 3]) for k in kept}

    def difficulty(self, keywords: List[str], country: str, language: str) -> Dict[str, int]:
        kept, _ = clean_keywords(keywords)
        return {k: _h("kd" + k) % 100 for k in kept}

    def ranked_keywords(self, domain: str, country: str, language: str, limit: int) -> List[RankedKeyword]:
        pool = [f"sample {topic}" for topic in TOPICS] + [f"demo {topic}" for topic in TOPICS]
        chosen = [k for k in pool if _h(domain + k) % 3 != 0][:limit]
        # Positions 1-30, so a preview gap reliably has competitor top-20 rows.
        return [RankedKeyword(keyword=k, position=_h(domain + "p" + k) % 30 + 1,
                              url=f"https://{domain}/{k.replace(' ', '-')}",
                              search_volume=(_h(k) % 500) * 10, difficulty=_h("kd" + k) % 100)
                for k in chosen]
