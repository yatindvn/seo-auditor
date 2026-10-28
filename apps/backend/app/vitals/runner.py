"""Measuring Core Web Vitals a few pages at a time."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from app.vitals.model import VitalsResult

logger = logging.getLogger(__name__)


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
