# Phase 5.2: JavaScript rendering (raw vs rendered) — Design

**Date:** 2026-10-28
**Status:** Approved, pending implementation plan
**Branch:** `feat/complete-site-audit`
**Brief:** `BUILD_PROMPT.md` Phase 5, item 1: "JS rendering with Playwright
(optional flag), rendered vs raw HTML comparison." Second of five Phase 5
sub-projects (5.1 Core Web Vitals is merged).

## Problem

The crawler fetches with `requests` and analyses raw HTML only. A page whose
title, canonical, robots, content or links are set by JavaScript is audited
on what a non-rendering crawler sees, and nothing reports the difference. The
only JS signal is a heuristic (`POSSIBLE_CSR_ONLY` in
`app/auditor/checks.py`).

## Decisions taken

- **Sample, not full render-crawl:** the crawl stays raw. Afterwards, up to
  `RENDER_MAX_PAGES` pages are rendered and compared. Links that exist only
  after JS are reported, not crawled.
- **Off by default:** request `render_js: true`, CLI `--render-js`, a home
  form checkbox, and a project's saved `audit_options.render_js` for
  scheduled audits.
- **Docker:** a `WITH_BROWSER` build arg (default off) adds Chromium (with
  system dependencies), Node and Lighthouse, so rendering *and* the 5.1
  Lighthouse fallback work on the Oracle VM. The default image only gains the
  `playwright` pip package (about 40 MB). `tests/test_requirements_declare_imports.py`
  requires every import to be declared in `requirements.txt`.

## Design

### 1. Page selection (shared)

`app/vitals/runner.select_vitals_pages` moves to
`app/analysis/sampling.py` as:

```python
select_pages(start_url, top_pages, results, limit, priority=())
```

The order is: the start URL, then `priority` URLs, then the top pages by
PageRank, then the shallowest pages. Only status-200 HTML pages, deduplicated,
up to `limit`. Vitals calls it with no `priority`. Rendering passes the pages
that carry `POSSIBLE_CSR_ONLY`.

### 2. Renderer layer: `app/rendering/`

```python
@dataclass
class RenderResult:
    url: str
    html: str = ""
    final_url: Optional[str] = None
    status: Optional[int] = None
    render_ms: Optional[float] = None
    error: Optional[str] = None

class Renderer(Protocol):
    name: str
    def render(self, urls: List[str], on_progress=None) -> List[RenderResult]: ...
```

- **`PlaywrightRenderer(timeout_ms)`**
  - Imports Playwright lazily.
  - Launches one headless Chromium per `render()` call and renders the URLs
    one at a time (the sync API is single-threaded).
  - Each URL gets a fresh context: JavaScript on, `accept_downloads=False`,
    `service_workers="block"`, no permissions, and Chromium's own
    User-Agent (it identifies as HeadlessChrome).
  - Images, media and fonts are aborted via `route`.
  - It runs `goto(wait_until="load", timeout=timeout_ms)`, then
    `wait_for_load_state("networkidle", timeout=2000)`. A timeout of that
    second wait is ignored.
  - `html = page.content()`.
  - Errors on one URL become that URL's `error`, and the rest continue.
  - The browser is always closed.
- **`renderer_available() -> Tuple[bool, str]`:** Playwright importable and
  Chromium executable present (`chromium.executable_path` exists). Otherwise
  `(False, reason)`.
- **`build_renderer()`** returns `PlaywrightRenderer(config.RENDER_TIMEOUT_MS)`,
  or `None` when it isn't available.
- **Shared Chromium:** `app/vitals/lighthouse.find_chrome()` falls back to
  Playwright's Chromium path, so Lighthouse works wherever Playwright's
  browser is installed.

### 3. Comparison and issues: `app/rendering/compare.py`

Both versions go through `page_pipeline.analyze_html` (rendered HTML in a
`PagePayload` with the raw page's URL, status 200 and headers), so they are
parsed identically. The comparison reads `meta["title"]`,
`meta["meta_description"]`, `meta["canonical"]`, `meta["meta_robots"]`,
`meta["h1"]`, `meta["word_count"]` and `internal_links`.

```python
compare(url, raw: HtmlAnalysis, rendered: HtmlAnalysis) -> RenderComparison
# RenderComparison: url, status="rendered", raw_word_count, rendered_word_count,
#   changes: Dict[field, {"raw": .., "rendered": ..}] (only changed fields;
#   strings compared after strip(); None == ""),
#   js_only_links: sorted(rendered.internal_links - raw.internal_links)[:50],
#   js_only_links_count, render_ms, error
```

**Issues** (added to the page's issues and to the session DB with
`add_issues`, so they count in the health score):

| Code | Severity | Rule |
| --- | --- | --- |
| `JS_CONTENT_DEPENDENT` | warning | rendered ≥ 2 × raw words and rendered − raw ≥ 200 |
| `JS_ROBOTS_CHANGED` | warning | `meta_robots` changed |
| `JS_CANONICAL_CHANGED` | warning | `canonical` changed |
| `JS_TITLE_CHANGED` | warning | `title` changed |
| `JS_META_DESCRIPTION_CHANGED` | info | `meta_description` changed |
| `JS_H1_CHANGED` | info | `h1` changed |
| `JS_ONLY_LINKS` | info | `js_only_links_count > 0` |

Messages name both values, e.g. "Title changed by JavaScript: 'Loading…' →
'Espresso machines'", or "40 words in raw HTML, 900 after JavaScript". A
failed render gets `status="failed"`, an `error`, and no issues.

`IMPACT_WEIGHTS` and `RECOMMENDATION_TEXT` get entries for every code.

### 4. Audit integration

- `_build_audit_result(..., render_js=False, renderer=None, render_max_pages=None)`
  and `run_full_audit(..., render_js=False)`.
- It runs after `site_wide` and Core Web Vitals, before recommendations.
- The raw `HtmlAnalysis` per URL comes from `analyses[url].html_part`.
  - Pages reused from the page cache also carry `html_part`.
  - A page without one (failed analysis) is not selected.
- Rendering runs in the audit's thread. `event_callback("rendering",
  {"done", "total", "url"})` drives the activity feed message "Rendering
  JavaScript (i/n)", and `routes.py` gets that branch.
- **Result JSON:**
  - `rendering`: a list of `RenderComparison` dicts
  - `render_status`: `"rendered" | "disabled" | "unavailable"`
  - `render_unavailable_reason`: when `"unavailable"`
  - All three are added to `SUMMARY_FIELDS`.
- `AuditRequestParams.render_js: Optional[bool] = False`, routes pass it, the
  CLI has `--render-js`, and the scheduler passes
  `render_js=bool(options.get("render_js", False))`.
- Rendering never fails the audit. Any exception becomes `render_status`
  `"unavailable"` with the reason logged, or a per-page error.

### 5. Storage

Migration `0005_render_comparisons` adds the table `render_comparisons`:

| Column | Type |
| --- | --- |
| `id` | int PK |
| `audit_id` | FK `audits.id`, `ON DELETE CASCADE`, indexed |
| `url` | text |
| `status` | string(16) |
| `error` | text, nullable |
| `render_ms` | float, nullable |
| `raw_word_count`, `rendered_word_count` | int, nullable |
| `changes_json` | JSON (default `{}`) |
| `js_only_links_json` | JSON (default `[]`) |
| `js_only_links_count` | int, default 0 |

`audit_store.record_audit` inserts the rows from `result["rendering"]`.

### 6. API

`GET /api/audits/{id}/rendering` → `{audit_id, status, reason, items:
[{url, status, error, render_ms, raw_word_count, rendered_word_count,
changes, js_only_links, js_only_links_count}]}`.

- `status` comes from the audit's `summary_json.render_status`: `"rendered"`
  if there are rows, else `"disabled"`.
- Returns 404 for an unknown audit.

### 7. UI

- **Shared types:** `RenderChange`, `RenderComparison`, `RenderStatus`,
  `AuditRendering`. `Platform.auditRendering(id)`. `AuditResponse` gains
  `rendering?`, `render_status?`, `render_unavailable_reason?`.
  `AuditRequestParams` gains `render_js?`.
- **`components/platform/rendering-table.tsx`** (`RenderingTable({rows,
  status, reason})`):
  - **Columns:** Page, Words (raw → rendered), What changed (chips: Title,
    Description, Canonical, Robots, H1, plus "Content" when
    `JS_CONTENT_DEPENDENT` applies), JS-only links (count), Time.
  - **Expanding a row** shows each change as raw vs rendered, plus up to 10
    JS-only links.
  - **Empty states:**
    - `disabled`: "Not rendered. Run an audit with *Render JavaScript* on."
    - `unavailable`: "Browser not available on this server: {reason}"
    - rows with nothing changed: a "No differences" chip
  - Failed rows show "Couldn't render: {error}".
- **Site Audit tab:** a "JavaScript rendering" section for the selected audit.
- **Report (`/dashboard`):** the same section in its layout, when
  `render_status` is present.
- **Home form:** a "Render JavaScript (slower)" checkbox → `render_js`.

### 8. Docker and config

- **Dockerfile:**
  - `ARG WITH_BROWSER=false`.
  - When `true`, it runs `python -m playwright install --with-deps chromium`
    and installs `nodejs npm`, then `npm i -g lighthouse@12`.
  - It sets `ENV LIGHTHOUSE_ENABLED=true` and
    `PLAYWRIGHT_BROWSERS_PATH=/ms-playwright`, readable by the non-root
    user.
  - `requirements.txt` gains `playwright>=1.48`.
- **Compose:** a `WITH_BROWSER` build arg (default `false`), plus the env
  vars below.
- **`docs/deployment-oracle.md`:** how to build with the browser, and the
  memory note: about 150 MB per page while rendering, one page at a time.

| Env | Default | Meaning |
| --- | --- | --- |
| `RENDER_MAX_PAGES` | `20` | Pages rendered per audit when `render_js` is on |
| `RENDER_TIMEOUT_MS` | `20000` | Per-page navigation timeout |

## Error handling

| Case | Result |
| --- | --- |
| `render_js` false | `render_status="disabled"`, nothing launched |
| Playwright or Chromium missing | `"unavailable"` + reason, the audit continues |
| Browser launch fails | `"unavailable"` + reason |
| One page times out or errors | that row `status="failed"`, `error`, the others continue |
| No raw analysis for a page | not selected |

## Testing

- **`select_pages`:** the order (start, priority, PageRank, depth), filters
  and limit. The vitals tests keep passing through the moved function.
- **`compare` + issues:** every rule and boundary (2× and +200 words), a
  None/"" equivalence, JS-only link capping at 50, a failed render with no
  issues.
- **`PlaywrightRenderer`:** with `sync_playwright` mocked:
  - context options (no downloads, service workers blocked)
  - resource blocking
  - a per-URL error doesn't stop the rest
  - the browser is closed on error
  - the networkidle timeout is ignored
- **`renderer_available`:** an import failure or a missing executable gives
  `(False, reason)`.
- **Pipeline** with a fake renderer:
  - issues added and stored
  - `rendering` and `render_status` in the result
  - `render_js=False` doesn't build a renderer
  - unavailable doesn't fail the audit
  - progress events
- **Storage and API:** rows written, the endpoint, 404.
- **CLI `--render-js`, request param, scheduler passthrough.**
- **Frontend:** the table (changes, chips, expand, failed row, the three
  states), the Site Audit section, the home checkbox sends `render_js`.
- **No real browser in tests.**
- **Live check:**
  - a real Chromium render of books.toscrape.com (expect no changes)
  - a small local test page whose title, canonical and content are set by
    JS (expect the changes and issues)
  - the UI at 1440 and 390 px

## Done when

An audit with `render_js` on renders up to 20 pages locally and stores and
shows the raw-vs-rendered differences and issues. Without Playwright's
browser it reports "unavailable" and completes. The Docker image builds with
`WITH_BROWSER=true` (or that check is reported as not run). Tests and docs are
updated.

## Out of scope

- Crawling JS-only links, rendering every page, screenshots.
- Comparing structured data or hreflang (possible later).
