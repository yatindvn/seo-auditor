"""DataForSEO keyword data: Google Ads search volume, Labs keyword difficulty,
Labs ranked keywords (shapes per docs.dataforseo.com, checked 2026-10-25).

Each call: cache first, then the dataforseo_labs budget, then HTTP -- so a
repeat within the TTL makes no request and spends nothing.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List

import requests

from app.providers import cache, spend
from app.providers.dataforseo import location_for, post_task
from app.providers.keywords import KeywordMetrics, RankedKeyword, clean_keywords

BUDGET = "dataforseo_labs"
VOLUME_PATH = "/v3/keywords_data/google_ads/search_volume/live"
DIFFICULTY_PATH = "/v3/dataforseo_labs/google/bulk_keyword_difficulty/live"
RANKED_PATH = "/v3/dataforseo_labs/google/ranked_keywords/live"
METRICS_TTL = timedelta(days=30)
RANKED_TTL = timedelta(days=7)
MAX_RANKED_LIMIT = 1000


class DataForSeoKeywordProvider:
    name = "dataforseo"

    def __init__(self, login: str, password: str, cap: int, http=requests, factory=None) -> None:
        self._auth = (login, password)
        self._http = http
        self.cap = cap
        self._factory = factory

    def _call(self, path: str, task: dict, ttl: timedelta):
        def fetch():
            spend.reserve(BUDGET, self.cap, factory=self._factory)
            return post_task(self._http, self._auth, path, task).get("result") or []
        return cache.cached_call(BUDGET, path, task, ttl, fetch, factory=self._factory)

    def metrics(self, keywords: List[str], country: str, language: str) -> Dict[str, KeywordMetrics]:
        kept, _ = clean_keywords(keywords)
        if not kept:
            return {}
        task = {"keywords": kept, "location_name": location_for(country), "language_code": language}
        out = {}
        for item in self._call(VOLUME_PATH, task, METRICS_TTL):
            keyword = (item.get("keyword") or "").lower()
            if keyword:
                out[keyword] = KeywordMetrics(keyword, item.get("search_volume"),
                                              item.get("cpc"), item.get("competition"))
        return out

    def difficulty(self, keywords: List[str], country: str, language: str) -> Dict[str, int]:
        kept, _ = clean_keywords(keywords)
        if not kept:
            return {}
        task = {"keywords": kept, "location_name": location_for(country), "language_code": language}
        result = self._call(DIFFICULTY_PATH, task, METRICS_TTL)
        items = (result[0].get("items") or []) if result else []
        return {(i.get("keyword") or "").lower(): i["keyword_difficulty"]
                for i in items if i.get("keyword") and i.get("keyword_difficulty") is not None}

    def ranked_keywords(self, domain: str, country: str, language: str, limit: int) -> List[RankedKeyword]:
        task = {"target": domain, "location_name": location_for(country), "language_code": language,
                "limit": max(1, min(limit, MAX_RANKED_LIMIT)), "item_types": ["organic"]}
        result = self._call(RANKED_PATH, task, RANKED_TTL)
        items = (result[0].get("items") or []) if result else []
        out = []
        for item in items:
            data = item.get("keyword_data") or {}
            serp_item = (item.get("ranked_serp_element") or {}).get("serp_item") or {}
            keyword, position = data.get("keyword"), serp_item.get("rank_group")
            if not keyword or not position:
                continue
            out.append(RankedKeyword(
                keyword=keyword.lower(), position=int(position), url=serp_item.get("url") or "",
                search_volume=(data.get("keyword_info") or {}).get("search_volume"),
                difficulty=(data.get("keyword_properties") or {}).get("keyword_difficulty"),
            ))
        return out
