"""Which pages an audit measures, and measuring them a few at a time."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

from app.vitals.model import VitalsResult

logger = logging.getLogger(__name__)


def _measurable(page: Any) -> bool:
    content_type = (getattr(page, "content_type", "") or "text/html").lower()
    return page is not None and page.status_code == 200 and "html" in content_type


def select_vitals_pages(start_url: str, top_pages: List[Dict[str, Any]],
                        results: Dict[str, Any], limit: int) -> List[str]:
    """The start URL, then pages by internal PageRank, then the shallowest
    pages. Only status-200 HTML pages, each once, up to `limit`."""
    by_depth = sorted(results, key=lambda u: (getattr(results[u], "depth", 0) or 0))
    candidates = [start_url] + [p["url"] for p in top_pages] + by_depth
    chosen: List[str] = []
    for url in candidates:
        if len(chosen) >= limit:
            break
        if url not in chosen and _measurable(results.get(url)):
            chosen.append(url)
    return chosen


def measure_pages(provider, urls: List[str], strategy: str = "mobile",
                  on_progress: Optional[Callable[[int, int, str], None]] = None,
                  max_workers: int = 3) -> List[VitalsResult]:
    """Measure `urls`, at most `max_workers` at a time (PSI allows about 4 per
    second, and every Lighthouse run is a Chrome). Results come back in `urls`
    order, and an exception is that page's error, never the audit's."""
    found: Dict[str, VitalsResult] = {}
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(provider.measure, url, strategy): url for url in urls}
        for done, future in enumerate(as_completed(futures), start=1):
            url = futures[future]
            try:
                found[url] = future.result()
            except Exception as exc:
                logger.error("Measuring Core Web Vitals failed on %s: %s", url, exc, exc_info=exc)
                found[url] = VitalsResult(url=url, strategy=strategy,
                                          error=f"unexpected error ({type(exc).__name__})")
            if on_progress:
                on_progress(done, len(urls), url)
    return [found[url] for url in urls]
