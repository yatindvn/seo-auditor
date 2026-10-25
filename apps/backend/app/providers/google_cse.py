"""Google Custom Search as a SerpProvider. The request itself is
rank_checker.fetch_cse_urls -- one implementation for audits and tracking."""

from __future__ import annotations

from app.providers.serp import SerpItem, SerpQuery, SerpResult, domain_of

CSE_MAX = 10


class GoogleCseProvider:
    name = "google_cse"

    def __init__(self, cfg) -> None:
        self._cfg = cfg

    def search(self, query: SerpQuery) -> SerpResult:
        from app.seo.rank_checker import fetch_cse_urls

        urls = fetch_cse_urls(query.keyword, self._cfg, gl=query.country.lower(),
                              num=min(query.depth, CSE_MAX))
        notes = []
        if query.depth > CSE_MAX:
            notes.append(f"Google CSE returns at most {CSE_MAX} results")
        if query.device != "desktop":
            notes.append("device not supported by google_cse")
        items = [SerpItem(position=i, url=u, domain=domain_of(u)) for i, u in enumerate(urls, start=1)]
        return SerpResult(items=items, provider=self.name, note="; ".join(notes) or None)
