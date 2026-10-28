# Phase 5.3: Accessibility audit with axe-core — Design

**Date:** 2026-10-29
**Status:** Approved, pending implementation plan
**Branch:** `feat/complete-site-audit`
**Brief:** `BUILD_PROMPT.md` Phase 5, item 3: "Full accessibility audit with
axe-core through Playwright." Third of five Phase 5 sub-projects (5.1 Core
Web Vitals and 5.2 JavaScript rendering are merged).

## Problem

Accessibility today is three raw-HTML checks in `app/auditor/checks.py`:
`A11Y_IMG_NO_ALT_ATTR`, `A11Y_UNLABELED_FORM_FIELD` and `A11Y_MISSING_LANG`.
Real problems such as colour contrast, ARIA misuse, focus order or button
names need a loaded page and a rules engine. Phase 5.2 already loads a sample
of pages in Chromium.

## Decisions taken

- **Own option, shared browser pass.** `accessibility` is separate from
  `render_js`. When either is on, each sampled page is loaded once, and both
  features use that load.
- **Damped severity, plus its own score.**
  - axe critical/serious → `warning`
  - moderate/minor → `info`
  - each page gets an accessibility score (0–100)
- **axe-core is vendored.** axe-core 4.10.x `axe.min.js` (MPL-2.0) is
  committed under `app/accessibility/vendor/` with its version and licence.
  It works offline and needs no extra install in Docker.

## Design

### 1. axe-core: `app/accessibility/axe.py`

- Vendored files:
  - `app/accessibility/vendor/axe.min.js`
  - `vendor/VERSION` (e.g. `4.10.3`)
  - `vendor/LICENSE` (MPL-2.0 text, from the package)
  - `vendor/README.md` (source and how to upgrade)
- `AXE_VERSION`: read from `VERSION`.
- `axe_source()`: reads `axe.min.js` once and caches it.
- `AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]`.
- `AXE_RUN = "async (tags) => await axe.run(document, {runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']})"`.

### 2. Renderer: one load, optional axe

`PlaywrightRenderer.render(urls, on_progress=None, run_axe=False)`:

- After `html = page.content()`, when `run_axe` is on:
  - `page.evaluate(axe_source())`, then
    `raw = page.evaluate(AXE_RUN, AXE_TAGS)`
  - The script is evaluated rather than injected as a `<script>` tag, so a
    page's Content-Security-Policy cannot block it.
- The result goes to `RenderResult.axe` (the raw dict). An exception from
  axe goes to `RenderResult.axe_error` (short message), and the HTML is kept.
- A navigation failure is unchanged: `error`, with no HTML and no axe.
- `Renderer` protocol and `RenderResult` gain `run_axe`, `axe` and
  `axe_error`.

### 3. Results, score and issues: `app/accessibility/model.py`, `scoring.py`

```python
@dataclass
class A11yResult:
    url: str
    status: str = "scanned"            # scanned | failed
    error: Optional[str] = None
    score: Optional[int] = None
    counts: Dict[str, int]             # critical, serious, moderate, minor (failed rules)
    violations: List[Dict]             # id, impact, help, help_url, wcag, nodes_count, targets
    def to_dict(self) -> dict
```

- **`summarize(url, raw) -> A11yResult`** builds one violation entry per rule:
  - `wcag`: only the tags that start with `wcag`
  - `targets`: the first 5 `node.target` selectors, joined with " " when
    nested
  - `nodes_count`: `len(nodes)`
  - Violations are sorted by impact (critical first), then by id.
- **Score:** `max(0, 100 − Σ penalty)` with penalties critical 10, serious 7,
  moderate 3, minor 1, per failed rule. A missing impact counts as minor.
- **`a11y_issues(result) -> List[issue]`:**
  - one issue per violation, coded `A11Y_` + `id.upper().replace("-", "_")`
  - severity `warning` for critical/serious, `info` otherwise
  - message `"{help} ({n} element[s], {impact})"`
  - rules `image-alt`, `label` and `html-has-lang` are skipped as issues (raw
    checks already report them on every page), but they stay in the stored
    result
  - a failed scan raises no issues
- `RECOMMENDATION_TEXT` falls back to the issue's own message for unknown
  codes. Check `generate_recommendations`; if it needs per-code text, add a
  generic accessibility line keyed on the `A11Y_` prefix.

### 4. Browser pass: `app/rendering/runner.py`

`render_and_compare` becomes:

```python
run_browser_pass(renderer, start_url, top_pages, results, analyses, limit,
                 render_js: bool, accessibility: bool, on_progress=None)
    -> Tuple[List[RenderComparison], List[A11yResult]]
```

- Same page selection as 5.2.
- Calls `renderer.render(urls, on_progress, run_axe=accessibility)` once.
- When `render_js` is on, it compares, as in 5.2.
- When `accessibility` is on:
  - `summarize` each `axe` result
  - an `axe_error` gives `A11yResult(status="failed", error=axe_error)`
  - a navigation error gives `status="failed"` with that error

### 5. Pipeline

- `_build_audit_result(..., accessibility=False)`, `run_full_audit(..., accessibility=False)`.
- The existing rendering block becomes a **browser block**:
  - It runs when `render_js or accessibility` is on.
  - Availability is checked once, and an unavailable browser marks both
    statuses `unavailable` with the same reason.
  - It calls `run_browser_pass` and adds both kinds of issues to
    `all_page_issues` and `db.add_issues`.
  - An exception sets both requested statuses to `unavailable`.
- The progress event stays `rendering`. The activity message reads
  "Rendering JavaScript (i/n)", or "Scanning accessibility (i/n)" when only
  accessibility is on: the event payload gains `"kind": "render" | "a11y"`.
- **Result JSON:**
  - `accessibility`: a list of `A11yResult` dicts
  - `accessibility_status`: `"scanned" | "disabled" | "unavailable"`
  - `accessibility_unavailable_reason`
  - `axe_version`
  - All four are added to `SUMMARY_FIELDS`.
- `AuditRequestParams.accessibility: Optional[bool] = False`, routes, CLI
  `--a11y`, scheduler `options.get("accessibility")`.

### 6. Storage

Migration `0006_accessibility_results` adds the table `accessibility_results`:

| Column | Type |
| --- | --- |
| `id` | int PK |
| `audit_id` | FK `audits.id`, `ON DELETE CASCADE`, indexed |
| `url` | text |
| `status` | string(16) |
| `error` | text, nullable |
| `score` | int, nullable |
| `critical`, `serious`, `moderate`, `minor` | int, default 0 |
| `violations_json` | JSON, default `[]` |

`record_audit` inserts the rows from `result["accessibility"]`.

### 7. API

`GET /api/audits/{id}/accessibility` → `{audit_id, status, reason, axe_version,
items: [{url, status, error, score, counts, violations}]}`.

- `status`, `reason` and `axe_version` come from `summary_json`. Without
  them, the status is `"scanned"` if there are rows, else `"disabled"`.
- Returns 404 for an unknown audit.

### 8. UI

- **Types:** `A11yImpact`, `A11yViolation`, `A11yResult`, `A11yStatus`,
  `AuditAccessibility`. `Platform.auditAccessibility(id)`. `AuditResponse`
  and `AuditRequestParams` gain the matching fields.
- **`components/platform/accessibility-table.tsx`**
  (`AccessibilityTable({rows, status, reason})`):
  - **Columns:** Page, Score (pill: ≥ 90 good, ≥ 50 needs work, else poor;
    icon + text), Critical, Serious, Moderate, Minor.
  - **Expanding a row** lists violations: impact pill (icon + text), help
    text, element count, WCAG tags, up to 5 selectors (monospace, wrapped),
    and a "How to fix" link (`target="_blank" rel="noopener noreferrer"`).
  - A failed row shows "Couldn't scan: {error}".
  - A footnote states the score formula, and that automated checks find
    about a third of accessibility problems, so this is not a full WCAG
    audit.
  - **States:**
    - `disabled`: "Not scanned. Run an audit with *Accessibility audit* on."
    - `unavailable`: "Browser not available on this server: {reason}"
- **Site Audit tab:** an "Accessibility" section after "JavaScript rendering".
- **Report:** an `accessibility` panel after `rendering`, hidden when there is
  no status.
- **Home form:** an "Accessibility audit (slower)" checkbox → `accessibility`.

## Error handling

| Case | Result |
| --- | --- |
| Option off | `accessibility_status="disabled"`, axe never injected |
| No browser | `"unavailable"` + reason, the audit completes |
| axe throws on a page | that row `failed` + error, rendering for that page still compared |
| Navigation fails | the row `failed`, the others continue |
| Missing vendored file | `"unavailable"`, "axe-core not found" (checked before the pass) |

## Testing

- **`summarize`, score, issues:**
  - impact mapping
  - the duplicate-rule skip
  - the floor at 0
  - the 5-selector cap, with nested targets joined
  - sort order
  - singular/plural "element"
- **Renderer:** with Playwright faked, `run_axe=True` evaluates the axe source
  and `AXE_RUN` with `AXE_TAGS`, an axe exception becomes `axe_error` with the
  HTML kept, and `run_axe=False` doesn't evaluate.
- **`run_browser_pass`:** rendering only, accessibility only, both (one
  `render` call), failures.
- **Pipeline:** a fake renderer gives issues, rows, statuses and events,
  unavailable, and `accessibility=False`.
- **Storage, API, CLI `--a11y`, request param, scheduler option.**
- **Vendored file:** it exists, `VERSION` matches the `axe.version` string
  inside the file, and the licence is present.
- **Frontend:** the table, expanding a row, the states, the footnote, the
  checkbox sends `accessibility`.
- **No real browser or network in tests.**
- **Live check:**
  - books.toscrape.com with real axe
  - a local page with a low-contrast button, an image without alt text and an
    unlabeled input
  - UI screenshots at 1440 and 390 px

## Done when

An audit with `accessibility` on scans up to 20 pages with axe-core and stores
and shows per-page scores and violations, with issues feeding the health
score (damped). It is off by default, never fails an audit, and the docs and
tests are updated.

## Out of scope

- Keyboard and focus-order simulation, screenshots of failing elements, and
  best-practice (non-WCAG) rules.
- An accessibility trend on the Overview (possible later).
