# JavaScript Rendering (Phase 5.2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With `render_js` on, an audit renders up to 20 important pages in
headless Chromium, compares them with the raw HTML, and stores and shows what
JavaScript changed, as issues and a per-page table.

**Architecture:**
- A new `app/rendering/` package holds:
  - a result model
  - a pure comparison and issues module, which reuses `page_pipeline.analyze_html` for the rendered HTML
  - a Playwright renderer behind a small interface, with a lazy import
  - a runner that picks pages and compares them
- Page selection moves to a shared `app/analysis/sampling.py`, used by both
  rendering and Core Web Vitals.
- The pipeline calls the runner after Core Web Vitals. Rows go to a new table
  that one endpoint serves to the Site Audit tab and the report.

**Tech Stack:** Python 3, Playwright (sync API), SQLAlchemy/Alembic, FastAPI, pytest; Next.js 14, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-28-js-rendering-design.md`

## Global Constraints

- **Off by default:** request `render_js` (default `false`), CLI `--render-js`, home form checkbox, scheduler `audit_options.render_js`.
- **Page cap:** `RENDER_MAX_PAGES` default 20. **Timeout:** `RENDER_TIMEOUT_MS` default 20000, then up to 2000 ms of network idle (its timeout is ignored).
- **Page order:** start URL → pages with `POSSIBLE_CSR_ONLY` → top PageRank → shallowest. Only status-200 HTML pages that have a raw `html_part`.
- **Browser setup:** one headless Chromium per audit, pages one at a time.
  - Each page gets a fresh context: `accept_downloads=False`, `service_workers="block"`.
  - Images, media and fonts are aborted.
  - The User-Agent is Chromium's default (it identifies as HeadlessChrome).
- **Issue rules:**
  - `JS_CONTENT_DEPENDENT` (warning) when rendered ≥ 2× raw words and rendered − raw ≥ 200.
  - `JS_ROBOTS_CHANGED`, `JS_CANONICAL_CHANGED`, `JS_TITLE_CHANGED` (warning).
  - `JS_META_DESCRIPTION_CHANGED`, `JS_H1_CHANGED`, `JS_ONLY_LINKS` (info).
- **String comparison:** strings are compared after `strip()`, and None == "". JS-only links are capped at 50.
- **Never fatal:** a missing Playwright or browser gives `render_status="unavailable"` with a reason, and the audit completes. A per-page failure gives `status="failed"` with an `error` and no issues.
- **Tests:** no real browser and no network. Run the full backend suite before each commit.

---

## File map

**Backend, create:**
- `app/analysis/sampling.py`: `select_pages`
- `app/rendering/__init__.py`
- `app/rendering/model.py`: `RenderResult`, `RenderComparison`, `Renderer`
- `app/rendering/compare.py`: `analyze_rendered`, `compare`, `rendering_issues`
- `app/rendering/playwright_renderer.py`: `_load_playwright`, `PlaywrightRenderer`, `renderer_available`, `playwright_chromium`
- `app/rendering/runner.py`: `render_and_compare`
- `app/api/rendering.py`
- `alembic/versions/0005_render_comparisons.py`
- Tests:
  - `tests/test_sampling.py`
  - `tests/test_render_compare.py`
  - `tests/test_render_playwright.py`
  - `tests/test_render_storage.py`
  - `tests/test_render_pipeline.py`
  - `tests/test_render_api.py`

**Backend, modify:**
- `app/vitals/runner.py`: remove `select_vitals_pages`
- `app/services/audit_service.py`
- `app/vitals/lighthouse.py`: `find_chrome` fallback
- `app/db/models.py`, `app/db/audit_store.py`
- `app/services/summary_fields.py`
- `app/ai/ai_suggestions.py`
- `app/schemas/schemas.py`, `app/api/routes.py`, `app/cli.py`
- `app/scheduler/jobs.py`, `app/main.py`, `app/config/config.py`
- `requirements.txt`, `Dockerfile`
- Tests: `tests/test_vitals_runner.py`, `tests/test_db_schema.py`, `tests/test_vitals_lighthouse.py`, `tests/test_scheduler.py`

**Frontend:**
- `packages/shared/src/types/platform.ts`, `packages/shared/src/types/index.ts`
- `apps/frontend/services/platform.ts`
- Create `apps/frontend/components/platform/rendering-table.tsx`
- `app/projects/[id]/audits/page.tsx`, `app/dashboard/page.tsx`, `app/page.tsx`
- Tests:
  - create `components/__tests__/rendering-table.test.tsx`
  - create `components/__tests__/render-js-option.test.tsx`
  - modify `components/__tests__/site-audit-page.test.tsx`

**Docs:** `apps/backend/.env.example`, `deploy/oracle/docker-compose.yml`, `docs/env.md`, `docs/api.md`, `docs/deployment-oracle.md`, `README.md`

---

### Task 1: Shared page selection

**Files:**
- Create: `apps/backend/app/analysis/sampling.py`, `apps/backend/tests/test_sampling.py`
- Modify: `apps/backend/app/vitals/runner.py`, `apps/backend/app/services/audit_service.py`, `apps/backend/tests/test_vitals_runner.py`

**Interfaces:**
- Produces: `select_pages(start_url: str, top_pages: List[dict], results: Dict[str, Any], limit: int, priority: Iterable[str] = ()) -> List[str]`
- Removes: `app.vitals.runner.select_vitals_pages`. Its callers switch to `select_pages`.

- [ ] **Step 1: Write the failing test** (`tests/test_sampling.py`)

```python
"""Choosing which crawled pages get expensive treatment (Core Web Vitals,
JavaScript rendering)."""

from types import SimpleNamespace as Page

from app.analysis.sampling import select_pages


def _results():
    return {
        "https://a.com/": Page(status_code=200, depth=0, content_type="text/html"),
        "https://a.com/shop": Page(status_code=200, depth=1, content_type="text/html; charset=utf-8"),
        "https://a.com/blog": Page(status_code=200, depth=1, content_type=""),
        "https://a.com/gone": Page(status_code=404, depth=1, content_type="text/html"),
        "https://a.com/file.pdf": Page(status_code=200, depth=1, content_type="application/pdf"),
        "https://a.com/deep": Page(status_code=200, depth=3, content_type="text/html"),
    }


def test_start_url_first_then_pagerank_order():
    top = [{"url": "https://a.com/deep", "score": 0.3}, {"url": "https://a.com/", "score": 0.2},
           {"url": "https://a.com/gone", "score": 0.1}, {"url": "https://a.com/shop", "score": 0.05}]
    assert select_pages("https://a.com/", top, _results(), 3) == [
        "https://a.com/", "https://a.com/deep", "https://a.com/shop"]


def test_priority_pages_come_right_after_the_start_url():
    top = [{"url": "https://a.com/shop", "score": 0.3}]
    assert select_pages("https://a.com/", top, _results(), 3, priority=["https://a.com/deep", "https://a.com/gone"]) == [
        "https://a.com/", "https://a.com/deep", "https://a.com/shop"]


def test_without_pagerank_the_shallowest_pages_fill_in():
    assert select_pages("https://a.com/", [], _results(), 10) == [
        "https://a.com/", "https://a.com/shop", "https://a.com/blog", "https://a.com/deep"]


def test_a_failed_start_url_is_skipped_and_limit_zero_selects_nothing():
    results = _results()
    results["https://a.com/"].status_code = 500
    assert select_pages("https://a.com/", [], results, 1) == ["https://a.com/shop"]
    assert select_pages("https://a.com/", [], _results(), 0) == []
```

In `tests/test_vitals_runner.py`:
- Delete the three `select_vitals_pages` tests, the `_results` helper and the `select_vitals_pages` import. They now live in `test_sampling.py`.
- Keep `_Provider` and `test_measure_keeps_order_reports_progress_and_contains_errors`.
- Fix the import line to `from app.vitals.runner import measure_pages`.

- [ ] **Step 2: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_sampling.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.analysis.sampling'`

- [ ] **Step 3: Implement `app/analysis/sampling.py`**

```python
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
```

In `app/vitals/runner.py`:
- Delete `_measurable` and `select_vitals_pages`.
- Update the module docstring to "Measuring Core Web Vitals a few pages at a time."
- Drop imports that are now unused.

In `app/services/audit_service.py`:
- Add `from app.analysis.sampling import select_pages`.
- Replace `vitals_runner.select_vitals_pages(` with `select_pages(`. The arguments are unchanged.

- [ ] **Step 4: Run and pass**

Run: `python -m pytest tests/test_sampling.py tests/test_vitals_runner.py tests/test_vitals_pipeline.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/analysis/sampling.py apps/backend/app/vitals/runner.py apps/backend/app/services/audit_service.py apps/backend/tests/test_sampling.py apps/backend/tests/test_vitals_runner.py
git commit -m "refactor: shared page sampling (start URL, priority, PageRank, depth)"
```

---

### Task 2: Comparison model, rules and issues

**Files:**
- Create: `apps/backend/app/rendering/__init__.py`, `apps/backend/app/rendering/model.py`, `apps/backend/app/rendering/compare.py`
- Modify: `apps/backend/app/ai/ai_suggestions.py`
- Test: `apps/backend/tests/test_render_compare.py`

**Interfaces:**
- Consumes: `page_pipeline.PagePayload`, `page_pipeline.analyze_html`, `page_pipeline.HtmlAnalysis`; `checks.issue`.
- Produces:
  - `RenderResult(url, html="", final_url=None, status=None, render_ms=None, error=None)`
  - `RenderComparison(url, status="rendered", error=None, render_ms=None, raw_word_count=None, rendered_word_count=None, changes={}, js_only_links=[], js_only_links_count=0)` with `.to_dict()`
  - `Renderer` Protocol (`name`, `render(urls, on_progress=None) -> List[RenderResult]`)
  - `COMPARED_FIELDS`
  - `analyze_rendered(url, final_url, html) -> HtmlAnalysis`
  - `compare(url, raw, rendered, render_ms=None) -> RenderComparison`
  - `rendering_issues(comparison) -> List[dict]`

- [ ] **Step 1: Write the failing test**

```python
"""Raw vs rendered: what changed, and which changes are issues."""

from app.rendering.compare import analyze_rendered, compare, rendering_issues
from app.rendering.model import RenderComparison
from app.services.page_pipeline import HtmlAnalysis


def _part(words=50, links=(), **meta):
    base = {"title": "Shop", "meta_description": "Buy", "canonical": "https://a.com/",
            "meta_robots": None, "h1": "Shop", "word_count": words}
    return HtmlAnalysis(meta={**base, **meta}, internal_links=list(links))


def test_no_changes_means_no_issues():
    c = compare("https://a.com/", _part(), _part())
    assert c.changes == {} and c.js_only_links == [] and rendering_issues(c) == []


def test_none_and_empty_string_and_whitespace_are_the_same():
    c = compare("https://a.com/", _part(meta_robots=None, title="Shop "), _part(meta_robots="", title="Shop"))
    assert c.changes == {}


def test_each_changed_field_is_recorded_and_raises_its_issue():
    raw = _part(title="Loading…", canonical="https://a.com/", meta_robots=None, meta_description=None, h1=None)
    rendered = _part(title="Espresso machines", canonical="https://a.com/espresso",
                     meta_robots="noindex", meta_description="Best machines", h1="Espresso")
    c = compare("https://a.com/", raw, rendered)
    assert c.changes["title"] == {"raw": "Loading…", "rendered": "Espresso machines"}
    assert set(c.changes) == {"title", "canonical", "meta_robots", "meta_description", "h1"}
    issues = {i["code"]: i for i in rendering_issues(c)}
    assert {k: v["severity"] for k, v in issues.items()} == {
        "JS_TITLE_CHANGED": "warning", "JS_CANONICAL_CHANGED": "warning", "JS_ROBOTS_CHANGED": "warning",
        "JS_META_DESCRIPTION_CHANGED": "info", "JS_H1_CHANGED": "info"}
    assert issues["JS_TITLE_CHANGED"]["message"] == "Title changed by JavaScript: 'Loading…' → 'Espresso machines'"
    assert issues["JS_META_DESCRIPTION_CHANGED"]["message"] == "Meta description changed by JavaScript: (none) → 'Best machines'"


def test_content_dependence_needs_double_and_two_hundred_more_words():
    assert "JS_CONTENT_DEPENDENT" in [i["code"] for i in rendering_issues(compare("u", _part(words=40), _part(words=900)))]
    assert "JS_CONTENT_DEPENDENT" not in [i["code"] for i in rendering_issues(compare("u", _part(words=40), _part(words=230)))]   # +190
    assert "JS_CONTENT_DEPENDENT" not in [i["code"] for i in rendering_issues(compare("u", _part(words=300), _part(words=599)))]  # < 2x
    issue = [i for i in rendering_issues(compare("u", _part(words=40), _part(words=900))) if i["code"] == "JS_CONTENT_DEPENDENT"][0]
    assert issue == {"severity": "warning", "code": "JS_CONTENT_DEPENDENT",
                     "message": "40 words in raw HTML, 900 after JavaScript"}


def test_js_only_links_are_sorted_capped_and_counted():
    rendered_links = [f"https://a.com/p{i:03d}" for i in range(60)] + ["https://a.com/raw"]
    c = compare("u", _part(links=["https://a.com/raw"]), _part(links=rendered_links))
    assert c.js_only_links_count == 60 and len(c.js_only_links) == 50 and c.js_only_links[0] == "https://a.com/p000"
    assert [i for i in rendering_issues(c) if i["code"] == "JS_ONLY_LINKS"][0]["message"] == \
        "60 internal links appear only after JavaScript"


def test_a_failed_render_raises_nothing():
    assert rendering_issues(RenderComparison(url="u", status="failed", error="Timeout")) == []


def test_analyze_rendered_parses_like_the_crawler():
    html = "<html><head><title>JS Title</title><link rel='canonical' href='https://a.com/x'></head>" \
           "<body><h1>Hello</h1><a href='/next'>n</a></body></html>"
    part = analyze_rendered("https://a.com/", "https://a.com/", html)
    assert part.meta["title"] == "JS Title" and part.meta["h1"] == "Hello"
    assert "https://a.com/next" in part.internal_links


def test_to_dict_is_json_ready():
    d = compare("u", _part(), _part(title="New"), render_ms=812.5).to_dict()
    assert d["url"] == "u" and d["status"] == "rendered" and d["render_ms"] == 812.5
    assert d["changes"] == {"title": {"raw": "Shop", "rendered": "New"}}
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_render_compare.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rendering'`

- [ ] **Step 3: Implement**

`app/rendering/__init__.py`:

```python
"""JavaScript rendering: render a sample of pages in headless Chromium and
compare them with the raw HTML the crawler saw."""
```

`app/rendering/model.py`:

```python
"""Rendering results, and the comparison stored per page."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol


@dataclass
class RenderResult:
    url: str
    html: str = ""
    final_url: Optional[str] = None
    status: Optional[int] = None
    render_ms: Optional[float] = None
    error: Optional[str] = None


@dataclass
class RenderComparison:
    url: str
    status: str = "rendered"                  # rendered | failed
    error: Optional[str] = None
    render_ms: Optional[float] = None
    raw_word_count: Optional[int] = None
    rendered_word_count: Optional[int] = None
    changes: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    js_only_links: List[str] = field(default_factory=list)
    js_only_links_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Renderer(Protocol):
    name: str

    def render(self, urls: List[str],
               on_progress: Optional[Callable[[int, int, str], None]] = None) -> List[RenderResult]: ...
```

`app/rendering/compare.py`:

```python
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
```

In `app/ai/ai_suggestions.py`, add to `IMPACT_WEIGHTS` (after the `CWV_*` entries):

```python
    "JS_CONTENT_DEPENDENT": 6, "JS_ROBOTS_CHANGED": 8, "JS_CANONICAL_CHANGED": 7, "JS_TITLE_CHANGED": 5,
    "JS_META_DESCRIPTION_CHANGED": 2, "JS_H1_CHANGED": 2, "JS_ONLY_LINKS": 3,
```

and to `RECOMMENDATION_TEXT` (after the `CWV_TBT_NEEDS_IMPROVEMENT` entry):

```python
    "JS_CONTENT_DEPENDENT": "Server-render (SSR/SSG) the main content so it is in the HTML, not only after JavaScript runs.",
    "JS_ROBOTS_CHANGED": "Set meta robots in the server HTML; changing it with JavaScript gives crawlers conflicting signals.",
    "JS_CANONICAL_CHANGED": "Put the final canonical in the server HTML; don't change it with JavaScript.",
    "JS_TITLE_CHANGED": "Render the real title on the server so every crawler and social preview sees it.",
    "JS_META_DESCRIPTION_CHANGED": "Render the meta description on the server.",
    "JS_H1_CHANGED": "Render the main heading on the server.",
    "JS_ONLY_LINKS": "Use plain <a href> links in the server HTML so crawlers can discover these pages without JavaScript.",
```

- [ ] **Step 4: Run and pass**

Run: `python -m pytest tests/test_render_compare.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/rendering apps/backend/app/ai/ai_suggestions.py apps/backend/tests/test_render_compare.py
git commit -m "feat(rendering): raw vs rendered comparison and JS_* issues"
```

---

### Task 3: Playwright renderer, availability, shared Chromium

**Files:**
- Create: `apps/backend/app/rendering/playwright_renderer.py`
- Modify: `apps/backend/app/vitals/lighthouse.py`, `apps/backend/app/config/config.py`, `apps/backend/requirements.txt`
- Test: `apps/backend/tests/test_render_playwright.py`, plus one test in `tests/test_vitals_lighthouse.py`

**Interfaces:**
- Consumes: `RenderResult` (Task 2).
- Produces:
  - `_load_playwright() -> (sync_playwright, TimeoutError)`
  - `PlaywrightRenderer(timeout_ms: int)` with `.name == "playwright"` and `.render(urls, on_progress=None)`
  - `renderer_available() -> Tuple[bool, str]`
  - `playwright_chromium() -> Optional[str]`
  - Config: `RENDER_MAX_PAGES`, `RENDER_TIMEOUT_MS`

- [ ] **Step 1: Config and dependency**

Append to `app/config/config.py` after the `LIGHTHOUSE_CLI` line:

```python
# JavaScript rendering (Phase 5.2): when an audit asks for it, this many pages
# are rendered in headless Chromium and compared with their raw HTML.
RENDER_MAX_PAGES = int(os.getenv("RENDER_MAX_PAGES", "20"))
RENDER_TIMEOUT_MS = int(os.getenv("RENDER_TIMEOUT_MS", "20000"))
```

Append to `requirements.txt`:

```
# JavaScript rendering (Phase 5.2), imported lazily in app/rendering. The pip
# package alone is ~40 MB; the browser itself is only installed by the
# Dockerfile's WITH_BROWSER build arg, and without it rendering reports
# "unavailable" instead of failing the audit.
playwright>=1.48
```

- [ ] **Step 2: Write the failing tests** (`tests/test_render_playwright.py`)

```python
"""The Playwright renderer, with Playwright itself faked: no browser runs in
tests."""

from unittest.mock import MagicMock

import pytest

from app.rendering import playwright_renderer as pr


class FakeTimeout(Exception):
    pass


def _fake_playwright(pages):
    """pages: url -> (html, status) or an Exception to raise from goto."""
    browser = MagicMock(name="browser")
    contexts = []

    def new_context(**kwargs):
        ctx = MagicMock(name="context")
        ctx.kwargs = kwargs
        page = MagicMock(name="page")
        state = {}

        def goto(url, **kw):
            state["url"] = url
            outcome = pages[url]
            if isinstance(outcome, Exception):
                raise outcome
            page.url = url
            return MagicMock(status=outcome[1])

        page.goto.side_effect = goto
        page.wait_for_load_state.side_effect = FakeTimeout("network never idle")
        page.content.side_effect = lambda: pages[state["url"]][0]
        ctx.new_page.return_value = page
        contexts.append(ctx)
        return ctx

    browser.new_context.side_effect = new_context
    pw = MagicMock(name="pw")
    pw.chromium.launch.return_value = browser
    manager = MagicMock()
    manager.__enter__.return_value = pw
    sync_playwright = MagicMock(return_value=manager)
    return sync_playwright, browser, contexts


def test_renders_each_url_in_a_locked_down_context(monkeypatch):
    sync, browser, contexts = _fake_playwright({"https://a.com/": ("<html>A</html>", 200),
                                                "https://a.com/b": ("<html>B</html>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    seen = []
    results = pr.PlaywrightRenderer(5000).render(["https://a.com/", "https://a.com/b"],
                                                 on_progress=lambda d, t, u: seen.append((d, t, u)))
    assert [(r.url, r.html, r.status, r.error) for r in results] == [
        ("https://a.com/", "<html>A</html>", 200, None), ("https://a.com/b", "<html>B</html>", 200, None)]
    assert all(r.render_ms is not None for r in results)
    assert contexts[0].kwargs == {"java_script_enabled": True, "accept_downloads": False, "service_workers": "block"}
    page = contexts[0].new_page.return_value
    assert page.goto.call_args.kwargs == {"wait_until": "load", "timeout": 5000}
    assert page.route.call_args.args[0] == "**/*"
    assert all(c.close.called for c in contexts) and browser.close.called
    assert seen == [(1, 2, "https://a.com/"), (2, 2, "https://a.com/b")]


def test_heavy_resources_are_blocked():
    for kind, aborted in (("image", True), ("media", True), ("font", True), ("script", False), ("xhr", False)):
        route = MagicMock()
        route.request.resource_type = kind
        pr._block_heavy(route)
        assert route.abort.called is aborted and route.continue_.called is (not aborted)


def test_one_failing_page_does_not_stop_the_rest(monkeypatch):
    boom = RuntimeError("net::ERR_NAME_NOT_RESOLVED at https://a.com/x\nCall log:\n  - navigating")
    sync, browser, contexts = _fake_playwright({"https://a.com/x": boom, "https://a.com/": ("<p>ok</p>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    results = pr.PlaywrightRenderer(5000).render(["https://a.com/x", "https://a.com/"])
    assert results[0].error == "RuntimeError: net::ERR_NAME_NOT_RESOLVED at https://a.com/x"
    assert results[1].html == "<p>ok</p>"
    assert contexts[0].close.called and browser.close.called


def test_the_browser_is_closed_when_something_unexpected_happens(monkeypatch):
    sync, browser, _ = _fake_playwright({"https://a.com/": ("<p/>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    with pytest.raises(ValueError):
        pr.PlaywrightRenderer(5000).render(["https://a.com/"], on_progress=MagicMock(side_effect=ValueError("x")))
    assert browser.close.called


def test_unavailable_without_playwright(monkeypatch):
    def missing():
        raise ImportError("No module named 'playwright'")
    monkeypatch.setattr(pr, "_load_playwright", missing)
    assert pr.renderer_available() == (False, "Playwright is not installed")
    assert pr.playwright_chromium() is None


def test_unavailable_without_chromium(monkeypatch, tmp_path):
    sync, _, _ = _fake_playwright({})
    sync.return_value.__enter__.return_value.chromium.executable_path = str(tmp_path / "missing" / "chrome")
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    ok, reason = pr.renderer_available()
    assert ok is False and reason.startswith("Chromium is not installed")


def test_available_when_chromium_exists(monkeypatch, tmp_path):
    chrome = tmp_path / "chrome"; chrome.write_text("")
    sync, _, _ = _fake_playwright({})
    sync.return_value.__enter__.return_value.chromium.executable_path = str(chrome)
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    assert pr.renderer_available() == (True, "")
    assert pr.playwright_chromium() == str(chrome)
```

Append to `tests/test_vitals_lighthouse.py`:

```python
def test_find_chrome_falls_back_to_playwrights_chromium(monkeypatch):
    monkeypatch.setattr(lighthouse, "_chrome_candidates", lambda: [])
    monkeypatch.setattr(lighthouse.shutil, "which", lambda name: None)
    monkeypatch.setattr(lighthouse, "playwright_chromium", lambda: "/ms-playwright/chromium/chrome")
    assert find_chrome() == "/ms-playwright/chromium/chrome"
```

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/test_render_playwright.py tests/test_vitals_lighthouse.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'app.rendering.playwright_renderer'`)

- [ ] **Step 4: Implement `app/rendering/playwright_renderer.py`**

```python
"""Render pages in headless Chromium through Playwright.

Imported lazily: the default server image has the playwright package but no
browser, and an audit must then report rendering as unavailable, not fail."""

from __future__ import annotations

import logging
import os
import time
from typing import Callable, List, Optional, Tuple

from app.rendering.model import RenderResult

logger = logging.getLogger(__name__)

_BLOCKED = {"image", "media", "font"}
NETWORK_IDLE_MS = 2000


def _load_playwright():
    from playwright.sync_api import TimeoutError as PlaywrightTimeout
    from playwright.sync_api import sync_playwright
    return sync_playwright, PlaywrightTimeout


def _block_heavy(route) -> None:
    """Images, media and fonts change nothing an SEO check reads, and cost
    most of a page's bytes."""
    if route.request.resource_type in _BLOCKED:
        route.abort()
    else:
        route.continue_()


def _short(exc: Exception) -> str:
    first = (str(exc).splitlines() or [""])[0][:200]
    return f"{type(exc).__name__}: {first}" if first else type(exc).__name__


def _chromium_path() -> Tuple[Optional[str], str]:
    try:
        sync_playwright, _ = _load_playwright()
    except ImportError:
        return None, "Playwright is not installed"
    try:
        with sync_playwright() as pw:
            path = pw.chromium.executable_path
    except Exception as exc:
        return None, f"Playwright could not start: {_short(exc)}"
    if not path or not os.path.exists(path):
        return None, "Chromium is not installed (run: python -m playwright install chromium)"
    return path, ""


def renderer_available() -> Tuple[bool, str]:
    path, reason = _chromium_path()
    return (True, "") if path else (False, reason)


def playwright_chromium() -> Optional[str]:
    """Playwright's Chromium binary, if installed -- also used as Lighthouse's Chrome."""
    return _chromium_path()[0]


class PlaywrightRenderer:
    name = "playwright"

    def __init__(self, timeout_ms: int) -> None:
        self.timeout_ms = timeout_ms

    def render(self, urls: List[str],
               on_progress: Optional[Callable[[int, int, str], None]] = None) -> List[RenderResult]:
        """One browser for the whole batch, one page at a time (the sync API
        is single-threaded). A page's failure is that page's error."""
        sync_playwright, timeout_error = _load_playwright()
        results: List[RenderResult] = []
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for done, url in enumerate(urls, start=1):
                    results.append(self._render_one(browser, url, timeout_error))
                    if on_progress:
                        on_progress(done, len(urls), url)
            finally:
                browser.close()
        return results

    def _render_one(self, browser, url: str, timeout_error) -> RenderResult:
        # A fresh context per page: no cookies, storage or service workers
        # carried from one page to the next, and nothing downloaded.
        context = browser.new_context(java_script_enabled=True, accept_downloads=False,
                                      service_workers="block")
        try:
            page = context.new_page()
            page.route("**/*", _block_heavy)
            started = time.monotonic()
            response = page.goto(url, wait_until="load", timeout=self.timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=NETWORK_IDLE_MS)
            except timeout_error:
                pass  # long-polling pages never go idle; what has rendered by now counts
            html = page.content()
            return RenderResult(url=url, html=html, final_url=page.url,
                                status=response.status if response else None,
                                render_ms=round((time.monotonic() - started) * 1000, 1))
        except Exception as exc:
            logger.warning("Rendering %s failed: %s", url, _short(exc))
            return RenderResult(url=url, error=_short(exc))
        finally:
            context.close()
```

In `app/vitals/lighthouse.py`:
- Add `from app.rendering.playwright_renderer import playwright_chromium`.
- In `find_chrome`, replace the final `return None` with:

```python
    # Last resort: Playwright's own Chromium (the WITH_BROWSER server image has
    # no system Chrome, only this one).
    return playwright_chromium()
```

- [ ] **Step 5: Run and pass**

Run: `pip install "playwright>=1.48"` (already installed locally), then `python -m pytest tests/test_render_playwright.py tests/test_vitals_lighthouse.py tests/test_requirements_declare_imports.py -q`
Expected: all pass.

- [ ] **Step 6: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/rendering/playwright_renderer.py apps/backend/app/vitals/lighthouse.py apps/backend/app/config/config.py apps/backend/requirements.txt apps/backend/tests/test_render_playwright.py apps/backend/tests/test_vitals_lighthouse.py
git commit -m "feat(rendering): Playwright renderer with lazy import; Lighthouse can use its Chromium"
```

---

### Task 4: Storage

**Files:**
- Create: `apps/backend/alembic/versions/0005_render_comparisons.py`, `apps/backend/tests/test_render_storage.py`
- Modify:
  - `apps/backend/app/db/models.py`
  - `apps/backend/app/db/audit_store.py`
  - `apps/backend/app/services/summary_fields.py`
  - `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Consumes: `RenderComparison.to_dict()` (Task 2).
- Produces:
  - Model `RenderedPage` (table `render_comparisons`)
  - `record_audit` stores `result["rendering"]`
  - `SUMMARY_FIELDS` gains `"rendering", "render_status", "render_unavailable_reason"`

- [ ] **Step 1: Write the failing test**

```python
"""Raw-vs-rendered comparisons in the central DB."""

from sqlalchemy import select

from app.db.audit_store import record_audit
from app.db.engine import get_session_factory
from app.db.models import Audit, RenderedPage
from app.models.session_db import SessionDB
from app.rendering.model import RenderComparison


def test_record_audit_stores_comparisons_and_status(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": []}])
    rows = [RenderComparison(url="https://a.com/", render_ms=900, raw_word_count=40, rendered_word_count=900,
                             changes={"title": {"raw": "Loading", "rendered": "Shop"}},
                             js_only_links=["https://a.com/x"], js_only_links_count=1).to_dict(),
            RenderComparison(url="https://a.com/b", status="failed", error="Timeout").to_dict()]
    result = {"executive_summary": {"health_score": {"score": 70}}, "pages": [],
              "rendering": rows, "render_status": "rendered"}
    factory = get_session_factory()
    audit_id, _ = record_audit(factory, db, result, session_id="s1", start_url="https://a.com/")
    with factory() as session:
        stored = session.scalars(select(RenderedPage).where(RenderedPage.audit_id == audit_id)
                                 .order_by(RenderedPage.id)).all()
        assert [(r.url, r.status, r.rendered_word_count, r.changes_json, r.js_only_links_count, r.error) for r in stored] == [
            ("https://a.com/", "rendered", 900, {"title": {"raw": "Loading", "rendered": "Shop"}}, 1, None),
            ("https://a.com/b", "failed", None, {}, 0, "Timeout")]
        assert stored[0].js_only_links_json == ["https://a.com/x"]
        assert session.get(Audit, audit_id).summary_json["render_status"] == "rendered"
```

In `tests/test_db_schema.py`, add `"render_comparisons"` to `TABLES` next to `"web_vitals"`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_render_storage.py tests/test_db_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'RenderedPage'`

- [ ] **Step 3: Model** (append to `app/db/models.py`)

```python
class RenderedPage(Base):
    """One page's raw-vs-rendered comparison in one audit (Phase 5.2)."""
    __tablename__ = "render_comparisons"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    render_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rendered_word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    changes_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    js_only_links_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    js_only_links_count: Mapped[int] = mapped_column(Integer, default=0)
```

- [ ] **Step 4: Migration `alembic/versions/0005_render_comparisons.py`**

```python
"""render comparisons

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('render_comparisons',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('render_ms', sa.Float(), nullable=True),
    sa.Column('raw_word_count', sa.Integer(), nullable=True),
    sa.Column('rendered_word_count', sa.Integer(), nullable=True),
    sa.Column('changes_json', sa.JSON(), nullable=False),
    sa.Column('js_only_links_json', sa.JSON(), nullable=False),
    sa.Column('js_only_links_count', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_render_comparisons_audit_id'), 'render_comparisons', ['audit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_render_comparisons_audit_id'), table_name='render_comparisons')
    op.drop_table('render_comparisons')
```

- [ ] **Step 5: `record_audit` and summary fields**

In `app/db/audit_store.py`:
- Import `RenderedPage`.
- Add the helper below after `_record_vitals`.
- Call `_record_rendering(session, audit.id, result.get("rendering") or [])` after the `_record_vitals(...)` call.

```python
def _record_rendering(session: Session, audit_id: int, rows: List[Dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(RenderedPage), [{
            "audit_id": audit_id, "url": r["url"], "status": r.get("status", "rendered"),
            "error": r.get("error"), "render_ms": r.get("render_ms"),
            "raw_word_count": r.get("raw_word_count"), "rendered_word_count": r.get("rendered_word_count"),
            "changes_json": r.get("changes") or {}, "js_only_links_json": r.get("js_only_links") or [],
            "js_only_links_count": r.get("js_only_links_count") or 0,
        } for r in rows])
```

In `app/services/summary_fields.py`, change `"web_vitals", "web_vitals_status", "note",` to `"web_vitals", "web_vitals_status", "rendering", "render_status", "render_unavailable_reason", "note",`.

- [ ] **Step 6: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_render_storage.py tests/test_db_schema.py tests/test_audit_store.py -q
python -m pytest -q
git add apps/backend/app/db apps/backend/alembic/versions/0005_render_comparisons.py apps/backend/app/services/summary_fields.py apps/backend/tests/test_render_storage.py apps/backend/tests/test_db_schema.py
git commit -m "feat(rendering): render_comparisons table, migration 0005, stored with each audit"
```

---

### Task 5: Runner, pipeline, request, CLI, scheduler, progress

**Files:**
- Create: `apps/backend/app/rendering/runner.py`, `apps/backend/tests/test_render_pipeline.py`
- Modify:
  - `apps/backend/app/services/audit_service.py`
  - `apps/backend/app/schemas/schemas.py`
  - `apps/backend/app/api/routes.py`
  - `apps/backend/app/cli.py`
  - `apps/backend/app/scheduler/jobs.py`
  - `apps/backend/tests/test_cli.py`
  - `apps/backend/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `select_pages` (Task 1); `analyze_rendered`, `compare`, `rendering_issues` (Task 2); `PlaywrightRenderer`, `renderer_available` (Task 3).
- Produces:
  - `render_and_compare(renderer, start_url, top_pages, results, analyses, limit, on_progress=None) -> List[RenderComparison]`
  - `_build_audit_result(..., render_js=False, renderer=None, render_max_pages=None)` and `run_full_audit(..., render_js=False)`
  - Result keys: `rendering`, `render_status`, `render_unavailable_reason`
  - Event `("rendering", {"done", "total", "url"})`
  - `AuditRequestParams.render_js`, CLI `--render-js`

- [ ] **Step 1: Write the failing tests** (`tests/test_render_pipeline.py`)

```python
"""JavaScript rendering inside an audit: opt-in, compared against the raw
analysis, issues added and stored, never fatal."""

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import RenderedPage
from app.rendering.model import RenderResult
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler

JS_HTML = ("<html><head><title>Espresso machines</title><meta name='robots' content='noindex'></head>"
           "<body><h1>Best Espresso Machines</h1><p>" + "espresso " * 400 + "</p>"
           "<a href='/js-only'>more</a></body></html>")


class FakeRenderer:
    name = "fake"

    def __init__(self, html=JS_HTML, error=None, raises=None):
        self.calls, self.html, self.error, self.raises = [], html, error, raises

    def render(self, urls, on_progress=None):
        self.calls.append(list(urls))
        if self.raises:
            raise self.raises
        out = []
        for i, url in enumerate(urls, 1):
            out.append(RenderResult(url=url, error=self.error) if self.error
                       else RenderResult(url=url, html=self.html, final_url=url, status=200, render_ms=50))
            if on_progress:
                on_progress(i, len(urls), url)
        return out


def _run(**kwargs):
    events = []
    result = audit_service._build_audit_result(
        "https://example.com/", FakeCrawler(), progress_callback=None,
        event_callback=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return result, events


def test_off_by_default_and_nothing_launched(monkeypatch):
    monkeypatch.setattr(audit_service, "renderer_available", lambda: (_ for _ in ()).throw(AssertionError("checked")))
    result, _ = _run()
    assert result["render_status"] == "disabled" and result["rendering"] == []


def test_renders_compares_and_adds_issues():
    renderer = FakeRenderer()
    result, events = _run(render_js=True, renderer=renderer)
    assert renderer.calls == [["https://example.com/"]]
    assert result["render_status"] == "rendered"
    row = result["rendering"][0]
    assert row["changes"]["title"] == {"raw": "Espresso Machines", "rendered": "Espresso machines"}
    assert row["changes"]["meta_robots"]["rendered"] == "noindex"
    assert row["js_only_links"] == ["https://example.com/js-only"]
    codes = [i["code"] for i in result["page_issues_detail"]["https://example.com/"]]
    assert {"JS_TITLE_CHANGED", "JS_ROBOTS_CHANGED", "JS_CONTENT_DEPENDENT", "JS_ONLY_LINKS"} <= set(codes)
    assert ("rendering", {"done": 1, "total": 1, "url": "https://example.com/"}) in events
    with get_session_factory()() as session:
        stored = session.scalars(select(RenderedPage).where(RenderedPage.audit_id == result["audit_id"])).all()
        assert [r.url for r in stored] == ["https://example.com/"]


def test_a_failed_page_is_recorded_without_issues():
    result, _ = _run(render_js=True, renderer=FakeRenderer(error="TimeoutError: 20000ms"))
    assert result["rendering"][0]["status"] == "failed"
    assert not [i for i in result["page_issues_detail"]["https://example.com/"] if i["code"].startswith("JS_")]


def test_unavailable_browser_does_not_fail_the_audit(monkeypatch):
    monkeypatch.setattr(audit_service, "renderer_available", lambda: (False, "Playwright is not installed"))
    result, _ = _run(render_js=True)
    assert result["render_status"] == "unavailable"
    assert result["render_unavailable_reason"] == "Playwright is not installed"
    assert result["persisted"] is True


def test_a_crashing_renderer_is_unavailable_not_fatal():
    result, _ = _run(render_js=True, renderer=FakeRenderer(raises=RuntimeError("browser crashed")))
    assert result["render_status"] == "unavailable"
    assert result["render_unavailable_reason"] == "RuntimeError: browser crashed"


def test_the_page_limit_is_respected():
    renderer = FakeRenderer()
    _run(render_js=True, renderer=renderer, render_max_pages=0)
    assert renderer.calls == []
```

Append to `tests/test_cli.py`:

```python
def test_render_js_flag_reaches_the_audit_pipeline():
    from unittest.mock import patch

    from app import cli

    args = cli.build_parser().parse_args(["https://example.com/", "--render-js"])
    with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
        cli._run_audit(args)
    assert build.call_args.kwargs["render_js"] is True
    args = cli.build_parser().parse_args(["https://example.com/"])
    with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
        cli._run_audit(args)
    assert build.call_args.kwargs["render_js"] is False
```

In `tests/test_scheduler.py`, read the existing test that checks how `run_due_audits` calls its `runner` (it passes a fake runner and inspects kwargs). Add a test in the same style: a project with `audit_options={"render_js": True}` leads to `render_js=True` in the runner's kwargs, and a project without the option leads to `render_js=False`.

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_render_pipeline.py tests/test_cli.py tests/test_scheduler.py -q`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'render_js'` (and others)

- [ ] **Step 3: Implement `app/rendering/runner.py`**

```python
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
```

- [ ] **Step 4: Pipeline** (`app/services/audit_service.py`)

1. Imports:

```python
from app.rendering.compare import rendering_issues
from app.rendering.playwright_renderer import PlaywrightRenderer, renderer_available
from app.rendering.runner import render_and_compare
```

2. In `run_full_audit`, add the parameter `render_js: bool = False` (after `enable_web_vitals`) and pass `render_js=render_js`.

3. In `_build_audit_result`, add the parameters `render_js: bool = False, renderer=None, render_max_pages: Optional[int] = None` after `vitals_provider=None`.

4. In the Core Web Vitals block, compute the start page once:
   - Before `provider = None`, add `start_page = getattr(crawler, "start_url", None) or url`.
   - Use `start_page` in the `select_pages(` call in place of `getattr(crawler, "start_url", None) or url`.

5. Right after the Core Web Vitals block (after the `db.add_issues(measured.url, found)` loop and its blank line), insert:

```python
    # JavaScript rendering: opt-in, a sample of pages, compared with the raw
    # analysis. A missing browser or a crash reports "unavailable" -- the audit
    # stands either way.
    render_status, render_reason, render_results = "disabled", None, []
    if render_js:
        active = renderer
        if active is None:
            available, render_reason = renderer_available()
            active = PlaywrightRenderer(config.RENDER_TIMEOUT_MS) if available else None
        if active is None:
            render_status = "unavailable"
        else:
            def _render_progress(done: int, total: int, page_url: str) -> None:
                if event_callback:
                    event_callback("rendering", {"done": done, "total": total, "url": page_url})

            try:
                render_results = render_and_compare(
                    active, start_page, site_wide.get("top_pages_by_importance") or [],
                    crawler.results, analyses,
                    config.RENDER_MAX_PAGES if render_max_pages is None else render_max_pages,
                    on_progress=_render_progress)
                render_status = "rendered"
            except Exception as exc:
                logger.error("JavaScript rendering failed: %s", exc, exc_info=exc)
                first_line = (str(exc).splitlines() or [""])[0][:200]
                render_status = "unavailable"
                render_reason = f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__
            for comparison in render_results:
                found = rendering_issues(comparison)
                if found:
                    all_page_issues.setdefault(comparison.url, []).extend(found)
                    db.add_issues(comparison.url, found)
```

6. In `result_data`, after the `"web_vitals_status": web_vitals_status,` line, add:

```python
        "rendering": [c.to_dict() for c in render_results],
        "render_status": render_status,
        "render_unavailable_reason": render_reason,
```

- [ ] **Step 5: Request, routes, CLI, scheduler**

`app/schemas/schemas.py`, in `AuditRequestParams` after `enable_web_vitals`:

```python
    # Render a sample of pages in headless Chromium and compare with the raw
    # HTML (Phase 5.2). Off by default: it costs about 2 s per page.
    render_js: Optional[bool] = False
```

`app/api/routes.py`:
- In the `run_full_audit(` call, add `render_js=bool(params.render_js),` after the `enable_web_vitals=` line.
- Add `"rendering"` to the event tuple.
- Add this branch next to the `web_vitals` one:

```python
            elif event_type == "rendering":
                msg = f"Rendering JavaScript ({payload['done']}/{payload['total']})"
```

`app/cli.py`:
- After the `--psi-max-pages` argument, add the code below.
- In `_run_audit`, pass `render_js=args.render_js,` after `vitals_max_pages=args.psi_max_pages,`.

```python
    p.add_argument("--render-js", action="store_true",
                   help="Render the top pages in headless Chromium and compare with the raw HTML")
```

`app/scheduler/jobs.py`, in the `runner(` call, after `ignore_robots=...`:

```python
                render_js=bool(options.get("render_js", False)),
```

- [ ] **Step 6: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_render_pipeline.py tests/test_cli.py tests/test_scheduler.py -q
python -m pytest -q
git add apps/backend/app apps/backend/tests
git commit -m "feat(rendering): opt-in render_js for audits, CLI --render-js, scheduled audits"
```

---

### Task 6: Read API

**Files:**
- Create: `apps/backend/app/api/rendering.py`, `apps/backend/tests/test_render_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces: `GET /api/audits/{id}/rendering` → `{audit_id, status, reason, items: [{url, status, error, render_ms, raw_word_count, rendered_word_count, changes, js_only_links, js_only_links_count}]}`

- [ ] **Step 1: Write the failing test**

```python
"""Raw-vs-rendered comparisons over HTTP."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import Audit, Project, RenderedPage
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _audit(session, project_id, n, summary):
    t = datetime(2026, 10, 28, tzinfo=timezone.utc)
    audit = Audit(project_id=project_id, session_id=f"s{n}", start_url="https://a.com/", status="completed",
                  trigger="manual", started_at=t, finished_at=t, page_count=1, summary_json=summary)
    session.add(audit); session.flush()
    return audit.id


def test_lists_rows_with_status(client):
    with get_session_factory().begin() as s:
        project = Project(name="a.com", domain="a.com"); s.add(project); s.flush()
        rendered = _audit(s, project.id, 1, {"render_status": "rendered"})
        s.add(RenderedPage(audit_id=rendered, url="https://a.com/", status="rendered", render_ms=900,
                           raw_word_count=40, rendered_word_count=900,
                           changes_json={"title": {"raw": "Loading", "rendered": "Shop"}},
                           js_only_links_json=["https://a.com/x"], js_only_links_count=1))
        unavailable = _audit(s, project.id, 2, {"render_status": "unavailable",
                                                "render_unavailable_reason": "Playwright is not installed"})
        old = _audit(s, project.id, 3, {})
    body = client.get(f"/api/audits/{rendered}/rendering").json()
    assert body["status"] == "rendered" and body["reason"] is None
    assert body["items"] == [{"url": "https://a.com/", "status": "rendered", "error": None, "render_ms": 900.0,
                              "raw_word_count": 40, "rendered_word_count": 900,
                              "changes": {"title": {"raw": "Loading", "rendered": "Shop"}},
                              "js_only_links": ["https://a.com/x"], "js_only_links_count": 1}]
    assert client.get(f"/api/audits/{unavailable}/rendering").json() == {
        "audit_id": unavailable, "status": "unavailable", "reason": "Playwright is not installed", "items": []}
    assert client.get(f"/api/audits/{old}/rendering").json()["status"] == "disabled"
    assert client.get("/api/audits/99999/rendering").status_code == 404
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_render_api.py -q`
Expected: FAIL (404 for every route).

- [ ] **Step 3: Implement `app/api/rendering.py`**

```python
"""Raw-vs-rendered comparisons (Phase 5.2). Rendering happens inside audits,
so this is read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import Audit, RenderedPage

router = APIRouter()


@router.get("/audits/{audit_id}/rendering")
def audit_rendering(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        rows = session.scalars(select(RenderedPage).where(RenderedPage.audit_id == audit_id)
                               .order_by(RenderedPage.id)).all()
        summary = audit.summary_json or {}
        return {
            "audit_id": audit_id,
            "status": summary.get("render_status") or ("rendered" if rows else "disabled"),
            "reason": summary.get("render_unavailable_reason"),
            "items": [{
                "url": r.url, "status": r.status, "error": r.error, "render_ms": r.render_ms,
                "raw_word_count": r.raw_word_count, "rendered_word_count": r.rendered_word_count,
                "changes": r.changes_json or {}, "js_only_links": r.js_only_links_json or [],
                "js_only_links_count": r.js_only_links_count,
            } for r in rows],
        }
```

In `app/main.py`, after the vitals router lines:

```python
from app.api.rendering import router as rendering_router  # noqa: E402
app.include_router(rendering_router, prefix="/api")
```

- [ ] **Step 4: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_render_api.py -q
python -m pytest -q
git add apps/backend/app/api/rendering.py apps/backend/app/main.py apps/backend/tests/test_render_api.py
git commit -m "feat(rendering): audit rendering endpoint"
```

---

### Task 7: Frontend

**Files:**
- Modify:
  - `packages/shared/src/types/platform.ts`
  - `packages/shared/src/types/index.ts`
  - `apps/frontend/services/platform.ts`
  - `app/projects/[id]/audits/page.tsx`
  - `app/dashboard/page.tsx`
  - `app/page.tsx`
  - `components/__tests__/site-audit-page.test.tsx`
- Create:
  - `apps/frontend/components/platform/rendering-table.tsx`
  - `components/__tests__/rendering-table.test.tsx`
  - `components/__tests__/render-js-option.test.tsx`

**Interfaces:**
- Consumes: the Task 6 endpoint; the result keys from Task 5.
- Produces:
  - Types `RenderStatus`, `RenderChange`, `RenderComparison`, `AuditRendering`
  - `Platform.auditRendering(id)`
  - `<RenderingTable rows status reason />`

- [ ] **Step 1: Types and service**

Append to `packages/shared/src/types/platform.ts`:

```ts
// JavaScript rendering (backend Phase 5.2).
export type RenderStatus = "rendered" | "disabled" | "unavailable";
export interface RenderChange { raw: string | null; rendered: string | null }

export interface RenderComparison {
  url: string;
  status: "rendered" | "failed";
  error: string | null;
  render_ms: number | null;
  raw_word_count: number | null;
  rendered_word_count: number | null;
  changes: Partial<Record<"title" | "meta_description" | "canonical" | "meta_robots" | "h1", RenderChange>>;
  js_only_links: string[];
  js_only_links_count: number;
}

export interface AuditRendering { audit_id: number; status: RenderStatus; reason: string | null; items: RenderComparison[] }
```

In `packages/shared/src/types/index.ts`:
- Extend the import to `import type { RenderComparison, RenderStatus, VitalsRow, VitalsStatus } from "./platform";`.
- Add these after `web_vitals_status?: VitalsStatus;` in `AuditResponse`:

```ts
  rendering?: RenderComparison[];
  render_status?: RenderStatus;
  render_unavailable_reason?: string | null;
```

- Add `render_js?: boolean;` after `enable_web_vitals?: boolean;` in `AuditRequestParams`.

In `apps/frontend/services/platform.ts`:
- Add `AuditRendering` to the type import.
- Add this after `auditVitals`:

```ts
  auditRendering: (auditId: number) => request<AuditRendering>(`/audits/${auditId}/rendering`),
```

Then rebuild the shared package: `cd packages/shared && npx tsc` (`dist/` is gitignored and consumed by the frontend).

- [ ] **Step 2: Write the failing tests**

`components/__tests__/rendering-table.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { RenderingTable } from "@/components/platform/rendering-table";

const row = (over: object = {}) => ({
  url: "https://a.com/", status: "rendered" as const, error: null, render_ms: 812, raw_word_count: 40,
  rendered_word_count: 900, changes: { title: { raw: "Loading…", rendered: "Shop" }, meta_robots: { raw: null, rendered: "noindex" } },
  js_only_links: ["https://a.com/x"], js_only_links_count: 1, ...over,
});

describe("RenderingTable", () => {
  it("shows word counts, change chips and JS-only links", () => {
    render(<RenderingTable rows={[row()]} status="rendered" reason={null} />);
    expect(screen.getByText("40 → 900")).toBeInTheDocument();
    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Robots")).toBeInTheDocument();
    expect(screen.getByText("Content")).toBeInTheDocument();
    expect(screen.getByText("0.8 s")).toBeInTheDocument();
  });

  it("expands a row to show raw against rendered", async () => {
    render(<RenderingTable rows={[row()]} status="rendered" reason={null} />);
    await userEvent.click(screen.getByRole("button", { name: /show changes for https:\/\/a.com\//i }));
    expect(screen.getByText("Loading…")).toBeInTheDocument();
    expect(screen.getByText("noindex")).toBeInTheDocument();
    expect(screen.getByText("https://a.com/x")).toBeInTheDocument();
  });

  it("says when nothing changed", () => {
    render(<RenderingTable rows={[row({ changes: {}, rendered_word_count: 41, js_only_links: [], js_only_links_count: 0 })]} status="rendered" reason={null} />);
    expect(screen.getByText("No differences")).toBeInTheDocument();
  });

  it("shows a failed render's error", () => {
    render(<RenderingTable rows={[row({ status: "failed", error: "TimeoutError: 20000ms" })]} status="rendered" reason={null} />);
    expect(screen.getByText(/Couldn't render: TimeoutError: 20000ms/)).toBeInTheDocument();
  });

  it("explains the disabled and unavailable states", () => {
    const { rerender } = render(<RenderingTable rows={[]} status="disabled" reason={null} />);
    expect(screen.getByText(/Render JavaScript/)).toBeInTheDocument();
    rerender(<RenderingTable rows={[]} status="unavailable" reason="Playwright is not installed" />);
    expect(screen.getByText(/Browser not available on this server: Playwright is not installed/)).toBeInTheDocument();
  });
});
```

`components/__tests__/render-js-option.test.tsx`:

```tsx
/** "Render JavaScript" asks the API to render a sample of pages for one audit. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LandingPage from "@/app/page";
import { ApiService } from "@/services/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ startNewAudit: vi.fn(), setError: vi.fn(), isLoading: false, error: null }),
}));

async function submitWith(renderJs: boolean) {
  const runAudit = vi.spyOn(ApiService, "runAudit").mockResolvedValue({ session_id: "s" } as never);
  render(<LandingPage />);
  await userEvent.type(screen.getByPlaceholderText("https://example.com"), "https://example.com");
  await userEvent.click(screen.getByText("Advanced Overrides"));
  if (renderJs) await userEvent.click(screen.getByLabelText(/render javascript/i));
  await userEvent.click(screen.getByRole("button", { name: /start seo audit/i }));
  await waitFor(() => expect(runAudit).toHaveBeenCalled());
  return runAudit.mock.calls[0][0];
}

describe("Render JavaScript option", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("is off by default", async () => {
    expect(await submitWith(false)).toMatchObject({ render_js: false });
  });

  it("sends render_js when ticked", async () => {
    expect(await submitWith(true)).toMatchObject({ render_js: true });
  });
});
```

In `components/__tests__/site-audit-page.test.tsx`:
- In `beforeEach`, add `vi.spyOn(Platform, "auditRendering").mockResolvedValue({ audit_id: 3, status: "disabled", reason: null, items: [] });`.
- Add this test:

```tsx
  it("shows JavaScript rendering for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/Run an audit with/)).toBeInTheDocument();
    expect(Platform.auditRendering).toHaveBeenCalledWith(3);
  });
```

- [ ] **Step 3: Run and watch them fail**

Run: `cd apps/frontend && npx vitest run components/__tests__/rendering-table.test.tsx components/__tests__/render-js-option.test.tsx components/__tests__/site-audit-page.test.tsx`
Expected: FAIL.

- [ ] **Step 4: `components/platform/rendering-table.tsx`**

```tsx
"use client";

import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { RenderComparison, RenderStatus } from "@seo-auditor/shared";

const LABELS = { title: "Title", meta_description: "Description", canonical: "Canonical", meta_robots: "Robots", h1: "H1" } as const;
type Field = keyof typeof LABELS;

/** Mirrors JS_CONTENT_DEPENDENT in app/rendering/compare.py. */
function contentDependent(r: RenderComparison): boolean {
  const raw = r.raw_word_count ?? 0, rendered = r.rendered_word_count ?? 0;
  return rendered >= 2 * raw && rendered - raw >= 200;
}

function Chip({ children, tone = "amber" }: { children: React.ReactNode; tone?: "amber" | "slate" }) {
  const cls = tone === "amber"
    ? "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400"
    : "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400";
  return <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>{children}</span>;
}

const shown = (v: string | null) => (v && v.trim() ? v : "(none)");

export function RenderingTable({ rows, status, reason }: { rows: RenderComparison[]; status: RenderStatus; reason: string | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (status === "disabled") return <p className="text-sm text-muted-foreground">Not rendered. Run an audit with <em>Render JavaScript</em> on.</p>;
  if (status === "unavailable") return <p className="text-sm text-muted-foreground">Browser not available on this server: {reason ?? "unknown reason"}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No pages were rendered.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th>
            <th className="py-2 pr-4 font-medium">Words (raw → rendered)</th>
            <th className="py-2 pr-4 font-medium">What changed</th>
            <th className="py-2 pr-4 font-medium">JS-only links</th>
            <th className="py-2 font-medium">Time</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => {
            const fields = Object.keys(r.changes) as Field[];
            const expandable = r.status === "rendered" && (fields.length > 0 || r.js_only_links.length > 0);
            const isOpen = open === r.url;
            return (
              <Fragment key={r.url}>
                <tr className="align-top">
                  <td className="sticky left-0 max-w-[140px] break-all bg-card py-2 pr-4 sm:max-w-[260px]">
                    {expandable ? (
                      <button type="button" onClick={() => setOpen(isOpen ? null : r.url)} aria-expanded={isOpen}
                              aria-label={`Show changes for ${r.url}`} className="flex items-start gap-1 text-left hover:text-primary">
                        {isOpen ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
                        {r.url}
                      </button>
                    ) : r.url}
                  </td>
                  {r.status === "failed" ? (
                    <td colSpan={4} className="py-2 text-muted-foreground">Couldn&apos;t render: {r.error}</td>
                  ) : (
                    <>
                      <td className="whitespace-nowrap py-2 pr-4 tabular-nums">{r.raw_word_count ?? "—"} → {r.rendered_word_count ?? "—"}</td>
                      <td className="py-2 pr-4">
                        <span className="flex flex-wrap gap-1">
                          {contentDependent(r) && <Chip>Content</Chip>}
                          {fields.map((f) => <Chip key={f}>{LABELS[f]}</Chip>)}
                          {!contentDependent(r) && fields.length === 0 && r.js_only_links_count === 0 && <Chip tone="slate">No differences</Chip>}
                        </span>
                      </td>
                      <td className="py-2 pr-4 tabular-nums">{r.js_only_links_count}</td>
                      <td className="whitespace-nowrap py-2 tabular-nums">{r.render_ms != null ? `${(r.render_ms / 1000).toFixed(1)} s` : "—"}</td>
                    </>
                  )}
                </tr>
                {isOpen && (
                  <tr>
                    <td colSpan={5} className="bg-muted/30 px-3 py-3">
                      <dl className="space-y-2">
                        {fields.map((f) => (
                          <div key={f} className="grid gap-1 sm:grid-cols-[120px_1fr_1fr]">
                            <dt className="text-xs font-medium text-muted-foreground">{LABELS[f]}</dt>
                            <dd className="break-all"><span className="text-xs text-muted-foreground">Raw: </span>{shown(r.changes[f]!.raw)}</dd>
                            <dd className="break-all"><span className="text-xs text-muted-foreground">Rendered: </span>{shown(r.changes[f]!.rendered)}</dd>
                          </div>
                        ))}
                        {r.js_only_links.length > 0 && (
                          <div>
                            <dt className="text-xs font-medium text-muted-foreground">Links only after JavaScript ({r.js_only_links_count})</dt>
                            <dd><ul className="mt-1 space-y-0.5">{r.js_only_links.slice(0, 10).map((l) => <li key={l} className="break-all">{l}</li>)}</ul></dd>
                          </div>
                        )}
                      </dl>
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 5: Wire into the pages**

`app/projects/[id]/audits/page.tsx`:
- Import `RenderingTable`.
- Add this after the `vitals` hook:

```tsx
  const rendering = useApi(selected !== null ? () => Platform.auditRendering(selected) : null, [selected]);
```

- Insert this right after the Core Web Vitals `</section>`:

```tsx
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">JavaScript rendering</h2>
              <AsyncState state={rendering}>{(r) => <RenderingTable rows={r.items} status={r.status} reason={r.reason} />}</AsyncState>
            </section>
```

`app/dashboard/page.tsx`:
- Import `RenderingTable` from `@/components/platform/rendering-table`.
- In `DEFAULT_LAYOUT`, add `{ id: "rendering", width: "full", visible: true },` after the `performance` entry.
- In the panel map, add this after the `"performance": (...)` entry:

```tsx
    "rendering": auditData.render_status ? (
      <Card><CardHeader className="pb-3"><CardTitle className="text-base">JavaScript rendering</CardTitle></CardHeader>
        <CardContent><RenderingTable rows={auditData.rendering ?? []} status={auditData.render_status} reason={auditData.render_unavailable_reason ?? null} /></CardContent></Card>
    ) : null,
```

Read how the panel map is typed and rendered first. If a `null` entry breaks the layout loop's rendering (an empty wrapper), skip null panels the same way other conditional panels are handled.

`app/page.tsx`:
- Add `const [renderJs, setRenderJs] = useState(false);` after the `recheckAll` state.
- Add `render_js: renderJs,` after `fresh: recheckAll,` in `runAudit`.
- Insert this checkbox after the "Re-check every page" `</label>`:

```tsx
                <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border/50 bg-muted/20 p-3 hover:bg-muted/40 transition-colors">
                  <input
                    type="checkbox"
                    checked={renderJs}
                    onChange={(e) => setRenderJs(e.target.checked)}
                    className="h-4 w-4 rounded border-input bg-background text-primary focus:ring-primary"
                    disabled={isLoading}
                    aria-label="Render JavaScript"
                  />
                  <div>
                    <p className="text-sm font-semibold">Render JavaScript (slower)</p>
                    <p className="text-xs text-muted-foreground">Open the most important pages in a real browser and report what JavaScript changes</p>
                  </div>
                </label>
```

- [ ] **Step 6: Run and pass, then commit**

```bash
npx vitest run && npx tsc --noEmit
(cd ../backend && python -m pytest -q)
git add packages/shared/src apps/frontend
git commit -m "feat(frontend): JavaScript rendering table on Site Audit and report; Render JavaScript option"
```

---

### Task 8: Docker, env, docs

**Files:**
- Modify:
  - `apps/backend/Dockerfile`
  - `deploy/oracle/docker-compose.yml`
  - `apps/backend/.env.example`
  - `docs/env.md`, `docs/api.md`, `docs/deployment-oracle.md`
  - `README.md`

- [ ] **Step 1: Dockerfile**

Insert after the `RUN pip install --no-cache-dir -r requirements.txt` line:

```dockerfile
# Optional browser (Phase 5.2): Chromium for JavaScript rendering, plus Node and
# Lighthouse for the Core Web Vitals fallback, which uses the same Chromium.
# Off by default -- it adds a few hundred MB. Build with --build-arg WITH_BROWSER=true.
ARG WITH_BROWSER=false
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN if [ "$WITH_BROWSER" = "true" ]; then \
        python -m playwright install --with-deps chromium \
        && apt-get update && apt-get install -y --no-install-recommends nodejs npm \
        && npm install -g lighthouse@12 \
        && rm -rf /var/lib/apt/lists/* /root/.npm \
        && chmod -R a+rX /ms-playwright; \
    fi
ENV LIGHTHOUSE_ENABLED=${WITH_BROWSER}
```

- [ ] **Step 2: Compose**

In `deploy/oracle/docker-compose.yml`, under `backend.build`, add:

```yaml
      args:
        WITH_BROWSER: ${WITH_BROWSER:-false}
```

Under `backend.environment`, after `PSI_MAX_PAGES`, add:

```yaml
      RENDER_MAX_PAGES: ${RENDER_MAX_PAGES:-20}
      RENDER_TIMEOUT_MS: ${RENDER_TIMEOUT_MS:-20000}
```

- [ ] **Step 3: Env docs**

In `apps/backend/.env.example`, after `LIGHTHOUSE_CLI=`, add:

```
# JavaScript rendering (when an audit asks for it): pages rendered and the
# per-page timeout. Needs Playwright's Chromium: `python -m playwright install chromium`.
RENDER_MAX_PAGES=20
RENDER_TIMEOUT_MS=20000
```

In `docs/env.md`, after the `LIGHTHOUSE_CLI` row, add:

```
| `RENDER_MAX_PAGES` | Pages rendered in headless Chromium per audit when `render_js` is on | `20` |
| `RENDER_TIMEOUT_MS` | Per-page navigation timeout for rendering | `20000` |
```

- [ ] **Step 4: `docs/api.md`**

Append a section, "JavaScript rendering". It should cover:
- `POST /api/audit` accepts `"render_js": true`
- the result keys `rendering`, `render_status` (`rendered`/`disabled`/`unavailable`) and `render_unavailable_reason`
- the `JS_*` issue table, copied from the spec
- `GET /api/audits/{id}/rendering`, with the example response from Task 6's test in a fenced `json` block

- [ ] **Step 5: `docs/deployment-oracle.md`**

Append a section, "Optional browser (JavaScript rendering, Lighthouse)":

```markdown
## Optional browser (JavaScript rendering, Lighthouse)

The default backend image has no browser: audits run normally, rendering
reports "unavailable", and Core Web Vitals use PageSpeed Insights only. To add
Chromium (for `render_js`) plus Node and Lighthouse (the Core Web Vitals
fallback, using the same Chromium):

    WITH_BROWSER=true docker compose up -d --build backend

The image grows by a few hundred MB. Rendering is one page at a time, about
150 MB of memory while a page renders, 20 pages per audit by default
(`RENDER_MAX_PAGES`).
```

- [ ] **Step 6: README**

Append a section, "JavaScript rendering (Phase 5.2)". It should cover:
- what it does
- that it's off by default
- the form checkbox, `render_js` and `--render-js`
- that a project's saved `audit_options` (`{"render_js": true}`) apply to its scheduled audits
- the env vars and the Docker build arg
- a **How to verify (no money spent)** block:

```bash
cd apps/backend
python -m pytest tests/test_sampling.py tests/test_render_compare.py tests/test_render_playwright.py \
  tests/test_render_storage.py tests/test_render_pipeline.py tests/test_render_api.py -q
python -m playwright install chromium        # once
export SESSION_DIR=/tmp/seo-render
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links --render-js --json \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['render_status']); [print(r['url'], r['status'], r['raw_word_count'], r['rendered_word_count'], list(r['changes'])) for r in d['rendering']]"
```

Expected: `rendered`, then one line per page, and for this server-rendered site the change lists are empty.

- [ ] **Step 7: Commit**

```bash
python -m pytest -q
git add apps/backend/Dockerfile deploy/oracle/docker-compose.yml apps/backend/.env.example docs README.md
git commit -m "docs+deploy: JavaScript rendering env, API, optional browser image"
```

---

### Task 9: Live check

- [ ] **Step 1:** Run the README CLI command against books.toscrape.com with real Chromium. Expect `rendered`, and changes that are empty or near empty.
- [ ] **Step 2:** Serve a JS test site from a scratch directory with `python -m http.server 8765 --bind 127.0.0.1`.
  - `index.html` has `<title>Loading…</title>`, a `<div id="root">` and a script that sets `document.title`, adds `<meta name="robots" content="noindex">`, and inserts 400 words plus `<a href="/about.html">`.
  - `about.html` is plain.
  - Run the CLI with `--render-js` on `http://127.0.0.1:8765/`.
  - Expect `JS_TITLE_CHANGED`, `JS_ROBOTS_CHANGED`, `JS_CONTENT_DEPENDENT` and `JS_ONLY_LINKS` on `/`.
- [ ] **Step 3:** Start the backend (same `SESSION_DIR`) and `next dev`. Check at 1440 and 390 px:
  - the Site Audit "JavaScript rendering" section (including expanding a row)
  - the report panel
  - the home checkbox
  - no sideways page scroll
- [ ] **Step 4:** If Docker Desktop is running, `docker build --build-arg WITH_BROWSER=true -t seo-backend-browser apps/backend`, then `docker run --rm seo-backend-browser python -c "from app.rendering.playwright_renderer import renderer_available; print(renderer_available())"`. Expect `(True, '')`. If Docker isn't running, report the build as not tested.
- [ ] **Step 5:** Fix anything found (with a test when it's behaviour), commit, and stop the servers.
