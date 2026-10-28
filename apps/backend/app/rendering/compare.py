"""What JavaScript changed on a page, and which changes are issues.

Both versions go through page_pipeline.analyze_html, so the rendered page is
parsed exactly the way the crawler parsed the raw one."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.auditor.checks import issue
from app.rendering.model import RenderComparison
from app.services.page_pipeline import HtmlAnalysis, PagePayload, analyze_html

MAX_LINKS = 50
# field -> (severity, code, label), in the order issues are reported.
COMPARED_FIELDS = {
    "title": ("warning", "JS_TITLE_CHANGED", "Title"),
    "meta_description": ("info", "JS_META_DESCRIPTION_CHANGED", "Meta description"),
    "canonical": ("warning", "JS_CANONICAL_CHANGED", "Canonical"),
    "meta_robots": ("warning", "JS_ROBOTS_CHANGED", "Meta robots"),
    "h1": ("info", "JS_H1_CHANGED", "H1"),
}


def analyze_rendered(url: str, final_url: Optional[str], html: str) -> HtmlAnalysis:
    return analyze_html(PagePayload(
        url=url, final_url=final_url or url, status_code=200, headers={}, html=html,
        enable_keyword_analysis=False,
    ))


def _norm(value: Any) -> str:
    return (value or "").strip() if isinstance(value, str) or value is None else str(value)


def compare(url: str, raw: HtmlAnalysis, rendered: HtmlAnalysis,
            render_ms: Optional[float] = None) -> RenderComparison:
    changes: Dict[str, Dict[str, Any]] = {}
    for name in COMPARED_FIELDS:
        before, after = raw.meta.get(name), rendered.meta.get(name)
        if _norm(before) != _norm(after):
            changes[name] = {"raw": before, "rendered": after}
    js_only = sorted(set(rendered.internal_links) - set(raw.internal_links))
    return RenderComparison(
        url=url, render_ms=render_ms,
        raw_word_count=raw.meta.get("word_count"), rendered_word_count=rendered.meta.get("word_count"),
        changes=changes, js_only_links=js_only[:MAX_LINKS], js_only_links_count=len(js_only),
    )


def _quote(value: Any) -> str:
    text = _norm(value)
    return f"'{text[:80]}'" if text else "(none)"


def rendering_issues(c: RenderComparison) -> List[Dict[str, str]]:
    if c.status != "rendered":
        return []
    out = []
    raw_words, rendered_words = c.raw_word_count or 0, c.rendered_word_count or 0
    if rendered_words >= 2 * raw_words and rendered_words - raw_words >= 200:
        out.append(issue("warning", "JS_CONTENT_DEPENDENT",
                         f"{raw_words} words in raw HTML, {rendered_words} after JavaScript"))
    for name, (severity, code, label) in COMPARED_FIELDS.items():
        if name in c.changes:
            change = c.changes[name]
            out.append(issue(severity, code,
                             f"{label} changed by JavaScript: {_quote(change['raw'])} → {_quote(change['rendered'])}"))
    if c.js_only_links_count:
        out.append(issue("info", "JS_ONLY_LINKS",
                         f"{c.js_only_links_count} internal links appear only after JavaScript"))
    return out
