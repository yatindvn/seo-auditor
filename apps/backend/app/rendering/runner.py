"""One Chromium load per sampled page, feeding JavaScript rendering and the
accessibility scan."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from app.accessibility.model import A11yResult
from app.accessibility.scoring import summarize
from app.analysis.sampling import select_pages
from app.rendering.compare import analyze_rendered, compare
from app.rendering.model import RenderComparison


def run_browser_pass(renderer, start_url: str, top_pages: List[Dict[str, Any]],
                     results: Dict[str, Any], analyses: Dict[str, Any], limit: int,
                     render_js: bool, accessibility: bool,
                     on_progress: Optional[Callable[[int, int, str], None]] = None,
                     ) -> Tuple[List[RenderComparison], List[A11yResult]]:
    """Pages without a raw HTML analysis (failed ones) are never chosen, so
    every rendered page can be compared. Pages the raw checks already suspect
    of client-side rendering go right after the start URL."""
    raw = {u: a.html_part for u, a in analyses.items()
           if a is not None and not a.failed and a.html_part is not None}
    flagged = [u for u, part in raw.items() if any(i["code"] == "POSSIBLE_CSR_ONLY" for i in part.issues)]
    eligible = {u: r for u, r in results.items() if u in raw}
    urls = select_pages(start_url, top_pages, eligible, limit, priority=flagged)
    if not urls:
        return [], []
    comparisons: List[RenderComparison] = []
    scans: List[A11yResult] = []
    for page in renderer.render(urls, on_progress=on_progress, run_axe=accessibility):
        if render_js:
            if page.error:
                comparisons.append(RenderComparison(url=page.url, status="failed", error=page.error,
                                                    render_ms=page.render_ms))
            else:
                comparisons.append(compare(page.url, raw[page.url],
                                           analyze_rendered(page.url, page.final_url, page.html),
                                           render_ms=page.render_ms))
        if accessibility:
            problem = page.error or page.axe_error or (None if page.axe is not None else "axe returned no result")
            scans.append(A11yResult(url=page.url, status="failed", error=problem) if problem
                         else summarize(page.url, page.axe))
    return comparisons, scans
