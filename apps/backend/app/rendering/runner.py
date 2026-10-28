"""Choose pages, render them, compare each with its raw analysis."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from app.analysis.sampling import select_pages
from app.rendering.compare import analyze_rendered, compare
from app.rendering.model import RenderComparison


def render_and_compare(renderer, start_url: str, top_pages: List[Dict[str, Any]],
                       results: Dict[str, Any], analyses: Dict[str, Any], limit: int,
                       on_progress: Optional[Callable[[int, int, str], None]] = None) -> List[RenderComparison]:
    """Pages without a raw HTML analysis (failed ones) can't be compared, so
    they're never chosen. Pages the raw checks already suspect of client-side
    rendering go right after the start URL."""
    raw = {u: a.html_part for u, a in analyses.items()
           if a is not None and not a.failed and a.html_part is not None}
    flagged = [u for u, part in raw.items() if any(i["code"] == "POSSIBLE_CSR_ONLY" for i in part.issues)]
    eligible = {u: r for u, r in results.items() if u in raw}
    urls = select_pages(start_url, top_pages, eligible, limit, priority=flagged)
    if not urls:
        return []
    comparisons = []
    for rendered in renderer.render(urls, on_progress=on_progress):
        if rendered.error:
            comparisons.append(RenderComparison(url=rendered.url, status="failed", error=rendered.error,
                                                render_ms=rendered.render_ms))
            continue
        comparisons.append(compare(rendered.url, raw[rendered.url],
                                   analyze_rendered(rendered.url, rendered.final_url, rendered.html),
                                   render_ms=rendered.render_ms))
    return comparisons
