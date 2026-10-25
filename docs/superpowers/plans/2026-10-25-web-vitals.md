# Core Web Vitals (Phase 5.1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every audit measures Core Web Vitals for the homepage plus the top
pages: PageSpeed Insights first, local Lighthouse as an opt-in fallback.
Results are stored per audit and shown on the project Overview, the Site Audit
tab and the report.

**Architecture:**
- A new provider package, `app/vitals/`, holds the result type, the rating
  thresholds and issues, a PSI provider, a Lighthouse provider, a fallback
  chain, page selection and a small thread-pool runner.
- `_build_audit_result` calls it once, after the crawl, in place of today's
  per-page PSI call.
- The rows go to a new `web_vitals` table, which two read endpoints serve to
  the Next.js pages.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, `requests`, `subprocess`
(Lighthouse 12 via `node`), pytest. Frontend: Next.js 14, Recharts, Vitest,
Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-25-web-vitals-design.md`

## Global Constraints

- Pages: start URL + top pages by internal PageRank, up to `PSI_MAX_PAGES` (default 5), mobile, status-200 HTML only.
- Thresholds (good ≤ / poor >):
  - LCP 2500/4000 ms
  - INP 200/500 ms
  - CLS 0.1/0.25
  - TBT 200/600 ms (lab stand-in for INP)
- Field (page-level CrUX) data rates when present, else lab data. Origin-fallback field data is ignored.
- Issue severities: `CWV_<METRIC>_POOR` = `warning`, `CWV_<METRIC>_NEEDS_IMPROVEMENT` = `info`.
- `PSI_DAILY_CAP` default 50, enforced through `app.providers.spend.reserve("psi", cap)`.
- The PSI key never appears in errors or logs.
- `LIGHTHOUSE_ENABLED` defaults to false.
  - Lighthouse runs as `[node, <lighthouse cli.js>, url, ...]`: never a shell, never `npx`/`.cmd`.
  - `subprocess` gets a list argv and a 90 s timeout.
- CWV never fails an audit: every error becomes a per-page `error`.
- No real network in tests. Run the full backend suite before each commit.
- Existing CLI flags keep working. `--psi-key` still selects PSI, and the CLI now measures `--psi-max-pages` (default 5) pages.
- UI rating pills: icon + text label, emerald / amber / rose. Never color alone.

---

## File map

**Create (backend):**
- `apps/backend/app/vitals/__init__.py`
- `apps/backend/app/vitals/model.py`: `VitalsResult`, `VitalsProvider`, `THRESHOLDS`, `rate_metric`, `rate`, `metric_ratings`, `vitals_issues`
- `apps/backend/app/vitals/psi.py`: `parse_lab`, `parse_field`, `parse_psi`, `PsiProvider`
- `apps/backend/app/vitals/lighthouse.py`: `find_chrome`, `find_lighthouse_cli`, `parse_lighthouse`, `LighthouseProvider`
- `apps/backend/app/vitals/providers.py`: `FallbackChain`, `build_vitals_provider`
- `apps/backend/app/vitals/runner.py`: `select_vitals_pages`, `measure_pages`
- `apps/backend/alembic/versions/0004_web_vitals.py`
- `apps/backend/app/api/vitals.py`
- Tests:
  - `tests/test_vitals_rating.py`
  - `tests/test_vitals_psi.py`
  - `tests/test_vitals_lighthouse.py`
  - `tests/test_vitals_runner.py`
  - `tests/test_vitals_storage.py`
  - `tests/test_vitals_pipeline.py`
  - `tests/test_vitals_api.py`

**Modify (backend):**
- `app/config/config.py`
- `app/db/models.py`
- `app/db/audit_store.py`
- `app/models/session_db.py`
- `app/services/audit_service.py`
- `app/utils/performance.py`: delete `fetch_psi_metrics`
- `app/ai/ai_suggestions.py`
- `app/schemas/schemas.py`
- `app/api/routes.py`
- `app/cli.py`
- `app/main.py`
- `tests/conftest.py`
- `tests/test_pipeline_options.py`
- `tests/test_db_schema.py`
- `apps/backend/.env.example`
- `deploy/oracle/docker-compose.yml`
- `docs/env.md`
- `docs/api.md`
- `README.md`

**Create (frontend):**
- `apps/frontend/components/platform/vitals-table.tsx` (`RatingPill`, `VitalsTable`)
- `apps/frontend/components/platform/vitals-card.tsx`
- Tests:
  - `components/__tests__/vitals-table.test.tsx`
  - `components/__tests__/vitals-card.test.tsx`

**Modify (frontend):**
- `packages/shared/src/types/platform.ts`
- `packages/shared/src/types/index.ts`
- `apps/frontend/services/platform.ts`
- `apps/frontend/lib/platform-charts.ts` (+ its test)
- `app/projects/[id]/page.tsx`
- `app/projects/[id]/audits/page.tsx`
- `app/dashboard/page.tsx`
- `components/__tests__/project-overview.test.tsx`
- `components/__tests__/site-audit-page.test.tsx`

---

### Task 1: Result type, thresholds, rating, issues

**Files:**
- Create: `apps/backend/app/vitals/__init__.py`
- Create: `apps/backend/app/vitals/model.py`
- Modify: `apps/backend/app/ai/ai_suggestions.py` (`IMPACT_WEIGHTS`, `RECOMMENDATION_TEXT`)
- Test: `apps/backend/tests/test_vitals_rating.py`

**Interfaces:**
- Produces:
  - `VitalsResult` (dataclass), with fields `url, strategy="mobile", source="not_measured", data_kind=None, performance_score, lcp_ms, inp_ms, cls, fcp_ms, ttfb_ms, tbt_ms, rating, error` (all `Optional`, default `None`) and method `to_dict() -> dict`, which includes `metric_ratings`
  - `VitalsProvider` (Protocol: `name: str`, `measure(url, strategy="mobile") -> VitalsResult`)
  - `THRESHOLDS: Dict[str, Tuple[float, float]]`
  - `rate_metric(metric, value) -> Optional[str]`
  - `rate(result) -> Optional[str]`
  - `metric_ratings(obj) -> Dict[str, Optional[str]]`
  - `vitals_issues(result) -> List[dict]`

- [ ] **Step 1: Write the failing tests**

```python
"""Core Web Vitals rating: Google's thresholds, field data before lab, and
the issues a measurement raises."""

import pytest

from app.vitals.model import VitalsResult, metric_ratings, rate, rate_metric, vitals_issues


@pytest.mark.parametrize("metric, value, expected", [
    ("lcp_ms", 2500, "good"), ("lcp_ms", 2501, "needs_improvement"),
    ("lcp_ms", 4000, "needs_improvement"), ("lcp_ms", 4001, "poor"),
    ("inp_ms", 200, "good"), ("inp_ms", 500, "needs_improvement"), ("inp_ms", 501, "poor"),
    ("cls", 0.1, "good"), ("cls", 0.25, "needs_improvement"), ("cls", 0.26, "poor"),
    ("tbt_ms", 200, "good"), ("tbt_ms", 600, "needs_improvement"), ("tbt_ms", 601, "poor"),
    ("lcp_ms", None, None),
])
def test_rate_metric_boundaries(metric, value, expected):
    assert rate_metric(metric, value) == expected


def test_field_data_rates_on_inp_and_ignores_tbt():
    r = VitalsResult(url="u", source="psi", data_kind="field", lcp_ms=2000, inp_ms=150, cls=0.05, tbt_ms=900)
    assert rate(r) == "good"


def test_lab_data_rates_on_tbt_in_place_of_inp():
    r = VitalsResult(url="u", source="lighthouse", data_kind="lab", lcp_ms=2000, cls=0.05, tbt_ms=900)
    assert rate(r) == "poor"


def test_the_page_rating_is_its_worst_metric_and_missing_ones_are_ignored():
    r = VitalsResult(url="u", source="psi", data_kind="lab", lcp_ms=3000, cls=None, tbt_ms=100)
    assert rate(r) == "needs_improvement"
    assert rate(VitalsResult(url="u", source="psi", data_kind="lab")) is None


def test_issues_name_value_threshold_and_data_kind():
    r = VitalsResult(url="u", source="lighthouse", data_kind="lab", lcp_ms=4800, cls=0.12, tbt_ms=100)
    issues = {i["code"]: i for i in vitals_issues(r)}
    assert set(issues) == {"CWV_LCP_POOR", "CWV_CLS_NEEDS_IMPROVEMENT"}
    assert issues["CWV_LCP_POOR"]["severity"] == "warning"
    assert issues["CWV_LCP_POOR"]["message"] == "LCP 4.8 s (lab) — poor, over 4.0 s"
    assert issues["CWV_CLS_NEEDS_IMPROVEMENT"]["severity"] == "info"
    assert issues["CWV_CLS_NEEDS_IMPROVEMENT"]["message"] == "CLS 0.12 (lab) — needs improvement, over 0.10"


def test_lab_tbt_gets_its_own_code():
    r = VitalsResult(url="u", source="psi", data_kind="lab", tbt_ms=700)
    assert [i["code"] for i in vitals_issues(r)] == ["CWV_TBT_POOR"]


def test_a_failed_measurement_raises_no_issues():
    r = VitalsResult(url="u", source="not_measured", error="timeout", lcp_ms=9000)
    assert vitals_issues(r) == []


def test_to_dict_carries_per_metric_ratings():
    d = VitalsResult(url="u", source="psi", data_kind="field", lcp_ms=5000, cls=0.01).to_dict()
    assert d["url"] == "u" and d["lcp_ms"] == 5000
    assert d["metric_ratings"] == {"lcp_ms": "poor", "inp_ms": None, "cls": "good", "tbt_ms": None}
    assert metric_ratings(VitalsResult(url="u")) == {"lcp_ms": None, "inp_ms": None, "cls": None, "tbt_ms": None}
```

- [ ] **Step 2: Run them and watch them fail**

Run: `cd apps/backend && python -m pytest tests/test_vitals_rating.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.vitals'`

- [ ] **Step 3: Implement**

`apps/backend/app/vitals/__init__.py`:

```python
"""Core Web Vitals: providers (PageSpeed Insights, local Lighthouse), rating,
and the page selection an audit measures."""
```

`apps/backend/app/vitals/model.py`:

```python
"""The Core Web Vitals result type, Google's thresholds, and the issues a
measurement raises."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Protocol, Tuple

from app.auditor.checks import issue

# (good at or under, poor over) -- Google's published Core Web Vitals
# thresholds. TBT is Lighthouse's own scale: lab runs have no INP, and TBT is
# the lab measure Google points to in its place.
THRESHOLDS: Dict[str, Tuple[float, float]] = {
    "lcp_ms": (2500, 4000),
    "inp_ms": (200, 500),
    "cls": (0.1, 0.25),
    "tbt_ms": (200, 600),
}
_LABELS = {"lcp_ms": "LCP", "inp_ms": "INP", "cls": "CLS", "tbt_ms": "TBT"}
_ORDER = ["good", "needs_improvement", "poor"]


@dataclass
class VitalsResult:
    url: str
    strategy: str = "mobile"
    source: str = "not_measured"          # psi | lighthouse | not_measured
    data_kind: Optional[str] = None       # field | lab: which data the rating used
    performance_score: Optional[float] = None
    lcp_ms: Optional[float] = None
    inp_ms: Optional[float] = None
    cls: Optional[float] = None
    fcp_ms: Optional[float] = None
    ttfb_ms: Optional[float] = None
    tbt_ms: Optional[float] = None
    rating: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "metric_ratings": metric_ratings(self)}


class VitalsProvider(Protocol):
    name: str

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult: ...


def rate_metric(metric: str, value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    good, poor = THRESHOLDS[metric]
    if value <= good:
        return "good"
    return "needs_improvement" if value <= poor else "poor"


def _rated(result) -> List[str]:
    """Field data is rated on LCP, INP and CLS. Lab data has no INP, so TBT
    stands in for it."""
    return ["lcp_ms", "inp_ms", "cls"] if result.data_kind == "field" else ["lcp_ms", "tbt_ms", "cls"]


def rate(result) -> Optional[str]:
    """The page's rating: its worst rated metric. Missing metrics are ignored."""
    ratings = [r for r in (rate_metric(m, getattr(result, m)) for m in _rated(result)) if r]
    return max(ratings, key=_ORDER.index) if ratings else None


def metric_ratings(obj) -> Dict[str, Optional[str]]:
    """Per-metric ratings for any object with the metric attributes (a
    VitalsResult or a stored row), so the UI never re-implements thresholds."""
    return {m: rate_metric(m, getattr(obj, m, None)) for m in THRESHOLDS}


def _fmt(metric: str, value: float) -> str:
    if metric == "cls":
        return f"{value:.2f}"
    if metric == "lcp_ms":
        return f"{value / 1000:.1f} s"
    return f"{round(value)} ms"


def vitals_issues(result) -> List[Dict[str, str]]:
    if result.error or result.source == "not_measured":
        return []
    out = []
    for metric in _rated(result):
        value = getattr(result, metric)
        rating = rate_metric(metric, value)
        if rating in (None, "good"):
            continue
        good, poor = THRESHOLDS[metric]
        label = _LABELS[metric]
        if rating == "poor":
            out.append(issue("warning", f"CWV_{label}_POOR",
                             f"{label} {_fmt(metric, value)} ({result.data_kind}) — poor, over {_fmt(metric, poor)}"))
        else:
            out.append(issue("info", f"CWV_{label}_NEEDS_IMPROVEMENT",
                             f"{label} {_fmt(metric, value)} ({result.data_kind}) — needs improvement, over {_fmt(metric, good)}"))
    return out
```

In `apps/backend/app/ai/ai_suggestions.py`, add to `IMPACT_WEIGHTS` (after `"META_DESC_TOO_LONG": 2, "META_DESC_TOO_SHORT": 2,`):

```python
    "CWV_LCP_POOR": 7, "CWV_INP_POOR": 7, "CWV_CLS_POOR": 7, "CWV_TBT_POOR": 5,
    "CWV_LCP_NEEDS_IMPROVEMENT": 3, "CWV_INP_NEEDS_IMPROVEMENT": 3,
    "CWV_CLS_NEEDS_IMPROVEMENT": 3, "CWV_TBT_NEEDS_IMPROVEMENT": 2,
```

and to `RECOMMENDATION_TEXT` (after the `"SLOW_TTFB"` entry):

```python
    "CWV_LCP_POOR": "Speed up the largest element: optimise the hero image, preload it, and cut server response time.",
    "CWV_LCP_NEEDS_IMPROVEMENT": "Speed up the largest element: optimise the hero image, preload it, and cut server response time.",
    "CWV_INP_POOR": "Break up long JavaScript tasks and defer non-critical scripts so the page responds to input quickly.",
    "CWV_INP_NEEDS_IMPROVEMENT": "Break up long JavaScript tasks and defer non-critical scripts so the page responds to input quickly.",
    "CWV_CLS_POOR": "Reserve space for images, ads and embeds (width/height or aspect-ratio) so the layout doesn't shift.",
    "CWV_CLS_NEEDS_IMPROVEMENT": "Reserve space for images, ads and embeds (width/height or aspect-ratio) so the layout doesn't shift.",
    "CWV_TBT_POOR": "Reduce main-thread JavaScript work (split bundles, remove unused code) to unblock the page.",
    "CWV_TBT_NEEDS_IMPROVEMENT": "Reduce main-thread JavaScript work (split bundles, remove unused code) to unblock the page.",
```

- [ ] **Step 4: Run and pass**

Run: `python -m pytest tests/test_vitals_rating.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/vitals apps/backend/app/ai/ai_suggestions.py apps/backend/tests/test_vitals_rating.py
git commit -m "feat(vitals): result type, Google thresholds, rating and CWV issues"
```

---

### Task 2: PageSpeed Insights provider and config

**Files:**
- Create: `apps/backend/app/vitals/psi.py`
- Modify: `apps/backend/app/config/config.py`, `apps/backend/tests/conftest.py`
- Test: `apps/backend/tests/test_vitals_psi.py`

**Interfaces:**
- Consumes: `VitalsResult`, `rate` (Task 1); `app.providers.spend.reserve(name, cap)`; `app.providers.serp.ProviderSkipped`.
- Produces:
  - `PSI_ENDPOINT`
  - `parse_lab(lhr: dict) -> dict` (keys `performance_score, lcp_ms, cls, fcp_ms, tbt_ms, ttfb_ms`)
  - `parse_field(loading_experience) -> dict`
  - `parse_psi(url, strategy, data) -> VitalsResult`
  - `PsiProvider(api_key: str, cap: int, timeout: int = 60)` with `.name == "psi"` and `.measure(url, strategy)`
  - Config: `PSI_API_KEY, PSI_DAILY_CAP, PSI_MAX_PAGES, LIGHTHOUSE_ENABLED, CHROME_PATH, LIGHTHOUSE_CLI`

- [ ] **Step 1: Config and test isolation**

In `apps/backend/app/config/config.py`, append after the `GOOGLE_CSE_DAILY_QUOTA` line:

```python
# Core Web Vitals (Phase 5.1). PageSpeed Insights is free but quota'd, so it
# still has a hard daily cap. Lighthouse is a local fallback, opt-in because it
# needs Node, Chrome and a global `npm i -g lighthouse@12`.
PSI_API_KEY = os.getenv("PSI_API_KEY", "")
PSI_DAILY_CAP = int(os.getenv("PSI_DAILY_CAP", "50"))
PSI_MAX_PAGES = int(os.getenv("PSI_MAX_PAGES", "5"))
LIGHTHOUSE_ENABLED = os.getenv("LIGHTHOUSE_ENABLED", "").strip().lower() in ("1", "true", "yes")
CHROME_PATH = os.getenv("CHROME_PATH", "")
LIGHTHOUSE_CLI = os.getenv("LIGHTHOUSE_CLI", "")
```

Append to `apps/backend/tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def no_live_web_vitals(monkeypatch):
    """A developer's .env may hold a PSI key or LIGHTHOUSE_ENABLED=true. Tests
    must never reach Google or launch Chrome, so both are off unless a test
    turns them on."""
    monkeypatch.setattr(app_config, "PSI_API_KEY", "")
    monkeypatch.setattr(app_config, "LIGHTHOUSE_ENABLED", False)
```

- [ ] **Step 2: Write the failing tests**

```python
"""PageSpeed Insights: raw-number parsing, field before lab, the daily cap,
and errors that never leak the key."""

from unittest.mock import MagicMock, patch

import requests

from app.vitals import psi
from app.vitals.psi import PsiProvider, parse_field, parse_lab, parse_psi

LAB = {
    "categories": {"performance": {"score": 0.42}},
    "audits": {
        "largest-contentful-paint": {"numericValue": 4810.5, "displayValue": "4.8 s"},
        "cumulative-layout-shift": {"numericValue": 0.12},
        "first-contentful-paint": {"numericValue": 1900},
        "total-blocking-time": {"numericValue": 350},
        "server-response-time": {"numericValue": 420},
    },
}
FIELD = {"metrics": {
    "LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300},
    "INTERACTION_TO_NEXT_PAINT": {"percentile": 180},
    "CUMULATIVE_LAYOUT_SHIFT_SCORE": {"percentile": 5},     # PSI sends CLS x100
    "FIRST_CONTENTFUL_PAINT_MS": {"percentile": 1200},
    "EXPERIMENTAL_TIME_TO_FIRST_BYTE": {"percentile": 600},
}}


def _response(status=200, body=None, text=""):
    resp = MagicMock(status_code=status, text=text)
    resp.json.return_value = body
    return resp


def test_parse_lab_reads_raw_numbers_not_display_strings():
    assert parse_lab(LAB) == {"performance_score": 42.0, "lcp_ms": 4810.5, "cls": 0.12,
                              "fcp_ms": 1900.0, "tbt_ms": 350.0, "ttfb_ms": 420.0}


def test_parse_field_divides_cls_and_ignores_origin_fallback():
    assert parse_field(FIELD) == {"lcp_ms": 2300.0, "inp_ms": 180.0, "cls": 0.05,
                                  "fcp_ms": 1200.0, "ttfb_ms": 600.0}
    assert parse_field({**FIELD, "origin_fallback": True}) == {}
    assert parse_field(None) == {}


def test_field_data_wins_and_lab_keeps_score_and_tbt():
    r = parse_psi("https://a.com/", "mobile", {"lighthouseResult": LAB, "loadingExperience": FIELD})
    assert (r.source, r.data_kind) == ("psi", "field")
    assert (r.lcp_ms, r.inp_ms, r.cls) == (2300.0, 180.0, 0.05)
    assert (r.performance_score, r.tbt_ms) == (42.0, 350.0)
    assert r.rating == "good"


def test_lab_only_is_rated_on_lab_numbers():
    r = parse_psi("https://a.com/", "mobile", {"lighthouseResult": LAB})
    assert r.data_kind == "lab" and r.inp_ms is None and r.rating == "poor"


def test_a_lighthouse_runtime_error_is_an_error():
    r = parse_psi("https://a.com/", "mobile", {"lighthouseResult": {"runtimeError": {"code": "NO_FCP", "message": "No content"}}})
    assert r.error == "PSI: No content"


def test_measure_calls_psi_and_parses():
    with patch.object(psi.requests, "get", return_value=_response(body={"lighthouseResult": LAB})) as get:
        r = PsiProvider("k-123", cap=5).measure("https://a.com/")
    assert get.call_args.kwargs["params"] == {"url": "https://a.com/", "key": "k-123",
                                              "strategy": "mobile", "category": "performance"}
    assert r.lcp_ms == 4810.5 and r.error is None


def test_http_errors_are_reported_without_the_key():
    body = {"error": {"message": "API key k-123 not valid"}}
    with patch.object(psi.requests, "get", return_value=_response(400, body)):
        r = PsiProvider("k-123", cap=5).measure("https://a.com/")
    assert r.error == "PSI returned 400: API key *** not valid"


def test_network_errors_name_the_type_only():
    """str() of a requests exception contains the request URL, key included."""
    boom = requests.ConnectionError("https://www.googleapis.com/...?key=k-123")
    with patch.object(psi.requests, "get", side_effect=boom):
        r = PsiProvider("k-123", cap=5).measure("https://a.com/")
    assert r.error == "PSI request failed: ConnectionError" and "k-123" not in r.error


def test_the_daily_cap_stops_calls():
    with patch.object(psi.requests, "get", return_value=_response(body={"lighthouseResult": LAB})) as get:
        provider = PsiProvider("k", cap=1)
        first, second = provider.measure("https://a.com/"), provider.measure("https://a.com/b")
    assert first.error is None
    assert second.error == "daily cap of 1 psi calls reached"
    assert get.call_count == 1
```

- [ ] **Step 3: Run and watch them fail**

Run: `python -m pytest tests/test_vitals_psi.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.vitals.psi'`

- [ ] **Step 4: Implement `apps/backend/app/vitals/psi.py`**

```python
"""Google PageSpeed Insights v5: lab data from Lighthouse in Google's cloud,
plus page-level field data (CrUX) when Google has enough real-user traffic."""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from app.providers.serp import ProviderSkipped
from app.providers.spend import reserve
from app.vitals.model import VitalsResult, rate

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

_FIELD_METRICS = {
    "lcp_ms": "LARGEST_CONTENTFUL_PAINT_MS",
    "inp_ms": "INTERACTION_TO_NEXT_PAINT",
    "cls": "CUMULATIVE_LAYOUT_SHIFT_SCORE",
    "fcp_ms": "FIRST_CONTENTFUL_PAINT_MS",
    "ttfb_ms": "EXPERIMENTAL_TIME_TO_FIRST_BYTE",
}


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_lab(lhr: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Numbers from a Lighthouse result (PSI's lighthouseResult, or the local
    CLI's JSON): numericValue, never the display strings."""
    audits = lhr.get("audits") or {}
    score = _number(((lhr.get("categories") or {}).get("performance") or {}).get("score"))

    def audit(key: str) -> Optional[float]:
        return _number((audits.get(key) or {}).get("numericValue"))

    return {
        "performance_score": round(score * 100, 1) if score is not None else None,
        "lcp_ms": audit("largest-contentful-paint"),
        "cls": audit("cumulative-layout-shift"),
        "fcp_ms": audit("first-contentful-paint"),
        "tbt_ms": audit("total-blocking-time"),
        "ttfb_ms": audit("server-response-time"),
    }


def parse_field(loading_experience: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """This page's 75th-percentile field values, or {} when Google has none
    for it. Origin-wide data (origin_fallback) is not this page's, so it is
    ignored."""
    if not loading_experience or loading_experience.get("origin_fallback"):
        return {}
    metrics = loading_experience.get("metrics") or {}
    out: Dict[str, float] = {}
    for key, name in _FIELD_METRICS.items():
        value = _number((metrics.get(name) or {}).get("percentile"))
        if value is not None:
            out[key] = value / 100 if key == "cls" else value   # CLS arrives x100
    return out if any(k in out for k in ("lcp_ms", "inp_ms", "cls")) else {}


def parse_psi(url: str, strategy: str, data: Dict[str, Any]) -> VitalsResult:
    lhr = data.get("lighthouseResult") or {}
    runtime = lhr.get("runtimeError")
    if runtime:
        return VitalsResult(url=url, strategy=strategy, source="psi",
                            error=f"PSI: {runtime.get('message') or runtime.get('code')}")
    field = parse_field(data.get("loadingExperience"))
    result = VitalsResult(url=url, strategy=strategy, source="psi",
                          data_kind="field" if field else "lab", **parse_lab(lhr))
    for key, value in field.items():    # field values replace lab ones where present
        setattr(result, key, value)
    result.rating = rate(result)
    return result


class PsiProvider:
    name = "psi"

    def __init__(self, api_key: str, cap: int, timeout: int = 60) -> None:
        self.api_key = api_key
        self.cap = cap
        self.timeout = timeout

    def _redact(self, text: str) -> str:
        return text.replace(self.api_key, "***") if self.api_key else text

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        def failed(message: str) -> VitalsResult:
            return VitalsResult(url=url, strategy=strategy, source="psi", error=self._redact(message))

        try:
            reserve(self.name, self.cap)
        except ProviderSkipped as exc:
            return failed(str(exc))
        try:
            resp = requests.get(PSI_ENDPOINT, timeout=self.timeout, params={
                "url": url, "key": self.api_key, "strategy": strategy, "category": "performance",
            })
        except requests.RequestException as exc:
            # The type only: str(exc) carries the request URL, key included.
            return failed(f"PSI request failed: {type(exc).__name__}")
        if resp.status_code != 200:
            try:
                detail = (resp.json() or {}).get("error", {}).get("message") or ""
            except ValueError:
                detail = resp.text
            return failed(f"PSI returned {resp.status_code}: {detail[:200]}")
        try:
            data = resp.json()
        except ValueError:
            return failed("PSI returned invalid JSON")
        return parse_psi(url, strategy, data or {})
```

- [ ] **Step 5: Run and pass**

Run: `python -m pytest tests/test_vitals_psi.py -q`
Expected: all pass.

- [ ] **Step 6: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/vitals/psi.py apps/backend/app/config/config.py apps/backend/tests/conftest.py apps/backend/tests/test_vitals_psi.py
git commit -m "feat(vitals): PageSpeed Insights provider with daily cap and key-safe errors"
```

---

### Task 3: Lighthouse provider, fallback chain, provider factory

**Files:**
- Create: `apps/backend/app/vitals/lighthouse.py`, `apps/backend/app/vitals/providers.py`
- Test: `apps/backend/tests/test_vitals_lighthouse.py`

**Interfaces:**
- Consumes: `VitalsResult`, `rate` (Task 1); `parse_lab`, `PsiProvider` (Task 2); config from Task 2.
- Produces:
  - `find_chrome(explicit: str = "") -> Optional[str]`
  - `find_lighthouse_cli(explicit: str = "") -> Optional[str]`
  - `parse_lighthouse(url, strategy, lhr) -> VitalsResult`
  - `LighthouseProvider(chrome_path, cli_path, node_path, timeout=90)` with `.name == "lighthouse"` and `.command(url, strategy) -> List[str]`
  - `FallbackChain(providers)` with `.measure`
  - `build_vitals_provider(psi_key: Optional[str] = None) -> Optional[FallbackChain]`

- [ ] **Step 1: Write the failing tests**

```python
"""Local Lighthouse (opt-in fallback), the fallback chain, and which
providers an audit gets."""

import json
import subprocess
from unittest.mock import MagicMock, patch

from app.config import config
from app.vitals import lighthouse, providers
from app.vitals.lighthouse import LighthouseProvider, find_chrome, find_lighthouse_cli, parse_lighthouse
from app.vitals.model import VitalsResult
from app.vitals.providers import FallbackChain, build_vitals_provider

LHR = {"categories": {"performance": {"score": 0.9}},
       "audits": {"largest-contentful-paint": {"numericValue": 1800},
                  "cumulative-layout-shift": {"numericValue": 0.01},
                  "total-blocking-time": {"numericValue": 90}}}


def _provider():
    return LighthouseProvider("C:/chrome.exe", "C:/npm/lighthouse/cli/index.js", "C:/node.exe")


def test_the_command_runs_node_directly_never_a_shell_script():
    cmd = _provider().command("https://a.com/?q=1&x=2", "mobile")
    assert cmd[:3] == ["C:/node.exe", "C:/npm/lighthouse/cli/index.js", "https://a.com/?q=1&x=2"]
    assert "--output=json" in cmd and "--output-path=stdout" in cmd
    assert "--only-categories=performance" in cmd


def test_measure_parses_lab_results_and_passes_chrome_path():
    proc = MagicMock(returncode=0, stdout=json.dumps(LHR), stderr="")
    with patch.object(lighthouse.subprocess, "run", return_value=proc) as run:
        r = _provider().measure("https://a.com/")
    args, kwargs = run.call_args
    assert isinstance(args[0], list) and "shell" not in kwargs
    assert kwargs["timeout"] == 90 and kwargs["env"]["CHROME_PATH"] == "C:/chrome.exe"
    assert (r.source, r.data_kind, r.lcp_ms, r.tbt_ms, r.rating) == ("lighthouse", "lab", 1800.0, 90.0, "good")


def test_timeouts_and_failures_become_errors():
    with patch.object(lighthouse.subprocess, "run", side_effect=subprocess.TimeoutExpired("node", 90)):
        assert _provider().measure("https://a.com/").error == "Lighthouse timed out after 90s"
    with patch.object(lighthouse.subprocess, "run", return_value=MagicMock(returncode=1, stdout="", stderr="x" * 500 + "Chrome not found")):
        error = _provider().measure("https://a.com/").error
    assert error.startswith("Lighthouse failed (exit 1): ") and error.endswith("Chrome not found") and len(error) < 260
    with patch.object(lighthouse.subprocess, "run", return_value=MagicMock(returncode=0, stdout="not json", stderr="")):
        assert _provider().measure("https://a.com/").error == "Lighthouse returned no JSON"


def test_a_lighthouse_runtime_error_is_an_error():
    r = parse_lighthouse("https://a.com/", "mobile", {"runtimeError": {"code": "NO_FCP", "message": "No content"}})
    assert r.error == "Lighthouse: No content"


def test_finders_honour_explicit_paths(tmp_path):
    chrome = tmp_path / "chrome.exe"; chrome.write_text("")
    cli = tmp_path / "index.js"; cli.write_text("")
    assert find_chrome(str(chrome)) == str(chrome)
    assert find_chrome(str(tmp_path / "missing")) is None
    assert find_lighthouse_cli(str(cli)) == str(cli)
    assert find_lighthouse_cli(str(tmp_path / "missing.js")) is None


class _Stub:
    def __init__(self, name, result=None, raises=None):
        self.name, self.result, self.raises, self.calls = name, result, raises, 0

    def measure(self, url, strategy="mobile"):
        self.calls += 1
        if self.raises:
            raise self.raises
        return self.result


def test_the_chain_returns_the_first_success():
    ok = VitalsResult(url="u", source="lighthouse", data_kind="lab", lcp_ms=1)
    psi = _Stub("psi", VitalsResult(url="u", source="psi", error="PSI returned 500: x"))
    lh = _Stub("lighthouse", ok)
    assert FallbackChain([psi, lh]).measure("u") is ok


def test_the_chain_reports_every_reason_when_all_fail():
    chain = FallbackChain([_Stub("psi", VitalsResult(url="u", error="cap")), _Stub("lighthouse", raises=RuntimeError("boom"))])
    r = chain.measure("u")
    assert r.source == "not_measured" and r.error == "psi: cap; lighthouse: unexpected error (RuntimeError)"


def test_build_returns_none_when_nothing_is_configured():
    assert build_vitals_provider() is None


def test_build_uses_psi_then_lighthouse(monkeypatch):
    monkeypatch.setattr(config, "PSI_API_KEY", "env-key")
    monkeypatch.setattr(config, "LIGHTHOUSE_ENABLED", True)
    monkeypatch.setattr(providers, "find_chrome", lambda explicit="": "C:/chrome.exe")
    monkeypatch.setattr(providers, "find_lighthouse_cli", lambda explicit="": "C:/cli.js")
    monkeypatch.setattr(providers.shutil, "which", lambda name: "C:/node.exe")
    chain = build_vitals_provider()
    assert [p.name for p in chain.providers] == ["psi", "lighthouse"]
    assert chain.providers[0].api_key == "env-key"
    assert build_vitals_provider(psi_key="cli-key").providers[0].api_key == "cli-key"


def test_lighthouse_is_skipped_when_chrome_is_missing(monkeypatch):
    monkeypatch.setattr(config, "LIGHTHOUSE_ENABLED", True)
    monkeypatch.setattr(providers, "find_chrome", lambda explicit="": None)
    monkeypatch.setattr(providers, "find_lighthouse_cli", lambda explicit="": "C:/cli.js")
    assert build_vitals_provider() is None
```

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_vitals_lighthouse.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.vitals.lighthouse'`

- [ ] **Step 3: Implement `apps/backend/app/vitals/lighthouse.py`**

```python
"""Local Lighthouse: the fallback when PageSpeed Insights isn't available.

Run as `node <lighthouse>/cli/index.js`, never through npx or a .cmd shim. On
Windows those are batch files, and cmd.exe would interpret characters like `&`
in a crawled URL. Lighthouse must be installed once with
`npm i -g lighthouse@12`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.vitals.model import VitalsResult, rate
from app.vitals.psi import parse_lab


def _chrome_candidates() -> List[str]:
    local = os.environ.get("LOCALAPPDATA", "")
    return [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.join(local, r"Google\Chrome\Application\chrome.exe") if local else "",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]


def find_chrome(explicit: str = "") -> Optional[str]:
    if explicit:
        return explicit if os.path.exists(explicit) else None
    for path in _chrome_candidates():
        if path and os.path.exists(path):
            return path
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def find_lighthouse_cli(explicit: str = "") -> Optional[str]:
    """The Lighthouse CLI entry script: LIGHTHOUSE_CLI, else the global npm
    install (`npm root -g`/lighthouse/cli/index.js)."""
    if explicit:
        return explicit if os.path.exists(explicit) else None
    npm = shutil.which("npm")
    if not npm:
        return None
    try:
        # Fixed arguments only, so running npm's .cmd shim here is safe.
        root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    cli = Path(root) / "lighthouse" / "cli" / "index.js"
    return str(cli) if root and cli.exists() else None


def parse_lighthouse(url: str, strategy: str, lhr: Dict[str, Any]) -> VitalsResult:
    runtime = lhr.get("runtimeError")
    if runtime:
        return VitalsResult(url=url, strategy=strategy, source="lighthouse",
                            error=f"Lighthouse: {runtime.get('message') or runtime.get('code')}")
    result = VitalsResult(url=url, strategy=strategy, source="lighthouse", data_kind="lab", **parse_lab(lhr))
    result.rating = rate(result)
    return result


class LighthouseProvider:
    name = "lighthouse"

    def __init__(self, chrome_path: str, cli_path: str, node_path: str, timeout: int = 90) -> None:
        self.chrome_path = chrome_path
        self.cli_path = cli_path
        self.node_path = node_path
        self.timeout = timeout

    def command(self, url: str, strategy: str = "mobile") -> List[str]:
        cmd = [self.node_path, self.cli_path, url, "--output=json", "--output-path=stdout",
               "--only-categories=performance", "--quiet",
               "--chrome-flags=--headless=new --no-sandbox"]
        if strategy == "desktop":
            cmd.append("--preset=desktop")
        return cmd

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        def failed(message: str) -> VitalsResult:
            return VitalsResult(url=url, strategy=strategy, source="lighthouse", error=message)

        try:
            proc = subprocess.run(
                self.command(url, strategy), capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=self.timeout, env={**os.environ, "CHROME_PATH": self.chrome_path},
            )
        except subprocess.TimeoutExpired:
            return failed(f"Lighthouse timed out after {self.timeout}s")
        except OSError as exc:
            return failed(f"Lighthouse could not start: {type(exc).__name__}")
        if proc.returncode != 0:
            return failed(f"Lighthouse failed (exit {proc.returncode}): {(proc.stderr or '').strip()[-200:]}")
        try:
            lhr = json.loads(proc.stdout)
        except ValueError:
            return failed("Lighthouse returned no JSON")
        return parse_lighthouse(url, strategy, lhr)
```

- [ ] **Step 4: Implement `apps/backend/app/vitals/providers.py`**

```python
"""Which Core Web Vitals sources an audit gets, tried in order."""

from __future__ import annotations

import logging
import shutil
from typing import List, Optional

from app.config import config
from app.vitals.lighthouse import LighthouseProvider, find_chrome, find_lighthouse_cli
from app.vitals.model import VitalsProvider, VitalsResult
from app.vitals.psi import PsiProvider

logger = logging.getLogger(__name__)


class FallbackChain:
    """The first provider whose result has no error wins. If they all fail,
    the result is `not_measured`, with every provider's reason."""

    name = "chain"

    def __init__(self, providers: List[VitalsProvider]) -> None:
        self.providers = list(providers)

    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult:
        reasons = []
        for provider in self.providers:
            try:
                result = provider.measure(url, strategy)
            except Exception as exc:
                logger.error("%s failed on %s: %s", provider.name, url, exc, exc_info=exc)
                reasons.append(f"{provider.name}: unexpected error ({type(exc).__name__})")
                continue
            if not result.error:
                return result
            reasons.append(f"{provider.name}: {result.error}")
        return VitalsResult(url=url, strategy=strategy, source="not_measured", error="; ".join(reasons))


def build_vitals_provider(psi_key: Optional[str] = None) -> Optional[FallbackChain]:
    """PSI if a key is set (the CLI's --psi-key overrides PSI_API_KEY), then
    Lighthouse if it's enabled and Chrome, Node and the CLI are all found.
    Returns None when neither is available."""
    chain: List[VitalsProvider] = []
    key = psi_key or config.PSI_API_KEY
    if key:
        chain.append(PsiProvider(key, config.PSI_DAILY_CAP))
    if config.LIGHTHOUSE_ENABLED:
        chrome = find_chrome(config.CHROME_PATH)
        cli = find_lighthouse_cli(config.LIGHTHOUSE_CLI)
        node = shutil.which("node")
        if chrome and cli and node:
            chain.append(LighthouseProvider(chrome, cli, node))
        else:
            missing = [n for n, v in (("Chrome", chrome), ("Lighthouse CLI", cli), ("node", node)) if not v]
            logger.warning("LIGHTHOUSE_ENABLED, but not found: %s", ", ".join(missing))
    return FallbackChain(chain) if chain else None
```

- [ ] **Step 5: Run and pass**

Run: `python -m pytest tests/test_vitals_lighthouse.py -q`
Expected: all pass.

- [ ] **Step 6: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/vitals/lighthouse.py apps/backend/app/vitals/providers.py apps/backend/tests/test_vitals_lighthouse.py
git commit -m "feat(vitals): opt-in local Lighthouse fallback and provider chain"
```

---

### Task 4: Page selection and the measuring runner

**Files:**
- Create: `apps/backend/app/vitals/runner.py`
- Test: `apps/backend/tests/test_vitals_runner.py`

**Interfaces:**
- Consumes: `VitalsResult` (Task 1).
- Produces:
  - `select_vitals_pages(start_url: str, top_pages: List[dict], results: Dict[str, PageResult-like], limit: int) -> List[str]`
  - `measure_pages(provider, urls, strategy="mobile", on_progress=None, max_workers=3) -> List[VitalsResult]` (in `urls` order; `on_progress(done, total, url)`)

- [ ] **Step 1: Write the failing tests**

```python
"""Which pages an audit measures, and measuring them a few at a time."""

import threading
from types import SimpleNamespace as Page

from app.vitals.model import VitalsResult
from app.vitals.runner import measure_pages, select_vitals_pages


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
    assert select_vitals_pages("https://a.com/", top, _results(), 3) == [
        "https://a.com/", "https://a.com/deep", "https://a.com/shop"]


def test_without_pagerank_the_shallowest_pages_fill_in():
    assert select_vitals_pages("https://a.com/", [], _results(), 10) == [
        "https://a.com/", "https://a.com/shop", "https://a.com/blog", "https://a.com/deep"]


def test_a_failed_start_url_is_skipped_and_limit_zero_measures_nothing():
    results = _results()
    results["https://a.com/"].status_code = 500
    assert select_vitals_pages("https://a.com/", [], results, 1) == ["https://a.com/shop"]
    assert select_vitals_pages("https://a.com/", [], _results(), 0) == []


class _Provider:
    name = "stub"

    def __init__(self):
        self.lock, self.active, self.peak = threading.Lock(), 0, 0

    def measure(self, url, strategy="mobile"):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            if url.endswith("boom"):
                raise RuntimeError("boom")
            return VitalsResult(url=url, source="psi", data_kind="lab", lcp_ms=1000)
        finally:
            with self.lock:
                self.active -= 1


def test_measure_keeps_order_reports_progress_and_contains_errors():
    urls = [f"https://a.com/{i}" for i in range(5)] + ["https://a.com/boom"]
    seen = []
    provider = _Provider()
    results = measure_pages(provider, urls, on_progress=lambda d, t, u: seen.append((d, t)))
    assert [r.url for r in results] == urls
    assert results[-1].source == "not_measured" and results[-1].error == "unexpected error (RuntimeError)"
    assert sorted(seen) == [(i, 6) for i in range(1, 7)]
    assert provider.peak <= 3
```

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_vitals_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.vitals.runner'`

- [ ] **Step 3: Implement `apps/backend/app/vitals/runner.py`**

```python
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
```

- [ ] **Step 4: Run and pass**

Run: `python -m pytest tests/test_vitals_runner.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/vitals/runner.py apps/backend/tests/test_vitals_runner.py
git commit -m "feat(vitals): choose pages to measure and measure them three at a time"
```

---

### Task 5: Storage: `web_vitals` table, session issues, `record_audit`

**Files:**
- Create: `apps/backend/alembic/versions/0004_web_vitals.py`
- Modify:
  - `apps/backend/app/db/models.py`
  - `apps/backend/app/db/audit_store.py` (`SUMMARY_FIELDS`, `record_audit`)
  - `apps/backend/app/models/session_db.py` (`add_issues`)
  - `apps/backend/tests/test_db_schema.py` (`TABLES`)
- Test: `apps/backend/tests/test_vitals_storage.py`

**Interfaces:**
- Consumes: `VitalsResult.to_dict()` (Task 1).
- Produces:
  - Model `WebVital` (table `web_vitals`)
  - `SessionDB.add_issues(url: str, issues: List[dict]) -> None`
  - `record_audit` storing `result["web_vitals"]` rows (dicts from `to_dict()`)
  - `"web_vitals_status"` added to `SUMMARY_FIELDS`

- [ ] **Step 1: Write the failing tests**

First read `tests/test_audit_store.py` to see how it builds a session DB and a result for `record_audit`, and reuse that helper. The test below assumes it is named `_session_with_pages(tmp_path)`. If the real helper differs, adapt the two lines that build `db` and `result`, and keep the assertions.

```python
"""Core Web Vitals rows in the central DB, and issues added to a page after
its row was written."""

from sqlalchemy import select

from app.db.audit_store import record_audit
from app.db.engine import get_session_factory
from app.db.models import Audit, WebVital
from app.models.session_db import SessionDB
from app.vitals.model import VitalsResult


def test_add_issues_appends_and_counts(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": [
        {"severity": "info", "code": "X", "message": "x"}]}])
    db.add_issues("https://a.com/", [{"severity": "warning", "code": "CWV_LCP_POOR", "message": "slow"}])
    db.add_issues("https://a.com/", [])
    codes = sorted(i["code"] for batch in db.iter_issues(100) for i in batch)
    assert codes == ["CWV_LCP_POOR", "X"]
    assert db.get_page("https://a.com/")["issue_count"] == 2


def test_record_audit_stores_vitals_rows_and_status(tmp_path):
    db = SessionDB(tmp_path / "s.db")
    db.add_pages([{"url": "https://a.com/", "meta": {}, "issues": []}])
    rows = [VitalsResult(url="https://a.com/", source="psi", data_kind="field", lcp_ms=2300,
                         inp_ms=180, cls=0.05, rating="good").to_dict(),
            VitalsResult(url="https://a.com/b", source="not_measured", error="timeout").to_dict()]
    result = {"executive_summary": {"health_score": {"score": 80}}, "pages": [],
              "web_vitals": rows, "web_vitals_status": "measured"}
    factory = get_session_factory()
    audit_id, _ = record_audit(factory, db, result, session_id="s1", start_url="https://a.com/")
    with factory() as session:
        stored = session.scalars(select(WebVital).where(WebVital.audit_id == audit_id).order_by(WebVital.id)).all()
        audit = session.get(Audit, audit_id)
        assert [(v.url, v.source, v.lcp_ms, v.rating, v.error) for v in stored] == [
            ("https://a.com/", "psi", 2300.0, "good", None),
            ("https://a.com/b", "not_measured", None, None, "timeout")]
        assert stored[0].measured_at is not None
        assert audit.summary_json["web_vitals_status"] == "measured"
```

If `SessionDB.get_page` returns no `issue_count` key, assert on the row returned by `get_pages` instead (read `session_db.py:143-215` first).

In `tests/test_db_schema.py`, add `"web_vitals"` to the `TABLES` set.

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_vitals_storage.py tests/test_db_schema.py -q`
Expected: FAIL with `ImportError: cannot import name 'WebVital'`

- [ ] **Step 3: Model**

Append to `apps/backend/app/db/models.py`:

```python
class WebVital(Base):
    """One page's Core Web Vitals in one audit (Phase 5.1)."""
    __tablename__ = "web_vitals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    audit_id: Mapped[int] = mapped_column(ForeignKey("audits.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    strategy: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(16))
    data_kind: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    rating: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    performance_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lcp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    inp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cls: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fcp_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    ttfb_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tbt_ms: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

- [ ] **Step 4: Migration `apps/backend/alembic/versions/0004_web_vitals.py`**

```python
"""web vitals

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-25 23:30:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('web_vitals',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('audit_id', sa.Integer(), nullable=False),
    sa.Column('url', sa.Text(), nullable=False),
    sa.Column('strategy', sa.String(length=16), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('data_kind', sa.String(length=8), nullable=True),
    sa.Column('rating', sa.String(length=24), nullable=True),
    sa.Column('performance_score', sa.Float(), nullable=True),
    sa.Column('lcp_ms', sa.Float(), nullable=True),
    sa.Column('inp_ms', sa.Float(), nullable=True),
    sa.Column('cls', sa.Float(), nullable=True),
    sa.Column('fcp_ms', sa.Float(), nullable=True),
    sa.Column('ttfb_ms', sa.Float(), nullable=True),
    sa.Column('tbt_ms', sa.Float(), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('measured_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['audit_id'], ['audits.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_web_vitals_audit_id'), 'web_vitals', ['audit_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_web_vitals_audit_id'), table_name='web_vitals')
    op.drop_table('web_vitals')
```

`test_the_models_match_the_migration` is the check that the model and migration agree. If it reports a diff, fix the migration so it matches the model.

- [ ] **Step 5: `SessionDB.add_issues`** (in `app/models/session_db.py`, after `add_pages`)

```python
    def add_issues(self, url: str, issues: List[Dict[str, Any]]) -> None:
        """Add issues found after a page's row was written: Core Web Vitals
        are measured once the crawl is over."""
        if not issues:
            return
        with self._conn:
            self._conn.executemany(
                "INSERT INTO issues VALUES (?,?,?,?)",
                [(url, i["severity"], i["code"], i["message"]) for i in issues],
            )
            self._conn.execute(
                "UPDATE pages SET issue_count = issue_count + ? WHERE url = ?", (len(issues), url)
            )
```

- [ ] **Step 6: `record_audit`** (in `app/db/audit_store.py`)

- Add `"web_vitals_status"` to the `SUMMARY_FIELDS` tuple/list.
- Import `WebVital` next to the other model imports.
- Add the helper below, and call `_record_vitals(session, audit.id, result.get("web_vitals") or [])` right after the `_record_rankings(...)` line.

```python
_VITALS_COLUMNS = ("url", "strategy", "source", "data_kind", "rating", "performance_score",
                   "lcp_ms", "inp_ms", "cls", "fcp_ms", "ttfb_ms", "tbt_ms", "error")


def _record_vitals(session: Session, audit_id: int, rows: List[Dict[str, Any]]) -> None:
    if rows:
        now = utcnow()
        session.execute(insert(WebVital), [
            {**{c: row.get(c) for c in _VITALS_COLUMNS}, "audit_id": audit_id, "measured_at": now}
            for row in rows
        ])
```

If `List` isn't already imported from `typing` there, add it.

- [ ] **Step 7: Run and pass**

Run: `python -m pytest tests/test_vitals_storage.py tests/test_db_schema.py tests/test_audit_store.py -q`
Expected: all pass.

- [ ] **Step 8: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/db apps/backend/alembic/versions/0004_web_vitals.py apps/backend/app/models/session_db.py apps/backend/tests/test_vitals_storage.py apps/backend/tests/test_db_schema.py
git commit -m "feat(vitals): web_vitals table, migration 0004, stored with each audit"
```

---

### Task 6: Audit pipeline, request flag, CLI, live progress

**Files:**
- Modify:
  - `apps/backend/app/services/audit_service.py`
  - `apps/backend/app/utils/performance.py` (delete `fetch_psi_metrics`, `PSI_ENDPOINT`, and the `requests` import if now unused)
  - `apps/backend/app/schemas/schemas.py`
  - `apps/backend/app/api/routes.py`
  - `apps/backend/app/cli.py`
  - `apps/backend/tests/test_pipeline_options.py` (replace the two PSI tests)
- Test: `apps/backend/tests/test_vitals_pipeline.py`

**Interfaces:**
- Consumes: Tasks 1–5.
- Produces:
  - `_build_audit_result(..., psi_key=None, psi_strategy="mobile", enable_web_vitals=True, vitals_max_pages=None, vitals_provider=None)`
  - `run_full_audit(..., enable_web_vitals=True)`
  - Result keys: `web_vitals: List[dict]`, `web_vitals_status: "measured"|"not_configured"|"disabled"`, `psi_metrics: {url: dict}`
  - Event `("web_vitals", {"done", "total", "url"})`
  - `AuditRequestParams.enable_web_vitals`
  - CLI `--psi-max-pages`

- [ ] **Step 1: Write the failing tests** (`tests/test_vitals_pipeline.py`)

```python
"""Core Web Vitals inside an audit: measured once after the crawl, issues
added, stored, and never fatal."""

from unittest.mock import patch

from sqlalchemy import select

from app.db.engine import get_session_factory
from app.db.models import WebVital
from app.services import audit_service
from app.vitals.model import VitalsResult

from test_audit_service_crawler_registry import FakeCrawler


class StubProvider:
    name = "stub"

    def __init__(self, result=None, raises=None):
        self.calls, self.result, self.raises = [], result, raises

    def measure(self, url, strategy="mobile"):
        self.calls.append((url, strategy))
        if self.raises:
            raise self.raises
        return self.result or VitalsResult(url=url, source="lighthouse", data_kind="lab",
                                           lcp_ms=4800, cls=0.01, tbt_ms=50, rating="poor")


def _run(**kwargs):
    events = []
    result = audit_service._build_audit_result(
        "https://example.com/", FakeCrawler(), progress_callback=None,
        event_callback=lambda kind, payload: events.append((kind, payload)), **kwargs)
    return result, events


def test_measures_after_the_crawl_and_adds_issues():
    provider = StubProvider()
    result, events = _run(vitals_provider=provider)
    assert provider.calls == [("https://example.com/", "mobile")]
    assert result["web_vitals_status"] == "measured"
    assert result["web_vitals"][0]["lcp_ms"] == 4800
    codes = [i["code"] for i in result["page_issues_detail"]["https://example.com/"]]
    assert "CWV_LCP_POOR" in codes
    assert ("web_vitals", {"done": 1, "total": 1, "url": "https://example.com/"}) in events
    assert result["psi_metrics"] == {}          # only PSI-sourced pages are listed there
    with get_session_factory()() as session:
        rows = session.scalars(select(WebVital).where(WebVital.audit_id == result["audit_id"])).all()
        assert [r.lcp_ms for r in rows] == [4800.0]


def test_psi_results_are_mirrored_in_psi_metrics():
    provider = StubProvider(VitalsResult(url="https://example.com/", source="psi", data_kind="lab",
                                         performance_score=91, lcp_ms=1200, rating="good"))
    result, _ = _run(vitals_provider=provider)
    assert result["psi_metrics"]["https://example.com/"]["lcp_ms"] == 1200


def test_disabled_and_not_configured():
    provider = StubProvider()
    result, _ = _run(vitals_provider=provider, enable_web_vitals=False)
    assert provider.calls == [] and result["web_vitals_status"] == "disabled" and result["web_vitals"] == []
    result, _ = _run()
    assert result["web_vitals_status"] == "not_configured" and result["web_vitals"] == []


def test_a_crashing_provider_never_fails_the_audit():
    result, _ = _run(vitals_provider=StubProvider(raises=RuntimeError("boom")))
    assert result["web_vitals"][0]["error"] == "unexpected error (RuntimeError)"
    assert result["persisted"] is True


def test_the_page_limit_is_respected():
    provider = StubProvider()
    _run(vitals_provider=provider, vitals_max_pages=0)
    assert provider.calls == []
```

In `tests/test_pipeline_options.py`, replace `test_psi_is_never_called_without_a_key` and `test_psi_runs_for_successful_pages_when_a_key_is_given` with:

```python
def test_psi_is_never_called_without_a_key():
    """PageSpeed Insights is a quota'd Google API. With no key configured it
    must not be reached at all -- the same discipline the CSE rank checker has."""
    crawler = SpyCrawler()

    with patch("app.vitals.psi.requests.get") as mock_get:
        result = _run(crawler)

    mock_get.assert_not_called()
    assert result["psi_metrics"] == {}
    assert result["web_vitals_status"] == "not_configured"


def test_psi_runs_for_successful_pages_when_a_key_is_given():
    from app.vitals.model import VitalsResult
    from app.vitals.psi import PsiProvider

    crawler = SpyCrawler()
    measured = VitalsResult(url="https://example.com/", strategy="desktop", source="psi",
                            data_kind="lab", lcp_ms=1200)
    with patch.object(PsiProvider, "measure", return_value=measured) as mock_measure:
        result = _run(crawler, psi_key="test-key", psi_strategy="desktop")

    mock_measure.assert_called_once_with("https://example.com/", "desktop")
    assert result["psi_metrics"]["https://example.com/"]["lcp_ms"] == 1200
```

Add a CLI test to `tests/test_cli.py`. Read that file first: it shows how `_run_audit`/args are exercised. The test must assert that `--psi-max-pages 7` reaches `_build_audit_result` as `vitals_max_pages=7`, and that `--psi-key k` is still passed as `psi_key="k"`. Patch `audit_service._build_audit_result` and inspect its kwargs.

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_vitals_pipeline.py tests/test_pipeline_options.py tests/test_cli.py -q`
Expected: FAIL with `TypeError: _build_audit_result() got an unexpected keyword argument 'vitals_provider'`

- [ ] **Step 3: Implement in `audit_service.py`**

1. Imports: `from app.vitals.model import vitals_issues`, `from app.vitals.providers import build_vitals_provider`, `from app.vitals import runner as vitals_runner`.
2. `run_full_audit`: add the parameter `enable_web_vitals: bool = True` (after `trigger`) and pass `enable_web_vitals=enable_web_vitals` to `_build_audit_result`.
3. `_build_audit_result`: add the parameters `enable_web_vitals: bool = True, vitals_max_pages: Optional[int] = None, vitals_provider=None` after `trigger`.
4. Delete `psi_results: Dict[str, Any] = {}` and the whole `if psi_key and page.status_code == 200:` block, including its comment.
5. Right after `site_wide = analysis.build_link_graph_stats(crawler)`, insert:

```python
    # Core Web Vitals: once, after the crawl, for the pages that matter most
    # (internal PageRank). PSI is a quota'd Google API and Lighthouse runs a
    # Chrome, so this is never per page, and never fatal to the audit.
    provider = None
    if enable_web_vitals:
        provider = vitals_provider or build_vitals_provider(psi_key)
    web_vitals_status = "disabled" if not enable_web_vitals else ("measured" if provider else "not_configured")
    vitals_results = []
    if provider is not None:
        vitals_pages = vitals_runner.select_vitals_pages(
            getattr(crawler, "start_url", None) or url,
            site_wide.get("top_pages_by_importance") or [],
            crawler.results,
            config.PSI_MAX_PAGES if vitals_max_pages is None else vitals_max_pages,
        )

        def _vitals_progress(done: int, total: int, page_url: str) -> None:
            if event_callback:
                event_callback("web_vitals", {"done": done, "total": total, "url": page_url})

        vitals_results = vitals_runner.measure_pages(
            provider, vitals_pages, psi_strategy, on_progress=_vitals_progress)
        for measured in vitals_results:
            found = vitals_issues(measured)
            if found:
                all_page_issues.setdefault(measured.url, []).extend(found)
                db.add_issues(measured.url, found)
```

6. In `result_data`, replace `"psi_metrics": psi_results,` with:

```python
        "web_vitals": [r.to_dict() for r in vitals_results],
        "web_vitals_status": web_vitals_status,
        # Kept for readers of the pre-5.1 JSON: PSI-measured pages only.
        "psi_metrics": {r.url: {k: v for k, v in r.to_dict().items() if k != "url"}
                        for r in vitals_results if r.source == "psi" and not r.error},
```

7. Check `config` is imported in `audit_service.py` (it is used for `CRAWL_CONCURRENCY`). Run `grep -n "performance\." app/services/audit_service.py` to confirm other `performance.` uses remain, so the module import stays.

- [ ] **Step 4: Delete the old PSI client from `app/utils/performance.py`**

- Remove `PSI_ENDPOINT` and `fetch_psi_metrics`.
- Remove `import requests` if nothing else in the file uses it.
- Run `grep -rn "fetch_psi_metrics\|PSI_ENDPOINT" app tests`. Expected: matches only in `app/vitals/psi.py`.

- [ ] **Step 5: Request flag, routes, CLI**

`app/schemas/schemas.py`, in `AuditRequestParams` after `fresh`:

```python
    # Core Web Vitals for the top pages, when a source is configured
    # (PSI_API_KEY or LIGHTHOUSE_ENABLED). False skips them for this audit.
    enable_web_vitals: Optional[bool] = True
```

`app/api/routes.py`:
- In the `run_full_audit(` call, add `enable_web_vitals=params.enable_web_vitals is not False,`.
- In `event_callback`, change the tuple to `("link_progress", "redirect", "broken_link", "timeout", "web_vitals")`, and add the branch below before `elif event_type == "link_progress":`.

```python
            elif event_type == "web_vitals":
                msg = f"Measuring Core Web Vitals ({payload['done']}/{payload['total']})"
```

`app/cli.py`:
- After the `--psi-strategy` argument, add the code below.
- In `_run_audit`, pass `vitals_max_pages=args.psi_max_pages,` after `psi_strategy=args.psi_strategy,`.

```python
    p.add_argument("--psi-max-pages", type=int, default=None,
                   help="Pages to measure Core Web Vitals on (default: PSI_MAX_PAGES, 5)")
```

- [ ] **Step 6: Run and pass**

Run: `python -m pytest tests/test_vitals_pipeline.py tests/test_pipeline_options.py tests/test_cli.py -q`
Expected: all pass.

- [ ] **Step 7: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app apps/backend/tests
git commit -m "feat(vitals): measure Core Web Vitals once per audit (top pages), CLI --psi-max-pages"
```

---

### Task 7: Read API

**Files:**
- Create: `apps/backend/app/api/vitals.py`
- Modify: `apps/backend/app/main.py`
- Test: `apps/backend/tests/test_vitals_api.py`

**Interfaces:**
- Consumes: `WebVital`, `Audit`, `Project`, `as_utc`; `metric_ratings` (Task 1); `_factory` from `app.api.projects`.
- Produces:
  - `GET /api/audits/{id}/vitals` → `{audit_id, status, items: [row]}`
  - `GET /api/projects/{id}/vitals/trend?limit=` → `{url, points: [point]}`
  - row = the stored columns + `measured_at` + `metric_ratings`
  - point = `audit_id, finished_at, url, source, data_kind, performance_score, lcp_ms, inp_ms, cls, tbt_ms, rating, metric_ratings`

- [ ] **Step 1: Write the failing tests**

```python
"""Core Web Vitals over HTTP: one audit's pages, and the homepage trend."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.db.engine import get_session_factory
from app.db.models import Audit, Project, WebVital
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def _seed():
    t0 = datetime(2026, 10, 20, tzinfo=timezone.utc)
    with get_session_factory().begin() as s:
        project = Project(name="a.com", domain="a.com")
        s.add(project); s.flush()
        ids = []
        for i, lcp in enumerate([5000, None, 2000]):
            audit = Audit(project_id=project.id, session_id=f"s{i}", start_url="https://a.com/",
                          status="completed", trigger="manual", started_at=t0 + timedelta(days=i),
                          finished_at=t0 + timedelta(days=i), page_count=1,
                          summary_json={"web_vitals_status": "measured"})
            s.add(audit); s.flush(); ids.append(audit.id)
            if i == 1:
                s.add(WebVital(audit_id=audit.id, url="https://a.com/", strategy="mobile",
                               source="not_measured", error="timeout"))
                continue
            s.add(WebVital(audit_id=audit.id, url="https://a.com/", strategy="mobile", source="psi",
                           data_kind="lab", lcp_ms=lcp, cls=0.05, tbt_ms=100, performance_score=70 + i,
                           rating="poor" if lcp > 4000 else "good"))
            s.add(WebVital(audit_id=audit.id, url="https://a.com/b", strategy="mobile", source="psi",
                           data_kind="lab", lcp_ms=1000, rating="good"))
        return project.id, ids


def test_audit_vitals_lists_rows_with_metric_ratings(client):
    _, ids = _seed()
    body = client.get(f"/api/audits/{ids[0]}/vitals").json()
    assert body["audit_id"] == ids[0] and body["status"] == "measured"
    assert [r["url"] for r in body["items"]] == ["https://a.com/", "https://a.com/b"]
    assert body["items"][0]["metric_ratings"]["lcp_ms"] == "poor"
    assert body["items"][0]["measured_at"].endswith("+00:00")
    assert client.get("/api/audits/99999/vitals").status_code == 404


def test_trend_is_the_homepage_oldest_first_skipping_failures(client):
    project_id, ids = _seed()
    body = client.get(f"/api/projects/{project_id}/vitals/trend").json()
    assert body["url"] == "https://a.com/"
    assert [p["audit_id"] for p in body["points"]] == [ids[0], ids[2]]
    assert [p["lcp_ms"] for p in body["points"]] == [5000.0, 2000.0]
    assert body["points"][1]["metric_ratings"]["lcp_ms"] == "good"
    assert client.get("/api/projects/99999/vitals/trend").status_code == 404


def test_trend_for_a_project_without_measurements(client):
    with get_session_factory().begin() as s:
        project = Project(name="b.com", domain="b.com"); s.add(project); s.flush(); pid = project.id
    assert client.get(f"/api/projects/{pid}/vitals/trend").json() == {"url": None, "points": []}
```

- [ ] **Step 2: Run and watch them fail**

Run: `python -m pytest tests/test_vitals_api.py -q`
Expected: FAIL with 404 on both endpoints (no route yet).

- [ ] **Step 3: Implement `apps/backend/app/api/vitals.py`**

```python
"""Core Web Vitals read endpoints (Phase 5.1). Measuring happens inside
audits, so there is nothing to write here."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.api.projects import _factory
from app.db.models import Audit, Project, WebVital, as_utc
from app.vitals.model import metric_ratings

router = APIRouter()

_FIELDS = ("url", "strategy", "source", "data_kind", "rating", "performance_score",
           "lcp_ms", "inp_ms", "cls", "fcp_ms", "ttfb_ms", "tbt_ms", "error")


def _row_json(v: WebVital) -> Dict[str, Any]:
    return {**{f: getattr(v, f) for f in _FIELDS},
            "measured_at": as_utc(v.measured_at).isoformat() if v.measured_at else None,
            "metric_ratings": metric_ratings(v)}


@router.get("/audits/{audit_id}/vitals")
def audit_vitals(audit_id: int):
    with _factory()() as session:
        audit = session.get(Audit, audit_id)
        if audit is None:
            raise HTTPException(status_code=404, detail="audit not found")
        rows = session.scalars(select(WebVital).where(WebVital.audit_id == audit_id).order_by(WebVital.id)).all()
        status = (audit.summary_json or {}).get("web_vitals_status") or ("measured" if rows else "not_configured")
        return {"audit_id": audit_id, "status": status, "items": [_row_json(v) for v in rows]}


@router.get("/projects/{project_id}/vitals/trend")
def vitals_trend(project_id: int, limit: int = Query(30, ge=1, le=200)):
    """The homepage per audit, oldest first. The homepage is each audit's
    first measured row, because pages are measured start URL first. Audits
    whose homepage wasn't measured are skipped."""
    with _factory()() as session:
        if session.get(Project, project_id) is None:
            raise HTTPException(status_code=404, detail="project not found")
        audits = session.scalars(
            select(Audit).where(Audit.project_id == project_id)
            .order_by(Audit.finished_at.desc(), Audit.id.desc()).limit(limit)
        ).all()
        points = []
        for audit in reversed(audits):
            home = session.scalar(select(WebVital).where(WebVital.audit_id == audit.id)
                                  .order_by(WebVital.id).limit(1))
            if home is None or home.error:
                continue
            points.append({
                "audit_id": audit.id, "finished_at": as_utc(audit.finished_at).isoformat(),
                "url": home.url, "source": home.source, "data_kind": home.data_kind,
                "performance_score": home.performance_score, "lcp_ms": home.lcp_ms,
                "inp_ms": home.inp_ms, "cls": home.cls, "tbt_ms": home.tbt_ms,
                "rating": home.rating, "metric_ratings": metric_ratings(home),
            })
        return {"url": points[-1]["url"] if points else None, "points": points}
```

In `app/main.py`, after the keywords router lines:

```python
from app.api.vitals import router as vitals_router  # noqa: E402
app.include_router(vitals_router, prefix="/api")
```

- [ ] **Step 4: Run and pass**

Run: `python -m pytest tests/test_vitals_api.py -q`
Expected: all pass.

- [ ] **Step 5: Full suite, then commit**

```bash
python -m pytest -q
git add apps/backend/app/api/vitals.py apps/backend/app/main.py apps/backend/tests/test_vitals_api.py
git commit -m "feat(vitals): audit vitals and homepage trend endpoints"
```

---

### Task 8: Frontend: types, service, table and card, three pages

**Files:**
- Modify:
  - `packages/shared/src/types/platform.ts`
  - `packages/shared/src/types/index.ts`
  - `apps/frontend/services/platform.ts`
  - `apps/frontend/lib/platform-charts.ts`
  - `apps/frontend/lib/__tests__/platform-charts.test.ts`: read it first and add to it. If the file has a different name, use whichever test file imports `healthTrend`.
- Create: `apps/frontend/components/platform/vitals-table.tsx`, `apps/frontend/components/platform/vitals-card.tsx`
- Modify: `app/projects/[id]/page.tsx`, `app/projects/[id]/audits/page.tsx`, `app/dashboard/page.tsx`
- Tests:
  - `components/__tests__/vitals-table.test.tsx` (new)
  - `components/__tests__/vitals-card.test.tsx` (new)
  - `components/__tests__/project-overview.test.tsx`
  - `components/__tests__/site-audit-page.test.tsx`

**Interfaces:**
- Consumes: the Task 7 endpoints; the `web_vitals`/`web_vitals_status` audit result keys (Task 6).
- Produces:
  - Types `VitalsRating, VitalsStatus, VitalsRow, AuditVitals, VitalsTrendPoint, VitalsTrend`
  - `Platform.auditVitals(id)`, `Platform.vitalsTrend(id, limit?)`
  - `formatVitalsMetric(metric, value)`, `vitalsScoreTrend(points)`
  - `<RatingPill rating />`, `<VitalsTable rows status />`, `<VitalsCard projectId />`

- [ ] **Step 1: Types**

Append to `packages/shared/src/types/platform.ts`:

```ts
// Core Web Vitals (backend Phase 5.1).
export type VitalsRating = "good" | "needs_improvement" | "poor";
export type VitalsStatus = "measured" | "not_configured" | "disabled";
export type VitalsMetric = "lcp_ms" | "inp_ms" | "cls" | "tbt_ms";

export interface VitalsRow {
  url: string;
  strategy: string;
  source: "psi" | "lighthouse" | "not_measured";
  data_kind: "field" | "lab" | null;
  rating: VitalsRating | null;
  performance_score: number | null;
  lcp_ms: number | null;
  inp_ms: number | null;
  cls: number | null;
  fcp_ms: number | null;
  ttfb_ms: number | null;
  tbt_ms: number | null;
  error: string | null;
  measured_at?: string | null;
  metric_ratings: Record<VitalsMetric, VitalsRating | null>;
}

export interface AuditVitals { audit_id: number; status: VitalsStatus; items: VitalsRow[] }

export interface VitalsTrendPoint {
  audit_id: number;
  finished_at: string;
  url: string;
  source: VitalsRow["source"];
  data_kind: VitalsRow["data_kind"];
  performance_score: number | null;
  lcp_ms: number | null;
  inp_ms: number | null;
  cls: number | null;
  tbt_ms: number | null;
  rating: VitalsRating | null;
  metric_ratings: VitalsRow["metric_ratings"];
}

export interface VitalsTrend { url: string | null; points: VitalsTrendPoint[] }
```

In `packages/shared/src/types/index.ts`:
- Add `import type { VitalsRow, VitalsStatus } from "./platform";` at the top.
- Add these to `AuditResponse` after `persisted?: boolean;`:

```ts
  web_vitals?: VitalsRow[];
  web_vitals_status?: VitalsStatus;
```

- And add `enable_web_vitals?: boolean;` to `AuditRequestParams`.

- [ ] **Step 2: Service methods**

In `apps/frontend/services/platform.ts`:
- Add `AuditVitals, VitalsTrend` to the type import.
- Add these to the `Platform` object after `auditDiff`:

```ts
  auditVitals: (auditId: number) => request<AuditVitals>(`/audits/${auditId}/vitals`),
  vitalsTrend: (id: number, limit = 30) => request<VitalsTrend>(`/projects/${id}/vitals/trend?limit=${limit}`),
```

- [ ] **Step 3: Write the failing tests**

Add to the platform-charts test file:

```ts
import { formatVitalsMetric, vitalsScoreTrend } from "@/lib/platform-charts";

describe("Core Web Vitals helpers", () => {
  it("formats each metric in its own unit", () => {
    expect(formatVitalsMetric("lcp_ms", 4810)).toBe("4.8 s");
    expect(formatVitalsMetric("inp_ms", 182.4)).toBe("182 ms");
    expect(formatVitalsMetric("tbt_ms", 90)).toBe("90 ms");
    expect(formatVitalsMetric("cls", 0.123)).toBe("0.12");
    expect(formatVitalsMetric("lcp_ms", null)).toBe("—");
  });

  it("charts the performance score per audit, gaps as null", () => {
    const point = (id: number, score: number | null) => ({
      audit_id: id, finished_at: `2026-10-2${id}T10:00:00+00:00`, url: "u", source: "psi" as const,
      data_kind: "lab" as const, performance_score: score, lcp_ms: null, inp_ms: null, cls: null,
      tbt_ms: null, rating: null, metric_ratings: { lcp_ms: null, inp_ms: null, cls: null, tbt_ms: null },
    });
    const data = vitalsScoreTrend([point(1, 71), point(2, null)]);
    expect(data.map((d) => d.score)).toEqual([71, null]);
    expect(data[0].label).toBeTruthy();
  });
});
```

`components/__tests__/vitals-table.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { VitalsTable } from "@/components/platform/vitals-table";

const row = (over: object = {}) => ({
  url: "https://a.com/", strategy: "mobile", source: "lighthouse" as const, data_kind: "lab" as const,
  rating: "poor" as const, performance_score: 41, lcp_ms: 4800, inp_ms: null, cls: 0.12, fcp_ms: null,
  ttfb_ms: null, tbt_ms: 90, error: null,
  metric_ratings: { lcp_ms: "poor" as const, inp_ms: null, cls: "needs_improvement" as const, tbt_ms: "good" as const },
  ...over,
});

describe("VitalsTable", () => {
  it("shows values with text-labelled ratings and the data kind", () => {
    render(<VitalsTable rows={[row()]} status="measured" />);
    expect(screen.getByText("4.8 s")).toBeInTheDocument();
    expect(screen.getByText("Poor")).toBeInTheDocument();
    expect(screen.getByText("Needs improvement")).toBeInTheDocument();
    expect(screen.getByText("Good")).toBeInTheDocument();
    expect(screen.getByText(/lab · lighthouse/i)).toBeInTheDocument();
  });

  it("shows why a page was not measured", () => {
    render(<VitalsTable rows={[row({ source: "not_measured", error: "psi: daily cap of 50 psi calls reached" })]} status="measured" />);
    expect(screen.getByText(/daily cap of 50/)).toBeInTheDocument();
  });

  it("explains how to turn measurement on", () => {
    render(<VitalsTable rows={[]} status="not_configured" />);
    expect(screen.getByText(/PSI_API_KEY/)).toBeInTheDocument();
  });

  it("says when it was turned off for the audit", () => {
    render(<VitalsTable rows={[]} status="disabled" />);
    expect(screen.getByText(/turned off for this audit/i)).toBeInTheDocument();
  });
});
```

`components/__tests__/vitals-card.test.tsx`:

```tsx
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { VitalsCard } from "@/components/platform/vitals-card";
import { ApiError, Platform } from "@/services/platform";

const point = (id: number, over: object = {}) => ({
  audit_id: id, finished_at: `2026-10-2${id}T10:00:00+00:00`, url: "https://a.com/", source: "psi",
  data_kind: "lab", performance_score: 60 + id, lcp_ms: 4800, inp_ms: null, cls: 0.05, tbt_ms: 350,
  rating: "poor", metric_ratings: { lcp_ms: "poor", inp_ms: null, cls: "good", tbt_ms: "needs_improvement" },
  ...over,
});

beforeEach(() => vi.restoreAllMocks());

describe("VitalsCard", () => {
  it("shows the homepage's latest lab numbers with TBT in place of INP", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: "https://a.com/", points: [point(1), point(2)] } as any);
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByText("4.8 s")).toBeInTheDocument();
    expect(screen.getByText("TBT (lab)")).toBeInTheDocument();
    expect(screen.getByText("350 ms")).toBeInTheDocument();
    expect(screen.getByText(/lab data · psi/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /show as table/i }));
    expect(screen.getByRole("cell", { name: "62" })).toBeInTheDocument();
  });

  it("uses INP when the data is from real users", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: "https://a.com/", points: [
      point(1, { data_kind: "field", inp_ms: 180, metric_ratings: { lcp_ms: "poor", inp_ms: "good", cls: "good", tbt_ms: null } })] } as any);
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByText("INP")).toBeInTheDocument();
    expect(screen.getByText(/field data/i)).toBeInTheDocument();
  });

  it("explains how to start measuring when there is nothing yet", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: null, points: [] });
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByText(/not measured yet/i)).toBeInTheDocument();
  });

  it("offers a retry on error", async () => {
    vi.spyOn(Platform, "vitalsTrend").mockRejectedValue(new ApiError(503, "central database unavailable"));
    render(<VitalsCard projectId={7} />);
    expect(await screen.findByRole("button", { name: /retry/i })).toBeInTheDocument();
  });
});
```

In `components/__tests__/project-overview.test.tsx`, add this to `beforeEach`:

```ts
  vi.spyOn(Platform, "vitalsTrend").mockResolvedValue({ url: null, points: [] });
```

and this test to the describe block:

```tsx
  it("has a Core Web Vitals card", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(1, 72)], total: 1, offset: 0, limit: 50 } as any);
    render(<OverviewPage params={{ id: "7" }} />);
    expect(await screen.findByText("Core Web Vitals")).toBeInTheDocument();
    expect(Platform.vitalsTrend).toHaveBeenCalledWith(7);
  });
```

In `components/__tests__/site-audit-page.test.tsx`:
- Add `beforeEach(() => { vi.restoreAllMocks(); vi.spyOn(Platform, "auditVitals").mockResolvedValue({ audit_id: 3, status: "not_configured", items: [] }); });`, replacing the existing `beforeEach`.
- Add this test:

```tsx
  it("shows Core Web Vitals for the selected audit", async () => {
    vi.spyOn(Platform, "listAudits").mockResolvedValue({ items: [audit(3)], total: 1, offset: 0, limit: 50 } as any);
    render(<SiteAuditPage params={{ id: "7" }} />);
    expect(await screen.findByText(/PSI_API_KEY/)).toBeInTheDocument();
    expect(Platform.auditVitals).toHaveBeenCalledWith(3);
  });
```

- [ ] **Step 4: Run them and watch them fail**

Run: `cd apps/frontend && npx vitest run components/__tests__/vitals-table.test.tsx components/__tests__/vitals-card.test.tsx components/__tests__/project-overview.test.tsx components/__tests__/site-audit-page.test.tsx lib`
Expected: FAIL (modules not found, missing exports).

- [ ] **Step 5: Chart helpers** (append to `apps/frontend/lib/platform-charts.ts`)

```ts
import type { VitalsMetric, VitalsTrendPoint } from "@seo-auditor/shared";

/** One Core Web Vitals value in its own unit; "—" when missing. */
export function formatVitalsMetric(metric: VitalsMetric, value: number | null | undefined): string {
  if (value == null) return "—";
  if (metric === "cls") return value.toFixed(2);
  if (metric === "lcp_ms") return `${(value / 1000).toFixed(1)} s`;
  return `${Math.round(value)} ms`;
}

/** The homepage's performance score per audit. A missing score is a gap, not 0. */
export function vitalsScoreTrend(points: VitalsTrendPoint[]) {
  return points.map((p) => ({
    label: new Date(p.finished_at).toLocaleDateString(undefined, { month: "short", day: "numeric" }),
    score: p.performance_score,
  }));
}
```

If `platform-charts.ts` already has an `import type ... from "@seo-auditor/shared"` line, merge these names into it.

- [ ] **Step 6: `components/platform/vitals-table.tsx`**

```tsx
import { AlertTriangle, CheckCircle2, XCircle } from "lucide-react";
import type { VitalsRating, VitalsRow, VitalsStatus } from "@seo-auditor/shared";

import { formatVitalsMetric } from "@/lib/platform-charts";

const PILL: Record<VitalsRating, { label: string; className: string; Icon: typeof CheckCircle2 }> = {
  good: { label: "Good", Icon: CheckCircle2, className: "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-400" },
  needs_improvement: { label: "Needs improvement", Icon: AlertTriangle, className: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950 dark:text-amber-400" },
  poor: { label: "Poor", Icon: XCircle, className: "border-rose-200 bg-rose-50 text-rose-700 dark:border-rose-900 dark:bg-rose-950 dark:text-rose-400" },
};

/** A rating as icon + text, never color alone. */
export function RatingPill({ rating }: { rating: VitalsRating | null }) {
  if (!rating) return null;
  const { label, className, Icon } = PILL[rating];
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}>
      <Icon className="h-3 w-3" aria-hidden />{label}
    </span>
  );
}

export const VITALS_NOT_CONFIGURED =
  "Core Web Vitals not measured. Set PSI_API_KEY or LIGHTHOUSE_ENABLED=true on the backend.";

function Metric({ row, metric }: { row: VitalsRow; metric: "lcp_ms" | "inp_ms" | "cls" | "tbt_ms" }) {
  const value = row[metric];
  if (value == null) return <span className="text-muted-foreground">—</span>;
  return (
    <span className="flex flex-wrap items-center gap-1.5 tabular-nums">
      {formatVitalsMetric(metric, value)} <RatingPill rating={row.metric_ratings[metric]} />
    </span>
  );
}

export function VitalsTable({ rows, status }: { rows: VitalsRow[]; status: VitalsStatus }) {
  if (status === "not_configured") return <p className="text-sm text-muted-foreground">{VITALS_NOT_CONFIGURED}</p>;
  if (status === "disabled") return <p className="text-sm text-muted-foreground">Core Web Vitals were turned off for this audit.</p>;
  if (rows.length === 0) return <p className="text-sm text-muted-foreground">No pages were measured.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-[13px]">
        <thead className="text-left text-xs text-muted-foreground">
          <tr className="border-b">
            <th className="sticky left-0 bg-card py-2 pr-4 font-medium">Page</th>
            <th className="py-2 pr-4 font-medium">Score</th>
            <th className="py-2 pr-4 font-medium">LCP</th>
            <th className="py-2 pr-4 font-medium">INP</th>
            <th className="py-2 pr-4 font-medium">CLS</th>
            <th className="py-2 pr-4 font-medium">TBT (lab)</th>
            <th className="py-2 font-medium">Data</th>
          </tr>
        </thead>
        <tbody className="divide-y">
          {rows.map((r) => (
            <tr key={r.url} className="align-top">
              <td className="sticky left-0 max-w-[260px] break-all bg-card py-2 pr-4">{r.url}</td>
              {r.error ? (
                <td colSpan={6} className="py-2 text-muted-foreground">Not measured: {r.error}</td>
              ) : (
                <>
                  <td className="py-2 pr-4 tabular-nums">{r.performance_score ?? "—"}</td>
                  <td className="py-2 pr-4"><Metric row={r} metric="lcp_ms" /></td>
                  <td className="py-2 pr-4"><Metric row={r} metric="inp_ms" /></td>
                  <td className="py-2 pr-4"><Metric row={r} metric="cls" /></td>
                  <td className="py-2 pr-4"><Metric row={r} metric="tbt_ms" /></td>
                  <td className="py-2 text-muted-foreground">{r.data_kind} · {r.source}</td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 7: `components/platform/vitals-card.tsx`**

```tsx
"use client";

import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { VitalsMetric } from "@seo-auditor/shared";

import { AsyncState } from "@/components/platform/async-state";
import { RatingPill, VITALS_NOT_CONFIGURED } from "@/components/platform/vitals-table";
import { formatVitalsMetric, SERIES_LIGHT, vitalsScoreTrend } from "@/lib/platform-charts";
import { useApi } from "@/lib/use-api";
import { Platform } from "@/services/platform";

/** The homepage's latest Core Web Vitals and its performance score over time. */
export function VitalsCard({ projectId }: { projectId: number }) {
  const trend = useApi(() => Platform.vitalsTrend(projectId), [projectId]);
  const [asTable, setAsTable] = useState(false);

  return (
    <section className="rounded-[18px] border bg-card p-5">
      <h2 className="mb-1 font-semibold tracking-tight">Core Web Vitals</h2>
      <AsyncState
        state={trend}
        isEmpty={(d) => d.points.length === 0}
        emptyTitle="Core Web Vitals not measured yet"
        emptyText={VITALS_NOT_CONFIGURED.replace("Core Web Vitals not measured. ", "") + " Then run an audit."}
      >
        {(d) => {
          const latest = d.points[d.points.length - 1];
          const responsiveness: VitalsMetric = latest.data_kind === "field" ? "inp_ms" : "tbt_ms";
          const tiles: { metric: VitalsMetric; label: string }[] = [
            { metric: "lcp_ms", label: "LCP" },
            { metric: responsiveness, label: responsiveness === "inp_ms" ? "INP" : "TBT (lab)" },
            { metric: "cls", label: "CLS" },
          ];
          const data = vitalsScoreTrend(d.points);
          return (
            <div className="space-y-4">
              <p className="break-all text-xs text-muted-foreground">
                {d.url} · {latest.data_kind === "field" ? "Field data" : "Lab data"} · {latest.source}
              </p>
              <div className="grid gap-3 sm:grid-cols-3">
                {tiles.map((t) => (
                  <div key={t.metric} className="rounded-xl border p-3">
                    <p className="text-xs text-muted-foreground">{t.label}</p>
                    <p className="text-lg font-semibold tabular-nums tracking-tight">{formatVitalsMetric(t.metric, latest[t.metric])}</p>
                    <RatingPill rating={latest.metric_ratings[t.metric]} />
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between">
                <p className="text-xs text-muted-foreground">Performance score per audit</p>
                <button type="button" onClick={() => setAsTable((v) => !v)}
                        className="rounded-full border px-3 py-1 text-xs active:scale-95">
                  {asTable ? "Show as chart" : "Show as table"}
                </button>
              </div>
              {asTable ? (
                <table className="w-full text-[13px]">
                  <thead className="text-left text-xs text-muted-foreground"><tr><th className="py-1">Audit</th><th className="py-1">Score</th></tr></thead>
                  <tbody>{data.map((p, i) => <tr key={d.points[i].audit_id}><td className="py-1">{p.label}</td><td className="py-1 tabular-nums">{p.score ?? "—"}</td></tr>)}</tbody>
                </table>
              ) : (
                <div className="h-40 w-full" role="img" aria-label="Performance score over time">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
                      <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                      <XAxis dataKey="label" tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
                      <YAxis domain={[0, 100]} tick={{ fontSize: 12, fill: "hsl(var(--muted-foreground))" }} tickLine={false} axisLine={false} />
                      <Tooltip contentStyle={{ borderRadius: 12, border: "1px solid hsl(var(--border))", fontSize: 12 }} />
                      <Line type="monotone" dataKey="score" name="Performance" stroke={SERIES_LIGHT[0]} strokeWidth={2}
                            dot={{ r: 4 }} activeDot={{ r: 5 }} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          );
        }}
      </AsyncState>
    </section>
  );
}
```

Check `AsyncState`'s props in `components/platform/async-state.tsx` (`isEmpty`, `emptyTitle`, `emptyText`, children as a function of data). If any prop name differs, use the real one.

- [ ] **Step 8: Wire into the pages**

`app/projects/[id]/page.tsx`:
- Import `VitalsCard`.
- Insert this right after the "Health over time" `</section>`:

```tsx
          <VitalsCard projectId={projectId} />
```

`app/projects/[id]/audits/page.tsx`:
- Import `VitalsTable`.
- Add this after the `diff` hook:

```tsx
  const vitals = useApi(selected !== null ? () => Platform.auditVitals(selected) : null, [selected]);
```

- Insert this immediately after the history table's closing `</div>`, before `{items.length < 2 ? (`:

```tsx
            <section className="rounded-[18px] border bg-card p-5">
              <h2 className="mb-3 font-semibold tracking-tight">Core Web Vitals</h2>
              <AsyncState state={vitals}>{(v) => <VitalsTable rows={v.items} status={v.status} />}</AsyncState>
            </section>
```

`app/dashboard/page.tsx`:
- Add `import { VitalsTable } from "@/components/platform/vitals-table";`.
- Replace the `"performance": <PerformancePanel pages={pages} />,` entry with:

```tsx
    "performance": (
      <div className="space-y-4">
        {auditData.web_vitals_status && (
          <Card><CardHeader className="pb-3"><CardTitle className="text-base">Core Web Vitals</CardTitle></CardHeader>
            <CardContent><VitalsTable rows={auditData.web_vitals ?? []} status={auditData.web_vitals_status} /></CardContent></Card>
        )}
        <PerformancePanel pages={pages} />
      </div>
    ),
```

- [ ] **Step 9: Run and pass**

Run: `npx vitest run && npx tsc --noEmit`
Expected: all pass, and `tsc` is clean.

- [ ] **Step 10: Backend suite, then commit**

```bash
(cd ../backend && python -m pytest -q)
git add packages/shared apps/frontend
git commit -m "feat(frontend): Core Web Vitals card, per-page table on Site Audit and report"
```

---

### Task 9: Docs, env, live verification

**Files:**
- Modify: `apps/backend/.env.example`, `deploy/oracle/docker-compose.yml`, `docs/env.md`, `docs/api.md`, `README.md`

- [ ] **Step 1: Env and compose**

In `apps/backend/.env.example`, after the `GOOGLE_CSE_DAILY_QUOTA` line (or at the end if it isn't there), add:

```
# Core Web Vitals. PageSpeed Insights key (free, quota'd); empty = not used.
PSI_API_KEY=
# Hard daily cap on PSI calls, and pages measured per audit.
PSI_DAILY_CAP=50
PSI_MAX_PAGES=5
# Local Lighthouse fallback: needs Node, Chrome and `npm i -g lighthouse@12`.
LIGHTHOUSE_ENABLED=false
# Optional: Chrome binary and Lighthouse CLI script (auto-detected when empty).
CHROME_PATH=
LIGHTHOUSE_CLI=
```

In `deploy/oracle/docker-compose.yml`, after the `DATAFORSEO_LABS_DAILY_CAP` line, add the lines below. Lighthouse stays off on the VM until sub-project 2 adds Chromium.

```yaml
      PSI_API_KEY: ${PSI_API_KEY:-}
      PSI_DAILY_CAP: ${PSI_DAILY_CAP:-50}
      PSI_MAX_PAGES: ${PSI_MAX_PAGES:-5}
```

In `docs/env.md`, add these rows after `DATAFORSEO_LABS_DAILY_CAP`:

```
| `PSI_API_KEY` | Google PageSpeed Insights key for Core Web Vitals. Empty = PSI not used | `""` |
| `PSI_DAILY_CAP` | Hard daily cap on PSI calls | `50` |
| `PSI_MAX_PAGES` | Pages measured per audit (start URL + top pages by internal PageRank) | `5` |
| `LIGHTHOUSE_ENABLED` | Local Lighthouse fallback (needs Node, Chrome, `npm i -g lighthouse@12`) | `false` |
| `CHROME_PATH` | Chrome binary for Lighthouse; auto-detected when empty | `""` |
| `LIGHTHOUSE_CLI` | Path to Lighthouse's `cli/index.js`; found via `npm root -g` when empty | `""` |
```

- [ ] **Step 2: `docs/api.md`**

Append:

```markdown
---

## Core Web Vitals

Each audit measures the start URL plus the top pages by internal PageRank (up to
`PSI_MAX_PAGES`, mobile). It uses PageSpeed Insights when `PSI_API_KEY` is set,
and local Lighthouse when `LIGHTHOUSE_ENABLED=true`. Page-level field data
(real Chrome users) is used for the rating when Google has it, otherwise lab
data. Lab data has no INP, so TBT stands in for it. Poor values add
`CWV_*_POOR` warnings, and values that need improvement add `CWV_*_NEEDS_IMPROVEMENT` info issues.

The audit result carries `web_vitals` (one object per page),
`web_vitals_status` (`measured`, `not_configured` or `disabled`), and
`psi_metrics` (PSI-measured pages, for older readers). `POST /api/audit`
accepts `"enable_web_vitals": false` to skip measuring.

### `GET /api/audits/{id}/vitals`

{"audit_id": 12, "status": "measured", "items": [{"url": "https://a.com/", "source": "psi",
 "data_kind": "field", "performance_score": 71, "lcp_ms": 2300, "inp_ms": 180, "cls": 0.05,
 "fcp_ms": 1200, "ttfb_ms": 600, "tbt_ms": 350, "rating": "good", "error": null,
 "metric_ratings": {"lcp_ms": "good", "inp_ms": "good", "cls": "good", "tbt_ms": "needs_improvement"}}]}

### `GET /api/projects/{id}/vitals/trend?limit=30`

The homepage per audit, oldest first. Audits whose homepage wasn't measured are skipped.
`{"url": "https://a.com/", "points": [{"audit_id": 12, "finished_at": "...", "performance_score": 71, ...}]}`
```

Wrap both JSON examples in fenced `json` code blocks in the real file.

- [ ] **Step 3: README**

Append a section titled **"Core Web Vitals (Phase 5.1)"**. It should cover:
- what is measured and where it shows (Overview card, Site Audit tab, report "Performance" tab)
- the env vars
- the CLI flags `--psi-key` and `--psi-max-pages`
- a **How to verify (no money spent)** subsection:

```bash
cd apps/backend
python -m pytest tests/test_vitals_rating.py tests/test_vitals_psi.py tests/test_vitals_lighthouse.py \
  tests/test_vitals_runner.py tests/test_vitals_storage.py tests/test_vitals_pipeline.py tests/test_vitals_api.py -q

# Local Lighthouse (one-time install, ~30MB from npm; uses your installed Chrome)
npm i -g lighthouse@12
export LIGHTHOUSE_ENABLED=true SESSION_DIR=/tmp/seo-cwv
python -m app.cli https://books.toscrape.com/ --max-pages 10 --skip-external-links --psi-max-pages 2 --json \
  | python -c "import sys,json; d=json.load(sys.stdin); print(d['web_vitals_status']); [print(v['url'], v['source'], v['lcp_ms'], v['rating'], v['error']) for v in d['web_vitals']]"
```

Expected: `measured`, then two lines with `lighthouse`, an LCP in ms, and a rating. Then start the backend and frontend as in the Phase 4 section, open the project's Overview, and check the Core Web Vitals card.

- [ ] **Step 4: Live check (ask the owner first)**

Ask before running `npm i -g lighthouse@12`, because it downloads from npm. Run the README commands against a scratch `SESSION_DIR`. Then run the app in Chrome and check, at 1440px and 390px:
- the Overview card
- the Site Audit CWV table
- the report's Performance tab

Fix anything found, with a test when it's behaviour. Don't use PSI until the owner gives a key and OKs the first live call.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/.env.example deploy/oracle/docker-compose.yml docs/env.md docs/api.md README.md
git commit -m "docs: Core Web Vitals env, API and verification"
```
