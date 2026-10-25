# Phase 5.1: Core Web Vitals (PSI + Lighthouse fallback) — Design

**Date:** 2026-10-25
**Status:** Approved, pending implementation plan
**Branch:** `feat/complete-site-audit`
**Brief:** `BUILD_PROMPT.md` Phase 5, item 2. This is the first of five Phase 5
sub-projects, in this order: Core Web Vitals → Playwright rendering → axe-core
→ custom rules → Search Console. Each has its own spec, plan and review stop.

## Problem

`app/utils/performance.py` `fetch_psi_metrics` exists, but only the CLI calls
it (`--psi-key`), and it runs once **per crawled page** (10–30 s each). The
API and UI never measure Core Web Vitals. Results live only in the session
JSON (`psi_metrics`), with no UI, no central DB rows and no history. There is
no fallback when no key is set.

## Decisions taken

- **Pages measured:** the start URL plus the top pages by internal PageRank, up
  to `PSI_MAX_PAGES` (default 5), mobile only.
- **Fallback:** local Lighthouse, opt-in (`LIGHTHOUSE_ENABLED=true`). Docker
  image changes wait for sub-project 2 (Playwright), which adds Chromium, so
  the image changes once.
- **CLI:** `--psi-key` keeps working. The CLI now measures the top 5 pages, not
  every page, and `--psi-max-pages N` restores a larger set.

## Design

### 1. Provider layer: `app/vitals/`

Same pattern as `app/providers/` (SERP, keywords): an interface, concrete
providers, and a factory read from env.

```python
@dataclass
class VitalsResult:
    url: str
    strategy: str                 # "mobile"
    source: str                   # "psi" | "lighthouse" | "not_measured"
    data_kind: Optional[str]      # "field" | "lab" (which data the rating used)
    performance_score: Optional[float]   # 0-100, lab
    lcp_ms: Optional[float]; inp_ms: Optional[float]; cls: Optional[float]
    fcp_ms: Optional[float]; ttfb_ms: Optional[float]; tbt_ms: Optional[float]
    rating: Optional[str]         # "good" | "needs_improvement" | "poor"
    error: Optional[str]

class VitalsProvider(Protocol):
    name: str
    def measure(self, url: str, strategy: str = "mobile") -> VitalsResult: ...
```

- **`PsiProvider(api_key, cap)`** calls the PSI v5 endpoint and parses **raw
  numbers** (`numericValue`, field `percentile`), not display strings. Field
  CLS percentiles arrive ×100 and are divided back. Every call first goes
  through `app.providers.spend.reserve("psi", PSI_DAILY_CAP)`, and a cap hit
  becomes `error="daily cap of N psi calls reached"`. Timeout 60 s. A non-200
  response becomes an error carrying the status and the start of the body
  (the key is never echoed).
- **`LighthouseProvider(chrome_path)`** runs `npx --yes lighthouse@12 <url>
  --output=json --output-path=stdout --only-categories=performance
  --chrome-flags="--headless=new --no-sandbox" --quiet` via `subprocess.run`
  with a list argv (no shell) and a 90 s timeout. `CHROME_PATH` is passed in
  the environment. It is lab only: TBT stands in for INP and is labelled.
- **`FallbackChain([psi, lighthouse])`** returns the first result without
  `error`. If every provider fails, the result is `source="not_measured"` with
  the joined reasons.
- **`build_vitals_provider(env)`**:
  - Uses PSI if `PSI_API_KEY` is set, and Lighthouse if `LIGHTHOUSE_ENABLED`
    is true and Chrome is found (`CHROME_PATH`, else the usual Windows, macOS
    and Linux install paths).
  - Returns `None` when neither is available.
  - The CLI's `--psi-key` overrides `PSI_API_KEY`.

### 2. Rating

Google's thresholds (good / poor boundary):

| Metric | Good ≤ | Poor > |
| --- | --- | --- |
| LCP | 2500 ms | 4000 ms |
| INP | 200 ms | 500 ms |
| CLS | 0.1 | 0.25 |
| TBT (lab stand-in for INP) | 200 ms | 600 ms |

- **Field data first:** if PSI returns field data (CrUX) for the page, the
  rating uses LCP, INP and CLS from it (`data_kind="field"`). Otherwise it uses
  lab LCP, TBT and CLS (`data_kind="lab"`).
- **Page rating:** the worst of its metrics. A missing metric is ignored.
- **Issues** (added to that page's issues, so they feed the health score):
  - `CWV_LCP_POOR`, `CWV_INP_POOR`, `CWV_CLS_POOR` (`warning`)
  - `CWV_LCP_NEEDS_IMPROVEMENT` etc. (`info`)
  - The message names the value, the threshold and field/lab, e.g. "LCP
    4.8 s (lab) — poor, over 4.0 s".

### 3. Page selection and audit integration

- The current per-page call in `_build_audit_result` is removed.
- After the crawl and `build_link_graph_stats`, `select_vitals_pages(start_url,
  top_pages_by_importance, pages, limit)` picks:
  - the start URL (or its final redirect target)
  - then pages by PageRank score
  - and when PageRank is empty, the shallowest pages
  - status-200 HTML pages only, deduplicated, up to `limit`
- Measurement runs in a `ThreadPoolExecutor(max_workers=3)`.
  `progress_callback` reports "Measuring Core Web Vitals (i/n)".
- `AuditRequestParams.enable_web_vitals: Optional[bool] = True`. Nothing runs
  when it is false or no provider is configured.
- **Result JSON:**
  - `web_vitals: [VitalsResult…]`
  - `psi_metrics` is kept (url → metrics dict, PSI-sourced pages only) for
    existing readers
  - `web_vitals_status`: `"measured" | "not_configured" | "disabled"`
- **CWV never fails the audit:** any exception becomes a per-page error.

### 4. Storage

Migration `0004_web_vitals` adds the table `web_vitals`:

| Column | Type |
| --- | --- |
| `id` | int PK |
| `audit_id` | FK `audits.id`, `ON DELETE CASCADE`, indexed |
| `url` | text |
| `strategy`, `source`, `data_kind`, `rating` | string |
| `performance_score`, `lcp_ms`, `inp_ms`, `cls`, `fcp_ms`, `ttfb_ms`, `tbt_ms` | float, nullable |
| `error` | text, nullable |
| `measured_at` | UTC datetime |

`audit_store.record_audit` inserts the rows in the same transaction as the
audit.

### 5. API

- `GET /api/audits/{id}/vitals` → `{audit_id, status, items: [VitalsRow]}`.
  Returns 404 for an unknown audit.
- `GET /api/projects/{id}/vitals/trend?limit=30` → `{url, points: [{audit_id,
  finished_at, source, data_kind, performance_score, lcp_ms, inp_ms, cls,
  tbt_ms, rating}]}`. It covers the project's homepage (the measured start
  URL), oldest first, and skips audits without a homepage row. Returns 404 for
  an unknown project.

### 6. UI

- **Shared types** in `packages/shared/src/types/platform.ts`:
  `VitalsRow`, `AuditVitals`, `VitalsTrend`. Plus `Platform.auditVitals`
  and `Platform.vitalsTrend`.
- **`components/platform/vitals-card.tsx`** (Overview):
  - LCP, INP (or "TBT (lab)"), CLS and score for the homepage's latest
    measurement
  - each metric with a rating pill: good / needs improvement / poor, icon +
    label, emerald/amber/rose
  - a "field" or "lab" tag, and the source
  - a small trend line of the performance score, with a table toggle
- **Site Audit tab:** a per-page CWV table for the selected (newest) audit.
- **Existing `/dashboard`:** a compact "Core Web Vitals" section when
  `web_vitals` is in the result.
- **Not configured:** "Core Web Vitals not measured. Set `PSI_API_KEY` or
  `LIGHTHOUSE_ENABLED=true` on the backend."

### 7. Configuration

| Env | Default | Meaning |
| --- | --- | --- |
| `PSI_API_KEY` | empty | Google PageSpeed Insights key |
| `PSI_DAILY_CAP` | `50` | Hard daily cap on PSI calls |
| `PSI_MAX_PAGES` | `5` | Pages measured per audit |
| `LIGHTHOUSE_ENABLED` | `false` | Local Lighthouse fallback |
| `CHROME_PATH` | empty | Chrome/Chromium binary for Lighthouse (auto-detected if empty) |

These go into `.env.example`, `docs/env.md` and the docker-compose env.

## Error handling

| Case | Result |
| --- | --- |
| No provider configured | `web_vitals_status="not_configured"`, no rows, UI hint |
| PSI 4xx/5xx/timeout | Lighthouse if enabled, else a `not_measured` row with the reason |
| PSI daily cap reached | Same as above, reason "daily cap of N psi calls reached" |
| Lighthouse missing/crash/timeout | `not_measured` row with the reason |
| Any unexpected exception | Caught per page. The audit still completes |

## Testing

- **Parsers:** recorded PSI JSON (field + lab, lab only, error) and Lighthouse
  JSON fixtures → `VitalsResult`.
- **Rating:** the boundaries of every threshold, field preferred over lab, a
  missing metric ignored, and the issue codes and severities.
- **`select_vitals_pages`:** start URL first, PageRank order, the
  shallowest-page fallback, non-200 skipped, dedupe, limit.
- **`FallbackChain`:** order, the PSI error falling through, all failing.
- **PSI cap:** `reserve` is consulted, and a cap hit makes no HTTP call.
- **Lighthouse:** argv has no shell, the timeout is handled, and
  `subprocess.run` is mocked.
- **Audit integration:** fake provider → `web_vitals` in the result, issues
  added, rows in the DB, and the two endpoints. `enable_web_vitals=false` and
  no provider → no calls.
- **CLI:** `--psi-key` and `--psi-max-pages` reach the provider. The JSON still
  has `psi_metrics`.
- **Frontend:** the card (data, lab label, not configured, loading, error) and
  the Site Audit table.
- **No real network in tests.**

## Done when

- An audit with `LIGHTHOUSE_ENABLED=true` (local Chrome) stores and shows CWV
  for up to 5 pages.
- With a PSI key (after the owner's OK for the first live call), PSI is used
  first.
- Without either, everything behaves as before, plus a "not measured" hint.
- All tests pass, and the docs and env example are updated.

## Out of scope

- Desktop strategy, per-project page lists, CrUX origin-level data.
- Docker image changes (sub-project 2).
