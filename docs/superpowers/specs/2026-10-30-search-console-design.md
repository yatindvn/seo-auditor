# Phase 5.5: Google Search Console — Design

**Date:** 2026-10-30
**Status:** Approved, pending implementation plan
**Branch:** `feat/complete-site-audit`
**Brief:** `BUILD_PROMPT.md` Phase 5, item 5: "Google Search Console
integration for indexing, clicks, impressions." Last of five Phase 5
sub-projects (5.1–5.4 are merged).

## Problem

The platform knows what the crawler sees, but not what Google does with the
site: which pages are indexed, and which get clicks and impressions for which
queries. Without that, fixes can't be prioritised by real search traffic, and
"not indexed" problems go unnoticed.

## Decisions taken

- **Auth:** a Google Cloud service account. Its JSON key is read from
  `GSC_SERVICE_ACCOUNT_FILE`. The user adds the service account's email as a
  user on each Search Console property. Scope:
  `https://www.googleapis.com/auth/webmasters.readonly`. No OAuth flow.
- **Scope:** Performance (a daily sync of totals, top pages and top queries),
  index status (URL Inspection of sampled pages during audits), and joining
  traffic into audits. Sitemaps are out.
- **Provider interface** with a dry-run implementation (`GSC_DRY_RUN=true`).
  The first live call waits for the owner's OK.

## Design

### 1. Provider: `app/gsc/`

```python
@dataclass(frozen=True)
class SiteEntry:      site_url: str; permission: str
@dataclass(frozen=True)
class AnalyticsRow:   keys: Tuple[str, ...]; clicks: float; impressions: float; ctr: float; position: float
@dataclass
class Inspection:     url: str; verdict: Optional[str]; coverage_state: Optional[str]; indexing_state: Optional[str]
                      robots_state: Optional[str]; fetch_state: Optional[str]; google_canonical: Optional[str]
                      user_canonical: Optional[str]; last_crawl: Optional[str]; error: Optional[str] = None

class GscProvider(Protocol):
    name: str; dry_run: bool
    def sites(self) -> List[SiteEntry]
    def search_analytics(self, site_url, start: date, end: date, dimensions: List[str], row_limit: int = 1000) -> List[AnalyticsRow]
    def inspect(self, site_url: str, url: str) -> Inspection
```

- **`ServiceAccountGsc(key_file)`** uses `google.oauth2.service_account` with
  `google.auth.transport.requests.AuthorizedSession`:
  - `GET https://www.googleapis.com/webmasters/v3/sites` → `siteEntry[]`
  - `POST https://www.googleapis.com/webmasters/v3/sites/{quote(site_url, safe='')}/searchAnalytics/query`
    with `{startDate, endDate, dimensions, rowLimit}` → `rows[]`
  - `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`
    with `{inspectionUrl, siteUrl}` → `inspectionResult.indexStatusResult`
  - Each analytics call reserves `gsc` under `GSC_DAILY_CAP` (default 100).
    Each inspection reserves `gsc_inspect` under `GSC_INSPECT_DAILY_CAP`
    (default 200). Both use the existing `reserve()`.
  - A non-2xx response raises `GscError(status, google_message)`. A 403
    becomes "the service account has no access to this property". The key
    file's contents never appear in errors or logs.
- **`DryRunGsc`:** deterministic data seeded by the property, with sites
  matching any requested domain. Analytics give plausible daily totals,
  pages under the domain and queries. Inspections are mostly PASS, with one
  "Crawled - currently not indexed". It sets `dry_run=True`.
- **`build_gsc_provider()`:**
  - `GSC_DRY_RUN=true` → `DryRunGsc`
  - else `GSC_SERVICE_ACCOUNT_FILE` set and the file exists → `ServiceAccountGsc`
  - else `None` (not configured)
- **Dependency:** `google-auth>=2.20` in `requirements.txt`.

### 2. Storage (migration `0008_search_console`)

- `projects` gains `gsc_property` (string 255, nullable) and
  `last_gsc_sync_at` (UTC datetime, nullable).
- `gsc_daily`: `id, project_id (FK cascade, indexed), date (Date),
  clicks, impressions, ctr, position (float), dry_run (bool)`, unique on
  `(project_id, date)`.
- `gsc_pages`: `id, project_id, url, clicks, impressions, ctr, position,
  synced_at, dry_run`. The rows for a project are replaced on each sync.
- `gsc_queries`: `id, project_id, query, clicks, impressions, ctr, position,
  synced_at, dry_run`. Also replaced on each sync.
- `gsc_inspections`: `id, audit_id (FK cascade, indexed), url, verdict,
  coverage_state, indexing_state, robots_state, fetch_state,
  google_canonical, user_canonical, last_crawl, error, dry_run`.

### 3. Property matching and sync: `app/gsc/sync.py`

- **`match_property(domain, sites) -> Optional[str]`:**
  - `sc-domain:<domain>` first
  - then a URL-prefix property whose `project_domain(site_url) == domain`,
    preferring `https://`, then `www.`
  - only permission levels other than `siteUnverifiedUser`
- **`sync_project(project_id, provider, today=None) -> SyncResult`:**
  - It resolves `gsc_property` (matching and saving it if empty). With no
    match it returns `status="no_access"` and the service account's site
    list size.
  - **Three analytics calls**, all ending at `today − 2 days` (GSC lag):
    - `dimensions=["date"]` over 90 days → upsert `gsc_daily`
    - `["page"]` over 28 days, up to 1,000 rows → replace `gsc_pages`
    - `["query"]` over 28 days, up to 1,000 rows → replace `gsc_queries`
  - It sets `last_gsc_sync_at` and returns
    `{status: "synced"|"no_access"|"not_configured", property, days, pages, queries, dry_run}`.
  - A `GscError` or cap hit becomes `status="error"` with the message.
    Partial writes are avoided: all three calls finish before one write
    transaction.
- **Scheduler:** `run_due_gsc_syncs(now)`, every 60 minutes, for projects
  with `last_gsc_sync_at` older than 24 h (or never), when a provider is
  configured. A failure on one project doesn't stop the others.

### 4. Index status during audits

- In `_build_audit_result`, after the browser pass:
  - It runs when a provider is configured, `enable_gsc` is not false, and
    the project (by `project_domain(url)`) has or can match a property.
  - It picks pages with `select_pages(start_page, top_pages, results,
    GSC_INSPECT_MAX_PAGES)` (default 20) and inspects them sequentially. A
    cap hit stops further inspections, and the rest are recorded with that
    error.
- **Issues:**
  - `GSC_NOT_INDEXED` (warning) when the verdict is `FAIL` or `NEUTRAL` and
    the page's own meta robots or X-Robots-Tag doesn't contain `noindex`.
    Message: "Not indexed by Google: {coverage_state}".
  - `GSC_CANONICAL_MISMATCH` (info) when both canonicals are present and
    differ after `normalize_url`. Message: "Google chose {google_canonical}
    over your canonical {user_canonical}".
- **Result:**
  - `gsc_inspections`: a list of dicts
  - `gsc_status`: `"inspected" | "disabled" | "not_configured" | "no_property" | "error"`
  - `gsc_property`
  - `gsc_dry_run`
  - all added to `SUMMARY_FIELDS`
  - `record_audit` stores the inspections
- **Request:** `AuditRequestParams.enable_gsc: Optional[bool] = True`. The
  CLI has `--no-gsc`. The scheduler passes `options.get("enable_gsc", True)`.
- Never fatal: errors become `gsc_status="error"` and the audit completes.

### 5. Audit join

`GET /api/audits/{id}/gsc` → `{audit_id, status, property, dry_run,
inspections: [...], pages: [{url, clicks, impressions, ctr, position,
inspection_verdict}], not_crawled: [{url, clicks, impressions}]}`.

- `pages`: the audit's crawled pages (from `audit_pages`), joined to the
  project's latest `gsc_pages` by `normalize_url`, sorted by clicks (desc),
  up to 200.
- `not_crawled`: `gsc_pages` rows with impressions > 0 whose normalised URL
  isn't among the crawled pages, sorted by impressions, up to 50.

### 6. API: `app/api/gsc.py`

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/gsc/sites` | `{configured, dry_run, sites: [{site_url, permission}]}` (503 on error with the message) |
| GET | `/api/projects/{id}/gsc` | `{configured, dry_run, property, last_sync_at, kpis, previous_kpis, daily: [...]}`. KPIs cover the last 28 days of `gsc_daily` vs the 28 before: clicks, impressions, CTR (clicks/impressions), position (impression-weighted mean) |
| GET | `/api/projects/{id}/gsc/pages?sort=clicks|impressions|ctr|position&limit&offset` | paginated |
| GET | `/api/projects/{id}/gsc/queries?…` | paginated |
| POST | `/api/projects/{id}/gsc/sync` | the `SyncResult` (409 when not configured) |
| GET | `/api/audits/{id}/gsc` | §5 |

`PATCH /api/projects/{id}` accepts `gsc_property` (an empty string clears it).

### 7. UI

- **Search Console tab** (`/projects/[id]/search-console`, added to `TABS`):
  - **Status card:**
    - property (with a picker filled from `/api/gsc/sites`)
    - last sync and a **Sync now** button (shows the result message)
    - not configured: setup steps (create a service account, download the
      JSON key, set `GSC_SERVICE_ACCOUNT_FILE`, add the service account email
      as a user in Search Console)
    - no access: "Add {service account email} as a user on this property"
      (the email is read from the key's `client_email` and returned by
      `/api/gsc/sites`)
  - **KPI tiles:** clicks, impressions, CTR and average position over 28
    days, each with the change vs the previous 28 days. Position is
    lower-is-better.
  - **Two line charts** (clicks, impressions), one measure each, never a
    dual axis, each with a "Show as table" toggle.
  - **Top pages and top queries tables:** sortable by clicks, impressions,
    CTR and position, paginated by 50.
  - A dry-run banner when `dry_run` is true.
- **Site Audit tab:** a "Search Console" section for the selected audit:
  - an index status table (URL, an indexed/not pill with icon + text,
    Google's reason, last crawl, the canonical when it differs)
  - "Crawled pages by clicks" (top 20)
  - "Pages Google shows that the crawl didn't reach"
- **Report:** the same section as a `search-console` panel, hidden without a
  status.

## Error handling

| Case | Result |
| --- | --- |
| No key and no dry run | Tab: setup steps. Audits: `gsc_status="not_configured"` |
| No property matches | `no_property` / `no_access`, plus the instruction to add the service account |
| Google 4xx/5xx | `GscError` → sync `status="error"` with the message. Audit `gsc_status="error"` |
| Cap reached | remaining inspections recorded with "daily cap of N gsc_inspect calls reached" |
| Key file unreadable | not configured, logged once |

## Testing

- **Provider:** with `AuthorizedSession` mocked: the request URLs and bodies
  (quoted site URL, dimensions, dates), row parsing, the inspection parsing,
  a 403 message, caps, and that the key isn't in errors.
- **`build_gsc_provider`:** all three modes.
- **`DryRunGsc`:** deterministic, and covers the shapes.
- **`match_property`:** domain first, URL-prefix fallback, unverified
  ignored, no match.
- **`sync_project`:** writes, upserting daily without duplicates, replacing
  pages and queries, `no_access`, an error with nothing written, dates.
- **Audit inspection:** the issues (FAIL, NEUTRAL with noindex skipped,
  canonical mismatch), the cap stopping, not configured, `enable_gsc=False`,
  stored rows.
- **API:** every endpoint, KPI math (weighted position, CTR), sorting and
  pagination, the audit join (normalisation, not_crawled), and the PATCH
  property.
- **Scheduler:** due projects only, and errors isolated.
- **Frontend:** the tab states (not configured, no access, dry run, data),
  KPI deltas (position lower-is-better), chart table toggles, sort, the
  property picker, Sync now, and the Site Audit section.
- **Live check:** `GSC_DRY_RUN=true` end to end (sync, audit, UI at 1440 and
  390 px). Real Google calls only after the owner provides a key and says go.

## Done when

With a service account key (or dry run), a project syncs Search Console
performance daily, shows KPIs, trends and top pages and queries, inspects
important pages during audits (with issues for unindexed pages), and joins
clicks and impressions into the audit view. Without credentials, everything
else is unchanged. Docs, env and tests are updated.

## Out of scope

- OAuth sign-in, sitemaps, the Search Console API's search appearance and
  country/device breakdowns, and writing back to Search Console (submitting
  sitemaps, requesting indexing).
