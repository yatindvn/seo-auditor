"""DataForSEO Google organic SERP (Live Advanced).

Request and response shape per docs.dataforseo.com, checked 2026-10-25:
POST a JSON array of tasks with HTTP basic auth; success is status_code 20000
at the response and task level; organic results are the items whose type is
"organic", ranked by rank_group.
"""

from __future__ import annotations

from typing import Dict, List

import requests

from app.providers.serp import ProviderError, SerpItem, SerpQuery, SerpResult, domain_of

BASE_URL = "https://api.dataforseo.com"
SERP_PATH = "/v3/serp/google/organic/live/advanced"
ENDPOINT = BASE_URL + SERP_PATH
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


def location_for(country: str) -> str:
    location = LOCATIONS.get(country.upper())
    if location is None:
        raise ValueError(f"no DataForSEO location mapped for country {country!r}")
    return location


def post_task(http, auth, path: str, task: dict) -> dict:
    """POST one task; return it, or raise ProviderError with DataForSEO's own
    status. Shared by every DataForSEO endpoint we call."""
    response = http.post(BASE_URL + path, json=[task], auth=auth, timeout=60)
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
    return tasks[0]


def _questions(items) -> List[str]:
    """People Also Ask. The docs don't name the question field; each nested
    element's `title` is read, and anything else is ignored."""
    found = []
    for block in items:
        if block.get("type") != "people_also_ask":
            continue
        for element in block.get("items") or []:
            title = element.get("title") if isinstance(element, dict) else None
            if isinstance(title, str) and title.strip():
                found.append(title.strip())
    return found


class DataForSeoProvider:
    name = "dataforseo"

    def __init__(self, login: str, password: str, http=requests) -> None:
        self._auth = (login, password)
        self._http = http

    def search(self, query: SerpQuery) -> SerpResult:
        task = {
            "keyword": query.keyword,
            "location_name": location_for(query.country),
            "language_code": query.language,
            "device": query.device,
            "depth": max(1, min(query.depth, MAX_DEPTH)),
        }
        results = post_task(self._http, self._auth, SERP_PATH, task).get("result") or []
        raw = (results[0].get("items") or []) if results else []
        items = sorted(
            (SerpItem(position=int(i["rank_group"]), url=i["url"],
                      domain=domain_of(i["url"]), title=i.get("title") or "")
             for i in raw if i.get("type") == "organic" and i.get("url") and i.get("rank_group")),
            key=lambda item: item.position,
        )
        return SerpResult(items=items, provider=self.name, questions=_questions(raw))
