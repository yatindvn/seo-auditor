"""A provider that never touches the network. Its results are made up -- they
are for previews and wiring checks, never for audits or rank history."""

from __future__ import annotations

import hashlib
from typing import List, Optional

from app.providers.serp import SerpItem, SerpQuery, SerpResult


class DryRunProvider:
    name = "dry_run"

    def __init__(self, items: Optional[List[SerpItem]] = None) -> None:
        self._items = items

    def search(self, query: SerpQuery) -> SerpResult:
        if self._items is not None:
            return SerpResult(items=list(self._items), provider=self.name, note="dry run")
        seed = int(hashlib.sha256(query.keyword.encode("utf-8")).hexdigest(), 16)
        slug = "-".join(query.keyword.lower().split())
        items = [
            SerpItem(position=i, url=f"https://site{(seed >> i) % 50}.example/{slug}",
                     domain=f"site{(seed >> i) % 50}.example", title=f"{query.keyword} #{i}")
            for i in range(1, 11)
        ]
        return SerpResult(items=items, provider=self.name, note="dry run")
