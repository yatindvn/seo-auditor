"""DataForSEO Google organic SERP (Live Advanced).

Request and response shape per docs.dataforseo.com, checked 2026-10-25:
POST a JSON array of tasks with HTTP basic auth; success is status_code 20000
at the response and task level; organic results are the items whose type is
"organic", ranked by rank_group.
"""

from __future__ import annotations

from typing import Dict

import requests

from app.providers.serp import ProviderError, SerpItem, SerpQuery, SerpResult, domain_of

ENDPOINT = "https://api.dataforseo.com/v3/serp/google/organic/live/advanced"
MAX_DEPTH = 200
OK = 20000

# ISO 3166-1 alpha-2 -> DataForSEO location_name. Extend as projects need.
LOCATIONS: Dict[str, str] = {
    "US": "United States", "GB": "United Kingdom", "IN": "India", "CA": "Canada",
    "AU": "Australia", "IE": "Ireland", "NZ": "New Zealand", "ZA": "South Africa",
    "SG": "Singapore", "AE": "United Arab Emirates", "DE": "Germany", "FR": "France",
    "ES": "Spain", "IT": "Italy", "NL": "Netherlands", "BR": "Brazil", "MX": "Mexico",
    "JP": "Japan",
}


class DataForSeoProvider:
    name = "dataforseo"

    def __init__(self, login: str, password: str, http=requests) -> None:
        self._auth = (login, password)
        self._http = http

    def search(self, query: SerpQuery) -> SerpResult:
        location = LOCATIONS.get(query.country.upper())
        if location is None:
            raise ValueError(f"no DataForSEO location mapped for country {query.country!r}")
        task = {
            "keyword": query.keyword,
            "location_name": location,
            "language_code": query.language,
            "device": query.device,
            "depth": max(1, min(query.depth, MAX_DEPTH)),
        }
        response = self._http.post(ENDPOINT, json=[task], auth=self._auth, timeout=60)
        try:
            data = response.json()
        except ValueError:
            raise ProviderError(f"DataForSEO returned HTTP {response.status_code} without JSON")

        if data.get("status_code") != OK:
            raise ProviderError(f"DataForSEO {data.get('status_code')}: {data.get('status_message')}")
        tasks = data.get("tasks") or []
        if not tasks or tasks[0].get("status_code") != OK:
            first = tasks[0] if tasks else {}
            raise ProviderError(f"DataForSEO task {first.get('status_code')}: {first.get('status_message')}")

        results = tasks[0].get("result") or []
        raw = (results[0].get("items") or []) if results else []
        items = sorted(
            (SerpItem(position=int(i["rank_group"]), url=i["url"],
                      domain=domain_of(i["url"]), title=i.get("title") or "")
             for i in raw if i.get("type") == "organic" and i.get("url") and i.get("rank_group")),
            key=lambda item: item.position,
        )
        return SerpResult(items=items, provider=self.name)
