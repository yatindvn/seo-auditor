# Accessibility Audit with axe-core (Phase 5.3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** With `accessibility` on, an audit runs axe-core (WCAG 2.2 A/AA) on
the sampled pages during the same Chromium load as JavaScript rendering, and
stores and shows per-page scores and violations. The issues feed the health
score, damped.

**Architecture:**
- A new `app/accessibility/` package holds:
  - vendored axe-core 4.14.0
  - the run script and tags
  - a result model
  - pure summarise/score/issue functions
- `PlaywrightRenderer.render` gains `run_axe`. On the already-loaded page it
  evaluates axe and returns the raw result.
- `render_and_compare` becomes `run_browser_pass`, which returns both
  rendering comparisons and accessibility results from one `render` call.
- The pipeline's rendering block becomes a browser block that drives both
  options.
- Storage, an endpoint and a table component follow the 5.2 pattern.

**Tech Stack:** Python, Playwright (sync), axe-core 4.14.0 (vendored, MPL-2.0), SQLAlchemy/Alembic, FastAPI, pytest; Next.js 14, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-accessibility-axe-design.md`

## Global Constraints

- **axe-core:** 4.14.0, vendored at `apps/backend/app/accessibility/vendor/`. The download was verified: the tarball sha512 matches npm's `dist.integrity`, and `axe.min.js` sha256 `IMCf4Veoo0ow4kGqofza3mV3NPCKs3ns++t9RcxG6Hg=` matches axe's `sri-history.json`.
- **Off by default:** request `accessibility` (default `false`), CLI `--a11y`, home checkbox, scheduler `audit_options.accessibility`.
- **Same browser pass as `render_js`:** the same page selection and `RENDER_MAX_PAGES`, and one `render()` call per audit even when both options are on.
- **Scan settings:** tags `wcag2a, wcag2aa, wcag21a, wcag21aa, wcag22aa`, `resultTypes: ['violations']`. axe is run with `page.evaluate` (CSP-proof), never via a `<script>` tag.
- **Score:** `max(0, 100 − Σ per failed rule)` with penalties critical 10, serious 7, moderate 3, minor 1. Unknown/missing impact counts as minor.
- **Issues:**
  - code `A11Y_` + rule id upper-cased with `-`→`_`
  - critical/serious → `warning`, moderate/minor → `info`
  - message `"{help} ({n} element[s], {impact})"`
  - rules `image-alt`, `label`, `html-has-lang` are stored but don't become issues
- **Untrusted page data:** axe runs in the page's own JS world, so a hostile page could tamper with it. Treat its output as untrusted:
  - impacts are whitelisted
  - strings are truncated (id 100, help 300, each target 200)
  - `help_url` is kept only if it starts with `https://dequeuniversity.com/`
  - at most 5 targets per rule
- **Never fatal:** no browser or no axe file → `accessibility_status="unavailable"` with a reason. An axe error on a page → that row `failed`.
- **Tests:** no real browser and no network. Run the full backend suite before each commit.

---

### Task 1: Vendor axe-core and its loader

**Files:**
- Create:
  - `apps/backend/app/accessibility/__init__.py`
  - `apps/backend/app/accessibility/axe.py`
  - `apps/backend/app/accessibility/vendor/axe.min.js` (copied)
  - `vendor/LICENSE` (copied)
  - `vendor/LICENSE-3RD-PARTY.txt` (copied)
  - `vendor/VERSION`
  - `vendor/README.md`
- Test: `apps/backend/tests/test_axe_vendor.py`

**Interfaces:**
- Produces: `AXE_VERSION: str`, `AXE_TAGS: List[str]`, `AXE_RUN: str`, `axe_source() -> str` (cached), `axe_available() -> Tuple[bool, str]`

- [ ] **Step 1: Write the failing test**

```python
"""The vendored axe-core: present, the version we say, licensed."""

from app.accessibility import axe


def test_the_vendored_file_is_the_version_we_record():
    assert axe.AXE_VERSION == "4.14.0"
    assert f'axe.version="{axe.AXE_VERSION}"' in axe.axe_source()


def test_the_licences_ship_with_it():
    assert "Mozilla Public License" in (axe.VENDOR / "LICENSE").read_text(encoding="utf-8")
    assert (axe.VENDOR / "LICENSE-3RD-PARTY.txt").exists()


def test_source_is_read_once():
    assert axe.axe_source() is axe.axe_source()


def test_wcag_22_a_and_aa_tags():
    assert axe.AXE_TAGS == ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
    assert "axe.run(document" in axe.AXE_RUN and "violations" in axe.AXE_RUN


def test_available_reports_a_missing_file(monkeypatch, tmp_path):
    assert axe.axe_available() == (True, "")
    monkeypatch.setattr(axe, "VENDOR", tmp_path)
    ok, reason = axe.axe_available()
    assert ok is False and reason == "axe-core not found (app/accessibility/vendor/axe.min.js)"
```

- [ ] **Step 2: Run and watch it fail**

Run: `cd apps/backend && python -m pytest tests/test_axe_vendor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.accessibility'`

- [ ] **Step 3: Copy the vendored files**

From the verified package in the scratchpad (`scratchpad/axe/package/`):

```bash
mkdir -p apps/backend/app/accessibility/vendor
cp "$S/axe/package/axe.min.js" "$S/axe/package/LICENSE" "$S/axe/package/LICENSE-3RD-PARTY.txt" apps/backend/app/accessibility/vendor/
printf '4.14.0\n' > apps/backend/app/accessibility/vendor/VERSION
```

`vendor/README.md`:

```markdown
# Vendored axe-core

`axe.min.js` is axe-core 4.14.0 from npm (`npm pack axe-core@4.14.0`),
unmodified, under the Mozilla Public License 2.0 (`LICENSE`; bundled
dependencies in `LICENSE-3RD-PARTY.txt`). Source: https://github.com/dequelabs/axe-core

Verified when added (2026-10-29):
- tarball sha512 matched npm's `dist.integrity`
- `axe.min.js` sha256 `IMCf4Veoo0ow4kGqofza3mV3NPCKs3ns++t9RcxG6Hg=` matched axe-core's `sri-history.json`

To upgrade:
1. `npm pack axe-core@<version>` and check both hashes the same way.
2. Copy `axe.min.js` and the two licence files here.
3. Update `VERSION`.
4. Run `pytest tests/test_axe_vendor.py`.
```

- [ ] **Step 4: Implement**

`app/accessibility/__init__.py`:

```python
"""Accessibility: axe-core (WCAG 2.2 A/AA) run inside pages loaded by the
JavaScript-rendering browser pass."""
```

`app/accessibility/axe.py`:

```python
"""The vendored axe-core (see vendor/README.md) and how it's run."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Tuple

VENDOR = Path(__file__).resolve().parent / "vendor"


def _version() -> str:
    try:
        return (VENDOR / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


AXE_VERSION = _version()
AXE_TAGS: List[str] = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
# Evaluated with page.evaluate, not injected as a <script> tag: a page's
# Content-Security-Policy can block injected scripts, not evaluation.
AXE_RUN = ("async (tags) => await axe.run(document, "
           "{runOnly: {type: 'tag', values: tags}, resultTypes: ['violations']})")


@lru_cache(maxsize=1)
def axe_source() -> str:
    return (VENDOR / "axe.min.js").read_text(encoding="utf-8")


def axe_available() -> Tuple[bool, str]:
    if (VENDOR / "axe.min.js").exists():
        return True, ""
    return False, "axe-core not found (app/accessibility/vendor/axe.min.js)"
```

- [ ] **Step 5: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_axe_vendor.py -q
python -m pytest -q
git add apps/backend/app/accessibility apps/backend/tests/test_axe_vendor.py
git commit -m "feat(a11y): vendor axe-core 4.14.0 (MPL-2.0, hash-verified) and its loader"
```

---

### Task 2: Results, score and issues

**Files:**
- Create: `apps/backend/app/accessibility/model.py`, `apps/backend/app/accessibility/scoring.py`
- Modify: `apps/backend/app/ai/ai_suggestions.py`
- Test: `apps/backend/tests/test_a11y_scoring.py`

**Interfaces:**
- Produces:
  - `IMPACTS = ("critical", "serious", "moderate", "minor")`
  - `A11yResult(url, status="scanned", error=None, score=None, counts={...0}, violations=[])` with `.to_dict()`
  - `summarize(url, raw: dict) -> A11yResult`
  - `a11y_issues(result) -> List[dict]`
  - `COVERED_BY_RAW_CHECKS`
  - `ai_suggestions.recommendation_text(code) -> Optional[str]`

- [ ] **Step 1: Write the failing test**

```python
"""axe results → a page's accessibility score, violations and issues."""

from app.accessibility.model import A11yResult
from app.accessibility.scoring import a11y_issues, summarize
from app.ai import ai_suggestions


def _v(rule, impact, n=1, **over):
    return {"id": rule, "impact": impact, "help": f"Help for {rule}",
            "helpUrl": f"https://dequeuniversity.com/rules/axe/4.14/{rule}",
            "tags": ["cat.color", "wcag2aa", "wcag143", "EN-301-549"],
            "nodes": [{"target": [f"#el{i}"]} for i in range(n)], **over}


RAW = {"violations": [_v("region", "moderate"), _v("color-contrast", "serious", 12),
                      _v("image-alt", "critical", 2), _v("aria-allowed-attr", "critical"),
                      _v("landmark-one-main", None)]}


def test_summary_sorts_counts_and_scores():
    r = summarize("https://a.com/", RAW)
    assert [v["id"] for v in r.violations] == ["aria-allowed-attr", "image-alt", "color-contrast", "region", "landmark-one-main"]
    assert r.counts == {"critical": 2, "serious": 1, "moderate": 1, "minor": 1}
    assert r.score == 100 - 10 - 10 - 7 - 3 - 1
    cc = [v for v in r.violations if v["id"] == "color-contrast"][0]
    assert cc == {"id": "color-contrast", "impact": "serious", "help": "Help for color-contrast",
                  "help_url": "https://dequeuniversity.com/rules/axe/4.14/color-contrast",
                  "wcag": ["wcag2aa", "wcag143"], "nodes_count": 12,
                  "targets": ["#el0", "#el1", "#el2", "#el3", "#el4"]}


def test_score_floors_at_zero():
    raw = {"violations": [_v(f"rule-{i}", "critical") for i in range(15)]}
    assert summarize("u", raw).score == 0


def test_no_violations_is_a_perfect_score():
    r = summarize("u", {"violations": []})
    assert (r.score, r.violations, r.counts["critical"]) == (100, [], 0)


def test_nested_targets_are_joined_and_page_data_is_distrusted():
    raw = {"violations": [_v("button-name", "evil-impact", helpUrl="javascript:alert(1)",
                             help="x" * 1000, nodes=[{"target": [["iframe#f", "#inner"]]}, {"target": ["#" + "a" * 500]}])]}
    v = summarize("u", raw).violations[0]
    assert v["impact"] == "minor" and v["help_url"] is None and len(v["help"]) == 300
    assert v["targets"][0] == "iframe#f #inner" and len(v["targets"][1]) == 200


def test_issues_are_damped_and_skip_rules_raw_checks_cover():
    issues = {i["code"]: i for i in a11y_issues(summarize("u", RAW))}
    assert "A11Y_IMAGE_ALT" not in issues
    assert issues["A11Y_COLOR_CONTRAST"] == {"severity": "warning", "code": "A11Y_COLOR_CONTRAST",
                                             "message": "Help for color-contrast (12 elements, serious)"}
    assert issues["A11Y_ARIA_ALLOWED_ATTR"]["severity"] == "warning"
    assert issues["A11Y_REGION"]["severity"] == "info"
    assert issues["A11Y_REGION"]["message"] == "Help for region (1 element, moderate)"
    assert issues["A11Y_LANDMARK_ONE_MAIN"]["severity"] == "info"


def test_a_failed_scan_raises_nothing():
    assert a11y_issues(A11yResult(url="u", status="failed", error="boom")) == []


def test_to_dict():
    d = summarize("u", RAW).to_dict()
    assert d["url"] == "u" and d["status"] == "scanned" and d["error"] is None and len(d["violations"]) == 5


def test_accessibility_codes_get_a_real_recommendation():
    recs = ai_suggestions.generate_recommendations(
        {"https://a.com/": [{"severity": "warning", "code": "A11Y_COLOR_CONTRAST", "message": "m"}]}, {})
    rec = [r for r in recs if r["code"] == "A11Y_COLOR_CONTRAST"][0]
    assert rec["recommendation"].startswith("Fix this accessibility problem")
    assert ai_suggestions.recommendation_text("MISSING_TITLE") == ai_suggestions.RECOMMENDATION_TEXT["MISSING_TITLE"]
    assert ai_suggestions.recommendation_text("SOMETHING_ELSE") is None
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_a11y_scoring.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.accessibility.model'`

- [ ] **Step 3: Implement**

`app/accessibility/model.py`:

```python
"""One page's accessibility scan."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

IMPACTS = ("critical", "serious", "moderate", "minor")


@dataclass
class A11yResult:
    url: str
    status: str = "scanned"                   # scanned | failed
    error: Optional[str] = None
    score: Optional[int] = None
    counts: Dict[str, int] = field(default_factory=lambda: {i: 0 for i in IMPACTS})
    violations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
```

`app/accessibility/scoring.py`:

```python
"""axe results -> violations, a 0-100 score, and audit issues.

axe runs inside the page's own JavaScript world, so a hostile page could
tamper with what it returns. Everything read here is treated as untrusted:
impacts are whitelisted, strings are cut short, and only Deque's help links
are kept."""

from __future__ import annotations

from typing import Any, Dict, List

from app.accessibility.model import IMPACTS, A11yResult
from app.auditor.checks import issue

PENALTY = {"critical": 10, "serious": 7, "moderate": 3, "minor": 1}
# Already reported on every page by the raw HTML checks (A11Y_IMG_NO_ALT_ATTR,
# A11Y_UNLABELED_FORM_FIELD, A11Y_MISSING_LANG): kept in the scan, not re-raised.
COVERED_BY_RAW_CHECKS = {"image-alt", "label", "html-has-lang"}
MAX_TARGETS = 5
HELP_HOST = "https://dequeuniversity.com/"


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _flatten(target: Any) -> List[str]:
    if isinstance(target, list):
        return [part for item in target for part in _flatten(item)]
    return [str(target)]


def _violation(raw: Dict[str, Any]) -> Dict[str, Any]:
    impact = raw.get("impact") if raw.get("impact") in PENALTY else "minor"
    nodes = raw.get("nodes") if isinstance(raw.get("nodes"), list) else []
    help_url = raw.get("helpUrl")
    rule = _text(raw.get("id"), 100)
    return {
        "id": rule,
        "impact": impact,
        "help": _text(raw.get("help") or rule, 300),
        "help_url": help_url if isinstance(help_url, str) and help_url.startswith(HELP_HOST) else None,
        "wcag": [t for t in (raw.get("tags") or []) if isinstance(t, str) and t.startswith("wcag")][:10],
        "nodes_count": len(nodes),
        "targets": [_text(" ".join(_flatten((n or {}).get("target") or [])), 200) for n in nodes[:MAX_TARGETS]],
    }


def summarize(url: str, raw: Dict[str, Any]) -> A11yResult:
    violations = [_violation(v) for v in (raw.get("violations") or []) if isinstance(v, dict)]
    violations.sort(key=lambda v: (IMPACTS.index(v["impact"]), v["id"]))
    counts = {i: 0 for i in IMPACTS}
    for v in violations:
        counts[v["impact"]] += 1
    score = max(0, 100 - sum(PENALTY[v["impact"]] for v in violations))
    return A11yResult(url=url, score=score, counts=counts, violations=violations)


def a11y_issues(result: A11yResult) -> List[Dict[str, str]]:
    if result.status != "scanned":
        return []
    out = []
    for v in result.violations:
        if v["id"] in COVERED_BY_RAW_CHECKS:
            continue
        n = v["nodes_count"]
        severity = "warning" if v["impact"] in ("critical", "serious") else "info"
        out.append(issue(severity, "A11Y_" + v["id"].upper().replace("-", "_"),
                         f"{v['help']} ({n} element{'' if n == 1 else 's'}, {v['impact']})"))
    return out
```

In `app/ai/ai_suggestions.py`:
- Add the code below after the `RECOMMENDATION_TEXT` dict.
- In `generate_recommendations`, replace `RECOMMENDATION_TEXT.get(code, f"Review and resolve: {code}")` with `recommendation_text(code) or f"Review and resolve: {code}"`.
- Replace `RECOMMENDATION_TEXT.get(code, "Review implementation and apply standard web practices.")` with `recommendation_text(code) or "Review implementation and apply standard web practices."`.

```python
A11Y_RECOMMENDATION = ("Fix this accessibility problem: the Accessibility section on the Site Audit "
                       "tab lists the affected elements and links to how to fix it.")


def recommendation_text(code: str):
    """Per-code advice; axe rule codes (A11Y_*) share one pointer to their details."""
    if code in RECOMMENDATION_TEXT:
        return RECOMMENDATION_TEXT[code]
    return A11Y_RECOMMENDATION if code.startswith("A11Y_") else None
```

- [ ] **Step 4: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_a11y_scoring.py -q
python -m pytest -q
git add apps/backend/app/accessibility apps/backend/app/ai/ai_suggestions.py apps/backend/tests/test_a11y_scoring.py
git commit -m "feat(a11y): summarise axe results, score pages, damped A11Y_* issues"
```

---

### Task 3: Renderer runs axe on the loaded page

**Files:**
- Modify: `apps/backend/app/rendering/model.py`, `apps/backend/app/rendering/playwright_renderer.py`, `apps/backend/tests/test_render_playwright.py`

**Interfaces:**
- Consumes: `axe_source`, `AXE_RUN`, `AXE_TAGS` (Task 1).
- Produces:
  - `RenderResult.axe: Optional[dict]`, `RenderResult.axe_error: Optional[str]`
  - `PlaywrightRenderer.render(urls, on_progress=None, run_axe=False)`
  - `Renderer.render(..., run_axe=False)`

- [ ] **Step 1: Write the failing tests**

In `tests/test_render_playwright.py`, give `_fake_playwright` an optional `evaluate` parameter. Change its signature to `def _fake_playwright(pages, evaluate=None):` and, right after `page.content.side_effect = ...`, add:

```python
        if evaluate is not None:
            page.evaluate.side_effect = evaluate
```

Then append:

```python
def test_axe_runs_on_the_loaded_page_when_asked(monkeypatch):
    calls = []

    def evaluate(script, *args):
        calls.append((script, args))
        return {"violations": [{"id": "region"}]} if args else None

    sync, _, _ = _fake_playwright({"https://a.com/": ("<p>A</p>", 200)}, evaluate=evaluate)
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    monkeypatch.setattr(pr, "axe_source", lambda: "/*axe*/")
    [result] = pr.PlaywrightRenderer(5000).render(["https://a.com/"], run_axe=True)
    assert calls == [("/*axe*/", ()), (pr.AXE_RUN, (pr.AXE_TAGS,))]
    assert result.axe == {"violations": [{"id": "region"}]} and result.axe_error is None
    assert result.html == "<p>A</p>"


def test_an_axe_failure_keeps_the_page(monkeypatch):
    def evaluate(script, *args):
        if args:
            raise RuntimeError("axe is not defined\nstack…")

    sync, _, _ = _fake_playwright({"https://a.com/": ("<p>A</p>", 200)}, evaluate=evaluate)
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    monkeypatch.setattr(pr, "axe_source", lambda: "/*axe*/")
    [result] = pr.PlaywrightRenderer(5000).render(["https://a.com/"], run_axe=True)
    assert result.error is None and result.html == "<p>A</p>"
    assert result.axe is None and result.axe_error == "RuntimeError: axe is not defined"


def test_axe_is_not_touched_by_default(monkeypatch):
    sync, _, contexts = _fake_playwright({"https://a.com/": ("<p>A</p>", 200)})
    monkeypatch.setattr(pr, "_load_playwright", lambda: (sync, FakeTimeout))
    [result] = pr.PlaywrightRenderer(5000).render(["https://a.com/"])
    assert not contexts[0].new_page.return_value.evaluate.called and result.axe is None
```

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_render_playwright.py -q`
Expected: the new tests FAIL (`unexpected keyword argument 'run_axe'`).

- [ ] **Step 3: Implement**

In `app/rendering/model.py`:
- Add these fields to `RenderResult` after `error`:

```python
    axe: Optional[Dict[str, Any]] = None       # raw axe-core results, when asked for
    axe_error: Optional[str] = None
```

- Change the `Renderer.render` signature to:

```python
    def render(self, urls: List[str],
               on_progress: Optional[Callable[[int, int, str], None]] = None,
               run_axe: bool = False) -> List[RenderResult]: ...
```

In `app/rendering/playwright_renderer.py`:
- Add `from app.accessibility.axe import AXE_RUN, AXE_TAGS, axe_source`.
- Change `render` to accept `run_axe: bool = False` and pass it to `self._render_one(browser, url, timeout_error, run_axe)`.
- In `_render_one(self, browser, url, timeout_error, run_axe=False)`, replace the `html = page.content()` / `return RenderResult(...)` lines with:

```python
            html = page.content()
            axe, axe_error = None, None
            if run_axe:
                try:
                    page.evaluate(axe_source())
                    axe = page.evaluate(AXE_RUN, AXE_TAGS)
                except Exception as exc:
                    axe_error = _short(exc)
            return RenderResult(url=url, html=html, final_url=page.url,
                                status=response.status if response else None,
                                render_ms=round((time.monotonic() - started) * 1000, 1),
                                axe=axe, axe_error=axe_error)
```

`render_ms` still covers navigation only. It's measured up to the end of
`networkidle`: move the `render_ms` computation into a variable set right
after the `wait_for_load_state` try/except, so the axe time is not counted.

- [ ] **Step 4: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_render_playwright.py -q
python -m pytest -q
git add apps/backend/app/rendering apps/backend/tests/test_render_playwright.py
git commit -m "feat(a11y): renderer can run axe-core on the page it already loaded"
```

---

### Task 4: One browser pass for rendering and accessibility

**Files:**
- Modify:
  - `apps/backend/app/rendering/runner.py` (replace `render_and_compare` with `run_browser_pass`)
  - `apps/backend/app/services/audit_service.py` (call site only)
  - `apps/backend/tests/test_render_pipeline.py` (`FakeRenderer.render` accepts `run_axe`)
- Test: `apps/backend/tests/test_browser_pass.py`

**Interfaces:**
- Consumes: `summarize`, `A11yResult` (Task 2); `RenderResult.axe`/`axe_error` (Task 3).
- Produces: `run_browser_pass(renderer, start_url, top_pages, results, analyses, limit, render_js: bool, accessibility: bool, on_progress=None) -> Tuple[List[RenderComparison], List[A11yResult]]`

- [ ] **Step 1: Write the failing test**

```python
"""One Chromium load per page feeds both rendering and accessibility."""

from types import SimpleNamespace as NS

from app.rendering.model import RenderResult
from app.rendering.runner import run_browser_pass
from app.services.page_pipeline import HtmlAnalysis

URL = "https://a.com/"
RAW_AXE = {"violations": [{"id": "color-contrast", "impact": "serious", "help": "Contrast",
                           "helpUrl": "https://dequeuniversity.com/x", "tags": ["wcag2aa"], "nodes": [{"target": ["#b"]}]}]}


class Renderer:
    name = "fake"

    def __init__(self, result):
        self.calls, self.result = [], result

    def render(self, urls, on_progress=None, run_axe=False):
        self.calls.append((list(urls), run_axe))
        return [self.result]


def _inputs():
    part = HtmlAnalysis(meta={"title": "Shop", "word_count": 10}, internal_links=[])
    return ({URL: NS(status_code=200, depth=0, content_type="text/html")},
            {URL: NS(failed=False, html_part=part)})


def _run(result, render_js, accessibility):
    results, analyses = _inputs()
    renderer = Renderer(result)
    out = run_browser_pass(renderer, URL, [], results, analyses, 5,
                           render_js=render_js, accessibility=accessibility)
    return renderer, out


def _loaded(**over):
    return RenderResult(url=URL, html="<title>Shop!</title>", final_url=URL, status=200, render_ms=10, **over)


def test_rendering_only():
    renderer, (comparisons, scans) = _run(_loaded(), True, False)
    assert renderer.calls == [([URL], False)]
    assert comparisons[0].changes["title"]["rendered"] == "Shop!" and scans == []


def test_accessibility_only():
    renderer, (comparisons, scans) = _run(_loaded(axe=RAW_AXE), False, True)
    assert renderer.calls == [([URL], True)]
    assert comparisons == [] and scans[0].score == 93 and scans[0].violations[0]["id"] == "color-contrast"


def test_both_share_one_load():
    renderer, (comparisons, scans) = _run(_loaded(axe=RAW_AXE), True, True)
    assert len(renderer.calls) == 1 and len(comparisons) == 1 and len(scans) == 1


def test_failures_are_per_feature():
    _, (comparisons, scans) = _run(_loaded(axe_error="RuntimeError: axe is not defined"), True, True)
    assert comparisons[0].status == "rendered"
    assert (scans[0].status, scans[0].error) == ("failed", "RuntimeError: axe is not defined")
    _, (comparisons, scans) = _run(RenderResult(url=URL, error="TimeoutError: 20000ms"), True, True)
    assert comparisons[0].status == "failed" and scans[0].status == "failed"
    assert scans[0].error == "TimeoutError: 20000ms"
    _, (_, scans) = _run(_loaded(), False, True)
    assert (scans[0].status, scans[0].error) == ("failed", "axe returned no result")
```

In `tests/test_render_pipeline.py`, change `def render(self, urls, on_progress=None):` to `def render(self, urls, on_progress=None, run_axe=False):`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_browser_pass.py -q`
Expected: FAIL with `ImportError: cannot import name 'run_browser_pass'`

- [ ] **Step 3: Implement** (replace the body of `app/rendering/runner.py` below its imports)

```python
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
```

In `app/services/audit_service.py`:
- Change the import to `from app.rendering.runner import run_browser_pass`.
- Change the call `render_results = render_and_compare(` to `render_results, _ = run_browser_pass(`.
- Add `render_js=True, accessibility=False,` before `on_progress=_render_progress`.

Task 6 replaces this block.

- [ ] **Step 4: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_browser_pass.py tests/test_render_pipeline.py -q
python -m pytest -q
git add apps/backend/app/rendering/runner.py apps/backend/app/services/audit_service.py apps/backend/tests/test_browser_pass.py apps/backend/tests/test_render_pipeline.py
git commit -m "refactor(rendering): one browser pass feeds rendering and accessibility"
```

---

### Task 5: Storage

**Files:**
- Create: `apps/backend/alembic/versions/0006_accessibility_results.py`, `apps/backend/tests/test_a11y_storage.py`
- Modify:
  - `apps/backend/app/db/models.py`
  - `apps/backend/app/db/audit_store.py`
  - `apps/backend/app/services/summary_fields.py`
  - `apps/backend/tests/test_db_schema.py`

**Interfaces:**
- Produces:
  - Model `AccessibilityScan` (table `accessibility_results`)
  - `record_audit` stores `result["accessibility"]`
  - `SUMMARY_FIELDS` + `"accessibility", "accessibility_status", "accessibility_unavailable_reason", "axe_version"`

- [ ] **Step 1: Write the failing test**

```python
"""Accessibility scans in the central DB."""

from sqlalchemy import select

from app.accessibility.model import A11yResult
from app.accessibility.scoring import summarize
from app.db.audit_store import record_audit
from app.db.engine import get_session_factory
from app.db.models import AccessibilityScan, Audit
from app.models.session_db import SessionDB


def test_record_audit_stores_scans_and_status(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": []}])
    scanned = summarize("https://a.com/", {"violations": [{"id": "region", "impact": "moderate", "help": "Landmarks",
                                                           "tags": ["wcag2a"], "nodes": [{"target": ["main"]}]}]})
    result = {"executive_summary": {"health_score": {"score": 70}}, "pages": [],
              "accessibility": [scanned.to_dict(), A11yResult(url="https://a.com/b", status="failed", error="boom").to_dict()],
              "accessibility_status": "scanned", "axe_version": "4.14.0"}
    factory = get_session_factory()
    audit_id, _ = record_audit(factory, db, result, session_id="s1", start_url="https://a.com/")
    with factory() as session:
        rows = session.scalars(select(AccessibilityScan).where(AccessibilityScan.audit_id == audit_id)
                               .order_by(AccessibilityScan.id)).all()
        assert [(r.url, r.status, r.score, r.moderate, r.critical, r.error) for r in rows] == [
            ("https://a.com/", "scanned", 97, 1, 0, None), ("https://a.com/b", "failed", None, 0, 0, "boom")]
        assert rows[0].violations_json[0]["id"] == "region"
        summary = session.get(Audit, audit_id).summary_json
        assert summary["accessibility_status"] == "scanned" and summary["axe_version"] == "4.14.0"
```

In `tests/test_db_schema.py`, add `"accessibility_results"` to `TABLES` next to `"render_comparisons"`.

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_a11y_storage.py tests/test_db_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'AccessibilityScan'`

- [ ] **Step 3: Model** (append to `app/db/models.py`)

```python
class AccessibilityScan(Base):
    """One page's axe-core scan in one audit (Phase 5.3)."""
    __tablename__ = "accessibility_results"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    critical: Mapped[int] = mapped_column(Integer, default=0)
    serious: Mapped[int] = mapped_column(Integer, default=0)
    moderate: Mapped[int] = mapped_column(Integer, default=0)
    minor: Mapped[int] = mapped_column(Integer, default=0)
    violations_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
```

- [ ] **Step 4: Migration `alembic/versions/0006_accessibility_results.py`**

```python
"""accessibility results

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-29 10:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('accessibility_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('score', sa.Integer(), nullable=True),
    sa.Column('critical', sa.Integer(), nullable=False),
    sa.Column('serious', sa.Integer(), nullable=False),
    sa.Column('moderate', sa.Integer(), nullable=False),
    sa.Column('minor', sa.Integer(), nullable=False),
    sa.Column('violations_json', sa.JSON(), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_accessibility_results_audit_id'), 'accessibility_results', ['audit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_accessibility_results_audit_id'), table_name='accessibility_results')
    op.drop_table('accessibility_results')
```

- [ ] **Step 5: `record_audit` and summary fields**

In `app/db/audit_store.py`:
- Import `AccessibilityScan`.
- Add the helper below after `_record_rendering`.
- Call `_record_accessibility(session, audit.id, result.get("accessibility") or [])` after the `_record_rendering(...)` call.

```python
def _record_accessibility(session: Session, audit_id: int, rows: List[Dict[str, Any]]) -> None:
    if rows:
        session.execute(insert(AccessibilityScan), [{
            "audit_id": audit_id, "url": r["url"], "status": r.get("status", "scanned"),
            "error": r.get("error"), "score": r.get("score"),
            **{k: (r.get("counts") or {}).get(k, 0) for k in ("critical", "serious", "moderate", "minor")},
            "violations_json": r.get("violations") or [],
        } for r in rows])
```

In `app/services/summary_fields.py`, change `"render_unavailable_reason", "note",` to `"render_unavailable_reason", "accessibility", "accessibility_status",\n    "accessibility_unavailable_reason", "axe_version", "note",`.

- [ ] **Step 6: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_a11y_storage.py tests/test_db_schema.py tests/test_audit_store.py -q
python -m pytest -q
git add apps/backend/app/db apps/backend/alembic/versions/0006_accessibility_results.py apps/backend/app/services/summary_fields.py apps/backend/tests/test_a11y_storage.py apps/backend/tests/test_db_schema.py
git commit -m "feat(a11y): accessibility_results table, migration 0006, stored with each audit"
```

---

### Task 6: Pipeline, request, CLI, scheduler, progress

**Files:**
- Modify:
  - `apps/backend/app/services/audit_service.py`
  - `apps/backend/app/schemas/schemas.py`
  - `apps/backend/app/api/routes.py`
  - `apps/backend/app/cli.py`
  - `apps/backend/app/scheduler/jobs.py`
  - `apps/backend/tests/test_render_pipeline.py`
  - `apps/backend/tests/test_cli.py`
  - `apps/backend/tests/test_scheduler.py`
- Test: `apps/backend/tests/test_a11y_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `_build_audit_result(..., accessibility=False)`, `run_full_audit(..., accessibility=False)`
  - Result keys: `accessibility`, `accessibility_status`, `accessibility_unavailable_reason`, `axe_version`
  - Event `("rendering", {"done", "total", "url", "kind": "render"|"a11y"})`
  - `AuditRequestParams.accessibility`, CLI `--a11y`, scheduler `accessibility`

- [ ] **Step 1: Write the failing tests** (`tests/test_a11y_pipeline.py`)

```python
"""Accessibility inside an audit: opt-in, shares the browser pass, damped
issues, stored, never fatal."""

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import AccessibilityScan
from app.rendering.model import RenderResult
from app.services import audit_service

from test_audit_service_crawler_registry import FakeCrawler

AXE = {"violations": [
    {"id": "color-contrast", "impact": "serious", "help": "Elements must meet minimum color contrast ratio thresholds",
     "helpUrl": "https://dequeuniversity.com/rules/axe/4.14/color-contrast", "tags": ["wcag2aa"],
     "nodes": [{"target": ["#a"]}, {"target": ["#b"]}]},
    {"id": "image-alt", "impact": "critical", "help": "Images must have alternative text",
     "helpUrl": "https://dequeuniversity.com/rules/axe/4.14/image-alt", "tags": ["wcag2a"], "nodes": [{"target": ["img"]}]},
]}


class FakeRenderer:
    name = "fake"

    def __init__(self, axe=AXE):
        self.calls, self.axe = [], axe

    def render(self, urls, on_progress=None, run_axe=False):
        self.calls.append((list(urls), run_axe))
        out = []
        for i, url in enumerate(urls, 1):
            out.append(RenderResult(url=url, html="<html><head><title>Espresso Machines</title></head><body></body></html>",
                                    final_url=url, status=200, render_ms=5, axe=self.axe if run_axe else None))
            if on_progress:
                on_progress(i, len(urls), url)
        return out


def _run(**kwargs):
    events = []
    result = audit_service._build_audit_result(
        "https://example.com/", FakeCrawler(), progress_callback=None,
        event_callback=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return result, events


def test_off_by_default():
    result, _ = _run()
    assert result["accessibility_status"] == "disabled" and result["accessibility"] == []
    assert result["axe_version"] is None


def test_scans_scores_and_adds_damped_issues():
    renderer = FakeRenderer()
    result, events = _run(accessibility=True, renderer=renderer)
    assert renderer.calls == [(["https://example.com/"], True)]
    assert result["accessibility_status"] == "scanned" and result["axe_version"] == "4.14.0"
    row = result["accessibility"][0]
    assert row["score"] == 100 - 7 - 10 and row["counts"]["critical"] == 1
    issues = {i["code"]: i for i in result["page_issues_detail"]["https://example.com/"]}
    assert issues["A11Y_COLOR_CONTRAST"]["severity"] == "warning"
    assert "A11Y_IMAGE_ALT" not in issues
    assert result["render_status"] == "disabled" and result["rendering"] == []
    assert ("rendering", {"done": 1, "total": 1, "url": "https://example.com/", "kind": "a11y"}) in events
    with get_session_factory()() as session:
        rows = session.scalars(select(AccessibilityScan).where(AccessibilityScan.audit_id == result["audit_id"])).all()
        assert [r.score for r in rows] == [83]


def test_both_options_share_one_render_call():
    renderer = FakeRenderer()
    result, events = _run(accessibility=True, render_js=True, renderer=renderer)
    assert renderer.calls == [(["https://example.com/"], True)]
    assert result["render_status"] == "rendered" and result["accessibility_status"] == "scanned"
    assert events[-1][1]["kind"] == "render"


def test_no_browser_marks_both_unavailable(monkeypatch):
    monkeypatch.setattr(audit_service, "renderer_available", lambda: (False, "Playwright is not installed"))
    result, _ = _run(accessibility=True, render_js=True)
    assert result["accessibility_status"] == "unavailable" and result["render_status"] == "unavailable"
    assert result["accessibility_unavailable_reason"] == "Playwright is not installed"
    assert result["persisted"] is True


def test_missing_axe_only_disables_accessibility(monkeypatch):
    monkeypatch.setattr(audit_service, "axe_available", lambda: (False, "axe-core not found (app/accessibility/vendor/axe.min.js)"))
    renderer = FakeRenderer()
    result, _ = _run(accessibility=True, render_js=True, renderer=renderer)
    assert result["accessibility_status"] == "unavailable" and result["render_status"] == "rendered"
    assert renderer.calls == [(["https://example.com/"], False)]
```

In `tests/test_render_pipeline.py`, in `test_renders_compares_and_adds_issues`, change the expected event to `("rendering", {"done": 1, "total": 1, "url": "https://example.com/", "kind": "render"})`.

Append to `tests/test_cli.py`:

```python
def test_a11y_flag_reaches_the_audit_pipeline():
    from unittest.mock import patch

    from app import cli

    for argv, expected in ((["https://example.com/", "--a11y"], True), (["https://example.com/"], False)):
        args = cli.build_parser().parse_args(argv)
        with patch.object(cli.audit_service, "_build_audit_result", return_value={}) as build:
            cli._run_audit(args)
        assert build.call_args.kwargs["accessibility"] is expected
```

In `tests/test_scheduler.py`, add the test below after `test_render_js_comes_from_the_project_options`:

```python
def test_accessibility_comes_from_the_project_options():
    _project("a11y.com", "daily", options={"accessibility": True})
    _project("plain2.com", "daily")
    calls = []

    jobs.run_due_audits(runner=_runner(calls))

    assert {c["url"]: c["accessibility"] for c in calls} == {
        "https://a11y.com/": True, "https://plain2.com/": False}
```

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_a11y_pipeline.py tests/test_render_pipeline.py tests/test_cli.py tests/test_scheduler.py -q`
Expected: FAIL (`unexpected keyword argument 'accessibility'`, …)

- [ ] **Step 3: Pipeline** (`app/services/audit_service.py`)

1. Imports: add `from app.accessibility.axe import AXE_VERSION, axe_available` and `from app.accessibility.scoring import a11y_issues`.
2. `run_full_audit`: add the parameter `accessibility: bool = False` after `render_js` and pass `accessibility=accessibility`.
3. `_build_audit_result`: add the parameter `accessibility: bool = False` after `render_max_pages`.
4. Replace the whole block, from the comment `# JavaScript rendering: opt-in, a sample of pages, compared with the raw` through the end of its `for comparison in render_results:` loop, with:

```python
    # Browser pass: JavaScript rendering and/or the accessibility scan, both
    # opt-in, sharing one Chromium load per sampled page. A missing browser or
    # a crash reports "unavailable" -- the audit stands either way.
    render_status, render_reason, render_results = "disabled", None, []
    a11y_status, a11y_reason, a11y_results = "disabled", None, []
    scan_a11y = accessibility
    if accessibility:
        axe_ok, axe_reason = axe_available()
        if not axe_ok:
            scan_a11y, a11y_status, a11y_reason = False, "unavailable", axe_reason
    if render_js or scan_a11y:
        active, reason = renderer, None
        if active is None:
            available, reason = renderer_available()
            active = PlaywrightRenderer(config.RENDER_TIMEOUT_MS) if available else None
        if active is not None:
            kind = "render" if render_js else "a11y"

            def _browser_progress(done: int, total: int, page_url: str) -> None:
                if event_callback:
                    event_callback("rendering", {"done": done, "total": total, "url": page_url, "kind": kind})

            try:
                render_results, a11y_results = run_browser_pass(
                    active, start_page, site_wide.get("top_pages_by_importance") or [],
                    crawler.results, analyses,
                    config.RENDER_MAX_PAGES if render_max_pages is None else render_max_pages,
                    render_js=render_js, accessibility=scan_a11y, on_progress=_browser_progress)
            except Exception as exc:
                logger.error("Browser pass failed: %s", exc, exc_info=exc)
                first_line = (str(exc).splitlines() or [""])[0][:200]
                active, reason = None, (f"{type(exc).__name__}: {first_line}" if first_line else type(exc).__name__)
        if render_js:
            render_status, render_reason = ("rendered", None) if active is not None else ("unavailable", reason)
        if scan_a11y:
            a11y_status, a11y_reason = ("scanned", None) if active is not None else ("unavailable", reason)
        found_by_url = [(c.url, rendering_issues(c)) for c in render_results]
        found_by_url += [(s.url, a11y_issues(s)) for s in a11y_results]
        for page_url, found in found_by_url:
            if found:
                all_page_issues.setdefault(page_url, []).extend(found)
                db.add_issues(page_url, found)
```

5. In `result_data`, after the `"render_unavailable_reason": render_reason,` line, add:

```python
        "accessibility": [s.to_dict() for s in a11y_results],
        "accessibility_status": a11y_status,
        "accessibility_unavailable_reason": a11y_reason,
        "axe_version": AXE_VERSION if a11y_status == "scanned" else None,
```

- [ ] **Step 4: Request, routes, CLI, scheduler**

`app/schemas/schemas.py`, after `render_js`:

```python
    # Scan the sampled pages with axe-core (WCAG 2.2 A/AA) in the same browser
    # pass as render_js (Phase 5.3). Off by default.
    accessibility: Optional[bool] = False
```

`app/api/routes.py`:
- Add `accessibility=bool(params.accessibility),` after `render_js=...` in the `run_full_audit(` call.
- Replace the `rendering` message branch with:

```python
            elif event_type == "rendering":
                what = "Scanning accessibility" if payload.get("kind") == "a11y" else "Rendering JavaScript"
                msg = f"{what} ({payload['done']}/{payload['total']})"
```

`app/cli.py`:
- After `--render-js`, add the code below.
- In `_run_audit`, pass `accessibility=args.accessibility,` after `render_js=args.render_js,`.

```python
    p.add_argument("--a11y", dest="accessibility", action="store_true",
                   help="Scan the top pages with axe-core (WCAG 2.2 A/AA) in headless Chromium")
```

`app/scheduler/jobs.py`, after `render_js=...`:

```python
                accessibility=bool(options.get("accessibility", False)),
```

- [ ] **Step 5: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_a11y_pipeline.py tests/test_render_pipeline.py tests/test_cli.py tests/test_scheduler.py -q
python -m pytest -q
git add apps/backend/app apps/backend/tests
git commit -m "feat(a11y): opt-in accessibility scan in the shared browser pass; CLI --a11y, scheduled audits"
```

---

### Task 7: Read API

**Files:**
- Create: `apps/backend/app/api/accessibility.py`, `apps/backend/tests/test_a11y_api.py`
- Modify: `apps/backend/app/main.py`

**Interfaces:**
- Produces: `GET /api/audits/{id}/accessibility` → `{audit_id, status, reason, axe_version, items: [{url, status, error, score, counts, violations}]}`

- [ ] **Step 1: Write the failing test**

```python
"""Accessibility scans over HTTP."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import AccessibilityScan, Audit, Project
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _audit(session, project_id, n, summary):
    t = datetime(2026, 10, 29, tzinfo=timezone.utc)
    audit = Audit(project_id=project_id, session_id=f"s{n}", start_url="https://a.com/", status="completed",
                  trigger="manual", started_at=t, finished_at=t, page_count=1, summary_json=summary)
    session.add(audit); session.flush()
    return audit.id


def test_lists_scans_with_status_and_version(client):
    violation = {"id": "region", "impact": "moderate", "help": "Landmarks", "help_url": None,
                 "wcag": ["wcag2a"], "nodes_count": 1, "targets": ["main"]}
    with get_session_factory().begin() as s:
        project = Project(name="a.com", domain="a.com"); s.add(project); s.flush()
        scanned = _audit(s, project.id, 1, {"accessibility_status": "scanned", "axe_version": "4.14.0"})
        s.add(AccessibilityScan(audit_id=scanned, url="https://a.com/", status="scanned", score=97,
                                critical=0, serious=0, moderate=1, minor=0, violations_json=[violation]))
        unavailable = _audit(s, project.id, 2, {"accessibility_status": "unavailable",
                                                "accessibility_unavailable_reason": "Playwright is not installed"})
        old = _audit(s, project.id, 3, {})
    body = client.get(f"/api/audits/{scanned}/accessibility").json()
    assert body == {"audit_id": scanned, "status": "scanned", "reason": None, "axe_version": "4.14.0", "items": [
        {"url": "https://a.com/", "status": "scanned", "error": None, "score": 97,
         "counts": {"critical": 0, "serious": 0, "moderate": 1, "minor": 0}, "violations": [violation]}]}
    assert client.get(f"/api/audits/{unavailable}/accessibility").json()["reason"] == "Playwright is not installed"
    assert client.get(f"/api/audits/{old}/accessibility").json()["status"] == "disabled"
    assert client.get("/api/audits/99999/accessibility").status_code == 404
```

- [ ] **Step 2: Run and watch it fail**

Run: `python -m pytest tests/test_a11y_api.py -q`
Expected: FAIL (404).

- [ ] **Step 3: Implement `app/api/accessibility.py`**

```python
"""Accessibility scans (Phase 5.3). Scanning happens inside audits, so this is
read-only."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import AccessibilityScan, Audit

router = APIRouter()


@router.get("/audits/{audit_id}/accessibility")
def audit_accessibility(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        rows = session.scalars(select(AccessibilityScan).where(AccessibilityScan.audit_id == audit_id)
                               .order_by(AccessibilityScan.id)).all()
        summary = audit.summary_json or {}
        return {
            "audit_id": audit_id,
            "status": summary.get("accessibility_status") or ("scanned" if rows else "disabled"),
            "reason": summary.get("accessibility_unavailable_reason"),
            "axe_version": summary.get("axe_version"),
            "items": [{
                "url": r.url, "status": r.status, "error": r.error, "score": r.score,
                "counts": {"critical": r.critical, "serious": r.serious, "moderate": r.moderate, "minor": r.minor},
                "violations": r.violations_json or [],
            } for r in rows],
        }
```

In `app/main.py`, after the rendering router lines:

```python
from app.api.accessibility import router as accessibility_router  # noqa: E402
app.include_router(accessibility_router, prefix="/api")
```

- [ ] **Step 4: Run and pass, full suite, then commit**

```bash
python -m pytest tests/test_a11y_api.py -q
python -m pytest -q
git add apps/backend/app/api/accessibility.py apps/backend/app/main.py apps/backend/tests/test_a11y_api.py
git commit -m "feat(a11y): audit accessibility endpoint"
```

---

### Task 8: Frontend

**Files:**
- Modify:
  - `packages/shared/src/types/platform.ts`, `packages/shared/src/types/index.ts`
  - `apps/frontend/services/platform.ts`
  - `app/projects/[id]/audits/page.tsx`, `app/dashboard/page.tsx`, `app/page.tsx`
  - `components/__tests__/site-audit-page.test.tsx`
- Create:
  - `apps/frontend/components/platform/accessibility-table.tsx`
  - `components/__tests__/accessibility-table.test.tsx`
  - `components/__tests__/a11y-option.test.tsx`

**Interfaces:**
- Produces:
  - Types `A11yImpact`, `A11yStatus`, `A11yViolation`, `A11yResult`, `AuditAccessibility`
  - `Platform.auditAccessibility(id)`
  - `<AccessibilityTable rows status reason />`

- [ ] **Step 1: Types and service**

Append to `packages/shared/src/types/platform.ts`:

```ts
// Accessibility (backend Phase 5.3, axe-core).
export type A11yImpact = "critical" | "serious" | "moderate" | "minor";
export type A11yStatus = "scanned" | "disabled" | "unavailable";

export interface A11yViolation {
  id: string;
  impact: A11yImpact;
  help: string;
  help_url: string | null;
  wcag: string[];
  nodes_count: number;
  targets: string[];
}

export interface A11yResult {
  url: string;
  status: "scanned" | "failed";
  error: string | null;
  score: number | null;
  counts: Record<A11yImpact, number>;
  violations: A11yViolation[];
}

export interface AuditAccessibility {
  audit_id: number;
  status: A11yStatus;
  reason: string | null;
  axe_version: string | null;
  items: A11yResult[];
}
```

In `packages/shared/src/types/index.ts`:
- Extend the import to include `A11yResult, A11yStatus`.
- Add these after `render_unavailable_reason?: string | null;` in `AuditResponse`:

```ts
  accessibility?: A11yResult[];
  accessibility_status?: A11yStatus;
  accessibility_unavailable_reason?: string | null;
  axe_version?: string | null;
```

- Add `accessibility?: boolean;` after `render_js?: boolean;` in `AuditRequestParams`.

In `apps/frontend/services/platform.ts`:
- Add `AuditAccessibility` to the type import.
- Add this after `auditRendering`:

```ts
  auditAccessibility: (auditId: number) => request<AuditAccessibility>(`/audits/${auditId}/accessibility`),
```

Rebuild shared: `cd packages/shared && npx tsc`.

- [ ] **Step 2: Write the failing tests**

`components/__tests__/accessibility-table.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AccessibilityTable } from "@/components/platform/accessibility-table";

const violation = {
  id: "color-contrast", impact: "serious" as const, help: "Elements must meet minimum color contrast ratio thresholds",
  help_url: "https://dequeuniversity.com/rules/axe/4.14/color-contrast", wcag: ["wcag2aa", "wcag143"],
  nodes_count: 12, targets: ["#hero > a.btn", "footer p"],
};
const row = (over: object = {}) => ({
  url: "https://a.com/", status: "scanned" as const, error: null, score: 83,
  counts: { critical: 1, serious: 1, moderate: 0, minor: 0 }, violations: [violation], ...over,
});

describe("AccessibilityTable", () => {
  it("shows the score with a labelled pill and the counts", () => {
    render(<AccessibilityTable rows={[row()]} status="scanned" reason={null} />);
    expect(screen.getByText("83")).toBeInTheDocument();
    expect(screen.getByText("Needs work")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /https:\/\/a.com\// })).toHaveTextContent("1");
  });

  it("expands a row to list each failed rule with how to fix it", async () => {
    render(<AccessibilityTable rows={[row()]} status="scanned" reason={null} />);
    await userEvent.click(screen.getByRole("button", { name: /show issues for https:\/\/a.com\//i }));
    expect(screen.getByText(violation.help)).toBeInTheDocument();
    expect(screen.getAllByText("Serious")).toHaveLength(2);   // column header + the impact pill
    expect(screen.getByText("12 elements")).toBeInTheDocument();
    expect(screen.getByText("#hero > a.btn")).toBeInTheDocument();
    expect(screen.getByText("wcag2aa")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: /how to fix/i });
    expect(link).toHaveAttribute("href", violation.help_url);
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("explains the score and its limits", () => {
    render(<AccessibilityTable rows={[row()]} status="scanned" reason={null} />);
    expect(screen.getByText(/100 minus 10\/7\/3\/1/)).toBeInTheDocument();
    expect(screen.getByText(/not a full WCAG audit/)).toBeInTheDocument();
  });

  it("shows a failed scan and the empty states", () => {
    const { rerender } = render(<AccessibilityTable rows={[row({ status: "failed", error: "RuntimeError: axe is not defined", score: null })]} status="scanned" reason={null} />);
    expect(screen.getByText(/Couldn't scan: RuntimeError: axe is not defined/)).toBeInTheDocument();
    rerender(<AccessibilityTable rows={[]} status="disabled" reason={null} />);
    expect(screen.getByText(/Accessibility audit/)).toBeInTheDocument();
    rerender(<AccessibilityTable rows={[]} status="unavailable" reason="Playwright is not installed" />);
    expect(screen.getByText(/Browser not available on this server: Playwright is not installed/)).toBeInTheDocument();
  });

  it("calls a perfect page good", () => {
    render(<AccessibilityTable rows={[row({ score: 100, counts: { critical: 0, serious: 0, moderate: 0, minor: 0 }, violations: [] })]} status="scanned" reason={null} />);
    expect(screen.getByText("Good")).toBeInTheDocument();
  });
});
```

`components/__tests__/a11y-option.test.tsx`:

```tsx
/** "Accessibility audit" asks the API to scan a sample of pages with axe-core. */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LandingPage from "@/app/page";
import { ApiService } from "@/services/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/audit-context", () => ({
  useAudit: () => ({ startNewAudit: vi.fn(), setError: vi.fn(), isLoading: false, error: null }),
}));

async function submitWith(on: boolean) {
  const runAudit = vi.spyOn(ApiService, "runAudit").mockResolvedValue({ session_id: "s" } as never);
  render(<LandingPage />);
  await userEvent.type(screen.getByPlaceholderText("https://example.com"), "https://example.com");
  await userEvent.click(screen.getByText("Advanced Overrides"));
  if (on) await userEvent.click(screen.getByLabelText(/accessibility audit/i));
  await userEvent.click(screen.getByRole("button", { name: /start seo audit/i }));
  await waitFor(() => expect(runAudit).toHaveBeenCalled());
  return runAudit.mock.calls[0][0];
}

describe("Accessibility audit option", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("is off by default", async () => {
    expect(await submitWith(false)).toMatchObject({ accessibility: false });
  });

  it("sends accessibility when ticked", async () => {
    expect(await submitWith(true)).toMatchObject({ accessibility: true });
  });
});
```

In `components/__tests__/site-audit-page.test.tsx`:
- In `beforeEach`, add `vi.spyOn(Platform, "auditAccessibility").mockResolvedValue({ audit_id: 3, status: "disabled", reason: null, axe_version: null, items: [] });`.
- Add this test:

```tsx
  it("shows accessibility for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/Not scanned/)).toBeInTheDocument();
    expect(Platform.auditAccessibility).toHaveBeenCalledWith(3);
  });
```

- [ ] **Step 3: Run and watch them fail**

Run: `cd apps/frontend && npx vitest run components/__tests__/accessibility-table.test.tsx components/__tests__/a11y-option.test.tsx components/__tests__/site-audit-page.test.tsx`
Expected: FAIL.

- [ ] **Step 4: `components/platform/accessibility-table.tsx`**

```tsx
"use client";

import { Fragment, useState } from "react";
import { AlertOctagon, AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Info, XCircle } from "lucide-react";
import type { A11yImpact, A11yResult, A11yStatus } from "@seo-auditor/shared";

const ROSE = "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400";
const AMBER = "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400";
const SLATE = "border-slate-200 bg-slate-50 text-slate-600 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400";
const EMERALD = "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400";

const IMPACT: Record<A11yImpact, { label: string; className: string; Icon: typeof Info }> = {
  critical: { label: "Critical", className: ROSE, Icon: XCircle },
  serious: { label: "Serious", className: ROSE, Icon: AlertOctagon },
  moderate: { label: "Moderate", className: AMBER, Icon: AlertTriangle },
  minor: { label: "Minor", className: SLATE, Icon: Info },
};

function Pill({ className, Icon, label }: { className: string; Icon: typeof Info; label: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      <Icon className="h-3 w-3" aria-hidden />{label}
    </span>
  );
}

function ScorePill({ score }: { score: number }) {
  if (score >= 90) return <Pill className={EMERALD} Icon={CheckCircle2} label="Good" />;
  if (score >= 50) return <Pill className={AMBER} Icon={AlertTriangle} label="Needs work" />;
  return <Pill className={ROSE} Icon={XCircle} label="Poor" />;
}

const ORDER: A11yImpact[] = ["critical", "serious", "moderate", "minor"];

export function AccessibilityTable({ rows, status, reason }: { rows: A11yResult[]; status: A11yStatus; reason: string | null }) {
  const [open, setOpen] = useState<string | null>(null);
  if (status === "disabled") return <p className="text-sm text-muted-foreground">Not scanned. Run an audit with <em>Accessibility audit</em> on.</p>;
  if (status === "unavailable") return <p className="text-sm text-muted-foreground">Browser not available on this server: {reason ?? "unknown reason"}</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No pages were scanned.</p>;
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-[13px]">
          <thead className="text-left text-xs text-muted-foreground">
            <tr className="border-b">
              <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th>
              <th className="py-2 pr-4 font-medium">Score</th>
              {ORDER.map((i) => <th key={i} className="py-2 pr-4 font-medium">{IMPACT[i].label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => {
              const isOpen = open === r.url;
              const expandable = r.status === "scanned" && r.violations.length > 0;
              return (
                <Fragment key={r.url}>
                  <tr className="align-top">
                    <td className="sticky left-0 max-w-[140px] break-all bg-card py-2 pr-4 sm:max-w-[260px]">
                      {expandable ? (
                        <button type="button" onClick={() => setOpen(isOpen ? null : r.url)} aria-expanded={isOpen}
                                aria-label={`Show issues for ${r.url}`} className="flex items-start gap-1 text-left hover:text-primary">
                          {isOpen ? <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden /> : <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />}
                          {r.url}
                        </button>
                      ) : r.url}
                    </td>
                    {r.status === "failed" ? (
                      <td colSpan={5} className="py-2 text-muted-foreground">Couldn&apos;t scan: {r.error}</td>
                    ) : (
                      <>
                        <td className="whitespace-nowrap py-2 pr-4">
                          <span className="flex items-center gap-1.5 tabular-nums">{r.score}{r.score != null && <ScorePill score={r.score} />}</span>
                        </td>
                        {ORDER.map((i) => <td key={i} className="py-2 pr-4 tabular-nums">{r.counts[i]}</td>)}
                      </>
                    )}
                  </tr>
                  {isOpen && (
                    <tr>
                      <td colSpan={6} className="bg-muted/30 px-3 py-3">
                        <ul className="space-y-3">
                          {r.violations.map((v) => {
                            const impact = IMPACT[v.impact];
                            return (
                              <li key={v.id} className="space-y-1">
                                <div className="flex flex-wrap items-center gap-2">
                                  <Pill className={impact.className} Icon={impact.Icon} label={impact.label} />
                                  <span className="font-medium">{v.help}</span>
                                  <span className="text-muted-foreground">{v.nodes_count} {v.nodes_count === 1 ? "element" : "elements"}</span>
                                  {v.help_url && (
                                    <a href={v.help_url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">How to fix</a>
                                  )}
                                </div>
                                {v.wcag.length > 0 && (
                                  <div className="flex flex-wrap gap-1">{v.wcag.map((t) => <span key={t} className="rounded border px-1 text-[10px] text-muted-foreground">{t}</span>)}</div>
                                )}
                                {v.targets.length > 0 && (
                                  <ul className="space-y-0.5">{v.targets.map((t, i) => <li key={i} className="break-all font-mono text-[11px] text-muted-foreground">{t}</li>)}</ul>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        Score: 100 minus 10/7/3/1 per failed rule (critical/serious/moderate/minor). Automated checks find about a
        third of accessibility problems, so this is not a full WCAG audit.
      </p>
    </div>
  );
}
```

- [ ] **Step 5: Wire into the pages**

`app/projects/[id]/audits/page.tsx`:
- Import `AccessibilityTable`.
- Add this after the `rendering` hook:

```tsx
  const accessibility = useApi(selected !== null ? () => Platform.auditAccessibility(selected) : null, [selected]);
```

- Insert this right after the "JavaScript rendering" `</section>`:

```tsx
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Accessibility</h2>
              <AsyncState state={accessibility}>{(a) => <AccessibilityTable rows={a.items} status={a.status} reason={a.reason} />}</AsyncState>
            </section>
```

`app/dashboard/page.tsx`:
- Import `AccessibilityTable`.
- In `DEFAULT_LAYOUT`, add `{ id: "accessibility", width: "full", visible: true },` after `rendering`.
- Add this widget after the `"rendering"` entry:

```tsx
    "accessibility": auditData.accessibility_status ? (
      <Card><CardHeader className="pb-3"><CardTitle className="text-base">Accessibility</CardTitle></CardHeader>
        <CardContent><AccessibilityTable rows={auditData.accessibility ?? []} status={auditData.accessibility_status} reason={auditData.accessibility_unavailable_reason ?? null} /></CardContent></Card>
    ) : null,
```

`app/page.tsx`:
- Add `const [accessibility, setAccessibility] = useState(false);` after the `renderJs` state.
- Add `accessibility,` after `render_js: renderJs,`.
- Insert this after the "Render JavaScript" `</label>`:

```tsx
                <label className="flex cursor-pointer items-center gap-3 rounded-lg border border-border/50 bg-muted/20 p-3 hover:bg-muted/40 transition-colors">
                  <input
                    type="checkbox"
                    checked={accessibility}
                    onChange={(e) => setAccessibility(e.target.checked)}
                    className="h-4 w-4 rounded border-input bg-background text-primary focus:ring-primary"
                    disabled={isLoading}
                    aria-label="Accessibility audit"
                  />
                  <div>
                    <p className="text-sm font-semibold">Accessibility audit (slower)</p>
                    <p className="text-xs text-muted-foreground">Check the most important pages against WCAG 2.2 A/AA with axe-core in a real browser</p>
                  </div>
                </label>
```

- [ ] **Step 6: Run and pass, then commit**

```bash
npx vitest run && npx tsc --noEmit
(cd ../backend && python -m pytest -q)
git add packages/shared/src apps/frontend
git commit -m "feat(frontend): accessibility table on Site Audit and report; Accessibility audit option"
```

---

### Task 9: Docs and live check

**Files:** `docs/api.md`, `README.md`

- [ ] **Step 1: `docs/api.md`**

Append a section, "Accessibility (axe-core)". It should cover:
- `POST /api/audit` accepts `"accessibility": true`, and it shares the browser pass with `render_js`
- the result keys
- the score formula
- the severity mapping and the three skipped rules
- `GET /api/audits/{id}/accessibility`, with the example body from Task 7's test in a fenced `json` block

- [ ] **Step 2: README**

Append a section, "Accessibility audit (Phase 5.3)". It should cover:
- what it does and that it's off by default
- the checkbox, `"accessibility": true` and `--a11y`
- `{"accessibility": true}` in a project's `audit_options`
- that it needs the same browser as rendering
- that axe-core 4.14.0 is vendored (see `apps/backend/app/accessibility/vendor/README.md`)
- the score note, and that automated checks find about a third of problems
- a **How to verify** block:

```bash
cd apps/backend
python -m pytest tests/test_axe_vendor.py tests/test_a11y_scoring.py tests/test_browser_pass.py \
  tests/test_a11y_storage.py tests/test_a11y_pipeline.py tests/test_a11y_api.py -q
export SESSION_DIR=/tmp/seo-a11y
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links --a11y --json \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['accessibility_status'], d['axe_version']); [print(r['url'], r['score'], r['counts'], [v['id'] for v in r['violations']]) for r in d['accessibility']]"
```

- [ ] **Step 3: Commit the docs**

```bash
python -m pytest -q
git add docs/api.md README.md
git commit -m "docs: accessibility audit API and verification"
```

- [ ] **Step 4: Live check**
  1. Run the README CLI against books.toscrape.com with real Chromium and axe 4.14.0. Expect `scanned 4.14.0` and real violations with plausible scores.
  2. Serve a local test page (`python -m http.server 8765 --bind 127.0.0.1` in a scratch dir) with a light-grey-on-white button, an `<img>` without `alt` and an `<input>` without a label. Run with `--a11y --render-js`. Expect `color-contrast` (`A11Y_COLOR_CONTRAST` issue), `image-alt` and `label` in the scan but not as issues, one load per page, and both statuses set.
  3. Start the backend and `next dev`, and screenshot at 1440 and 390 px (Chrome extension, or Playwright if the extension isn't connected): the Site Audit Accessibility section (expand a row), the report panel and the home checkbox. Check for no sideways page scroll.
  4. Fix anything found (with a test when it's behaviour), commit, and stop the servers.
