"""Which crawled pages get the expensive treatment -- Core Web Vitals,
JavaScript rendering. The most important pages first, each once."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _eligible(page: Any) -> bool:
    content_type = (getattr(page, "content_type", "") or "text/html").lower()
    return page is not None and page.status_code == 200 and "html" in content_type


def select_pages(start_url: str, top_pages: List[Dict[str, Any]], results: Dict[str, Any],
                 limit: int, priority: Iterable[str] = ()) -> List[str]:
    """The start URL, then `priority` pages, then pages by internal PageRank,
    then the shallowest. Status-200 HTML pages only, each once, up to `limit`."""
    by_depth = sorted(results, key=lambda u: (getattr(results[u], "depth", 0) or 0))
    candidates = [start_url, *priority, *(p["url"] for p in top_pages), *by_depth]
    chosen: List[str] = []
    for url in candidates:
        if len(chosen) >= limit:
            break
        if url not in chosen and _eligible(results.get(url)):
            chosen.append(url)
    return chosen
